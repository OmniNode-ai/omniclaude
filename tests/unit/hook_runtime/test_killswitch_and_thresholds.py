# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Kill-switch + raised-threshold unit tests. [OMN-9140]

Covers:
- DelegationConfig defaults match the generous values ratified in OMN-9140.
- server._hooks_disabled honors env var and file marker.
- DelegationState does not block under the raised defaults until far beyond
  the old block points.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.hook_runtime.delegation_state import DelegationConfig, DelegationState
from omniclaude.hook_runtime.server import _hooks_disabled


@pytest.mark.unit
def test_delegation_config_defaults_are_raised() -> None:
    cfg = DelegationConfig()
    assert cfg.write_warn_threshold == 100
    assert cfg.write_block_threshold == 500
    assert cfg.read_warn_threshold == 200
    assert cfg.read_block_threshold == 1000
    assert cfg.total_block_threshold == 1500
    assert cfg.skill_loaded_write_block == 300
    assert cfg.skill_loaded_read_block == 500
    assert cfg.skill_loaded_total_block == 1000


@pytest.mark.unit
def test_no_block_under_old_tight_counts() -> None:
    """Old thresholds blocked at 5 writes or 15 total — now a pass."""
    state = DelegationState(config=DelegationConfig())
    session = "session-raised-defaults"
    for _ in range(15):
        state.record_tool(session, "write")
    decision = state.check_thresholds(session)
    assert decision.decision == "pass", decision.message


@pytest.mark.unit
def test_skill_loaded_raised_thresholds_pass() -> None:
    """Old skill_loaded write_block=2 / total=4 now allow far more work."""
    state = DelegationState(config=DelegationConfig())
    session = "session-skill-loaded"
    state.set_skill_loaded(session)
    for _ in range(50):
        state.record_tool(session, "write")
    decision = state.check_thresholds(session)
    assert decision.decision == "pass", decision.message


@pytest.mark.unit
def test_hooks_disabled_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNICLAUDE_HOOKS_DISABLE", "1")
    assert _hooks_disabled() is True


@pytest.mark.unit
def test_hooks_disabled_env_var_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNICLAUDE_HOOKS_DISABLE", raising=False)
    # Ensure the file marker is not present in the test homedir we control.
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent-home-for-test"))
    assert _hooks_disabled() is False


@pytest.mark.unit
def test_hooks_disabled_file_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OMNICLAUDE_HOOKS_DISABLE", raising=False)
    fake_home = tmp_path
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude" / "omniclaude-hooks-disabled").touch()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert _hooks_disabled() is True


@pytest.mark.unit
def test_hooks_disabled_env_value_other_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only literal '1' enables the kill-switch — avoids accidental trips."""
    monkeypatch.setenv("OMNICLAUDE_HOOKS_DISABLE", "true")
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent-home-for-test"))
    assert _hooks_disabled() is False
