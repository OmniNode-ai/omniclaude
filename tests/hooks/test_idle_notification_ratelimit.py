# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for idle_ratelimit.py — 60s sliding window per agent_id (OMN-8924)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add hooks lib to path for direct import
_lib_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Redirect state file to a temp directory."""
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

    import importlib

    import idle_ratelimit as rl

    importlib.reload(rl)
    return rl


@pytest.mark.unit
def test_first_idle_notification_passes(state_file) -> None:
    result = state_file.should_allow_idle_notification("agent-1", now=1000.0)
    assert result is True


@pytest.mark.unit
def test_burst_only_first_passes(state_file) -> None:
    base = 1000.0
    results = [
        state_file.should_allow_idle_notification("agent-burst", now=base + i)
        for i in range(10)
    ]
    assert results[0] is True
    assert all(r is False for r in results[1:])


@pytest.mark.unit
def test_non_idle_messages_not_affected(state_file) -> None:
    # This module only implements the allow/deny logic; it doesn't filter by type.
    # The shell hook does the type check. Here we verify the state file doesn't
    # pollute across agent IDs.
    result1 = state_file.should_allow_idle_notification("agent-a", now=500.0)
    result2 = state_file.should_allow_idle_notification("agent-b", now=500.0)
    assert result1 is True
    assert result2 is True


@pytest.mark.unit
def test_window_reset_after_60s(state_file) -> None:
    state_file.should_allow_idle_notification("agent-reset", now=1000.0)
    # Within window — blocked
    assert state_file.should_allow_idle_notification("agent-reset", now=1059.9) is False
    # At exactly 60s — allowed (elapsed >= WINDOW_SECONDS)
    assert state_file.should_allow_idle_notification("agent-reset", now=1060.0) is True


@pytest.mark.unit
def test_two_agents_independent_windows(state_file) -> None:
    state_file.should_allow_idle_notification("agent-x", now=1000.0)
    state_file.should_allow_idle_notification("agent-y", now=1000.0)
    # agent-x is blocked, agent-y is also blocked within their own window
    assert state_file.should_allow_idle_notification("agent-x", now=1010.0) is False
    assert state_file.should_allow_idle_notification("agent-y", now=1010.0) is False
    # But agent-z (new) is allowed
    assert state_file.should_allow_idle_notification("agent-z", now=1010.0) is True
