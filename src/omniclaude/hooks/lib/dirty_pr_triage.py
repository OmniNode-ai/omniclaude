# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""DIRTY PR triage logic for autopilot close-out [OMN-6872].

Provides classification and stale detection for DIRTY/CONFLICTING PRs,
merge queue stall detection, and missing auto-merge detection.

All functions are pure (no I/O) to enable unit testing.
I/O wrappers call gh CLI and feed results to these classifiers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumDirtyPRAction(StrEnum):
    """Action to take on a DIRTY PR."""

    CLOSE_STALE = "close_stale"
    FLAG_RECENT = "flag_recent"
    SKIP = "skip"


class ModelDirtyPR(BaseModel):
    """A PR classified as DIRTY or CONFLICTING."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="Full repo name (e.g. OmniNode-ai/omniclaude)")
    number: int = Field(..., description="PR number")
    title: str = Field(default="", description="PR title")
    merge_state: str = Field(..., description="mergeStateStatus value")
    age_hours: float = Field(..., description="Hours since last update")
    author: str = Field(default="unknown", description="PR author login")
    url: str = Field(default="", description="PR URL")
    action: EnumDirtyPRAction = Field(..., description="Recommended action")


class ModelQueueHealthEntry(BaseModel):
    """Health status for a single repo's merge queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="Full repo name")
    queued_count: int = Field(
        ..., description="Number of PRs with active autoMergeRequest"
    )
    minutes_since_last_merge: float | None = Field(
        default=None, description="Minutes since last merge (None if no recent merges)"
    )
    is_stalled: bool = Field(default=False, description="Queue is stalled")
    queued_pr_numbers: list[int] = Field(default_factory=list)


class ModelMissingAutoMergePR(BaseModel):
    """A CLEAN PR that should have auto-merge but does not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    number: int
    title: str = ""


class ModelDirtyPRTriageResult(BaseModel):
    """Result of the DIRTY PR triage step."""

    model_config = ConfigDict(extra="forbid")

    dirty_prs: list[ModelDirtyPR] = Field(default_factory=list)
    stale_closed: list[ModelDirtyPR] = Field(default_factory=list)
    recent_flagged: list[ModelDirtyPR] = Field(default_factory=list)
    stalled_queues: list[ModelQueueHealthEntry] = Field(default_factory=list)
    missing_auto_merge: list[ModelMissingAutoMergePR] = Field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        """Return True if any issues were found."""
        return bool(
            self.stale_closed
            or self.recent_flagged
            or self.stalled_queues
            or self.missing_auto_merge
        )


# ---------------------------------------------------------------------------
# Pure classification functions (no I/O)
# ---------------------------------------------------------------------------

STALE_PR_THRESHOLD_HOURS: float = 24.0
QUEUE_STALL_THRESHOLD_MINUTES: float = 60.0


def classify_dirty_pr(
    repo: str,
    number: int,
    title: str,
    merge_state: str,
    updated_at_iso: str,
    author: str = "unknown",
    url: str = "",
    *,
    now: datetime | None = None,
    stale_threshold_hours: float = STALE_PR_THRESHOLD_HOURS,
) -> ModelDirtyPR:
    """Classify a DIRTY/CONFLICTING PR and determine the recommended action.

    Args:
        repo: Full repo name.
        number: PR number.
        title: PR title.
        merge_state: The mergeStateStatus value (DIRTY, CONFLICTING, etc).
        updated_at_iso: ISO 8601 timestamp of last update.
        author: PR author login.
        url: PR URL.
        now: Current time (injected for deterministic testing).
        stale_threshold_hours: Hours after which a DIRTY PR is considered stale.

    Returns:
        ModelDirtyPR with the recommended action.
    """
    if now is None:
        now = datetime.now(UTC)

    updated_at = datetime.fromisoformat(updated_at_iso.rstrip("Z")).replace(tzinfo=UTC)
    age_hours = (now - updated_at).total_seconds() / 3600

    if age_hours > stale_threshold_hours:
        action = EnumDirtyPRAction.CLOSE_STALE
    else:
        action = EnumDirtyPRAction.FLAG_RECENT

    return ModelDirtyPR(
        repo=repo,
        number=number,
        title=title,
        merge_state=merge_state.upper(),
        age_hours=round(age_hours, 1),
        author=author,
        url=url,
        action=action,
    )


def is_dirty_or_conflicting(
    mergeable: str,
    merge_state_status: str,
) -> bool:
    """Return True if a PR is in a DIRTY or CONFLICTING state.

    Args:
        mergeable: The PR's mergeable field (MERGEABLE, CONFLICTING, UNKNOWN).
        merge_state_status: The PR's mergeStateStatus field.

    Returns:
        True if the PR is DIRTY or CONFLICTING.
    """
    return (
        merge_state_status.upper() in ("DIRTY", "CONFLICTING")
        or mergeable.upper() == "CONFLICTING"
    )


def check_queue_health(
    repo: str,
    queued_pr_numbers: list[int],
    last_merge_time_iso: str | None,
    *,
    now: datetime | None = None,
    stall_threshold_minutes: float = QUEUE_STALL_THRESHOLD_MINUTES,
) -> ModelQueueHealthEntry:
    """Check whether a repo's merge queue is stalled.

    Args:
        repo: Full repo name.
        queued_pr_numbers: PR numbers with active autoMergeRequest.
        last_merge_time_iso: ISO 8601 timestamp of last merged PR, or None.
        now: Current time (injected for deterministic testing).
        stall_threshold_minutes: Minutes threshold for stall detection.

    Returns:
        ModelQueueHealthEntry with stall status.
    """
    if now is None:
        now = datetime.now(UTC)

    if not queued_pr_numbers:
        return ModelQueueHealthEntry(
            repo=repo,
            queued_count=0,
            minutes_since_last_merge=None,
            is_stalled=False,
            queued_pr_numbers=[],
        )

    minutes_since: float | None = None
    is_stalled = False

    if last_merge_time_iso is not None:
        last_merge = datetime.fromisoformat(last_merge_time_iso.rstrip("Z")).replace(
            tzinfo=UTC
        )
        minutes_since = (now - last_merge).total_seconds() / 60
        is_stalled = minutes_since > stall_threshold_minutes
    else:
        # No recent merges at all with items in queue = stalled
        is_stalled = True

    return ModelQueueHealthEntry(
        repo=repo,
        queued_count=len(queued_pr_numbers),
        minutes_since_last_merge=round(minutes_since, 1)
        if minutes_since is not None
        else None,
        is_stalled=is_stalled,
        queued_pr_numbers=queued_pr_numbers,
    )


def is_missing_auto_merge(
    mergeable: str,
    merge_state_status: str,
    is_draft: bool,
    auto_merge_request: object | None,
    all_required_checks_pass: bool,
    review_ok: bool,
) -> bool:
    """Return True if a PR is CLEAN and merge-ready but not in the merge queue.

    Args:
        mergeable: MERGEABLE | CONFLICTING | UNKNOWN
        merge_state_status: CLEAN | DIRTY | BEHIND | etc.
        is_draft: Whether the PR is a draft.
        auto_merge_request: The autoMergeRequest field (None = not armed).
        all_required_checks_pass: Whether all required CI checks pass.
        review_ok: Whether the review decision is APPROVED or None.

    Returns:
        True if auto-merge should be armed but isn't.
    """
    if is_draft:
        return False
    if mergeable != "MERGEABLE":
        return False
    if merge_state_status.upper() not in ("CLEAN", "HAS_HOOKS"):
        return False
    if auto_merge_request is not None:
        return False
    return all_required_checks_pass and review_ok


__all__ = [
    "EnumDirtyPRAction",
    "ModelDirtyPR",
    "ModelDirtyPRTriageResult",
    "ModelMissingAutoMergePR",
    "ModelQueueHealthEntry",
    "QUEUE_STALL_THRESHOLD_MINUTES",
    "STALE_PR_THRESHOLD_HOURS",
    "check_queue_health",
    "classify_dirty_pr",
    "is_dirty_or_conflicting",
    "is_missing_auto_merge",
]
