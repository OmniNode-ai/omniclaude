# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for agent-idle shipper models [OMN-6868].

Verifies:
- EnumShipperAction values and membership
- ModelStallDetection computed properties (has_uncommitted_work, needs_shipping)
- ModelShipperResult with all action types
- ModelShipperReport aggregation
- Clean worktree (no-op), staged changes, unpushed commits, no PR, pre-commit failure
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.agent_shipper import (
    EnumShipperAction,
    ModelShipperReport,
    ModelShipperResult,
    ModelStallDetection,
)

# ---------------------------------------------------------------------------
# EnumShipperAction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnumShipperAction:
    def test_all_values_present(self) -> None:
        expected = {"no_op", "committed", "pushed", "pr_created", "recovery_ticket"}
        assert {a.value for a in EnumShipperAction} == expected

    def test_str_enum(self) -> None:
        assert isinstance(EnumShipperAction.NO_OP, str)
        assert EnumShipperAction.PR_CREATED == "pr_created"


# ---------------------------------------------------------------------------
# ModelStallDetection — clean worktree (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStallDetectionClean:
    """A worktree with no changes should be a no-op."""

    def test_clean_worktree_no_uncommitted(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-1234/omniclaude",
            branch="jonah/omn-1234-feature",
            repo="omniclaude",
        )
        assert det.has_uncommitted_work is False
        assert det.needs_shipping is False

    def test_clean_with_remote_and_pr(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-1234/omniclaude",
            branch="jonah/omn-1234-feature",
            repo="omniclaude",
            has_remote=True,
            has_pr=True,
        )
        assert det.has_uncommitted_work is False
        assert det.needs_shipping is False


# ---------------------------------------------------------------------------
# ModelStallDetection — staged changes (auto-commit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStallDetectionStaged:
    """Staged but uncommitted changes should trigger shipping."""

    def test_staged_needs_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-2000/omnibase_core",
            branch="jonah/omn-2000-fix",
            repo="omnibase_core",
            has_staged=True,
        )
        assert det.has_uncommitted_work is True
        assert det.needs_shipping is True

    def test_unstaged_needs_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-2000/omnibase_core",
            branch="jonah/omn-2000-fix",
            repo="omnibase_core",
            has_unstaged=True,
        )
        assert det.has_uncommitted_work is True
        assert det.needs_shipping is True

    def test_untracked_needs_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-2000/omnibase_core",
            branch="jonah/omn-2000-fix",
            repo="omnibase_core",
            has_untracked=True,
        )
        assert det.has_uncommitted_work is True
        assert det.needs_shipping is True


# ---------------------------------------------------------------------------
# ModelStallDetection — unpushed commits (auto-push)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStallDetectionUnpushed:
    """Committed but unpushed work should trigger shipping."""

    def test_unpushed_commits_needs_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-3000/omnibase_infra",
            branch="jonah/omn-3000-infra",
            repo="omnibase_infra",
            commits_unpushed=3,
            has_remote=True,
        )
        assert det.has_uncommitted_work is False
        assert det.needs_shipping is True


# ---------------------------------------------------------------------------
# ModelStallDetection — pushed but no PR (auto-create)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStallDetectionNoPR:
    """Pushed branch with no open PR should trigger PR creation."""

    def test_pushed_no_pr_needs_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-4000/omnidash",
            branch="jonah/omn-4000-dash",
            repo="omnidash",
            has_remote=True,
            has_pr=False,
            commits_unpushed=0,
        )
        assert det.has_uncommitted_work is False
        assert det.needs_shipping is True

    def test_pushed_with_pr_no_shipping(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-4000/omnidash",
            branch="jonah/omn-4000-dash",
            repo="omnidash",
            has_remote=True,
            has_pr=True,
            commits_unpushed=0,
        )
        assert det.needs_shipping is False


# ---------------------------------------------------------------------------
# ModelStallDetection — frozen model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStallDetectionFrozen:
    def test_frozen_raises_on_mutation(self) -> None:
        det = ModelStallDetection(
            worktree_path="/omni_worktrees/OMN-1/a",
            branch="b",
            repo="c",
        )
        with pytest.raises(Exception):  # noqa: B017
            det.has_staged = True  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ModelStallDetection(
                worktree_path="/a",
                branch="b",
                repo="c",
                bogus_field="x",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# ModelShipperResult — all action types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShipperResult:
    def test_no_op_result(self) -> None:
        r = ModelShipperResult(
            worktree_path="/omni_worktrees/OMN-1/a",
            action_taken=EnumShipperAction.NO_OP,
        )
        assert r.pr_url is None
        assert r.error is None

    def test_committed_result(self) -> None:
        r = ModelShipperResult(
            worktree_path="/omni_worktrees/OMN-2/b",
            action_taken=EnumShipperAction.COMMITTED,
            ticket_id="OMN-2000",
        )
        assert r.action_taken == EnumShipperAction.COMMITTED
        assert r.ticket_id == "OMN-2000"

    def test_pr_created_result(self) -> None:
        r = ModelShipperResult(
            worktree_path="/omni_worktrees/OMN-3/c",
            action_taken=EnumShipperAction.PR_CREATED,
            pr_url="https://github.com/OmniNode-ai/omniclaude/pull/999",
            ticket_id="OMN-3000",
        )
        assert r.pr_url is not None
        assert "pull/999" in r.pr_url

    def test_recovery_ticket_result(self) -> None:
        r = ModelShipperResult(
            worktree_path="/omni_worktrees/OMN-5/e",
            action_taken=EnumShipperAction.RECOVERY_TICKET,
            ticket_id="OMN-5000",
            error="pre-commit hook failed: ruff check found 3 errors",
        )
        assert r.action_taken == EnumShipperAction.RECOVERY_TICKET
        assert r.error is not None
        assert "pre-commit" in r.error

    def test_frozen_raises_on_mutation(self) -> None:
        r = ModelShipperResult(
            worktree_path="/a",
            action_taken=EnumShipperAction.NO_OP,
        )
        with pytest.raises(Exception):  # noqa: B017
            r.action_taken = EnumShipperAction.PUSHED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ModelShipperReport — aggregation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShipperReport:
    def test_empty_report(self) -> None:
        report = ModelShipperReport()
        assert report.total_scanned == 0
        assert report.total_shipped == 0
        assert report.total_failed == 0
        assert report.detections == []
        assert report.results == []

    def test_report_with_mixed_results(self) -> None:
        det_clean = ModelStallDetection(
            worktree_path="/a",
            branch="b",
            repo="c",
        )
        det_stalled = ModelStallDetection(
            worktree_path="/d",
            branch="e",
            repo="f",
            has_staged=True,
        )
        res_shipped = ModelShipperResult(
            worktree_path="/d",
            action_taken=EnumShipperAction.PR_CREATED,
            pr_url="https://github.com/OmniNode-ai/f/pull/1",
        )
        report = ModelShipperReport(
            detections=[det_clean, det_stalled],
            results=[res_shipped],
            total_scanned=2,
            total_shipped=1,
            total_failed=0,
        )
        assert report.total_scanned == 2
        assert report.total_shipped == 1
        assert len(report.results) == 1
        assert report.results[0].action_taken == EnumShipperAction.PR_CREATED

    def test_report_frozen(self) -> None:
        report = ModelShipperReport()
        with pytest.raises(Exception):  # noqa: B017
            report.total_shipped = 5  # type: ignore[misc]

    def test_negative_counts_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ModelShipperReport(total_scanned=-1)

    def test_report_with_failure(self) -> None:
        res_fail = ModelShipperResult(
            worktree_path="/g",
            action_taken=EnumShipperAction.RECOVERY_TICKET,
            error="pre-commit failed",
        )
        report = ModelShipperReport(
            detections=[],
            results=[res_fail],
            total_scanned=1,
            total_shipped=0,
            total_failed=1,
        )
        assert report.total_failed == 1
        assert report.results[0].error == "pre-commit failed"
