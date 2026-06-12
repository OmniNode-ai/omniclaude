# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Armed-not-enqueued detector (OMN-13031).

Flags PRs where:
  - autoMergeRequest != null  (auto-merge is armed)
  - mergeStateStatus == "CLEAN"  (all required checks passing)
  - no ADDED_TO_MERGE_QUEUE_EVENT newer than the arming timestamp
  - sustained for more than ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES (default 30)

This is the "ghost" variant that specifically checks the queue-event timeline,
not just check-state duration. A PR can be CLEAN + armed indefinitely without
entering the queue — this detector surfaces those cases.

Usage:
    python -m plugins.onex.skills._bin._lib.armed_not_enqueued \
        --repos omniclaude,omnibase_core,omnibase_infra,onex_change_control,omnibase_compat,omnidash,omnimarket \
        --threshold-minutes 30 \
        --format json

    # Or use the CLI entry point from the worktree:
    python plugins/onex/skills/_bin/run_armed_not_enqueued.py \
        --repos OmniNode-ai/omniclaude \
        --format json

[OMN-13031]
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .base import run_gh

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Queue repos that are subject to the armed-not-enqueued pattern.
QUEUE_REPOS: tuple[str, ...] = (
    "OmniNode-ai/omniclaude",
    "OmniNode-ai/omnibase_core",
    "OmniNode-ai/omnibase_infra",
    "OmniNode-ai/onex_change_control",
    "OmniNode-ai/omnibase_compat",
    "OmniNode-ai/omnidash",
    "OmniNode-ai/omnimarket",
)

#: Default threshold — a PR must be in the armed-not-enqueued state for this
#: many minutes before the detector flags it.
ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES: int = 30


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EnumArmedNotEnqueuedStatus(StrEnum):
    """Classification of a PR's armed-not-enqueued state."""

    CLEAN = "CLEAN"  # Not armed or correctly enqueued
    ARMED_NOT_ENQUEUED = "ARMED_NOT_ENQUEUED"  # Armed, CLEAN, no queue event
    ARMED_CHECKS_PENDING = "ARMED_CHECKS_PENDING"  # Armed but checks not CLEAN yet
    NOT_ARMED = "NOT_ARMED"  # autoMergeRequest is null


class ModelArmedNotEnqueuedFinding(BaseModel):
    """A single PR finding from the armed-not-enqueued scan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="Repository slug (org/name)")
    pr_number: int = Field(..., description="PR number")
    pr_title: str = Field(default="", description="PR title for human context")
    head_ref: str = Field(default="", description="Head branch name")
    status: EnumArmedNotEnqueuedStatus = Field(
        ..., description="Armed-not-enqueued classification"
    )
    armed_at: str | None = Field(
        default=None, description="ISO timestamp when auto-merge was enabled"
    )
    last_queue_event_at: str | None = Field(
        default=None,
        description="ISO timestamp of most recent ADDED_TO_MERGE_QUEUE_EVENT, if any",
    )
    merge_state_status: str = Field(
        default="", description="GitHub mergeStateStatus field"
    )
    minutes_armed_without_queue: float = Field(
        default=0.0,
        description="Minutes since arming with no queue event (0 if queue event found)",
    )
    queue_event_count: int = Field(
        default=0,
        description="Number of ADDED_TO_MERGE_QUEUE_EVENTs in the PR timeline",
    )
    flagged: bool = Field(
        default=False,
        description="True when status==ARMED_NOT_ENQUEUED and threshold exceeded",
    )


class ModelArmedNotEnqueuedScanResult(BaseModel):
    """Result of scanning one or more repos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scanned_at: str = Field(..., description="ISO timestamp of the scan")
    threshold_minutes: int = Field(
        default=ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
        description="Threshold used for flagging",
    )
    repos_scanned: list[str] = Field(default_factory=list)
    findings: list[ModelArmedNotEnqueuedFinding] = Field(default_factory=list)
    flagged_count: int = Field(
        default=0,
        description="Number of PRs that are flagged (ARMED_NOT_ENQUEUED + threshold exceeded)",
    )
    scan_errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors encountered during scanning",
    )


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------


def _fetch_pr_list(repo: str) -> list[dict[str, Any]]:
    """Fetch all open PRs with auto-merge and merge-state fields.

    Uses a high ``--limit`` to avoid truncating large repos. The GitHub REST
    API caps PR list results at 1000; repos above that threshold are
    theoretical edge cases for queue repos, which typically have <100 open PRs.
    ``gh pr list`` does not support ``--paginate``; use ``gh api`` if true
    pagination is needed in the future.
    """
    result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "number,title,headRefName,autoMergeRequest,mergeStateStatus",
            "--limit",
            "1000",
        ]
    )
    if not result.stdout.strip():
        return []
    raw = json.loads(result.stdout)
    return raw if isinstance(raw, list) else []


def _fetch_queue_events(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch timeline events for a PR, filtered to queue-related events.

    Returns only ADDED_TO_MERGE_QUEUE_EVENT entries.

    The GitHub timeline API paginates with up to 100 items per page.
    For our use case (detecting presence/absence of queue events), a single
    page is sufficient — queue events appear promptly when enqueueing succeeds.
    """
    result = run_gh(
        [
            "api",
            f"repos/{repo}/issues/{pr_number}/timeline",
            "--paginate",
            "--jq",
            '[.[] | select(.event == "added_to_merge_queue")]',
        ]
    )
    if not result.stdout.strip():
        return []
    # --paginate with --jq returns multiple JSON arrays, one per page.
    # Merge them.
    events: list[dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            try:
                page = json.loads(line)
                if isinstance(page, list):
                    events.extend(page)
            except json.JSONDecodeError:
                # Malformed lines from --jq pagination output are silently skipped;
                # partial/empty lines do not represent actionable events.
                pass
    return events


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO timestamp string to a UTC-aware datetime, or None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def detect_armed_not_enqueued(
    repo: str,
    pr: dict[str, Any],
    *,
    threshold_minutes: int = ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
    now: datetime | None = None,
) -> ModelArmedNotEnqueuedFinding:
    """Classify a single PR for the armed-not-enqueued pattern.

    Args:
        repo: Repository slug.
        pr: PR data dict from ``gh pr list --json``.
        threshold_minutes: Flagging threshold.
        now: Current time (injectable for tests).

    Returns:
        A finding model describing the PR state.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    pr_number = pr["number"]
    pr_title = pr.get("title", "")
    head_ref = pr.get("headRefName", "")
    auto_merge = pr.get("autoMergeRequest")
    merge_state = (pr.get("mergeStateStatus") or "").upper()

    if auto_merge is None:
        return ModelArmedNotEnqueuedFinding(
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            head_ref=head_ref,
            status=EnumArmedNotEnqueuedStatus.NOT_ARMED,
            merge_state_status=merge_state,
        )

    # PR is armed — check if checks are clean
    if merge_state != "CLEAN":
        armed_at_str = auto_merge.get("enabledAt")
        return ModelArmedNotEnqueuedFinding(
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            head_ref=head_ref,
            status=EnumArmedNotEnqueuedStatus.ARMED_CHECKS_PENDING,
            armed_at=armed_at_str,
            merge_state_status=merge_state,
        )

    # Armed + CLEAN — check timeline for queue events
    queue_events = _fetch_queue_events(repo, pr_number)
    queue_event_count = len(queue_events)

    # Find the most recent queue event timestamp
    last_queue_event_at: str | None = None
    last_queue_event_dt: datetime | None = None
    for ev in queue_events:
        # GitHub timeline events use "created_at" for the timestamp
        ev_ts = ev.get("created_at")
        ev_dt = _parse_iso(ev_ts)
        if ev_dt and (last_queue_event_dt is None or ev_dt > last_queue_event_dt):
            last_queue_event_dt = ev_dt
            last_queue_event_at = ev_ts

    armed_at_str = auto_merge.get("enabledAt")
    armed_at_dt = _parse_iso(armed_at_str)

    # If there's a queue event AFTER the arming, the PR is correctly enqueued
    if last_queue_event_dt is not None and armed_at_dt is not None:
        if last_queue_event_dt >= armed_at_dt:
            return ModelArmedNotEnqueuedFinding(
                repo=repo,
                pr_number=pr_number,
                pr_title=pr_title,
                head_ref=head_ref,
                status=EnumArmedNotEnqueuedStatus.CLEAN,
                armed_at=armed_at_str,
                last_queue_event_at=last_queue_event_at,
                merge_state_status=merge_state,
                queue_event_count=queue_event_count,
            )

    # No queue event after arming — compute how long since arming.
    # When enabledAt is missing/unparsable we cannot determine elapsed time,
    # so we skip flagging (unknown ≠ overdue).
    if armed_at_dt is None:
        logger.debug(
            "[armed-not-enqueued] %s#%d: enabledAt missing or unparsable — "
            "cannot determine elapsed time; not flagging",
            repo,
            pr_number,
        )
        return ModelArmedNotEnqueuedFinding(
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            head_ref=head_ref,
            status=EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED,
            armed_at=armed_at_str,
            last_queue_event_at=last_queue_event_at,
            merge_state_status=merge_state,
            minutes_armed_without_queue=0.0,
            queue_event_count=queue_event_count,
            flagged=False,
        )

    delta = now - armed_at_dt
    minutes_armed = max(0.0, delta.total_seconds() / 60.0)
    flagged = minutes_armed > threshold_minutes

    return ModelArmedNotEnqueuedFinding(
        repo=repo,
        pr_number=pr_number,
        pr_title=pr_title,
        head_ref=head_ref,
        status=EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED,
        armed_at=armed_at_str,
        last_queue_event_at=last_queue_event_at,
        merge_state_status=merge_state,
        minutes_armed_without_queue=round(minutes_armed, 1),
        queue_event_count=queue_event_count,
        flagged=flagged,
    )


def scan_repo(
    repo: str,
    *,
    threshold_minutes: int = ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
    now: datetime | None = None,
) -> tuple[list[ModelArmedNotEnqueuedFinding], list[str]]:
    """Scan a single repo for armed-not-enqueued PRs.

    Returns:
        (findings, errors) — findings for all PRs with autoMergeRequest != null;
        errors is a list of non-fatal error strings.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    findings: list[ModelArmedNotEnqueuedFinding] = []
    errors: list[str] = []

    try:
        prs = _fetch_pr_list(repo)
    except Exception as exc:
        errors.append(f"{repo}: fetch failed — {exc}")
        return findings, errors

    for pr in prs:
        if pr.get("autoMergeRequest") is None:
            continue
        try:
            finding = detect_armed_not_enqueued(
                repo, pr, threshold_minutes=threshold_minutes, now=now
            )
            findings.append(finding)
        except Exception as exc:
            errors.append(f"{repo}#{pr.get('number', '?')}: detection failed — {exc}")

    return findings, errors


def scan_all_queue_repos(
    repos: tuple[str, ...] | None = None,
    *,
    threshold_minutes: int = ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
    now: datetime | None = None,
) -> ModelArmedNotEnqueuedScanResult:
    """Scan all configured queue repos for armed-not-enqueued PRs.

    Args:
        repos: Override the default QUEUE_REPOS list.
        threshold_minutes: Flagging threshold in minutes.
        now: Current time (injectable for tests).

    Returns:
        A scan result model with all findings across all repos.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    if repos is None:
        repos = QUEUE_REPOS

    all_findings: list[ModelArmedNotEnqueuedFinding] = []
    all_errors: list[str] = []

    for repo in repos:
        findings, errors = scan_repo(repo, threshold_minutes=threshold_minutes, now=now)
        all_findings.extend(findings)
        all_errors.extend(errors)

    flagged_count = sum(1 for f in all_findings if f.flagged)

    return ModelArmedNotEnqueuedScanResult(
        scanned_at=now.isoformat(),
        threshold_minutes=threshold_minutes,
        repos_scanned=list(repos),
        findings=all_findings,
        flagged_count=flagged_count,
        scan_errors=all_errors,
    )


# ---------------------------------------------------------------------------
# CLI summary rendering
# ---------------------------------------------------------------------------


def render_summary(result: ModelArmedNotEnqueuedScanResult) -> str:
    """Render a human-readable summary of scan results."""
    lines: list[str] = [
        f"Armed-not-enqueued scan — {result.scanned_at}",
        f"Threshold: {result.threshold_minutes} min | Repos: {len(result.repos_scanned)}",
        "",
    ]

    flagged = [f for f in result.findings if f.flagged]
    pending = [
        f
        for f in result.findings
        if f.status == EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED and not f.flagged
    ]
    checks_pending = [
        f
        for f in result.findings
        if f.status == EnumArmedNotEnqueuedStatus.ARMED_CHECKS_PENDING
    ]
    clean_queue = [
        f for f in result.findings if f.status == EnumArmedNotEnqueuedStatus.CLEAN
    ]

    if flagged:
        lines.append(
            f"FLAGGED ({len(flagged)}) — armed + CLEAN + no queue event > {result.threshold_minutes}min:"
        )
        for f in flagged:
            lines.append(
                f"  [{f.repo}] PR#{f.pr_number} '{f.pr_title[:60]}' "
                f"armed_at={f.armed_at} "
                f"minutes_without_queue={f.minutes_armed_without_queue:.1f}"
            )
    else:
        lines.append("FLAGGED (0) — no armed-not-enqueued PRs above threshold")

    if pending:
        lines.append(f"\nARMED+CLEAN but under threshold ({len(pending)}):")
        for f in pending:
            lines.append(
                f"  [{f.repo}] PR#{f.pr_number} '{f.pr_title[:60]}' "
                f"minutes={f.minutes_armed_without_queue:.1f}"
            )

    if checks_pending:
        lines.append(f"\nARMED (checks pending) ({len(checks_pending)}):")
        for f in checks_pending:
            lines.append(
                f"  [{f.repo}] PR#{f.pr_number} '{f.pr_title[:60]}' "
                f"mergeStateStatus={f.merge_state_status}"
            )

    if clean_queue:
        lines.append(f"\nCLEAN (correctly enqueued) ({len(clean_queue)}):")
        for f in clean_queue:
            lines.append(
                f"  [{f.repo}] PR#{f.pr_number} '{f.pr_title[:60]}' "
                f"last_queue_event={f.last_queue_event_at}"
            )

    if result.scan_errors:
        lines.append(f"\nSCAN ERRORS ({len(result.scan_errors)}):")
        for err in result.scan_errors:
            lines.append(f"  {err}")

    lines.append(
        f"\nTotal findings: {len(result.findings)} | Flagged: {result.flagged_count}"
    )
    return "\n".join(lines)


__all__ = [
    "ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES",
    "QUEUE_REPOS",
    "EnumArmedNotEnqueuedStatus",
    "ModelArmedNotEnqueuedFinding",
    "ModelArmedNotEnqueuedScanResult",
    "detect_armed_not_enqueued",
    "render_summary",
    "scan_all_queue_repos",
    "scan_repo",
]
