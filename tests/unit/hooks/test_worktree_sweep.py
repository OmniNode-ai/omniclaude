# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for worktree sweep models (OMN-6867).

Validates:
- EnumWorktreeStatus covers all 5 categories
- ModelWorktreeEntry enforces constraints and frozen semantics
- ModelWorktreeSweepReport aggregates entries correctly
- All status categories are constructable with valid data
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omniclaude.hooks.worktree_sweep import (
    EnumWorktreeStatus,
    ModelWorktreeEntry,
    ModelWorktreeSweepReport,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helper factories
# =============================================================================


def make_entry(
    *,
    status: EnumWorktreeStatus = EnumWorktreeStatus.ACTIVE,
    path: str = "/tmp/test_worktrees/OMN-1234/omniclaude",
    repo: str = "omniclaude",
    branch: str = "jonah/omn-1234-feat",
    commits_ahead: int = 5,
    has_uncommitted: bool = False,
    last_commit_date: datetime | None = None,
) -> ModelWorktreeEntry:
    """Build a valid ModelWorktreeEntry with sensible defaults."""
    return ModelWorktreeEntry(
        path=path,
        repo=repo,
        branch=branch,
        status=status,
        commits_ahead=commits_ahead,
        has_uncommitted=has_uncommitted,
        last_commit_date=last_commit_date
        or datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC),
    )


def make_report(
    entries: list[ModelWorktreeEntry] | None = None,
    cleaned_count: int = 0,
    tickets_created: int = 0,
) -> ModelWorktreeSweepReport:
    """Build a valid ModelWorktreeSweepReport."""
    entries = entries or []
    counts: dict[EnumWorktreeStatus, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return ModelWorktreeSweepReport(
        entries=entries,
        counts_by_status=counts,
        cleaned_count=cleaned_count,
        tickets_created=tickets_created,
    )


# =============================================================================
# EnumWorktreeStatus
# =============================================================================


class TestEnumWorktreeStatus:
    """EnumWorktreeStatus covers all 5 required categories."""

    def test_has_five_members(self) -> None:
        assert len(EnumWorktreeStatus) == 5

    def test_safe_to_delete_value(self) -> None:
        assert EnumWorktreeStatus.SAFE_TO_DELETE == "safe_to_delete"

    def test_lost_work_value(self) -> None:
        assert EnumWorktreeStatus.LOST_WORK == "lost_work"

    def test_stale_value(self) -> None:
        assert EnumWorktreeStatus.STALE == "stale"

    def test_active_value(self) -> None:
        assert EnumWorktreeStatus.ACTIVE == "active"

    def test_dirty_active_value(self) -> None:
        assert EnumWorktreeStatus.DIRTY_ACTIVE == "dirty_active"

    def test_is_str_enum(self) -> None:
        """All members are string-serializable."""
        for member in EnumWorktreeStatus:
            assert isinstance(member, str)
            assert isinstance(member.value, str)


# =============================================================================
# ModelWorktreeEntry — one test per status category
# =============================================================================


class TestModelWorktreeEntrySafeToDelete:
    """SAFE_TO_DELETE: branch merged (0 commits ahead), no uncommitted work."""

    def test_construction(self) -> None:
        entry = make_entry(
            status=EnumWorktreeStatus.SAFE_TO_DELETE,
            commits_ahead=0,
            has_uncommitted=False,
        )
        assert entry.status == EnumWorktreeStatus.SAFE_TO_DELETE
        assert entry.commits_ahead == 0
        assert entry.has_uncommitted is False

    def test_frozen(self) -> None:
        entry = make_entry(status=EnumWorktreeStatus.SAFE_TO_DELETE, commits_ahead=0)
        with pytest.raises(ValidationError):
            entry.status = EnumWorktreeStatus.ACTIVE  # type: ignore[misc]


class TestModelWorktreeEntryLostWork:
    """LOST_WORK: branch merged but has uncommitted changes."""

    def test_construction(self) -> None:
        entry = make_entry(
            status=EnumWorktreeStatus.LOST_WORK,
            commits_ahead=0,
            has_uncommitted=True,
        )
        assert entry.status == EnumWorktreeStatus.LOST_WORK
        assert entry.commits_ahead == 0
        assert entry.has_uncommitted is True


class TestModelWorktreeEntryStale:
    """STALE: branch not merged, clean, old, no open PR."""

    def test_construction(self) -> None:
        entry = make_entry(
            status=EnumWorktreeStatus.STALE,
            commits_ahead=3,
            has_uncommitted=False,
            last_commit_date=datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC),
        )
        assert entry.status == EnumWorktreeStatus.STALE
        assert entry.commits_ahead == 3
        assert entry.has_uncommitted is False


class TestModelWorktreeEntryActive:
    """ACTIVE: branch not merged, recent work, clean."""

    def test_construction(self) -> None:
        entry = make_entry(
            status=EnumWorktreeStatus.ACTIVE,
            commits_ahead=5,
            has_uncommitted=False,
        )
        assert entry.status == EnumWorktreeStatus.ACTIVE
        assert entry.commits_ahead == 5


class TestModelWorktreeEntryDirtyActive:
    """DIRTY_ACTIVE: branch not merged, has uncommitted work."""

    def test_construction(self) -> None:
        entry = make_entry(
            status=EnumWorktreeStatus.DIRTY_ACTIVE,
            commits_ahead=2,
            has_uncommitted=True,
        )
        assert entry.status == EnumWorktreeStatus.DIRTY_ACTIVE
        assert entry.has_uncommitted is True


# =============================================================================
# ModelWorktreeEntry — validation constraints
# =============================================================================


class TestModelWorktreeEntryValidation:
    """Field constraints on ModelWorktreeEntry."""

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(ValidationError):
            make_entry(path="")

    def test_rejects_empty_repo(self) -> None:
        with pytest.raises(ValidationError):
            make_entry(repo="")

    def test_rejects_empty_branch(self) -> None:
        with pytest.raises(ValidationError):
            make_entry(branch="")

    def test_rejects_negative_commits_ahead(self) -> None:
        with pytest.raises(ValidationError):
            make_entry(commits_ahead=-1)

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeEntry(
                path="/some/path",
                repo="omniclaude",
                branch="main",
                status=EnumWorktreeStatus.ACTIVE,
                commits_ahead=0,
                has_uncommitted=False,
                last_commit_date=datetime(2026, 3, 27, tzinfo=UTC),
                surprise="nope",  # type: ignore[call-arg]
            )


# =============================================================================
# ModelWorktreeSweepReport
# =============================================================================


class TestModelWorktreeSweepReport:
    """Aggregated report model tests."""

    def test_empty_report(self) -> None:
        report = make_report()
        assert report.entries == []
        assert report.counts_by_status == {}
        assert report.cleaned_count == 0
        assert report.tickets_created == 0

    def test_report_with_mixed_entries(self) -> None:
        entries = [
            make_entry(status=EnumWorktreeStatus.SAFE_TO_DELETE, commits_ahead=0),
            make_entry(
                status=EnumWorktreeStatus.SAFE_TO_DELETE,
                commits_ahead=0,
                path="/tmp/test_worktrees/OMN-1235/omnibase_core",
                repo="omnibase_core",
            ),
            make_entry(
                status=EnumWorktreeStatus.LOST_WORK,
                commits_ahead=0,
                has_uncommitted=True,
                path="/tmp/test_worktrees/OMN-1236/omnibase_infra",
                repo="omnibase_infra",
            ),
            make_entry(
                status=EnumWorktreeStatus.ACTIVE,
                path="/tmp/test_worktrees/OMN-1237/omniclaude",
            ),
            make_entry(
                status=EnumWorktreeStatus.STALE,
                commits_ahead=1,
                path="/tmp/test_worktrees/OMN-1238/omnidash",
                repo="omnidash",
                last_commit_date=datetime(2026, 3, 20, tzinfo=UTC),
            ),
            make_entry(
                status=EnumWorktreeStatus.DIRTY_ACTIVE,
                has_uncommitted=True,
                path="/tmp/test_worktrees/OMN-1239/omniintelligence",
                repo="omniintelligence",
            ),
        ]
        report = make_report(entries=entries, cleaned_count=2, tickets_created=1)

        assert len(report.entries) == 6
        assert report.counts_by_status[EnumWorktreeStatus.SAFE_TO_DELETE] == 2
        assert report.counts_by_status[EnumWorktreeStatus.LOST_WORK] == 1
        assert report.counts_by_status[EnumWorktreeStatus.ACTIVE] == 1
        assert report.counts_by_status[EnumWorktreeStatus.STALE] == 1
        assert report.counts_by_status[EnumWorktreeStatus.DIRTY_ACTIVE] == 1
        assert report.cleaned_count == 2
        assert report.tickets_created == 1

    def test_report_frozen(self) -> None:
        report = make_report()
        with pytest.raises(ValidationError):
            report.cleaned_count = 99  # type: ignore[misc]

    def test_rejects_negative_cleaned_count(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeSweepReport(
                entries=[],
                counts_by_status={},
                cleaned_count=-1,
                tickets_created=0,
            )

    def test_rejects_negative_tickets_created(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeSweepReport(
                entries=[],
                counts_by_status={},
                cleaned_count=0,
                tickets_created=-1,
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeSweepReport(
                entries=[],
                counts_by_status={},
                cleaned_count=0,
                tickets_created=0,
                bonus="nope",  # type: ignore[call-arg]
            )
