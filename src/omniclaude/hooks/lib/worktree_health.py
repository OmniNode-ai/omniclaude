# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Worktree health sweep logic for autopilot close-out [OMN-6867].

Detects dirty worktrees (uncommitted work), stale worktrees (>N days, no PR),
and provides classification for recovery ticket creation.

All classification functions are pure (no I/O) for unit testability.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
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


# ---------------------------------------------------------------------------
# Durability sweep (OMN-13044)
#
# Layered on top of the health classification above, the durability sweep flags
# worktrees that are at risk of stranding or losing work:
#   1. NO-TICKET   : directory name carries no OMN-NNNN identifier
#   2. DIRTY-PLAN  : unstaged changes to files referenced by a docs/plans/ or
#                    docs/handoffs/ document
#   3. RESCUE-REF  : on handoff-block, a rescue/<ticket>/<timestamp> tag is
#                    created over `git stash create` BEFORE the block is enforced
#   4. OFF-VOLUME  : a demo-critical .onex_state backup only counts toward DoD
#                    when it also has an off-volume copy (ticket attachment or
#                    docs-branch commit)
#
# All functions below are pure (no I/O) for unit testability; the worktree
# skill drives the git/gh side effects.
# ---------------------------------------------------------------------------

RESCUE_REF_PREFIX: str = "rescue"
"""Namespace prefix for rescue tags created on handoff-block."""

_TICKET_ID_RE = re.compile(r"OMN-\d+")


def extract_ticket_id(dirname: str) -> str | None:
    """Extract the first OMN-NNNN identifier from a worktree path or dir name.

    Detection is case-insensitive because Linear branch names lowercase the
    ticket id (``omn-1234``) while the canonical worktree layout uppercases it.

    Args:
        dirname: A worktree path or directory name.

    Returns:
        The uppercased ticket id (e.g. ``"OMN-13044"``) or ``None`` when the
        path carries no ticket identifier (a NO-TICKET worktree).
    """
    match = _TICKET_ID_RE.search(dirname.upper())
    return match.group(0) if match else None


def is_no_ticket_worktree(path: str) -> bool:
    """Return ``True`` when the worktree path has no OMN-NNNN identifier."""
    return extract_ticket_id(path) is None


def plan_referenced_dirty_files(
    changed_files: Iterable[str],
    plan_referenced_files: Iterable[str],
) -> tuple[str, ...]:
    """Return the sorted, de-duplicated intersection of dirty and plan files.

    A non-empty result flags a dirty worktree whose loss would strand work
    referenced by a ``docs/plans/`` or ``docs/handoffs/`` document.

    Args:
        changed_files: Files with unstaged/uncommitted changes (git status).
        plan_referenced_files: Files referenced by any plan/handoff document.

    Returns:
        The sorted tuple of files that are both dirty and plan-referenced.
    """
    referenced = set(plan_referenced_files)
    return tuple(sorted({f for f in changed_files if f in referenced}))


def build_rescue_ref(ticket: str, timestamp: str) -> str:
    """Build the rescue git tag name ``rescue/<ticket>/<timestamp>``.

    The worktree skill creates this tag over ``git stash create`` before
    blocking a handoff, so dirty work is recoverable even if the worktree is
    later pruned.

    Args:
        ticket: The ticket id (or ``NO-TICKET`` sentinel) owning the worktree.
        timestamp: A filesystem-safe timestamp (e.g. ``20260628T120000Z``).

    Returns:
        The fully-qualified rescue tag name.

    Raises:
        ValueError: If ``ticket`` or ``timestamp`` is empty.
    """
    if not ticket:
        raise ValueError("ticket is required to build a rescue ref")
    if not timestamp:
        raise ValueError("timestamp is required to build a rescue ref")
    return f"{RESCUE_REF_PREFIX}/{ticket}/{timestamp}"


def offvolume_backup_satisfied(
    *,
    has_ticket_attachment: bool,
    has_docs_branch_commit: bool,
) -> bool:
    """Return ``True`` when a demo-critical backup has an off-volume copy.

    A bare ``.onex_state`` backup that lives only on the work volume does NOT
    count toward DoD — the fix must also be durable off-volume, either as a
    Linear ticket attachment or a committed docs-branch artifact.

    Args:
        has_ticket_attachment: Whether the fix is attached to its Linear ticket.
        has_docs_branch_commit: Whether the fix is committed on a docs branch.

    Returns:
        ``True`` when at least one off-volume copy exists.
    """
    return has_ticket_attachment or has_docs_branch_commit


class ModelWorktreeDurabilityFlags(BaseModel):
    """Durability-sweep flags for a single worktree (OMN-13044).

    Surfaces the four at-risk conditions the durability sweep detects on top of
    the health classification: NO-TICKET worktrees, dirty worktrees touching
    plan/handoff-referenced files, the rescue ref auto-created on handoff-block,
    and whether the off-volume backup requirement is satisfied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1, description="Absolute path to the worktree")
    ticket_id: str | None = Field(
        default=None,
        description="OMN-NNNN id parsed from the path; None means NO-TICKET",
    )
    is_no_ticket: bool = Field(
        default=False,
        description="True when the directory name carries no OMN-NNNN identifier",
    )
    dirty_plan_files: tuple[str, ...] = Field(
        default=(),
        description="Unstaged files also referenced by a plan/handoff document",
    )
    rescue_ref: str | None = Field(
        default=None,
        description="rescue/<ticket>/<timestamp> tag created before a handoff-block",
    )
    offvolume_backup_ok: bool = Field(
        default=False,
        description="Demo-critical backup has a ticket/docs-branch off-volume copy",
    )

    @property
    def is_dirty_plan_worktree(self) -> bool:
        """Return ``True`` when unstaged changes touch plan-referenced files."""
        return bool(self.dirty_plan_files)


__all__ = [
    "EnumWorktreeStatus",
    "ModelWorktreeDurabilityFlags",
    "ModelWorktreeEntry",
    "ModelWorktreeHealthResult",
    "RESCUE_REF_PREFIX",
    "STALE_WORKTREE_DAYS",
    "build_rescue_ref",
    "build_worktree_entry",
    "classify_worktree",
    "extract_ticket_id",
    "is_no_ticket_worktree",
    "offvolume_backup_satisfied",
    "plan_referenced_dirty_files",
]
