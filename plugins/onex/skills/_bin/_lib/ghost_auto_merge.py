# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Ghost auto-merge detection and recovery (OMN-6813).

Detects PRs stuck with auto-merge enabled but never entering the merge queue
due to a GitHub API race condition. Provides recovery by toggling auto-merge
off/on, with a fallback to direct merge via GraphQL ``mergePullRequest``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .base import run_gh

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Time threshold (minutes) after which a PR with auto-merge + passing checks
#: is considered to be in ghost state.
GHOST_THRESHOLD_MINUTES: int = 30

#: Seconds to wait between disabling and re-enabling auto-merge during
#: the toggle recovery step.
TOGGLE_DELAY_SECONDS: int = 5


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EnumGhostRecoveryAction(StrEnum):
    """Recovery action taken for a ghost auto-merge PR."""

    TOGGLE = "toggle"
    DIRECT_MERGE = "direct_merge"
    NONE = "none"


class EnumGhostRecoveryResult(StrEnum):
    """Outcome of a ghost auto-merge recovery attempt."""

    RECOVERED = "recovered"
    FAILED = "failed"
    NOT_GHOST = "not_ghost"
    SKIPPED = "skipped"


class ModelGhostAutoMergeStatus(BaseModel):
    """Status of a single PR's ghost auto-merge check."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    repo: str = Field(..., description="Repository slug (org/name)")
    pr_number: int = Field(..., description="PR number")
    is_ghost: bool = Field(
        default=False, description="Whether the PR is in ghost auto-merge state"
    )
    auto_merge_enabled: bool = Field(
        default=False, description="Whether auto-merge is currently enabled"
    )
    checks_passing: bool = Field(
        default=False, description="Whether all required checks are passing"
    )
    auto_merge_enabled_at: str | None = Field(
        default=None,
        description="ISO timestamp when auto-merge was enabled (if available)",
    )
    minutes_stuck: float = Field(
        default=0.0,
        description="Minutes since auto-merge was enabled with passing checks",
    )
    recovery_action: EnumGhostRecoveryAction = Field(
        default=EnumGhostRecoveryAction.NONE,
        description="Recovery action taken",
    )
    recovery_result: EnumGhostRecoveryResult = Field(
        default=EnumGhostRecoveryResult.NOT_GHOST,
        description="Outcome of recovery attempt",
    )
    error: str | None = Field(
        default=None, description="Error message if recovery failed"
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_ghost_auto_merge(
    repo: str,
    pr_number: int,
    *,
    threshold_minutes: int = GHOST_THRESHOLD_MINUTES,
    now: datetime | None = None,
) -> ModelGhostAutoMergeStatus:
    """Check whether a PR is stuck in ghost auto-merge state.

    A PR is in ghost state when:
    1. Auto-merge is enabled
    2. All required status checks are passing (mergeStateStatus == CLEAN)
    3. It has been in this state for more than ``threshold_minutes``

    Args:
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        pr_number: PR number.
        threshold_minutes: Minutes before declaring ghost state.
        now: Current time (for testing); defaults to ``datetime.now(UTC)``.

    Returns:
        Status model describing the PR's ghost auto-merge state.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    pr_data = _fetch_pr_auto_merge_state(repo, pr_number)

    auto_merge = pr_data.get("autoMergeRequest")
    auto_merge_enabled = auto_merge is not None

    if not auto_merge_enabled:
        return ModelGhostAutoMergeStatus(
            repo=repo,
            pr_number=pr_number,
            is_ghost=False,
            auto_merge_enabled=False,
            checks_passing=False,
            recovery_result=EnumGhostRecoveryResult.NOT_GHOST,
        )

    merge_state = (pr_data.get("mergeStateStatus") or "").upper()
    checks_passing = merge_state == "CLEAN"

    # Try to determine when auto-merge was enabled
    enabled_at_str = auto_merge.get("enabledAt") if auto_merge else None
    minutes_stuck = 0.0

    if enabled_at_str and checks_passing:
        try:
            enabled_at = datetime.fromisoformat(enabled_at_str.replace("Z", "+00:00"))
            delta = now - enabled_at
            minutes_stuck = delta.total_seconds() / 60.0
        except (ValueError, TypeError):
            # If we can't parse the timestamp, use the threshold as a conservative estimate
            minutes_stuck = float(threshold_minutes) + 1.0

    is_ghost = (
        auto_merge_enabled and checks_passing and minutes_stuck > threshold_minutes
    )

    return ModelGhostAutoMergeStatus(
        repo=repo,
        pr_number=pr_number,
        is_ghost=is_ghost,
        auto_merge_enabled=auto_merge_enabled,
        checks_passing=checks_passing,
        auto_merge_enabled_at=enabled_at_str,
        minutes_stuck=round(minutes_stuck, 1),
        recovery_result=(
            EnumGhostRecoveryResult.NOT_GHOST
            if not is_ghost
            else EnumGhostRecoveryResult.SKIPPED
        ),
    )


def _fetch_pr_auto_merge_state(repo: str, pr_number: int) -> dict[str, Any]:
    """Fetch PR state needed for ghost auto-merge detection."""
    result = run_gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "autoMergeRequest,mergeStateStatus,mergeable,statusCheckRollup",
        ]
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def recover_ghost_auto_merge(
    repo: str,
    pr_number: int,
    status: ModelGhostAutoMergeStatus,
    *,
    toggle_delay: int = TOGGLE_DELAY_SECONDS,
) -> ModelGhostAutoMergeStatus:
    """Attempt to recover a PR from ghost auto-merge state.

    Recovery strategy:
    1. Disable auto-merge, wait ``toggle_delay`` seconds, re-enable auto-merge
    2. If still stuck after toggle, attempt direct merge via GraphQL

    Args:
        repo: Repository slug.
        pr_number: PR number.
        status: The detection result (must have ``is_ghost == True``).
        toggle_delay: Seconds to wait between disable/enable.

    Returns:
        Updated status model with recovery action and result.
    """
    if not status.is_ghost:
        return status

    # Step 1: Toggle auto-merge off/on
    logger.info(
        "[ghost-auto-merge] PR %s#%d: attempting toggle recovery", repo, pr_number
    )

    try:
        _disable_auto_merge(repo, pr_number)
        time.sleep(toggle_delay)
        _enable_auto_merge(repo, pr_number)

        # Check if the toggle resolved the issue
        post_toggle = detect_ghost_auto_merge(repo, pr_number, threshold_minutes=0)

        if not post_toggle.auto_merge_enabled:
            # Auto-merge was consumed (PR entered merge queue) -- success
            return ModelGhostAutoMergeStatus(
                repo=repo,
                pr_number=pr_number,
                is_ghost=False,
                auto_merge_enabled=False,
                checks_passing=status.checks_passing,
                auto_merge_enabled_at=status.auto_merge_enabled_at,
                minutes_stuck=status.minutes_stuck,
                recovery_action=EnumGhostRecoveryAction.TOGGLE,
                recovery_result=EnumGhostRecoveryResult.RECOVERED,
            )

    except Exception as exc:
        logger.warning(
            "[ghost-auto-merge] PR %s#%d: toggle failed: %s", repo, pr_number, exc
        )
        # Fall through to direct merge attempt

    # Step 2: Direct merge via GraphQL
    logger.info(
        "[ghost-auto-merge] PR %s#%d: toggle did not resolve; attempting direct merge",
        repo,
        pr_number,
    )

    try:
        _direct_merge(repo, pr_number)
        return ModelGhostAutoMergeStatus(
            repo=repo,
            pr_number=pr_number,
            is_ghost=False,
            auto_merge_enabled=status.auto_merge_enabled,
            checks_passing=status.checks_passing,
            auto_merge_enabled_at=status.auto_merge_enabled_at,
            minutes_stuck=status.minutes_stuck,
            recovery_action=EnumGhostRecoveryAction.DIRECT_MERGE,
            recovery_result=EnumGhostRecoveryResult.RECOVERED,
        )
    except Exception as exc:
        logger.warning(
            "[ghost-auto-merge] PR %s#%d: direct merge failed: %s",
            repo,
            pr_number,
            exc,
        )
        return ModelGhostAutoMergeStatus(
            repo=repo,
            pr_number=pr_number,
            is_ghost=True,
            auto_merge_enabled=status.auto_merge_enabled,
            checks_passing=status.checks_passing,
            auto_merge_enabled_at=status.auto_merge_enabled_at,
            minutes_stuck=status.minutes_stuck,
            recovery_action=EnumGhostRecoveryAction.DIRECT_MERGE,
            recovery_result=EnumGhostRecoveryResult.FAILED,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _disable_auto_merge(repo: str, pr_number: int) -> None:
    """Disable auto-merge on a PR via ``gh pr merge --disable-auto``."""
    run_gh(
        [
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            repo,
            "--disable-auto",
        ]
    )


def _enable_auto_merge(repo: str, pr_number: int) -> None:
    """Re-enable auto-merge on a PR via ``gh pr merge --auto --squash``."""
    run_gh(
        [
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            repo,
            "--auto",
            "--squash",
        ]
    )


def _direct_merge(repo: str, pr_number: int) -> None:
    """Merge a PR directly via ``gh pr merge --squash`` (no --auto)."""
    run_gh(
        [
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            repo,
            "--squash",
        ]
    )


# ---------------------------------------------------------------------------
# Batch detection for merge-sweep integration
# ---------------------------------------------------------------------------


def scan_for_ghost_auto_merges(
    repo: str,
    *,
    threshold_minutes: int = GHOST_THRESHOLD_MINUTES,
    now: datetime | None = None,
) -> list[ModelGhostAutoMergeStatus]:
    """Scan a repo for all open PRs with ghost auto-merge state.

    Returns a list of status models for PRs that are in ghost state.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    # Get all open PRs with auto-merge enabled
    result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "number,autoMergeRequest,mergeStateStatus,mergeable",
        ]
    )
    prs = json.loads(result.stdout) if result.stdout.strip() else []

    ghost_statuses: list[ModelGhostAutoMergeStatus] = []
    for pr in prs:
        if pr.get("autoMergeRequest") is None:
            continue
        status = detect_ghost_auto_merge(
            repo, pr["number"], threshold_minutes=threshold_minutes, now=now
        )
        if status.is_ghost:
            ghost_statuses.append(status)

    return ghost_statuses
