# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for session phase enforcement hook (OMN-11233, OMN-11282)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from omniclaude.hooks.session_phase_enforcement import (
    EnumPhaseEvaluation,
    ModelPhaseState,
    build_directive,
    build_enforcement_directive,
    read_phase_state,
)


def _write_state(tmp_path: Path, data: dict) -> None:
    state_dir = tmp_path / ".onex_state" / "session"
    state_dir.mkdir(parents=True)
    (state_dir / "phase_state.yaml").write_text(
        yaml.dump(data, default_flow_style=False),
        encoding="utf-8",
    )


def _write_phase_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(state, fh)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _hook_script() -> Path:
    return (
        _repo_root()
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "user_prompt_session_phase_enforcement.sh"
    )


# ---------------------------------------------------------------------------
# Legacy build_enforcement_directive tests (OMN-11233)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hook_injects_directive_on_transition_required(tmp_path: Path) -> None:
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
def test_hook_no_op_when_in_budget(tmp_path: Path) -> None:
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
def test_hook_injects_halt_on_halt_required(tmp_path: Path) -> None:
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
def test_hook_no_op_when_no_state_file(tmp_path: Path) -> None:
    result = build_enforcement_directive(state_dir=tmp_path / ".onex_state")
    assert result == ""


# ---------------------------------------------------------------------------
# Typed ModelPhaseState + build_directive tests (OMN-11282)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadPhaseState:
    def test_returns_none_when_no_state_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        result = read_phase_state(state_file)
        assert result is None

    def test_reads_valid_state_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        _write_phase_state(
            state_file,
            {
                "session_id": "test-session",
                "current_phase": "build",
                "last_evaluation": "no_action",
                "budget_elapsed_pct": 50,
            },
        )
        result = read_phase_state(state_file)
        assert result is not None
        assert isinstance(result, ModelPhaseState)
        assert result.current_phase == "build"
        assert result.last_evaluation == "no_action"

    def test_returns_none_on_invalid_yaml(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(": invalid: yaml: [unclosed")
        result = read_phase_state(state_file)
        assert result is None


@pytest.mark.unit
class TestBuildDirective:
    def test_no_op_when_no_action(self) -> None:
        state = ModelPhaseState(current_phase="build", last_evaluation="no_action")
        assert build_directive(state) is None

    def test_transition_required_injects_directive(self) -> None:
        state = ModelPhaseState(
            current_phase="build",
            last_evaluation="transition_required",
            budget_elapsed_pct=95,
            next_phase="close_out",
        )
        directive = build_directive(state)
        assert directive is not None
        assert "[PHASE ENFORCEMENT]" in directive
        assert "build" in directive
        assert "close_out" in directive
        assert "budget exhausted" in directive
        assert "Transition" in directive

    def test_halt_required_injects_directive(self) -> None:
        state = ModelPhaseState(
            current_phase="build",
            last_evaluation="halt_required",
            halt_reason="token budget exceeded",
        )
        directive = build_directive(state)
        assert directive is not None
        assert "[SESSION HALT]" in directive
        assert "token budget exceeded" in directive
        assert "Stop all work" in directive

    def test_budget_warning_injects_directive(self) -> None:
        state = ModelPhaseState(
            current_phase="build",
            last_evaluation="budget_warning",
            budget_elapsed_pct=75,
        )
        directive = build_directive(state)
        assert directive is not None
        assert "[PHASE WARNING]" in directive
        assert "build" in directive
        assert "75%" in directive
        assert "transition soon" in directive

    def test_unknown_evaluation_is_no_op(self) -> None:
        state = ModelPhaseState(
            current_phase="build",
            last_evaluation="some_future_evaluation_type",
        )
        assert build_directive(state) is None


@pytest.mark.unit
class TestHookInjectDirectiveEndToEnd:
    def test_hook_injects_directive_on_transition_required(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        _write_phase_state(
            state_file,
            {
                "session_id": "sess-001",
                "current_phase": "build",
                "last_evaluation": "transition_required",
                "budget_elapsed_pct": 98,
                "next_phase": "close_out",
            },
        )
        state = read_phase_state(state_file)
        assert state is not None
        directive = build_directive(state)
        assert directive is not None
        assert "[PHASE ENFORCEMENT]" in directive
        assert "build" in directive
        assert "close_out" in directive

    def test_hook_no_op_when_in_budget(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        _write_phase_state(
            state_file,
            {
                "session_id": "sess-002",
                "current_phase": "build",
                "last_evaluation": "no_action",
            },
        )
        state = read_phase_state(state_file)
        assert state is not None
        assert build_directive(state) is None

    def test_hook_injects_halt_on_halt_required(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        _write_phase_state(
            state_file,
            {
                "session_id": "sess-003",
                "current_phase": "build",
                "last_evaluation": "halt_required",
                "halt_reason": "daily token limit reached",
            },
        )
        state = read_phase_state(state_file)
        assert state is not None
        directive = build_directive(state)
        assert directive is not None
        assert "[SESSION HALT]" in directive
        assert "daily token limit reached" in directive

    def test_hook_no_op_when_no_state_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".onex_state" / "session" / "phase_state.yaml"
        assert read_phase_state(state_file) is None


@pytest.mark.unit
class TestSessionPhaseHookScript:
    def test_lite_mode_drains_stdin_before_success_exit(self, tmp_path: Path) -> None:
        env = {**os.environ, "OMNICLAUDE_MODE": "lite"}
        result = subprocess.run(
            ["/bin/bash", str(_hook_script())],
            input='{"prompt": "hello"}\n',
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_fallback_json_emitter_escapes_directive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state_file = tmp_path / "state" / "session" / "phase_state.yaml"
        _write_phase_state(
            state_file,
            {
                "current_phase": 'build "quoted"',
                "last_evaluation": "halt_required",
                "halt_reason": 'path C:\\tmp\\new\nstop "now"',
            },
        )
        path_without_jq = "/bin:/usr/bin"
        monkeypatch.setenv("PATH", path_without_jq)

        env = {
            **os.environ,
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "PATH": path_without_jq,
            "PLUGIN_PYTHON_BIN": sys.executable,
        }
        result = subprocess.run(
            ["/bin/bash", str(_hook_script())],
            input='{"prompt": "hello"}\n',
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            env=env,
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        additional_context = payload["hookSpecificOutput"]["additionalContext"]
        assert 'build "quoted"' not in additional_context
        assert 'C:\\tmp\\new\nstop "now"' in additional_context


@pytest.mark.unit
class TestEnumPhaseEvaluation:
    def test_known_values_exist(self) -> None:
        assert EnumPhaseEvaluation.NO_ACTION == "no_action"
        assert EnumPhaseEvaluation.TRANSITION_REQUIRED == "transition_required"
        assert EnumPhaseEvaluation.HALT_REQUIRED == "halt_required"
        assert EnumPhaseEvaluation.BUDGET_WARNING == "budget_warning"


@pytest.mark.unit
class TestModelPhaseState:
    def test_defaults_are_safe(self) -> None:
        state = ModelPhaseState()
        assert state.last_evaluation == EnumPhaseEvaluation.NO_ACTION
        assert state.current_phase == "unknown"
        assert state.budget_elapsed_pct == 0
        assert state.next_phase is None
        assert state.halt_reason is None

    def test_extra_fields_ignored(self) -> None:
        state = ModelPhaseState.model_validate(
            {"current_phase": "build", "unknown_future_field": "value"}
        )
        assert state.current_phase == "build"
