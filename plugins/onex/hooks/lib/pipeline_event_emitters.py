#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pipeline event emitters for Wave 2 observability topics (OMN-2922).

Provides fire-and-forget emit helpers for:
    epic.run.updated       → onex.evt.omniclaude.epic-run-updated.v1
    pr.watch.updated       → onex.evt.omniclaude.pr-watch-updated.v1

These helpers are called at terminal outcome points in the epic-team and pr-watch
skill orchestration flows. All emitters are non-blocking and never raise exceptions.

Usage (from epic-team or pr-watch skill invocation context):
    from plugins.onex.hooks.lib.pipeline_event_emitters import (
        emit_epic_run_updated,
        emit_pr_watch_updated,
    )

    emit_epic_run_updated(
        run_id="...",
        epic_id="OMN-2920",
        status="completed",
        tickets_total=5,
        tickets_completed=5,
        tickets_failed=0,
        correlation_id="...",
    )

    emit_pr_watch_updated(
        run_id="...",
        pr_number=381,
        repo="OmniNode-ai/omniclaude",
        ticket_id="OMN-2922",
        status="approved",
        review_cycles_used=1,
        watch_duration_hours=0.5,
        correlation_id="...",
    )
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)


def _get_emit_fn() -> object:
    """Lazily resolve emit_event from emit_client_wrapper.

    Returns the function on success, None if the daemon client is unavailable.
    """
    try:
        from emit_client_wrapper import emit_event  # noqa: PLC0415

        return emit_event
    except ImportError:
        return None


def emit_epic_run_updated(
    *,
    run_id: str,
    epic_id: str,
    status: Literal["running", "completed", "failed", "partial", "cancelled"],
    tickets_total: int = 0,
    tickets_completed: int = 0,
    tickets_failed: int = 0,
    phase: str | None = None,
    correlation_id: str = "",
    session_id: str | None = None,
) -> None:
    """Emit an epic.run.updated event (fire-and-forget, never raises).

    Consumers upsert into epic_run_lease keyed by run_id.
    Consumed by the omnidash /epic-pipeline view.

    Args:
        run_id: Epic run identifier — upsert key for epic_run_lease.
        epic_id: Linear epic identifier (e.g. "OMN-2920").
        status: Current run status.
        tickets_total: Total tickets in this epic run.
        tickets_completed: Number of tickets completed so far.
        tickets_failed: Number of tickets that failed.
        phase: Current pipeline phase name (optional).
        correlation_id: End-to-end correlation identifier.
        session_id: Optional Claude Code session identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "run_id": run_id,
            "epic_id": epic_id,
            "status": status,
            "tickets_total": tickets_total,
            "tickets_completed": tickets_completed,
            "tickets_failed": tickets_failed,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if phase is not None:
            payload["phase"] = phase
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("epic.run.updated", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_pr_watch_updated(
    *,
    run_id: str,
    pr_number: int,
    repo: str,
    ticket_id: str,
    status: Literal["watching", "approved", "capped", "timeout", "failed"],
    review_cycles_used: int = 0,
    watch_duration_hours: float = 0.0,
    correlation_id: str = "",
    session_id: str | None = None,
) -> None:
    """Emit a pr.watch.updated event (fire-and-forget, never raises).

    Consumers upsert into pr_watch_state keyed by run_id.
    Consumed by the omnidash /pr-watch view.

    Args:
        run_id: PR watch run identifier — upsert key for pr_watch_state.
        pr_number: GitHub PR number.
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        ticket_id: Linear ticket identifier (e.g. "OMN-2922").
        status: Current watch status.
        review_cycles_used: Number of pr-review-dev fix cycles consumed.
        watch_duration_hours: Wall-clock hours elapsed since watch started.
        correlation_id: End-to-end correlation identifier.
        session_id: Optional Claude Code session identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "run_id": run_id,
            "pr_number": pr_number,
            "repo": repo,
            "ticket_id": ticket_id,
            "status": status,
            "review_cycles_used": review_cycles_used,
            "watch_duration_hours": watch_duration_hours,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("pr.watch.updated", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


__all__ = [
    "emit_epic_run_updated",
    "emit_pr_watch_updated",
]
