# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for T18 telemetry additions to delegation_hook_runner.

Tests:
  - Delegatable path emits a second JSON line with telemetry fields
  - Telemetry JSON is non-authoritative (hook_path_non_authoritative=True)
  - Telemetry tokens/cost are zero (hook has no LLM visibility)
  - correlation_id / session_id propagate from payload fields
  - correlation_id / session_id fall back to env vars
  - Non-delegatable paths do NOT emit telemetry
  - Telemetry failure is silent (hook still exits 0 with DELEGATED: line)
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

_RUNNER_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "delegation_hook_runner.py"
)

_TELEMETRY_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "hook_delegation_telemetry.py"
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "delegation_hook_runner", _RUNNER_PATH
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_telemetry() -> ModuleType:
    name = "hook_delegation_telemetry"
    # Return already-loaded module so @dataclass sees consistent sys.modules entry
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _TELEMETRY_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_runner = _load_runner()
_telemetry_mod = _load_telemetry()


def _delegatable_score(
    task_type: str = "research", model: str = "Qwen3-30B"
) -> SimpleNamespace:
    return SimpleNamespace(
        delegatable=True,
        classified_intent=task_type,
        delegate_to_model=model,
    )


def _run_main(
    stdin_data: str, env: dict[str, str] | None = None
) -> tuple[list[str], int]:
    """Run runner.main() and return (stdout_lines, exit_code)."""
    captured = io.StringIO()
    env_patch = patch.dict("os.environ", env or {}, clear=False)
    with (
        patch.object(sys, "stdin", io.StringIO(stdin_data)),
        patch.object(sys, "stdout", captured),
        env_patch,
    ):
        code = _runner.main()
    lines = [ln for ln in captured.getvalue().splitlines() if ln]
    return lines, code


def _tool_json(
    prompt: str,
    tool_name: str = "Agent",
    correlation_id: str = "",
    session_id: str = "",
) -> str:
    payload: dict[str, object] = {
        "tool_name": tool_name,
        "tool_input": {"prompt": prompt},
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    if session_id:
        payload["session_id"] = session_id
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Telemetry shape on delegatable path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delegatable_emits_two_lines() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, code = _run_main(_tool_json("explain this module"))

    assert code == 0
    assert len(lines) == 2
    assert lines[0].startswith("DELEGATED:")


@pytest.mark.unit
def test_telemetry_line_is_valid_json() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score(
        "document", "local-model"
    )

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(_tool_json("summarize the PR"))

    telemetry = json.loads(lines[1])
    assert isinstance(telemetry, dict)


@pytest.mark.unit
def test_telemetry_non_authoritative_marker() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(_tool_json("explain code"))

    telemetry = json.loads(lines[1])
    assert telemetry["hook_path_non_authoritative"] is True


@pytest.mark.unit
def test_telemetry_tokens_and_cost_are_zero() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(_tool_json("research something"))

    telemetry = json.loads(lines[1])
    assert telemetry["tokens_input"] == 0
    assert telemetry["tokens_output"] == 0
    assert telemetry["cost_usd"] == 0.0


@pytest.mark.unit
def test_telemetry_task_type_propagates() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score(
        "code_review", "Qwen3"
    )

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(_tool_json("review this code"))

    telemetry = json.loads(lines[1])
    assert telemetry["task_type"] == "code_review"
    assert telemetry["delegated_to"] == "Qwen3"


@pytest.mark.unit
def test_telemetry_correlation_id_from_payload() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    stdin = _tool_json("explain X", correlation_id="corr-abc", session_id="sess-xyz")
    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(stdin)

    telemetry = json.loads(lines[1])
    assert telemetry["correlation_id"] == "corr-abc"
    assert telemetry["session_id"] == "sess-xyz"


@pytest.mark.unit
def test_telemetry_correlation_id_from_env_fallback() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    stdin = _tool_json("explain Y")  # no IDs in payload
    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(
                stdin,
                env={
                    "HOOK_CORRELATION_ID": "env-corr",
                    "CLAUDE_SESSION_ID": "env-sess",
                },
            )

    telemetry = json.loads(lines[1])
    assert telemetry["correlation_id"] == "env-corr"
    assert telemetry["session_id"] == "env-sess"


@pytest.mark.unit
def test_telemetry_quality_result_non_authoritative() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, _ = _run_main(_tool_json("explain this"))

    telemetry = json.loads(lines[1])
    qr = telemetry["quality_result"]
    assert qr["authoritative"] is False
    assert isinstance(qr["passed"], bool)


# ---------------------------------------------------------------------------
# Non-delegatable paths — no telemetry line
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_not_delegatable_emits_one_line_only() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = SimpleNamespace(
        delegatable=False, classified_intent="mutation", delegate_to_model=None
    )

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            lines, code = _run_main(_tool_json("git commit and push"))

    assert code == 0
    assert lines == ["not_delegatable"]


@pytest.mark.unit
def test_sensitive_emits_one_line_only() -> None:
    mock_gate = MagicMock()
    mock_gate.check.return_value = SimpleNamespace(is_sensitive=True, reasons=[])

    with patch.object(_runner, "_import_gate", return_value=mock_gate):
        lines, code = _run_main(_tool_json("password=supersecret"))

    assert code == 0
    assert lines == ["not_delegatable:sensitive"]


# ---------------------------------------------------------------------------
# Telemetry failure is silent — DELEGATED: line still emitted
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_telemetry_build_failure_does_not_crash() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            with patch.object(_runner, "_import_telemetry", return_value=(None, None)):
                lines, code = _run_main(_tool_json("explain this"))

    assert code == 0
    # Only the DELEGATED: line — no telemetry line when module unavailable
    assert len(lines) == 1
    assert lines[0].startswith("DELEGATED:")


@pytest.mark.unit
def test_telemetry_exception_during_build_does_not_crash() -> None:
    mock_classifier = MagicMock()
    mock_classifier.is_delegatable.return_value = _delegatable_score()

    broken_cls = MagicMock(side_effect=RuntimeError("telemetry exploded"))
    broken_hash = MagicMock(return_value="")

    with patch.object(_runner, "_import_gate", return_value=None):
        with patch.object(_runner, "_import_classifier", return_value=mock_classifier):
            with patch.object(
                _runner, "_import_telemetry", return_value=(broken_cls, broken_hash)
            ):
                lines, code = _run_main(_tool_json("explain this"))

    assert code == 0
    assert len(lines) == 1
    assert lines[0].startswith("DELEGATED:")
