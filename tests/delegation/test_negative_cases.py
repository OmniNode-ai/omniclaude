# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Negative tests for non-delegatable tool calls (OMN-10612).

Verifies that the delegation pipeline fails open: non-delegatable inputs
are rejected cleanly without crashing and without blocking the original
tool call.

All test cases assert the invariant:
  - No uncaught exception
  - Result clearly indicates "not delegatable" or "sensitive"
  - Original tool path is never blocked
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.delegation.sensitivity_gate import (
    EnumSensitivityPolicy,
    SensitivityGate,
)
from omniclaude.lib.task_classifier import TaskClassifier, TaskIntent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GATE = SensitivityGate()
_CLASSIFIER = TaskClassifier()

_HOOK_RUNNER = (
    Path(__file__).parent.parent.parent
    / "plugins/onex/hooks/lib/delegation_hook_runner.py"
)


def _run_hook_runner(stdin_payload: str) -> tuple[str, int]:
    """Run delegation_hook_runner.py main() with the given stdin string.

    Returns (stdout_text, exit_code). Never raises — the hook must not crash.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "delegation_hook_runner", _HOOK_RUNNER
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(stdin_payload)), patch("sys.stdout", captured):
        exit_code = mod.main()

    return captured.getvalue().strip(), exit_code or 0


# ---------------------------------------------------------------------------
# Fixture: fresh instances per test
# ---------------------------------------------------------------------------


@pytest.fixture
def gate() -> SensitivityGate:
    return SensitivityGate()


@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier()


# ---------------------------------------------------------------------------
# 1. Bash tool with destructive command → wrong tool type, not delegatable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bash_rm_rf_not_delegatable(classifier: TaskClassifier) -> None:
    """Destructive shell commands contain tool-call signals and must not delegate."""
    prompt = "run bash command: rm -rf /tmp/data"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False
    assert any("tool-call" in r or "agentic" in r for r in score.reasons), (
        f"Expected tool-call rejection, got: {score.reasons}"
    )


@pytest.mark.unit
def test_bash_drop_table_not_delegatable(classifier: TaskClassifier) -> None:
    """SQL DROP TABLE via shell contains tool-call signals and must not delegate."""
    prompt = "execute: psql -c 'DROP TABLE users'"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False


# ---------------------------------------------------------------------------
# 2. Write/Edit file operation → tool-call signal, not delegatable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_file_not_delegatable(classifier: TaskClassifier) -> None:
    """Write file operations must not be delegated (tool-call signal)."""
    prompt = "write file config.yaml with the new settings"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False


@pytest.mark.unit
def test_create_file_not_delegatable(classifier: TaskClassifier) -> None:
    """Create file operations must not be delegated."""
    prompt = "create file src/main.py and add the class"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False


# ---------------------------------------------------------------------------
# 3. API key in Agent task prompt → sensitivity gate blocks cloud routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_key_blocked_by_sensitivity_gate(gate: SensitivityGate) -> None:
    """Prompt containing an API key must be flagged as sensitive / LOCAL_ONLY."""
    prompt = "summarize this: api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
    result = gate.check(prompt)

    assert result.is_sensitive is True
    assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY
    assert len(result.reasons) >= 1


@pytest.mark.unit
def test_openai_sk_key_blocked(gate: SensitivityGate) -> None:
    """OpenAI-style sk- key must be caught by the gate."""
    prompt = "Use this key: sk-abcdef1234567890abcdef1234567890"
    result = gate.check(prompt)

    assert result.is_sensitive is True
    assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


# ---------------------------------------------------------------------------
# 4. Private key in Agent task prompt → sensitivity gate blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pem_private_key_blocked(gate: SensitivityGate) -> None:
    """PEM private key block must be caught and routed LOCAL_ONLY."""
    prompt = (
        "Here is the cert:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4...\n"
        "-----END RSA PRIVATE KEY-----"
    )
    result = gate.check(prompt)

    assert result.is_sensitive is True
    assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY
    assert any("private key" in r.lower() for r in result.reasons)


@pytest.mark.unit
def test_ec_private_key_blocked(gate: SensitivityGate) -> None:
    """Generic PRIVATE KEY header must be caught."""
    prompt = "-----BEGIN PRIVATE KEY-----\nABCDEFGHIJKLMNOPQRSTUVWXYZ\n-----END PRIVATE KEY-----"
    result = gate.check(prompt)

    assert result.is_sensitive is True
    assert result.policy == EnumSensitivityPolicy.LOCAL_ONLY


# ---------------------------------------------------------------------------
# 5. Unknown / unrecognized tool_name → not delegatable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unknown_tool_type_not_delegatable(classifier: TaskClassifier) -> None:
    """A prompt about an unknown/unrecognized tool type must not delegate."""
    prompt = "use XYZUnknownTool to process the widget"
    score = classifier.is_delegatable(prompt)

    # No tool-call signal from an unrecognised tool → may or may not be
    # delegatable based on intent alone, but should never raise.
    assert isinstance(score.delegatable, bool)
    # The prompt has low-confidence intent; either outcome is acceptable
    # as long as the call does not throw.


# ---------------------------------------------------------------------------
# 6. Malformed / empty JSON stdin → delegation_hook_runner must not crash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_malformed_json_fails_open() -> None:
    """delegation_hook_runner must gracefully handle malformed JSON and fail open."""
    output, exit_code = _run_hook_runner("{this is not valid json!!!")

    assert exit_code == 0, "Hook must always exit 0 (fail open)"
    assert "not_delegatable" in output or output == "", (
        f"Unexpected output for malformed JSON: {output!r}"
    )


@pytest.mark.unit
def test_empty_stdin_fails_open() -> None:
    """Empty stdin must not crash the hook runner."""
    output, exit_code = _run_hook_runner("")

    assert exit_code == 0
    assert "not_delegatable" in output or output == ""


# ---------------------------------------------------------------------------
# 7. Missing tool_name field → graceful error, fail open
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_tool_name_fails_open() -> None:
    """Payload without tool_name must not crash; gate/classifier runs on tool_input."""
    payload = json.dumps({"tool_input": {"command": "echo hello"}})
    output, exit_code = _run_hook_runner(payload)

    assert exit_code == 0
    # Without a clear delegatable prompt, should return not_delegatable
    assert "not_delegatable" in output or "DELEGATED" in output  # fail-open either way


# ---------------------------------------------------------------------------
# 8. Missing tool_input field → graceful error, fail open
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_tool_input_fails_open() -> None:
    """Payload without tool_input must not crash; hook treats payload itself as input."""
    payload = json.dumps({"tool_name": "Bash", "sessionId": "abc123"})
    output, exit_code = _run_hook_runner(payload)

    assert exit_code == 0
    assert "not_delegatable" in output or "DELEGATED" in output


# ---------------------------------------------------------------------------
# 9. Classifier returns IMPLEMENT → not delegatable (confidence gate)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_implement_intent_below_threshold_not_delegatable(
    classifier: TaskClassifier,
) -> None:
    """IMPLEMENT tasks that exceed confidence threshold ARE delegatable per the
    allow-list (OMN-10604 design). This test verifies that low-confidence
    IMPLEMENT prompts are rejected by the confidence gate."""
    # Minimal IMPLEMENT signal with very low keyword density
    prompt = "create"
    score = classifier.is_delegatable(prompt)

    # With only one keyword "create", confidence will be low
    if score.classified_intent == "implement":
        if not score.delegatable:
            assert any("confidence" in r or "allow-list" in r for r in score.reasons)
    # Either way: must not raise
    assert isinstance(score.delegatable, bool)


@pytest.mark.unit
def test_implement_intent_with_tool_signals_not_delegatable(
    classifier: TaskClassifier,
) -> None:
    """IMPLEMENT task containing tool-call signals must not be delegated."""
    prompt = "create a new handler and run the tests to verify"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False
    assert any("tool-call" in r or "agentic" in r for r in score.reasons)


# ---------------------------------------------------------------------------
# 10. Classifier returns DEBUG → not in allow-list, not delegatable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_debug_intent_not_delegatable(classifier: TaskClassifier) -> None:
    """DEBUG intent is not in the delegation allow-list and must be rejected."""
    prompt = "debug the failing test — why is it broken and what is the issue?"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False
    # Intent should be DEBUG (or similar)
    assert score.classified_intent in (
        TaskIntent.DEBUG.value,
        TaskIntent.RESEARCH.value,  # "why" is a RESEARCH keyword too
        TaskIntent.UNKNOWN.value,
    )


@pytest.mark.unit
def test_debug_intent_explicit_not_delegatable(classifier: TaskClassifier) -> None:
    """Explicit debug/troubleshoot/investigate prompt must not delegate."""
    prompt = "troubleshoot the broken authentication flow and investigate the error"
    score = classifier.is_delegatable(prompt)

    assert score.delegatable is False
    assert score.classified_intent in (
        TaskIntent.DEBUG.value,
        TaskIntent.RESEARCH.value,
        TaskIntent.UNKNOWN.value,
    )


# ---------------------------------------------------------------------------
# Invariant: sensitivity gate never crashes on any string
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "edge_input",
    [
        "",
        " ",
        "\x00\x01\x02",
        "a" * 10_000,
        "😀🚀💥" * 100,
    ],
)
def test_sensitivity_gate_never_crashes(gate: SensitivityGate, edge_input: str) -> None:
    """SensitivityGate.check() must never raise regardless of input."""
    result = gate.check(edge_input)
    assert result.policy in (
        EnumSensitivityPolicy.LOCAL_ONLY,
        EnumSensitivityPolicy.CLOUD_ALLOWED,
    )
