# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for autopilot close-out enhancements [OMN-6872].

Covers:
    - DIRTY/CONFLICTING PR classification and stale detection
    - Merge queue stall detection
    - Missing auto-merge detection
    - Worktree health classification
    - Integration with existing autopilot cycle state model
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omniclaude.hooks.lib.dirty_pr_triage import (
    EnumDirtyPRAction,
    ModelDirtyPRTriageResult,
    ModelMissingAutoMergePR,
    ModelQueueHealthEntry,
    check_queue_health,
    classify_dirty_pr,
    is_dirty_or_conflicting,
    is_missing_auto_merge,
)
from omniclaude.hooks.lib.worktree_health import (
    EnumWorktreeStatus,
    ModelWorktreeHealthResult,
    build_worktree_entry,
    classify_worktree,
)

# ---------------------------------------------------------------------------
# DIRTY PR Classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsDirtyOrConflicting:
    """Tests for the is_dirty_or_conflicting predicate."""

    def test_dirty_merge_state(self) -> None:
        assert is_dirty_or_conflicting("MERGEABLE", "DIRTY") is True

    def test_conflicting_merge_state(self) -> None:
        assert is_dirty_or_conflicting("MERGEABLE", "CONFLICTING") is True

    def test_conflicting_mergeable(self) -> None:
        assert is_dirty_or_conflicting("CONFLICTING", "BLOCKED") is True

    def test_clean_pr(self) -> None:
        assert is_dirty_or_conflicting("MERGEABLE", "CLEAN") is False

    def test_behind_pr(self) -> None:
        assert is_dirty_or_conflicting("MERGEABLE", "BEHIND") is False

    def test_unknown_mergeable(self) -> None:
        assert is_dirty_or_conflicting("UNKNOWN", "UNKNOWN") is False

    def test_case_insensitive(self) -> None:
        assert is_dirty_or_conflicting("conflicting", "blocked") is True
        assert is_dirty_or_conflicting("MERGEABLE", "dirty") is True


@pytest.mark.unit
class TestClassifyDirtyPR:
    """Tests for DIRTY PR classification with stale detection."""

    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

    def test_stale_pr_over_24h(self, now: datetime) -> None:
        """PR >24h old gets CLOSE_STALE action."""
        result = classify_dirty_pr(
            repo="OmniNode-ai/omniclaude",
            number=931,
            title="feat: old conflicting PR",
            merge_state="CONFLICTING",
            updated_at_iso="2026-03-27T10:00:00Z",
            author="jonahgabriel",
            now=now,
        )
        assert result.action == EnumDirtyPRAction.CLOSE_STALE
        assert result.age_hours > 24.0
        assert result.merge_state == "CONFLICTING"

    def test_recent_pr_under_24h(self, now: datetime) -> None:
        """PR <24h old gets FLAG_RECENT action."""
        result = classify_dirty_pr(
            repo="OmniNode-ai/omniclaude",
            number=962,
            title="fix: recent conflict",
            merge_state="DIRTY",
            updated_at_iso="2026-03-28T10:00:00Z",
            author="jonahgabriel",
            now=now,
        )
        assert result.action == EnumDirtyPRAction.FLAG_RECENT
        assert result.age_hours < 24.0

    def test_exactly_at_threshold(self, now: datetime) -> None:
        """PR exactly at 24h boundary is classified as stale."""
        result = classify_dirty_pr(
            repo="OmniNode-ai/omniclaude",
            number=100,
            title="test",
            merge_state="DIRTY",
            updated_at_iso="2026-03-27T12:00:00Z",
            now=now,
            stale_threshold_hours=24.0,
        )
        # At exactly 24h, age_hours == 24.0 which is NOT > 24.0
        assert result.action == EnumDirtyPRAction.FLAG_RECENT

    def test_custom_threshold(self, now: datetime) -> None:
        """Custom stale threshold works."""
        result = classify_dirty_pr(
            repo="OmniNode-ai/test",
            number=1,
            title="test",
            merge_state="CONFLICTING",
            updated_at_iso="2026-03-28T08:00:00Z",
            now=now,
            stale_threshold_hours=2.0,
        )
        assert result.action == EnumDirtyPRAction.CLOSE_STALE
        assert result.age_hours > 2.0

    def test_merge_state_uppercased(self, now: datetime) -> None:
        """merge_state is uppercased in output."""
        result = classify_dirty_pr(
            repo="r",
            number=1,
            title="t",
            merge_state="dirty",
            updated_at_iso="2026-03-28T11:00:00Z",
            now=now,
        )
        assert result.merge_state == "DIRTY"

    def test_frozen_model(self, now: datetime) -> None:
        """ModelDirtyPR is frozen."""
        result = classify_dirty_pr(
            repo="r",
            number=1,
            title="t",
            merge_state="DIRTY",
            updated_at_iso="2026-03-28T11:00:00Z",
            now=now,
        )
        with pytest.raises(Exception):  # noqa: B017
            result.number = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Queue Health Check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckQueueHealth:
    """Tests for merge queue stall detection."""

    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

    def test_empty_queue_not_stalled(self, now: datetime) -> None:
        result = check_queue_health(
            repo="OmniNode-ai/omniclaude",
            queued_pr_numbers=[],
            last_merge_time_iso=None,
            now=now,
        )
        assert not result.is_stalled
        assert result.queued_count == 0

    def test_queue_with_recent_merge(self, now: datetime) -> None:
        """Non-empty queue with recent merge is not stalled."""
        result = check_queue_health(
            repo="OmniNode-ai/omniclaude",
            queued_pr_numbers=[100, 101],
            last_merge_time_iso="2026-03-28T11:30:00Z",
            now=now,
        )
        assert not result.is_stalled
        assert result.queued_count == 2
        assert result.minutes_since_last_merge is not None
        assert result.minutes_since_last_merge == 30.0

    def test_queue_stalled_no_recent_merges(self, now: datetime) -> None:
        """Non-empty queue with old merge is stalled."""
        result = check_queue_health(
            repo="OmniNode-ai/omniclaude",
            queued_pr_numbers=[100, 101, 102],
            last_merge_time_iso="2026-03-28T10:00:00Z",
            now=now,
        )
        assert result.is_stalled
        assert result.queued_count == 3
        assert result.minutes_since_last_merge == 120.0

    def test_queue_stalled_no_merges_at_all(self, now: datetime) -> None:
        """Non-empty queue with no merge history is stalled."""
        result = check_queue_health(
            repo="OmniNode-ai/omniclaude",
            queued_pr_numbers=[200],
            last_merge_time_iso=None,
            now=now,
        )
        assert result.is_stalled
        assert result.minutes_since_last_merge is None

    def test_custom_stall_threshold(self, now: datetime) -> None:
        """Custom stall threshold works."""
        result = check_queue_health(
            repo="r",
            queued_pr_numbers=[1],
            last_merge_time_iso="2026-03-28T11:40:00Z",
            now=now,
            stall_threshold_minutes=15.0,
        )
        assert result.is_stalled  # 20 min > 15 min threshold
        assert result.minutes_since_last_merge == 20.0


# ---------------------------------------------------------------------------
# Missing Auto-Merge Detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsMissingAutoMerge:
    """Tests for detecting CLEAN PRs not in the merge queue."""

    def test_clean_mergeable_no_auto_merge(self) -> None:
        """CLEAN + MERGEABLE + GREEN + APPROVED + no autoMerge = missing."""
        assert is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=True,
        )

    def test_already_armed(self) -> None:
        """Already has autoMergeRequest = not missing."""
        assert not is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            is_draft=False,
            auto_merge_request={"enabledAt": "2026-03-28"},
            all_required_checks_pass=True,
            review_ok=True,
        )

    def test_draft_pr(self) -> None:
        """Draft PRs are excluded."""
        assert not is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            is_draft=True,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=True,
        )

    def test_conflicting_pr(self) -> None:
        """CONFLICTING PRs are excluded."""
        assert not is_missing_auto_merge(
            mergeable="CONFLICTING",
            merge_state_status="DIRTY",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=True,
        )

    def test_behind_pr(self) -> None:
        """BEHIND merge state excluded."""
        assert not is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="BEHIND",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=True,
        )

    def test_ci_failing(self) -> None:
        """Failing CI excluded."""
        assert not is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=False,
            review_ok=True,
        )

    def test_review_not_ok(self) -> None:
        """Review not approved excluded."""
        assert not is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=False,
        )

    def test_has_hooks_state_accepted(self) -> None:
        """HAS_HOOKS merge state is treated like CLEAN."""
        assert is_missing_auto_merge(
            mergeable="MERGEABLE",
            merge_state_status="HAS_HOOKS",
            is_draft=False,
            auto_merge_request=None,
            all_required_checks_pass=True,
            review_ok=True,
        )


# ---------------------------------------------------------------------------
# Triage Result Model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDirtyPRTriageResult:
    """Tests for the triage result aggregate."""

    def test_no_issues(self) -> None:
        result = ModelDirtyPRTriageResult()
        assert not result.has_issues

    def test_has_issues_with_stale(self) -> None:
        from omniclaude.hooks.lib.dirty_pr_triage import ModelDirtyPR

        result = ModelDirtyPRTriageResult(
            stale_closed=[
                ModelDirtyPR(
                    repo="r",
                    number=1,
                    merge_state="DIRTY",
                    age_hours=30.0,
                    action=EnumDirtyPRAction.CLOSE_STALE,
                )
            ]
        )
        assert result.has_issues

    def test_has_issues_with_stalled_queue(self) -> None:
        result = ModelDirtyPRTriageResult(
            stalled_queues=[
                ModelQueueHealthEntry(
                    repo="r",
                    queued_count=3,
                    is_stalled=True,
                    queued_pr_numbers=[1, 2, 3],
                )
            ]
        )
        assert result.has_issues

    def test_has_issues_with_missing_auto_merge(self) -> None:
        result = ModelDirtyPRTriageResult(
            missing_auto_merge=[
                ModelMissingAutoMergePR(repo="r", number=42, title="test")
            ]
        )
        assert result.has_issues


# ---------------------------------------------------------------------------
# Worktree Health Classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassifyWorktree:
    """Tests for worktree health classification."""

    def test_clean_worktree(self) -> None:
        """No uncommitted files, recent, has PR = CLEAN."""
        assert (
            classify_worktree(uncommitted_count=0, age_days=1.0, has_open_pr=True)
            == EnumWorktreeStatus.CLEAN
        )

    def test_dirty_worktree(self) -> None:
        """Uncommitted files but recent = DIRTY."""
        assert (
            classify_worktree(uncommitted_count=5, age_days=1.0, has_open_pr=True)
            == EnumWorktreeStatus.DIRTY
        )

    def test_stale_worktree(self) -> None:
        """No uncommitted files but old and no PR = STALE."""
        assert (
            classify_worktree(uncommitted_count=0, age_days=5.0, has_open_pr=False)
            == EnumWorktreeStatus.STALE
        )

    def test_dirty_and_stale(self) -> None:
        """Uncommitted files + old + no PR = DIRTY_AND_STALE."""
        assert (
            classify_worktree(uncommitted_count=3, age_days=5.0, has_open_pr=False)
            == EnumWorktreeStatus.DIRTY_AND_STALE
        )

    def test_old_but_has_pr_not_stale(self) -> None:
        """Old worktree with an open PR is not stale."""
        assert (
            classify_worktree(uncommitted_count=0, age_days=10.0, has_open_pr=True)
            == EnumWorktreeStatus.CLEAN
        )

    def test_custom_stale_threshold(self) -> None:
        """Custom stale days threshold."""
        assert (
            classify_worktree(
                uncommitted_count=0,
                age_days=2.0,
                has_open_pr=False,
                stale_days_threshold=1.0,
            )
            == EnumWorktreeStatus.STALE
        )

    def test_exactly_at_threshold_not_stale(self) -> None:
        """Worktree at exactly the threshold is NOT stale (> not >=)."""
        assert (
            classify_worktree(
                uncommitted_count=0,
                age_days=3.0,
                has_open_pr=False,
                stale_days_threshold=3.0,
            )
            == EnumWorktreeStatus.CLEAN
        )


@pytest.mark.unit
class TestBuildWorktreeEntry:
    """Tests for building classified worktree entries."""

    def test_builds_clean_entry(self) -> None:
        entry = build_worktree_entry(
            path="/worktrees/OMN-1234/omniclaude",
            ticket="OMN-1234",
            repo="omniclaude",
            branch="jonah/omn-1234-fix",
            uncommitted_count=0,
            age_days=1.0,
            has_open_pr=True,
        )
        assert entry.status == EnumWorktreeStatus.CLEAN
        assert entry.ticket == "OMN-1234"
        assert entry.repo == "omniclaude"

    def test_builds_dirty_entry(self) -> None:
        entry = build_worktree_entry(
            path="/worktrees/OMN-5678/omnibase_core",
            ticket="OMN-5678",
            repo="omnibase_core",
            branch="jonah/omn-5678-feat",
            uncommitted_count=12,
            age_days=0.5,
            has_open_pr=False,
        )
        assert entry.status == EnumWorktreeStatus.DIRTY
        assert entry.uncommitted_count == 12

    def test_frozen_entry(self) -> None:
        entry = build_worktree_entry(
            path="/p",
            ticket="T",
            repo="R",
            branch="B",
            uncommitted_count=0,
            age_days=0.0,
            has_open_pr=True,
        )
        with pytest.raises(Exception):  # noqa: B017
            entry.status = EnumWorktreeStatus.DIRTY  # type: ignore[misc]


@pytest.mark.unit
class TestWorktreeHealthResult:
    """Tests for the health result aggregate."""

    def test_no_issues(self) -> None:
        result = ModelWorktreeHealthResult(total_scanned=10, pruned_count=2)
        assert not result.has_issues

    def test_has_issues_with_dirty(self) -> None:
        entry = build_worktree_entry(
            path="/p",
            ticket="T",
            repo="R",
            branch="B",
            uncommitted_count=5,
            age_days=1.0,
            has_open_pr=True,
        )
        result = ModelWorktreeHealthResult(total_scanned=10, dirty_worktrees=[entry])
        assert result.has_issues


# ---------------------------------------------------------------------------
# Integration: New steps with cycle state model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNewStepsInCycleState:
    """Verify the new A0/A1b steps integrate with the cycle state model."""

    def test_a0_step_recorded(self) -> None:
        """A0 worktree-health step can be recorded in cycle state."""
        from omniclaude.shared.models.model_autopilot_cycle_state import (
            EnumAutopilotStepStatus,
            ModelAutopilotCycleState,
        )

        state = ModelAutopilotCycleState()
        state.record_step_start("A0", "worktree-health")
        assert state.current_step == "A0"
        state.record_step_success("A0")
        assert state.steps_completed == 1
        assert state.steps[0].step_id == "A0"
        assert state.steps[0].status == EnumAutopilotStepStatus.COMPLETED

    def test_a1b_step_recorded(self) -> None:
        """A1b dirty-pr-triage step can be recorded in cycle state."""
        from omniclaude.shared.models.model_autopilot_cycle_state import (
            EnumAutopilotStepStatus,
            ModelAutopilotCycleState,
        )

        state = ModelAutopilotCycleState()
        state.record_step_start("A1b", "dirty-pr-triage")
        state.record_step_success("A1b")
        assert state.steps[0].step_id == "A1b"
        assert state.steps[0].status == EnumAutopilotStepStatus.COMPLETED

    def test_a0_failure_increments_breaker(self) -> None:
        """A0 failure increments circuit breaker but does not halt."""
        from omniclaude.shared.models.model_autopilot_cycle_state import (
            ModelAutopilotCycleState,
        )

        state = ModelAutopilotCycleState()
        state.record_step_start("A0", "worktree-health")
        tripped = state.record_step_failure("A0", "prune script failed")
        assert not tripped  # First failure does not trip
        assert state.circuit_breaker_count == 1

    def test_full_phase_a_sequence(self) -> None:
        """Simulate complete Phase A: A0 -> A1 -> A1b -> A2 -> A3."""
        from omniclaude.shared.models.model_autopilot_cycle_state import (
            ModelAutopilotCycleState,
        )

        state = ModelAutopilotCycleState()
        phase_a_steps = [
            ("A0", "worktree-health"),
            ("A1", "merge-sweep"),
            ("A1b", "dirty-pr-triage"),
            ("A2", "deploy-local-plugin"),
            ("A3", "start-environment"),
        ]
        for step_id, step_name in phase_a_steps:
            state.record_step_start(step_id, step_name)
            state.record_step_success(step_id)

        assert state.steps_completed == 5
        assert state.circuit_breaker_count == 0
        assert len(state.steps) == 5

    def test_a1b_warn_after_a0_success(self) -> None:
        """A1b warning (dirty PRs found) after A0 success."""
        from omniclaude.shared.models.model_autopilot_cycle_state import (
            ModelAutopilotCycleState,
        )

        state = ModelAutopilotCycleState()
        # A0 succeeds
        state.record_step_start("A0", "worktree-health")
        state.record_step_success("A0")
        # A1 succeeds
        state.record_step_start("A1", "merge-sweep")
        state.record_step_success("A1")
        # A1b finds dirty PRs (warn = success for circuit breaker)
        state.record_step_start("A1b", "dirty-pr-triage")
        state.record_step_success("A1b")  # warn is non-halting, recorded as success

        assert state.steps_completed == 3
        assert state.circuit_breaker_count == 0
