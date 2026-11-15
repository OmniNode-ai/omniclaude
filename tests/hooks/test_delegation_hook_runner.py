# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for delegation_hook_runner (OMN-10607).

Tests the stdin→stdout contract of the delegation hook runner:
  - Sensitive inputs produce not_delegatable:sensitive without raw reasons
  - Delegatable prompts produce DELEGATED: ...
  - Non-delegatable (tool-call signals) produce not_delegatable
  - Malformed JSON is handled gracefully (not_delegatable)
  - Import errors fail open (not_delegatable)
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from omnimarket.nodes.node_hook_delegate_effect.handlers.handler_hook_delegate import (
    HandlerHookDelegate,
)
from omnimarket.nodes.node_hook_delegate_effect.models import (
    EnumHookDelegateOutcome,
    ModelHookDelegateResult,
)

# ---------------------------------------------------------------------------
# Locate the module under test (hooks/lib, not in the installed src package)
# ---------------------------------------------------------------------------
_MODULE_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "delegation_hook_runner.py"
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "delegation_hook_runner", _MODULE_PATH
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_runner = _load_runner()


def _clean_gate() -> MagicMock:
    """A sensitivity gate that finds nothing sensitive. Since OMN-23413 a missing
    gate keeps the task with Claude (fail closed), so tests of the classifier and
    the delegation path stand in this gate rather than none."""
    gate = MagicMock()
    gate.check.return_value = SimpleNamespace(is_sensitive=False, reasons=[])
    return gate


@pytest.fixture(autouse=True)
def _no_model_call(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("ONEX_HOOK_DELEGATE_TIMEOUT_S", "240")  # as the .sh sets it
    """Since OMN-23413 a delegatable task is delegated for real with onex delegate;
    these tests cover the gate and classifier, so no model is called."""
    with patch.object(
        HandlerHookDelegate,
        "handle",
        return_value=ModelHookDelegateResult(
            outcome=EnumHookDelegateOutcome.ANSWERED, answer="answer", run_id="run-0001"
        ),
    ):
        yield


def _run_main(stdin_data: str) -> tuple[str, int]:
    """Run runner.main() with captured stdin/stdout, return (stdout, exit_code)."""
    captured = io.StringIO()
    with (
        patch.object(sys, "stdin", io.StringIO(stdin_data)),
        patch.object(sys, "stdout", captured),
    ):
        code = _runner.main()
    return captured.getvalue().strip(), code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_json(prompt: str, tool_name: str = "Agent") -> str:
    return json.dumps({"tool_name": tool_name, "tool_input": {"prompt": prompt}})


# ---------------------------------------------------------------------------
# Tests — sensitivity gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sensitive_bearer_token_rejected() -> None:
    payload = _tool_json(
        "Here is my auth token: Bearer sk-abc123verylongtoken1234567890"
    )
    out, code = _run_main(payload)
    assert "not_delegatable" in out
    assert code == 0


@pytest.mark.unit
def test_sensitive_password_kv_rejected() -> None:
    payload = _tool_json("password=supersecret123 in the config")
    out, code = _run_main(payload)
    assert "not_delegatable" in out


# ---------------------------------------------------------------------------
# Tests — delegatable intents
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_research_prompt_delegates() -> None:
    payload = _tool_json("What does the agent_router module do? Find and explain it.")
    out, code = _run_main(payload)
    # Either delegated or not — must exit 0 with a known prefix
    assert code == 0
    assert out.startswith("DELEGATED:") or out.startswith("not_delegatable")


@pytest.mark.unit
def test_tool_call_prompt_not_delegated() -> None:
    payload = _tool_json("run git commit and push the branch")
    out, code = _run_main(payload)
    assert code == 0
    assert out.startswith("not_delegatable")


# ---------------------------------------------------------------------------
# Tests — malformed input
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_stdin_returns_not_delegatable() -> None:
    out, code = _run_main("")
    assert code == 0
    assert out.startswith("not_delegatable:")


@pytest.mark.unit
def test_invalid_json_returns_not_delegatable() -> None:
    out, code = _run_main("{not valid json!!}")
    assert code == 0
    assert out.startswith("not_delegatable:")


@pytest.mark.unit
def test_non_object_json_returns_not_delegatable() -> None:
    with (
        patch.object(_runner, "_import_gate", return_value=_clean_gate()),
        patch.object(_runner, "_import_classifier", return_value=None),
    ):
        out, code = _run_main("[]")

    assert code == 0
    assert out == "not_delegatable:no_classifier"


# ---------------------------------------------------------------------------
# Tests — fail-open when imports unavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_missing_gate_keeps_the_task_with_claude() -> None:
    """OMN-23413: without a sensitivity gate nothing goes to a delegated model."""
    payload = _tool_json("explain the architecture")
    with patch.object(_runner, "_import_gate", return_value=None):
        out, code = _run_main(payload)
    assert code == 0
    # the reason is named, so a broken install does not read as a real hit
    assert out == "not_delegatable:no_gate"


@pytest.mark.unit
def test_fail_open_when_classifier_unavailable() -> None:
    """Classifier import failure should return not_delegatable gracefully."""
    payload = _tool_json("explain the architecture")
    with (
        patch.object(_runner, "_import_gate", return_value=_clean_gate()),
        patch.object(_runner, "_import_classifier", return_value=None),
    ):
        out, code = _run_main(payload)
    assert code == 0
    assert out == "not_delegatable:no_classifier"


@pytest.mark.unit
def test_fail_open_when_gate_instantiation_fails() -> None:
    original_import = __import__

    class BrokenGate:
        def __init__(self) -> None:
            raise RuntimeError("gate init exploded")

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "omniclaude.delegation.sensitivity_gate":
            return SimpleNamespace(SensitivityGate=BrokenGate)
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        # OMN-23413: fails closed (nothing is sent) and names the reason
        assert _runner._gate_why("explain TCP") == "gate_error:RuntimeError"
        assert _runner._sensitive("explain TCP") is True


@pytest.mark.unit
def test_fail_open_when_classifier_instantiation_fails() -> None:
    original_import = __import__

    class BrokenClassifier:
        def __init__(self) -> None:
            raise RuntimeError("classifier init exploded")

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "omniclaude.lib.task_classifier":
            return SimpleNamespace(TaskClassifier=BrokenClassifier)
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        assert _runner._import_classifier() is None


@pytest.mark.unit
def test_a_gate_exception_keeps_the_task_with_claude() -> None:
    """An exception in gate.check() must not crash, and (OMN-23413) fails closed."""
    mock_gate = MagicMock()
    mock_gate.check.side_effect = RuntimeError("gate exploded")
    payload = _tool_json("explain the architecture")
    with patch.object(_runner, "_import_gate", return_value=mock_gate):
        out, code = _run_main(payload)
    assert code == 0
    assert out == "not_delegatable:gate_error:RuntimeError"
    assert "exploded" not in out


@pytest.mark.unit
def test_classifier_exception_returns_not_delegatable() -> None:
    """An exception in classifier.is_delegatable() must produce not_delegatable."""
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.side_effect = RuntimeError("classifier exploded")
    payload = _tool_json("explain the architecture")
    with (
        patch.object(_runner, "_import_gate", return_value=_clean_gate()),
        patch.object(_runner, "_import_classifier", return_value=mock_classifier),
    ):
        out, code = _run_main(payload)
    assert code == 0
    # OMN-23413: the reason is named, never the error's text (it may hold the task)
    assert out == "not_delegatable:error:RuntimeError"
    assert "exploded" not in out


@pytest.mark.unit
def test_sensitive_reasons_are_not_emitted() -> None:
    mock_gate = MagicMock()
    mock_gate.check.return_value = SimpleNamespace(
        is_sensitive=True,
        reasons=["raw password=supersecret123"],
    )

    payload = _tool_json("password=supersecret123")
    with patch.object(_runner, "_import_gate", return_value=mock_gate):
        out, code = _run_main(payload)

    assert code == 0
    assert out == "not_delegatable:sensitive"
    assert "supersecret123" not in out


# ---------------------------------------------------------------------------
# OMN-23413 review: the gate sees the text that is sent, and names its failures
# ---------------------------------------------------------------------------

_KEY_BODY = "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0UvWx"
_KEYS = [
    "sk-" + "ant-api03-" + _KEY_BODY + "-" + _KEY_BODY,
    "ghp_" + _KEY_BODY + "ab",
    "AKIA" + "ABCDEFGHIJ012345",
]


@pytest.mark.unit
@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("before", ["\n", "\t", "\n```\n", "\u2014", "密钥"])
def test_a_key_that_starts_a_line_keeps_the_task_with_claude(
    key: str, before: str
) -> None:
    """R1: the gate reads the decoded prompt, not its JSON form, where a newline
    is backslash-n and hides the key from a word-boundary anchor."""
    payload = _tool_json(f"Explain what this module does. My key is:{before}{key}")
    out, code = _run_main(payload)
    assert code == 0
    assert out == "not_delegatable:sensitive"


@pytest.mark.unit
def test_a_key_in_any_string_field_keeps_the_task_with_claude() -> None:
    """R1: every string value of tool_input is checked, nested ones included."""
    payload = json.dumps(
        {
            "tool_name": "Task",
            "tool_input": {
                "description": "q",
                "prompt": "Explain TCP",
                "extra": {"notes": ["see:\n" + _KEYS[0]]},
            },
        }
    )
    out, code = _run_main(payload)
    assert out == "not_delegatable:sensitive"


@pytest.mark.unit
def test_an_unimportable_gate_is_named_not_reported_as_sensitive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """R5b: a gate that cannot be imported still sends nothing, and says why."""
    with patch.dict(sys.modules, {"omniclaude.delegation.sensitivity_gate": None}):
        out, code = _run_main(_tool_json("explain the architecture"))
    assert code == 0
    assert out == "not_delegatable:gate_error:ModuleNotFoundError"
    assert "gate_error:ModuleNotFoundError" in capsys.readouterr().err


@pytest.mark.unit
def test_a_node_without_sensitive_is_named_and_sends_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """R5a: an omnimarket whose build_prompt_handler takes no ``sensitive`` (older
    than OMN-23413's fix) keeps every prompt with Claude, and the log says why."""
    from omnimarket.nodes.node_hook_delegate_effect import container

    def old_build_prompt_handler(cli: object | None = None) -> object:
        raise AssertionError("never built: the call itself must fail")

    prompt = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "skew",
        "prompt": "what is TCP?",
    }
    with (
        patch.object(container, "build_handler", return_value=MagicMock()),
        patch.object(container, "build_prompt_handler", old_build_prompt_handler),
    ):
        out, code = _run_main(json.dumps(prompt))
    assert code == 0
    assert out == ""  # nothing printed: the prompt goes to Claude as typed
    err = capsys.readouterr().err
    assert "node_skew" in err
    assert "what is TCP" not in err
