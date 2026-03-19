# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for session outcome payload builder.

Reference: OMN-5501 - Wire Stop hook to emit session outcome commands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Plugin lib modules live outside the normal package tree.
# Insert hooks/lib so session_outcome can be imported directly.
_HOOKS_LIB = str(Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib")
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from session_outcome import build_session_outcome_payload  # noqa: E402


@pytest.mark.unit
def test_build_session_outcome_payload_success() -> None:
    """Success outcome should have no error field."""
    result = build_session_outcome_payload(
        session_id="test-session-123",
        outcome="success",
        reason="tool_calls_completed > 0 and completion markers detected",
        correlation_id="corr-456",
    )

    assert result["session_id"] == "test-session-123"
    assert result["outcome"] == "success"
    assert result["correlation_id"] == "corr-456"
    assert result["error"] is None


@pytest.mark.unit
def test_build_session_outcome_payload_failed_includes_error() -> None:
    """Failed sessions should include error object with code, message, component."""
    result = build_session_outcome_payload(
        session_id="test-session-789",
        outcome="failed",
        reason="exit_code != 0",
        correlation_id="corr-012",
    )

    assert result["outcome"] == "failed"
    assert result["error"] is not None
    error = result["error"]
    assert isinstance(error, dict)
    assert error["code"] == "session_failed"
    assert error["message"] == "exit_code != 0"
    assert error["component"] == "claude_code"


@pytest.mark.unit
def test_build_session_outcome_payload_abandoned() -> None:
    """Abandoned outcome should have no error field."""
    result = build_session_outcome_payload(
        session_id="test-session-abc",
        outcome="abandoned",
        reason="session ended after 15.0s without completion markers",
    )

    assert result["outcome"] == "abandoned"
    assert result["error"] is None
    assert result["correlation_id"] == ""


@pytest.mark.unit
def test_build_session_outcome_payload_unknown() -> None:
    """Unknown outcome should have no error field."""
    result = build_session_outcome_payload(
        session_id="test-session-xyz",
        outcome="unknown",
        reason="insufficient_signal",
        correlation_id="corr-999",
    )

    assert result["outcome"] == "unknown"
    assert result["error"] is None
