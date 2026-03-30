# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end smoke tests for autopilot hardening (OMN-6501).

Covers:
    - OMN-6491: Cycle state file schema (ModelAutopilotCycleState)
    - OMN-6492: Cycle-level mutex (AutopilotMutex)
    - OMN-6505: Strike tracker / circuit breaker
    - OMN-6503: Hook health probe
    - OMN-6506: PR track classification
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID

import pytest

# Add merge_planner parent to sys.path so `from merge_planner.xxx` works
_lib_dir = str(
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "_lib"
)
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from omniclaude.shared.models.model_autopilot_cycle_state import (
    EnumAutopilotStepStatus,
    ModelAutopilotCycleState,
    ModelAutopilotStepRecord,
)

# ---------------------------------------------------------------------------
# OMN-6491: Cycle state model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAutopilotCycleState:
    """Tests for the autopilot cycle state model."""

    def test_default_construction(self) -> None:
        state = ModelAutopilotCycleState()
        assert isinstance(state.run_id, UUID)
        assert state.current_step is None
        assert state.steps_completed == 0
        assert state.steps_failed == 0
        assert state.circuit_breaker_count == 0
        assert state.last_error is None
        assert state.mode == "close-out"
        assert state.steps == []

    def test_record_step_start(self) -> None:
        state = ModelAutopilotCycleState()
        state.record_step_start("A1", "merge-sweep")
        assert state.current_step == "A1"
        assert len(state.steps) == 1
        assert state.steps[0].step_id == "A1"
        assert state.steps[0].step_name == "merge-sweep"
        assert state.steps[0].status == EnumAutopilotStepStatus.RUNNING
        assert state.steps[0].started_at is not None

    def test_record_step_success(self) -> None:
        state = ModelAutopilotCycleState()
        state.record_step_start("A1", "merge-sweep")
        state.record_step_success("A1")
        assert state.current_step is None
        assert state.steps_completed == 1
        assert state.circuit_breaker_count == 0
        assert state.steps[0].status == EnumAutopilotStepStatus.COMPLETED
        assert state.steps[0].completed_at is not None

    def test_record_step_failure(self) -> None:
        state = ModelAutopilotCycleState()
        state.record_step_start("B5", "integration-sweep")
        tripped = state.record_step_failure("B5", "CI check failed")
        assert not tripped
        assert state.current_step is None
        assert state.steps_failed == 1
        assert state.circuit_breaker_count == 1
        assert state.last_error == "CI check failed"
        assert state.steps[0].status == EnumAutopilotStepStatus.FAILED

    def test_circuit_breaker_trips_at_3(self) -> None:
        """Circuit breaker trips after 3 consecutive failures."""
        state = ModelAutopilotCycleState()
        for i in range(3):
            step_id = f"step_{i}"
            state.record_step_start(step_id, f"step-{i}")
            tripped = state.record_step_failure(step_id, f"error {i}")
            if i < 2:
                assert not tripped
            else:
                assert tripped
        assert state.circuit_breaker_count == 3
        assert state.steps_failed == 3

    def test_success_resets_circuit_breaker(self) -> None:
        """A successful step resets the consecutive failure counter."""
        state = ModelAutopilotCycleState()
        # Two failures
        state.record_step_start("A1", "step1")
        state.record_step_failure("A1", "err1")
        state.record_step_start("A2", "step2")
        state.record_step_failure("A2", "err2")
        assert state.circuit_breaker_count == 2
        # One success resets
        state.record_step_start("A3", "step3")
        state.record_step_success("A3")
        assert state.circuit_breaker_count == 0
        assert state.last_error is None

    def test_error_truncation(self) -> None:
        """Long error messages are truncated to 2000 chars."""
        state = ModelAutopilotCycleState()
        state.record_step_start("X1", "long-error")
        long_error = "x" * 3000
        state.record_step_failure("X1", long_error)
        assert len(state.last_error) == 2000  # type: ignore[arg-type]

    def test_serialization_roundtrip(self) -> None:
        """State can be serialized to JSON and back."""
        state = ModelAutopilotCycleState(mode="build")
        state.record_step_start("A1", "merge-sweep")
        state.record_step_success("A1")

        data = state.model_dump(mode="json")
        restored = ModelAutopilotCycleState.model_validate(data)
        assert restored.run_id == state.run_id
        assert restored.steps_completed == 1
        assert restored.mode == "build"
        assert len(restored.steps) == 1


@pytest.mark.unit
class TestModelAutopilotStepRecord:
    def test_frozen_model(self) -> None:
        record = ModelAutopilotStepRecord(step_id="A1", step_name="test")
        with pytest.raises(Exception):  # noqa: B017
            record.step_id = "A2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OMN-6492: Mutex
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutopilotMutex:
    """Tests for the file-based autopilot mutex."""

    @pytest.fixture(autouse=True)
    def _setup_state_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

    def test_acquire_and_release(self) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import AutopilotMutex

        mutex = AutopilotMutex()
        mutex.acquire(run_id="test-run-1")
        assert mutex.is_locked()
        mutex.release()
        assert not mutex.is_locked()

    def test_double_acquire_raises(self) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import (
            AutopilotMutex,
            AutopilotMutexError,
        )

        mutex = AutopilotMutex()
        mutex.acquire(run_id="test-run-1")
        with pytest.raises(AutopilotMutexError, match="mutex held"):
            mutex.acquire(run_id="test-run-2")
        mutex.release()

    def test_stale_lock_reclaimed(self, tmp_path: Path) -> None:
        """Stale locks (> threshold) are automatically reclaimed."""
        from omniclaude.hooks.lib.autopilot_state_manager import AutopilotMutex

        # Write a lock with a dead PID and old timestamp
        lock_path = tmp_path / "autopilot.lock"
        lock_data = {
            "pid": -99999,  # Non-existent PID
            "timestamp": time.time() - 100,
            "run_id": "old-run",
        }
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

        # Use 0-second threshold so the lock is considered stale
        mutex = AutopilotMutex(stale_seconds=0)
        # Should reclaim stale lock and acquire
        mutex.acquire(run_id="new-run")
        # Verify the lock file now has our PID
        new_data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert new_data["run_id"] == "new-run"
        assert new_data["pid"] == os.getpid()
        mutex.release()

    def test_release_idempotent(self) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import AutopilotMutex

        mutex = AutopilotMutex()
        mutex.release()  # No-op, should not raise
        mutex.acquire(run_id="test")
        mutex.release()
        mutex.release()  # Double release is safe


# ---------------------------------------------------------------------------
# OMN-6491 + OMN-6492: State persistence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStatePersistence:
    """Tests for cycle state save/load."""

    @pytest.fixture(autouse=True)
    def _setup_state_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

    def test_save_and_load(self) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import (
            load_cycle_state,
            save_cycle_state,
        )

        state = ModelAutopilotCycleState(mode="close-out")
        state.record_step_start("A1", "merge-sweep")
        state.record_step_success("A1")

        path = save_cycle_state(state)
        assert path.exists()

        loaded = load_cycle_state()
        assert loaded is not None
        assert loaded.run_id == state.run_id
        assert loaded.steps_completed == 1

    def test_load_missing_returns_none(self) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import load_cycle_state

        assert load_cycle_state() is None

    def test_load_corrupt_returns_none(self, tmp_path: Path) -> None:
        from omniclaude.hooks.lib.autopilot_state_manager import load_cycle_state

        corrupt_path = tmp_path / "autopilot-cycle.yaml"
        corrupt_path.write_text("not-valid-json{{{", encoding="utf-8")
        assert load_cycle_state() is None


# ---------------------------------------------------------------------------
# OMN-6505: Strike tracker (circuit breaker via cycle state)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStrikeTracker:
    """Tests for strike tracking integrated with cycle state."""

    def test_full_cycle_with_circuit_breaker(self) -> None:
        """Simulate an autopilot cycle where the circuit breaker trips."""
        state = ModelAutopilotCycleState()

        # Step 1: success
        state.record_step_start("A1", "merge-sweep")
        state.record_step_success("A1")
        assert state.circuit_breaker_count == 0

        # Steps 2-4: three consecutive failures -> trip
        state.record_step_start("B1", "dod-sweep")
        tripped = state.record_step_failure("B1", "dod check failed")
        assert not tripped

        state.record_step_start("B2", "aislop-sweep")
        tripped = state.record_step_failure("B2", "aislop failed")
        assert not tripped

        state.record_step_start("B3", "bus-audit")
        tripped = state.record_step_failure("B3", "bus unhealthy")
        assert tripped
        assert state.circuit_breaker_count == 3
        assert state.steps_completed == 1
        assert state.steps_failed == 3

    def test_interleaved_success_prevents_trip(self) -> None:
        """Success between failures prevents circuit breaker from tripping."""
        state = ModelAutopilotCycleState()

        state.record_step_start("A1", "step1")
        state.record_step_failure("A1", "err1")

        state.record_step_start("A2", "step2")
        state.record_step_failure("A2", "err2")

        # Success resets counter
        state.record_step_start("A3", "step3")
        state.record_step_success("A3")

        state.record_step_start("B1", "step4")
        tripped = state.record_step_failure("B1", "err3")
        assert not tripped
        assert state.circuit_breaker_count == 1


# ---------------------------------------------------------------------------
# OMN-6503: Hook health probe
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHookHealthProbe:
    """Tests for the session-start hook health probe."""

    def test_probe_returns_result(self) -> None:
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        result = probe_hook_health()
        # Should never raise, always returns a result
        assert result is not None
        assert isinstance(result.warnings, list)

    def test_probe_no_plugin_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        result = probe_hook_health()
        # May or may not find hooks.json depending on working directory
        assert result is not None

    def test_probe_with_hooks_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        # Create a minimal hooks.json
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        scripts_dir = hooks_dir / "scripts"
        scripts_dir.mkdir()

        # Create a real executable script
        script = scripts_dir / "test-hook.sh"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(0o755)

        hooks_json = hooks_dir / "hooks.json"
        hooks_json.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": str(script),
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        result = probe_hook_health()
        assert result.total_hooks == 1
        assert result.healthy_hooks == 1
        assert result.healthy

    def test_probe_detects_missing_script(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()

        hooks_json = hooks_dir / "hooks.json"
        hooks_json.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "/nonexistent/script.sh",
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        result = probe_hook_health()
        assert result.total_hooks == 1
        assert result.healthy_hooks == 0
        assert len(result.unhealthy_hooks) == 1
        assert result.degraded is False  # No healthy hooks, so not "degraded"

    def test_health_result_properties(self) -> None:
        from omniclaude.hooks.hook_health_probe import ModelHookHealthResult

        # All healthy
        r1 = ModelHookHealthResult(total_hooks=3, healthy_hooks=3)
        assert r1.healthy
        assert not r1.degraded

        # Degraded (some healthy, some not)
        r2 = ModelHookHealthResult(
            total_hooks=3,
            healthy_hooks=2,
            unhealthy_hooks=["/bad.sh"],
        )
        assert not r2.healthy
        assert r2.degraded


# ---------------------------------------------------------------------------
# OMN-6506: PR track classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPRTrackClassifier:
    """Tests for merge-sweep Track A/B/C PR classification."""

    def test_track_a_ready_to_merge(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=42,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            mergeable_state="MERGEABLE",
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_A
        assert result.number == 42

    def test_track_b_unresolved_comments(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=43,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            mergeable_state="MERGEABLE",
            has_unresolved_comments=True,
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_B

    def test_track_c_ci_failure(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=44,
            repo="OmniNode-ai/omniclaude",
            ci_status="failure",
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_C

    def test_track_c_draft(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=45,
            repo="OmniNode-ai/omniclaude",
            is_draft=True,
            ci_status="success",
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_C

    def test_track_c_conflicts(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=46,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            mergeable_state="CONFLICTING",
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_C

    def test_track_c_changes_requested(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=47,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            review_decision="changes_requested",
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_C

    def test_track_c_merge_queue(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=48,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            in_merge_queue=True,
        )
        result = classify_pr_track(pr)
        assert result.track == EnumMergeSweepTrack.TRACK_C

    def test_is_in_merge_queue_true(self) -> None:
        """OMN-6468: is_in_merge_queue returns True for queued PRs."""
        from merge_planner.track_classifier import (
            ModelPRClassificationInput,
            is_in_merge_queue,
        )

        pr = ModelPRClassificationInput(
            number=50,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            in_merge_queue=True,
        )
        assert is_in_merge_queue(pr) is True

    def test_is_in_merge_queue_false(self) -> None:
        """OMN-6468: is_in_merge_queue returns False for normal PRs."""
        from merge_planner.track_classifier import (
            ModelPRClassificationInput,
            is_in_merge_queue,
        )

        pr = ModelPRClassificationInput(
            number=51,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            in_merge_queue=False,
        )
        assert is_in_merge_queue(pr) is False

    def test_merge_queue_pr_skipped_in_classification(self) -> None:
        """OMN-6468: Merge queue PRs get reason 'In merge queue — skip'."""
        from merge_planner.track_classifier import (
            ModelPRClassificationInput,
            classify_pr_track,
        )

        pr = ModelPRClassificationInput(
            number=52,
            repo="OmniNode-ai/omniclaude",
            ci_status="success",
            in_merge_queue=True,
        )
        result = classify_pr_track(pr)
        assert "merge queue" in result.reason.lower()

    def test_classify_batch(self) -> None:
        from merge_planner.track_classifier import (
            EnumMergeSweepTrack,
            ModelPRClassificationInput,
            classify_prs,
        )

        prs = [
            ModelPRClassificationInput(number=1, repo="r", ci_status="success"),
            ModelPRClassificationInput(
                number=2,
                repo="r",
                ci_status="success",
                has_unresolved_comments=True,
            ),
            ModelPRClassificationInput(number=3, repo="r", ci_status="failure"),
        ]
        results = classify_prs(prs)
        assert len(results[EnumMergeSweepTrack.TRACK_A]) == 1
        assert len(results[EnumMergeSweepTrack.TRACK_B]) == 1
        assert len(results[EnumMergeSweepTrack.TRACK_C]) == 1


# ---------------------------------------------------------------------------
# E2E: Full autopilot cycle simulation (OMN-6501)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutopilotE2ESmokeTest:
    """Simulates a full autopilot cycle exercising all hardening features."""

    @pytest.fixture(autouse=True)
    def _setup_state_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        self.tmp_path = tmp_path

    def test_full_cycle_happy_path(self) -> None:
        """Full cycle: acquire mutex, run steps, persist state, release."""
        from omniclaude.hooks.lib.autopilot_state_manager import (
            AutopilotMutex,
            load_cycle_state,
            save_cycle_state,
        )

        # 1. Acquire mutex
        mutex = AutopilotMutex()
        state = ModelAutopilotCycleState(mode="close-out")
        mutex.acquire(run_id=str(state.run_id))

        try:
            # 2. Run steps
            steps = [
                ("A1", "merge-sweep"),
                ("A2", "deploy-plugin"),
                ("B5", "integration"),
            ]
            for step_id, step_name in steps:
                state.record_step_start(step_id, step_name)
                save_cycle_state(state)
                # Simulate work...
                state.record_step_success(step_id)
                save_cycle_state(state)

            # 3. Verify state
            assert state.steps_completed == 3
            assert state.steps_failed == 0
            assert state.circuit_breaker_count == 0
        finally:
            mutex.release()

        # 4. Verify persistence
        loaded = load_cycle_state()
        assert loaded is not None
        assert loaded.steps_completed == 3

        # 5. Verify mutex released
        assert not mutex.is_locked()

    def test_full_cycle_circuit_breaker_trip(self) -> None:
        """Cycle where 3 consecutive failures trip the circuit breaker."""
        from omniclaude.hooks.lib.autopilot_state_manager import (
            AutopilotMutex,
            save_cycle_state,
        )

        mutex = AutopilotMutex()
        state = ModelAutopilotCycleState(mode="close-out")
        mutex.acquire(run_id=str(state.run_id))

        try:
            # Step 1: success
            state.record_step_start("A1", "merge-sweep")
            state.record_step_success("A1")

            # Steps 2-4: three consecutive failures
            for i, (sid, sname) in enumerate(
                [("B1", "dod-sweep"), ("B2", "aislop"), ("B3", "bus-audit")]
            ):
                state.record_step_start(sid, sname)
                tripped = state.record_step_failure(sid, f"{sname} failed")
                save_cycle_state(state)
                if i == 2:
                    assert tripped, "Circuit breaker should trip at 3"
                    break
        finally:
            mutex.release()

        assert state.circuit_breaker_count == 3
        assert state.steps_failed == 3
        assert state.steps_completed == 1
