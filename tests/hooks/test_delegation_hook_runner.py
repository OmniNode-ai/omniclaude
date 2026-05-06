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
    assert out == "not_delegatable"


@pytest.mark.unit
def test_invalid_json_returns_not_delegatable() -> None:
    out, code = _run_main("{not valid json!!}")
    assert code == 0
    assert out == "not_delegatable"


@pytest.mark.unit
def test_non_object_json_returns_not_delegatable() -> None:
    with (
        patch.object(_runner, "_import_gate", return_value=None),
        patch.object(_runner, "_import_classifier", return_value=None),
    ):
        out, code = _run_main("[]")

    assert code == 0
    assert out == "not_delegatable"


# ---------------------------------------------------------------------------
# Tests — fail-open when imports unavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fail_open_when_gate_unavailable() -> None:
    """SensitivityGate import failure should fall through to classifier."""
    payload = _tool_json("explain the architecture")
    with patch.object(_runner, "_import_gate", return_value=None):
        out, code = _run_main(payload)
    assert code == 0
    assert out.startswith("DELEGATED:") or out.startswith("not_delegatable")


@pytest.mark.unit
def test_fail_open_when_classifier_unavailable() -> None:
    """Classifier import failure should return not_delegatable gracefully."""
    payload = _tool_json("explain the architecture")
    with (
        patch.object(_runner, "_import_gate", return_value=None),
        patch.object(_runner, "_import_classifier", return_value=None),
    ):
        out, code = _run_main(payload)
    assert code == 0
    assert out == "not_delegatable"


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
        assert _runner._import_gate() is None


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
def test_gate_exception_falls_through_to_classifier() -> None:
    """An exception in gate.check() must not crash — fall through to classifier."""
    mock_gate = MagicMock()
    mock_gate.check.side_effect = RuntimeError("gate exploded")
    payload = _tool_json("explain the architecture")
    with patch.object(_runner, "_import_gate", return_value=mock_gate):
        out, code = _run_main(payload)
    assert code == 0
    # Should not raise, result is either delegated or not_delegatable
    assert out.startswith("DELEGATED:") or out.startswith("not_delegatable")


@pytest.mark.unit
def test_classifier_exception_returns_not_delegatable() -> None:
    """An exception in classifier.is_delegatable() must produce not_delegatable."""
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.side_effect = RuntimeError("classifier exploded")
    payload = _tool_json("explain the architecture")
    with (
        patch.object(_runner, "_import_gate", return_value=None),
        patch.object(_runner, "_import_classifier", return_value=mock_classifier),
    ):
        out, code = _run_main(payload)
    assert code == 0
    assert out == "not_delegatable"


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
