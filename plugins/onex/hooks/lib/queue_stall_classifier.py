# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Merge-queue stall classifier [OMN-9065].

Pure classification + repeat-offender tracking for the `/onex:unstick_queue`
skill. Decides whether a PR sitting at the head of a merge queue is a
``STALL`` (safe to dequeue+re-enqueue), a ``BROKEN`` (real failure — leave
alone), a ``HEALTHY`` (no action), or an ``ESCALATE`` (same PR repeatedly
unstuck within a window → surface via ``/onex:record_friction`` instead of
auto-healing again).

The classifier is side-effect free for the classification step itself; it
only touches the filesystem when the caller asks it to record an unstick
action via :func:`record_unstick`. Storage lives under
``$ONEX_STATE_DIR/queue-unstick/<repo>/<pr>.json`` so persistence is
externally observable and survives process restarts.

Used by:
    * ``plugins/onex/skills/unstick_queue/SKILL.md``
    * ``scripts/cron-unstick-queue.sh``

Refs:
    * Ticket: OMN-9065
    * Sibling classifier pattern: ``tick_activity_classifier.py`` (OMN-9053)
"""

from __future__ import annotations

import fcntl
import json
import os
import pathlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# Thresholds from OMN-9065 ticket DoD. The AWAITING_CHECKS gate (30 min) is
# deliberately longer than the orphaned-check gate (20 min) because a queue
# head may legitimately be awaiting fresh CI for a few cycles before any
# individual check-run would be considered orphaned.
AWAITING_CHECKS_STALL_MINUTES: int = 30
ORPHANED_CHECK_MINUTES: int = 20

# Repeat-offender escalation per ticket DoD: if the SAME PR gets unstuck more
# than 3 times in 1 hour, stop auto-unsticking and emit friction.
REPEAT_OFFENDER_WINDOW_SECONDS: int = 3600
REPEAT_OFFENDER_MAX_UNSTICKS: int = 3


class EnumQueueStallVerdict(StrEnum):
    """Four-way classification of a queue-head PR."""

    HEALTHY = "healthy"
    STALL = "stall"
    BROKEN = "broken"
    ESCALATE = "escalate"


def _parse_iso8601(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (GitHub API format), returning None on fall-through.

    GitHub returns timestamps like ``2026-04-17T15:13:14Z``. ``fromisoformat``
    in 3.12 accepts the trailing ``Z``; in earlier versions it does not, so
    normalise just in case a different runtime surface this function.
    """
    if not value:
        return None
    try:
        normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        return None


def _minutes_since(timestamp: datetime | None, now: datetime) -> float:
    """Return minutes elapsed between ``timestamp`` and ``now``.

    Returns ``0.0`` when ``timestamp`` is ``None`` so callers can treat a
    missing timestamp as "not yet old enough to stall" rather than as an
    error — GitHub's API occasionally returns null entry timestamps for
    freshly-enqueued PRs.
    """
    if timestamp is None:
        return 0.0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    delta = now - timestamp
    return delta.total_seconds() / 60.0


def has_failed_required_check(
    status_check_rollup: list[dict[str, Any]],
    required_contexts: set[str],
) -> bool:
    """True when any REQUIRED check in the rollup has conclusion=FAILURE.

    A required failure means the PR is genuinely broken; unsticking it via
    dequeue/re-enqueue would just re-fail. Per DoD non-goal: do not manually
    mark or bypass failed checks.
    """
    for check in status_check_rollup:
        name = check.get("name") or check.get("context") or ""
        if name not in required_contexts:
            continue
        conclusion = (check.get("conclusion") or "").upper()
        if conclusion == "FAILURE":
            return True
    return False


def has_orphaned_check(
    status_check_rollup: list[dict[str, Any]],
    now: datetime,
    orphan_minutes: int = ORPHANED_CHECK_MINUTES,
) -> bool:
    """True when at least one check has been IN_PROGRESS >= orphan_minutes.

    Only ``status=IN_PROGRESS`` with ``conclusion=null`` counts as an orphan
    candidate. ``status=None`` (freshly-queued or StatusContext-normalised) and
    ``status=QUEUED`` are excluded: they represent checks that have not yet
    started, not checks that are hung mid-run.  Accepting null/QUEUED would
    trigger an unstick on a legitimately-pending check before it has had a
    chance to run.
    """
    for check in status_check_rollup:
        status = check.get("status")
        conclusion = check.get("conclusion")
        if status == "IN_PROGRESS" and conclusion is None:
            started_at = _parse_iso8601(check.get("startedAt"))
            if started_at is None:
                # No start time → can't prove it's orphaned; err on the side
                # of healthy rather than unsticking prematurely.
                continue
            if _minutes_since(started_at, now) >= orphan_minutes:
                return True
    return False


def classify_queue_entry(
    entry: dict[str, Any],
    status_check_rollup: list[dict[str, Any]],
    required_contexts: set[str],
    now: datetime,
    prior_unsticks: list[datetime] | None = None,
    awaiting_minutes_threshold: int = AWAITING_CHECKS_STALL_MINUTES,
    orphan_minutes_threshold: int = ORPHANED_CHECK_MINUTES,
    repeat_window_seconds: int = REPEAT_OFFENDER_WINDOW_SECONDS,
    repeat_max: int = REPEAT_OFFENDER_MAX_UNSTICKS,
) -> EnumQueueStallVerdict:
    """Classify a single merge-queue entry.

    Arguments:
        entry: Merge-queue entry dict with at least ``position``, ``state``,
            ``enqueuedAt`` keys (from ``repository.mergeQueue.entries`` GraphQL).
        status_check_rollup: List of check-run/status entries on the PR.
        required_contexts: Set of required status-check context names from
            ``branches/main/protection/required_status_checks.contexts``.
        now: Current timestamp (injected for deterministic testing per repo
            invariant: no ``datetime.now()`` defaults).
        prior_unsticks: Prior unstick timestamps for this PR from
            :func:`load_unstick_history`. None/empty = no history.
        awaiting_minutes_threshold: Minutes at queue head with AWAITING_CHECKS
            before considering a stall.
        orphan_minutes_threshold: Minutes a check must be IN_PROGRESS/null
            before considered orphaned.
        repeat_window_seconds: Time window for repeat-offender detection.
        repeat_max: Max unsticks allowed within window before escalation.

    Returns:
        EnumQueueStallVerdict:
            - HEALTHY: not at queue head, or head but not stalled
            - STALL: head, AWAITING_CHECKS > threshold, with orphaned check
            - BROKEN: head, has a failed required check (skip — real failure)
            - ESCALATE: same PR unstuck >= repeat_max times in repeat_window
    """
    position = entry.get("position")
    if position != 1:
        return EnumQueueStallVerdict.HEALTHY

    state = (entry.get("state") or "").upper()
    if state != "AWAITING_CHECKS":
        return EnumQueueStallVerdict.HEALTHY

    enqueued_at = _parse_iso8601(entry.get("enqueuedAt"))
    if _minutes_since(enqueued_at, now) < awaiting_minutes_threshold:
        return EnumQueueStallVerdict.HEALTHY

    if has_failed_required_check(status_check_rollup, required_contexts):
        return EnumQueueStallVerdict.BROKEN

    if not has_orphaned_check(status_check_rollup, now, orphan_minutes_threshold):
        return EnumQueueStallVerdict.HEALTHY

    # At this point the PR is a genuine stall candidate. Escalate instead of
    # auto-healing if we've already unstuck it too many times recently.
    if prior_unsticks:
        cutoff = now.timestamp() - repeat_window_seconds
        recent = [t for t in prior_unsticks if t.timestamp() >= cutoff]
        if len(recent) >= repeat_max:
            return EnumQueueStallVerdict.ESCALATE

    return EnumQueueStallVerdict.STALL


def _state_root() -> pathlib.Path:
    """Return the queue-unstick state root. Raises KeyError if ONEX_STATE_DIR unset.

    Uses the fail-fast pattern from ``~/.claude/CLAUDE.md`` operating rule #8:
    silent defaults produce cross-machine breakage. Callers that want a
    tolerant path (e.g. classification-only dry-runs) should catch KeyError.
    """
    base = os.environ["ONEX_STATE_DIR"]
    return pathlib.Path(base) / "queue-unstick"


def load_unstick_history(repo: str, pr_number: int) -> list[datetime]:
    """Load prior unstick timestamps for ``(repo, pr_number)``.

    Returns an empty list when the state file is missing or corrupt —
    classifier behaviour degrades gracefully (treat as first-time stall)
    rather than blocking recovery on missing state.
    """
    try:
        path = _state_root() / repo / f"pr-{pr_number}.json"
    except KeyError:
        return []
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    raw_times = data.get("unsticks") or []
    parsed: list[datetime] = []
    for value in raw_times:
        if not isinstance(value, str):
            continue
        ts = _parse_iso8601(value)
        if ts is not None:
            parsed.append(ts)
    return parsed


def record_unstick(repo: str, pr_number: int, when: datetime) -> pathlib.Path:
    """Append an unstick event for ``(repo, pr_number)`` at ``when``.

    Creates the per-repo directory on demand. Returns the path written. Raises
    KeyError if ``ONEX_STATE_DIR`` is unset — unlike classification, persisting
    state requires a configured environment.
    """
    root = _state_root() / repo
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"pr-{pr_number}.json"

    # Use an exclusive lock file to serialise concurrent read-modify-write so
    # that two overlapping tick/manual invocations cannot drop timestamps or
    # leave a truncated JSON file behind.
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            existing: dict[str, Any] = {"repo": repo, "pr": pr_number, "unsticks": []}
            if path.is_file():
                try:
                    loaded = json.loads(path.read_text())
                    if isinstance(loaded, dict):
                        existing = loaded
                        if not isinstance(existing.get("unsticks"), list):
                            existing["unsticks"] = []
                except (json.JSONDecodeError, OSError):
                    pass

            existing["repo"] = repo
            existing["pr"] = pr_number
            existing["unsticks"].append(when.astimezone(UTC).isoformat())

            path.write_text(json.dumps(existing, indent=2, sort_keys=True))
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
    return path


__all__ = [
    "AWAITING_CHECKS_STALL_MINUTES",
    "ORPHANED_CHECK_MINUTES",
    "REPEAT_OFFENDER_MAX_UNSTICKS",
    "REPEAT_OFFENDER_WINDOW_SECONDS",
    "EnumQueueStallVerdict",
    "classify_queue_entry",
    "has_failed_required_check",
    "has_orphaned_check",
    "load_unstick_history",
    "record_unstick",
]
