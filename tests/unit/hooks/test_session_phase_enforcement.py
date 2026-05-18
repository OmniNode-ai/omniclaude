# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for session_phase_enforcement hook (OMN-11233)."""

from __future__ import annotations

import pytest
import yaml

from omniclaude.hooks.session_phase_enforcement import build_enforcement_directive


def _write_state(tmp_path, data: dict) -> None:
    state_dir = tmp_path / ".onex_state" / "session"
    state_dir.mkdir(parents=True)
    (state_dir / "phase_state.yaml").write_text(
        yaml.dump(data, default_flow_style=False),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_hook_injects_directive_on_transition_required(tmp_path):
    _write_state(
        tmp_path,
        {
            "last_evaluation": "transition_required",
            "current_phase": "build",
            "next_phase": "closeout",
            "budget_elapsed_pct": 100,
        },
    )
    result = build_enforcement_directive(state_dir=tmp_path / ".onex_state")
    assert "[PHASE ENFORCEMENT]" in result
    assert "build" in result
    assert "closeout" in result
    assert "Transition to" in result


@pytest.mark.unit
def test_hook_no_op_when_in_budget(tmp_path):
    _write_state(
        tmp_path,
        {
            "last_evaluation": "in_budget",
            "current_phase": "build",
            "next_phase": "closeout",
            "budget_elapsed_pct": 40,
        },
    )
    result = build_enforcement_directive(state_dir=tmp_path / ".onex_state")
    assert result == ""


@pytest.mark.unit
def test_hook_injects_halt_on_halt_required(tmp_path):
    _write_state(
        tmp_path,
        {
            "last_evaluation": "halt_required",
            "current_phase": "build",
            "next_phase": "none",
            "budget_elapsed_pct": 100,
        },
    )
    result = build_enforcement_directive(state_dir=tmp_path / ".onex_state")
    assert "[SESSION HALT]" in result
    assert "Stop all work immediately" in result


@pytest.mark.unit
def test_hook_no_op_when_no_state_file(tmp_path):
    result = build_enforcement_directive(state_dir=tmp_path / ".onex_state")
    assert result == ""
