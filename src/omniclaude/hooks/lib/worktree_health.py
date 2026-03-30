# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Worktree health sweep logic for autopilot close-out [OMN-6867].

Detects dirty worktrees (uncommitted work), stale worktrees (>N days, no PR),
and provides classification for recovery ticket creation.

All classification functions are pure (no I/O) for unit testability.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumWorktreeStatus(StrEnum):
    """Classification of a worktree's health state."""

    CLEAN = "clean"
    DIRTY = "dirty"
    STALE = "stale"
    DIRTY_AND_STALE = "dirty_and_stale"


class ModelWorktreeEntry(BaseModel):
    """A single worktree and its health classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., description="Absolute path to the worktree")
    ticket: str = Field(default="", description="Ticket ID extracted from path")
    repo: str = Field(default="", description="Repository name")
    branch: str = Field(default="", description="Current branch name")
    uncommitted_count: int = Field(
        default=0, description="Number of uncommitted files (git status --porcelain)"
    )
    age_days: float = Field(default=0.0, description="Age of worktree in days")
    has_open_pr: bool = Field(
        default=False, description="Whether an open PR exists for this branch"
    )
    status: EnumWorktreeStatus = Field(
        default=EnumWorktreeStatus.CLEAN, description="Health classification"
    )


class ModelWorktreeHealthResult(BaseModel):
    """Result of the worktree health sweep."""

    model_config = ConfigDict(extra="forbid")

    total_scanned: int = Field(default=0)
    pruned_count: int = Field(default=0, description="Merged worktrees auto-cleaned")
    dirty_worktrees: list[ModelWorktreeEntry] = Field(default_factory=list)
    stale_worktrees: list[ModelWorktreeEntry] = Field(default_factory=list)
    recovery_tickets_created: list[str] = Field(
        default_factory=list,
        description="Linear ticket IDs created for dirty worktrees",
    )

    @property
    def has_issues(self) -> bool:
        """Return True if any worktrees need attention."""
        return bool(self.dirty_worktrees or self.stale_worktrees)


# ---------------------------------------------------------------------------
# Pure classification functions (no I/O)
# ---------------------------------------------------------------------------

STALE_WORKTREE_DAYS: float = 3.0


def classify_worktree(
    uncommitted_count: int,
    age_days: float,
    has_open_pr: bool,
    *,
    stale_days_threshold: float = STALE_WORKTREE_DAYS,
) -> EnumWorktreeStatus:
    """Classify a worktree's health status.

    Args:
        uncommitted_count: Number of uncommitted files from git status.
        age_days: Age of the worktree directory in days.
        has_open_pr: Whether the branch has an open PR on GitHub.
        stale_days_threshold: Days after which a worktree without a PR is stale.

    Returns:
        The worktree's health classification.
    """
    is_dirty = uncommitted_count > 0
    is_stale = age_days > stale_days_threshold and not has_open_pr

    if is_dirty and is_stale:
        return EnumWorktreeStatus.DIRTY_AND_STALE
    if is_dirty:
        return EnumWorktreeStatus.DIRTY
    if is_stale:
        return EnumWorktreeStatus.STALE
    return EnumWorktreeStatus.CLEAN


def build_worktree_entry(
    path: str,
    ticket: str,
    repo: str,
    branch: str,
    uncommitted_count: int,
    age_days: float,
    has_open_pr: bool,
    *,
    stale_days_threshold: float = STALE_WORKTREE_DAYS,
) -> ModelWorktreeEntry:
    """Build a classified worktree entry.

    Args:
        path: Absolute path to the worktree.
        ticket: Ticket ID extracted from the path.
        repo: Repository name.
        branch: Current branch name.
        uncommitted_count: Number of uncommitted files.
        age_days: Age in days.
        has_open_pr: Whether the branch has an open PR.
        stale_days_threshold: Days threshold for stale classification.

    Returns:
        A classified ModelWorktreeEntry.
    """
    status = classify_worktree(
        uncommitted_count=uncommitted_count,
        age_days=age_days,
        has_open_pr=has_open_pr,
        stale_days_threshold=stale_days_threshold,
    )
    return ModelWorktreeEntry(
        path=path,
        ticket=ticket,
        repo=repo,
        branch=branch,
        uncommitted_count=uncommitted_count,
        age_days=round(age_days, 1),
        has_open_pr=has_open_pr,
        status=status,
    )


__all__ = [
    "EnumWorktreeStatus",
    "ModelWorktreeEntry",
    "ModelWorktreeHealthResult",
    "STALE_WORKTREE_DAYS",
    "build_worktree_entry",
    "classify_worktree",
]
