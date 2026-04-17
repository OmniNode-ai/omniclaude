# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the watchdog state reducer.

The reducer is the permanent logic: reduce(state, event, policy) -> (new_state, intents).
Shell scripts and future ONEX nodes are just dispatch surfaces over this reducer.

Covers:
- Pure reducer: event->state transitions and intent generation
- Escalation policy loading and lookup
- FSM state transitions
- Intent types per escalation level
- Success resets all streaks
- Independent loop tracking
- Action recording via events
- Correlation IDs flow through to intents
- State file I/O (load/save/corrupt recovery)
- Shell script integration tests (dispatch surface)
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from omniclaude.shared.models.model_watchdog_state import (
    EnumRunResult,
    EnumWatchdogAction,
    EnumWatchdogEventKind,
    EnumWatchdogFsmState,
    IntentAlertUser,
    IntentCreateTicket,
    IntentFix,
    IntentInvestigate,
    IntentRestart,
    ModelEscalationPolicy,
    ModelWatchdogEvent,
    ModelWatchdogState,
    check_escalation,
    load_policy,
    load_state,
    record_action,
    record_run,
    reduce,
    save_state,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "watchdog"
    d.mkdir()
    return d


@pytest.fixture
def policy() -> ModelEscalationPolicy:
    return load_policy()


@pytest.fixture
def empty_state() -> ModelWatchdogState:
    return ModelWatchdogState()


def _make_event(
    loop: str = "closeout",
    result: str = "fail",
    phase: str = "B1",
    error: str | None = "test error",
    correlation_id: str | None = None,
) -> ModelWatchdogEvent:
    """Helper to build a run_completed event with deterministic timestamp."""
    return ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.RUN_COMPLETED,
        loop=loop,
        result=EnumRunResult(result),
        phase=phase,
        error_message=error,
        timestamp="2026-04-02T20:00:00Z",
        correlation_id=correlation_id or str(uuid.uuid4()),
    )


def _make_action_event(
    loop: str = "closeout",
    action: str = "restarted",
    detail: str = "auto-restart",
) -> ModelWatchdogEvent:
    return ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.ACTION_TAKEN,
        loop=loop,
        action=action,
        detail=detail,
        timestamp="2026-04-02T20:00:00Z",
        correlation_id=str(uuid.uuid4()),
    )


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


class TestPolicyLoading:
    def test_load_real_policy_file(self) -> None:
        policy = load_policy()
        assert policy.schema_version == "1.0"
        assert len(policy.escalation_levels) == 6

    def test_policy_levels_ordered(self, policy: ModelEscalationPolicy) -> None:
        levels = [lv.level for lv in policy.escalation_levels]
        assert levels == sorted(levels)

    def test_policy_covers_full_streak_range(
        self, policy: ModelEscalationPolicy
    ) -> None:
        for streak in [0, 1, 2, 3, 4, 5, 10, 100, 999]:
            matched = any(
                lv.min_streak <= streak <= lv.max_streak
                for lv in policy.escalation_levels
            )
            assert matched, f"No level matched streak {streak}"

    def test_policy_fsm_transitions_complete(
        self, policy: ModelEscalationPolicy
    ) -> None:
        for state_name, transitions in policy.fsm_transitions.items():
            assert "on_pass" in transitions
            assert "on_fail" in transitions

    def test_fallback_when_file_missing(self, tmp_path: Path) -> None:
        policy = load_policy(tmp_path / "nonexistent.yaml")
        assert len(policy.escalation_levels) == 6


# ---------------------------------------------------------------------------
# Pure reducer tests
# ---------------------------------------------------------------------------


class TestReducer:
    def test_single_failure_emits_restart_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        event = _make_event()
        new_state, intents = reduce(empty_state, event, policy)
        assert new_state.loops["closeout"].escalation_level == 1
        assert len(intents) == 1
        assert isinstance(intents[0], IntentRestart)

    def test_two_failures_emits_investigate_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(2):
            state, intents = reduce(state, _make_event(), policy)
        assert state.loops["closeout"].escalation_level == 2
        assert isinstance(intents[0], IntentInvestigate)
        assert intents[0].failing_phase == "B1"
        assert intents[0].consecutive_failures == 2

    def test_three_failures_emits_fix_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(3):
            state, intents = reduce(state, _make_event(), policy)
        assert isinstance(intents[0], IntentFix)
        assert intents[0].consecutive_failures == 3

    def test_four_failures_emits_ticket_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(4):
            state, intents = reduce(state, _make_event(), policy)
        assert isinstance(intents[0], IntentCreateTicket)

    def test_five_failures_emits_alert_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(5):
            state, intents = reduce(state, _make_event(), policy)
        assert isinstance(intents[0], IntentAlertUser)
        assert intents[0].reason  # non-empty reason string

    def test_six_failures_caps_at_level_5(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(6):
            state, intents = reduce(state, _make_event(), policy)
        assert state.loops["closeout"].escalation_level == 5
        assert isinstance(intents[0], IntentAlertUser)

    def test_success_emits_no_intents(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(3):
            state, _ = reduce(state, _make_event(), policy)
        state, intents = reduce(
            state, _make_event(result="pass", phase="complete"), policy
        )
        assert len(intents) == 0
        assert state.loops["closeout"].escalation_level == 0
        assert state.loops["closeout"].failure_streaks == {}

    def test_correlation_id_flows_to_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        cid = "my-correlation-id-123"
        event = _make_event(correlation_id=cid)
        _, intents = reduce(empty_state, event, policy)
        assert intents[0].correlation_id == cid

    def test_error_message_in_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(2):
            state, intents = reduce(
                state, _make_event(error="PostgreSQL unreachable"), policy
            )
        assert isinstance(intents[0], IntentInvestigate)
        assert intents[0].last_error == "PostgreSQL unreachable"

    def test_different_phases_independent_streaks(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state, _ = reduce(empty_state, _make_event(phase="B1"), policy)
        state, intents = reduce(state, _make_event(phase="B2"), policy)
        assert state.loops["closeout"].escalation_level == 1
        assert isinstance(intents[0], IntentRestart)

    def test_highest_streak_determines_intent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(3):
            state, _ = reduce(state, _make_event(phase="B1"), policy)
        state, intents = reduce(state, _make_event(phase="B2"), policy)
        # B1 has 3, B2 has 1 -> level 3 -> fix intent based on B1
        assert isinstance(intents[0], IntentFix)
        assert intents[0].failing_phase == "B1"


# ---------------------------------------------------------------------------
# FSM transitions
# ---------------------------------------------------------------------------


class TestFsmTransitions:
    def test_healthy_to_degraded(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state, _ = reduce(empty_state, _make_event(), policy)
        assert state.loops["closeout"].fsm_state == EnumWatchdogFsmState.DEGRADED

    def test_full_degradation_path(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        expected = [
            EnumWatchdogFsmState.DEGRADED,
            EnumWatchdogFsmState.INVESTIGATING,
            EnumWatchdogFsmState.FIXING,
            EnumWatchdogFsmState.TICKETED,
            EnumWatchdogFsmState.BLOCKED,
            EnumWatchdogFsmState.BLOCKED,
        ]
        state = empty_state
        for i, exp in enumerate(expected):
            state, _ = reduce(state, _make_event(), policy)
            assert state.loops["closeout"].fsm_state == exp, f"Iteration {i}"

    def test_any_state_to_healthy_on_pass(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(4):
            state, _ = reduce(state, _make_event(), policy)
        assert state.loops["closeout"].fsm_state == EnumWatchdogFsmState.TICKETED
        state, _ = reduce(state, _make_event(result="pass", phase="complete"), policy)
        assert state.loops["closeout"].fsm_state == EnumWatchdogFsmState.HEALTHY


# ---------------------------------------------------------------------------
# Independent loop tracking
# ---------------------------------------------------------------------------


class TestIndependentLoops:
    def test_loops_independent(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(2):
            state, _ = reduce(state, _make_event(loop="closeout"), policy)
        state, _ = reduce(state, _make_event(loop="buildloop"), policy)
        assert state.loops["closeout"].escalation_level == 2
        assert state.loops["buildloop"].escalation_level == 1

    def test_success_one_doesnt_reset_other(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(2):
            state, _ = reduce(state, _make_event(loop="closeout"), policy)
        state, _ = reduce(
            state,
            _make_event(loop="buildloop", result="pass", phase="complete"),
            policy,
        )
        assert state.loops["closeout"].escalation_level == 2
        assert state.loops["buildloop"].escalation_level == 0


# ---------------------------------------------------------------------------
# Action recording via reducer
# ---------------------------------------------------------------------------


class TestActionRecording:
    def test_action_event_records_to_state(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state, intents = reduce(empty_state, _make_action_event(), policy)
        assert len(intents) == 0
        assert len(state.loops["closeout"].actions_taken) == 1
        assert state.loops["closeout"].actions_taken[0].action == "restarted"

    def test_actions_prepended(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state, _ = reduce(
            empty_state, _make_action_event(action="restarted", detail="first"), policy
        )
        state, _ = reduce(
            state, _make_action_event(action="investigated", detail="second"), policy
        )
        assert state.loops["closeout"].actions_taken[0].action == "investigated"

    def test_max_actions_enforced(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for i in range(25):
            state, _ = reduce(state, _make_action_event(detail=f"action-{i}"), policy)
        assert len(state.loops["closeout"].actions_taken) <= 20


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


class TestRunHistory:
    def test_runs_trimmed(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(25):
            state, _ = reduce(state, _make_event(), policy)
        assert len(state.loops["closeout"].runs) <= 20

    def test_error_message_truncated(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        event = _make_event(error="x" * 500)
        state, _ = reduce(empty_state, event, policy)
        assert len(state.loops["closeout"].runs[0].error_message or "") <= 200

    def test_run_records_correlation_id(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        cid = "test-cid-456"
        event = _make_event(correlation_id=cid)
        state, _ = reduce(empty_state, event, policy)
        assert state.loops["closeout"].runs[0].correlation_id == cid


# ---------------------------------------------------------------------------
# check_escalation (read-only query)
# ---------------------------------------------------------------------------


class TestCheckEscalation:
    def test_empty_state(self, empty_state: ModelWatchdogState) -> None:
        result = check_escalation(empty_state, "closeout")
        assert result.action == EnumWatchdogAction.RESTART
        assert result.level == 0

    def test_includes_last_error(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state = empty_state
        for _ in range(2):
            state, _ = reduce(
                state, _make_event(error="PostgreSQL unreachable"), policy
            )
        result = check_escalation(state, "closeout")
        assert result.last_error == "PostgreSQL unreachable"

    def test_includes_fsm_state(
        self, empty_state: ModelWatchdogState, policy: ModelEscalationPolicy
    ) -> None:
        state, _ = reduce(empty_state, _make_event(), policy)
        result = check_escalation(state, "closeout")
        assert result.fsm_state == EnumWatchdogFsmState.DEGRADED


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------


class TestStateIO:
    def test_load_missing_returns_empty(self, state_dir: Path) -> None:
        state = load_state(state_dir)
        assert len(state.loops) == 0

    def test_roundtrip(self, state_dir: Path, policy: ModelEscalationPolicy) -> None:
        state = ModelWatchdogState()
        state, _ = reduce(state, _make_event(), policy)
        save_state(state, state_dir)
        loaded = load_state(state_dir)
        assert loaded.loops["closeout"].escalation_level == 1
        assert loaded.loops["closeout"].fsm_state == EnumWatchdogFsmState.DEGRADED

    def test_corrupt_recovery(self, state_dir: Path) -> None:
        (state_dir / "loop-health.json").write_text("{{not json")
        state = load_state(state_dir)
        assert len(state.loops) == 0
        assert (state_dir / "loop-health.corrupt.json").exists()

    def test_atomic_no_tmp_files(self, state_dir: Path) -> None:
        save_state(ModelWatchdogState(), state_dir)
        assert len(list(state_dir.glob("*.tmp.*"))) == 0

    def test_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested"
        save_state(ModelWatchdogState(), nested)
        assert (nested / "loop-health.json").exists()


# ---------------------------------------------------------------------------
# Convenience wrappers (backward compat)
# ---------------------------------------------------------------------------


class TestConvenienceWrappers:
    def test_record_run_works(self, empty_state: ModelWatchdogState) -> None:
        state = record_run(empty_state, "closeout", "fail", "B1", "err")
        assert state.loops["closeout"].escalation_level == 1

    def test_record_action_works(self, empty_state: ModelWatchdogState) -> None:
        state = record_action(empty_state, "closeout", "restarted", "auto-restart")
        assert len(state.loops["closeout"].actions_taken) == 1


# ---------------------------------------------------------------------------
# Shell script integration tests
# ---------------------------------------------------------------------------


class TestShellScripts:
    @pytest.fixture
    def clean_state(self, tmp_path: Path) -> Path:
        omni_home = tmp_path / "omni_home"
        (omni_home / ".onex_state" / "watchdog").mkdir(parents=True)
        return omni_home

    def _run(
        self, script: str, args: list[str], omni_home: Path
    ) -> subprocess.CompletedProcess[str]:
        # Include the project venv so the reducer CLI can find Python 3.12+ with all deps
        venv_bin = str(SCRIPTS_DIR.parent / ".venv" / "bin")
        return subprocess.run(
            [str(SCRIPTS_DIR / script), *args],
            capture_output=True,
            text=True,
            env={
                "ONEX_REGISTRY_ROOT": str(omni_home),
                "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
            },
            timeout=10,
            check=False,
        )

    def test_write_failure(self, clean_state: Path) -> None:
        r = self._run(
            "watchdog-state-write.sh",
            ["closeout", "fail", "B1", "pg down"],
            clean_state,
        )
        assert r.returncode == 0
        assert "escalation=1" in r.stdout

    def test_write_emits_intent_json(self, clean_state: Path) -> None:
        r = self._run(
            "watchdog-state-write.sh",
            ["closeout", "fail", "B1", "pg down"],
            clean_state,
        )
        lines = r.stdout.strip().split("\n")
        assert len(lines) == 2
        intent = json.loads(lines[1])
        assert intent["intent_type"] == "restart"

    def test_write_success_resets(self, clean_state: Path) -> None:
        for _ in range(3):
            self._run(
                "watchdog-state-write.sh",
                ["closeout", "fail", "B1", "err"],
                clean_state,
            )
        r = self._run(
            "watchdog-state-write.sh", ["closeout", "pass", "complete", ""], clean_state
        )
        assert "escalation=0" in r.stdout

    def test_write_invalid_loop(self, clean_state: Path) -> None:
        r = self._run(
            "watchdog-state-write.sh", ["invalid", "fail", "B1", "err"], clean_state
        )
        assert r.returncode != 0

    def test_write_invalid_result(self, clean_state: Path) -> None:
        r = self._run(
            "watchdog-state-write.sh", ["closeout", "invalid", "B1", "err"], clean_state
        )
        assert r.returncode != 0

    def test_check_exit_codes(self, clean_state: Path) -> None:
        # No state = exit 0
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 0

        # Level 1 = exit 0
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 0

        # Level 2 = exit 2
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 2

        # Level 3 = exit 3
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 3

        # Level 4 = exit 4
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 4

        # Level 5 = exit 5
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        assert r.returncode == 5

    def test_check_json_includes_fsm_state(self, clean_state: Path) -> None:
        self._run(
            "watchdog-state-write.sh",
            ["closeout", "fail", "B1", "pg down"],
            clean_state,
        )
        self._run(
            "watchdog-state-write.sh",
            ["closeout", "fail", "B1", "pg down"],
            clean_state,
        )
        r = self._run("watchdog-check.sh", ["closeout"], clean_state)
        data = json.loads(r.stdout)
        assert data["fsm_state"] == "investigating"
        assert data["action"] == "investigate"

    def test_read_missing_state(self, clean_state: Path) -> None:
        r = self._run("watchdog-state-read.sh", ["closeout", "--level"], clean_state)
        assert r.returncode == 2
        assert r.stdout.strip() == "0"

    def test_record_action(self, clean_state: Path) -> None:
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        r = self._run(
            "watchdog-record-action.sh", ["closeout", "restarted", "auto"], clean_state
        )
        assert r.returncode == 0
        assert "Recorded action" in r.stdout

    def test_independent_loops(self, clean_state: Path) -> None:
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        self._run(
            "watchdog-state-write.sh", ["closeout", "fail", "B1", "err"], clean_state
        )
        self._run(
            "watchdog-state-write.sh", ["buildloop", "fail", "exec", "err"], clean_state
        )
        r1 = self._run("watchdog-state-read.sh", ["closeout", "--level"], clean_state)
        r2 = self._run("watchdog-state-read.sh", ["buildloop", "--level"], clean_state)
        assert r1.stdout.strip() == "2"
        assert r2.stdout.strip() == "1"
