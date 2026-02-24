#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Epic Milestone Notifier - Slack notifications for epic lifecycle events.

Wraps PipelineSlackNotifier to emit Slack notifications at the four
defined milestone events of an epic-team run.

## Slack Event Policy

Only four events trigger Slack notifications:

1. Pipeline started   — notify_pipeline_started() in PipelineSlackNotifier
2. Ticket completed   — notify_ticket_completed()
3. Ticket failed      — notify_ticket_failed()
4. Epic done          — notify_epic_done()

**Zero Slack during monitoring polling turns** — monitoring loops that poll
ticket status must use console output only (print/log). Do NOT add calls to
this module inside polling or retry loops. Violating this floods the Slack
thread with noise and violates the epic-team Slack event policy.

## thread_ts Contract

The notifier is stateless with respect to thread_ts. The caller (prompt.md /
state.yaml) is responsible for persisting and supplying thread_ts across
invocations:

    # First call — thread_ts=None → posts a root message
    ts = notify_ticket_completed(..., thread_ts=None)

    # Persist ts in state.yaml
    state["slack_thread_ts"] = ts

    # Subsequent calls — pass ts → threads replies
    ts = notify_ticket_completed(..., thread_ts=state["slack_thread_ts"])

The notifier never overwrites a non-None thread_ts with None. If the
underlying Slack call fails, the original thread_ts is returned unchanged.
This preserves the caller's ability to continue threading even after a
transient Slack failure.

## Graceful Degradation

This module is never fatal. If Slack is unavailable, not configured, or the
underlying handler raises, the functions log a warning and return the
thread_ts that was passed in (preserving caller state). The epic-team run
continues unaffected.

Message Format:
    [OMN-XXXX][epic-team][run:abcd-1234]
    Ticket OMN-YYYY completed — PR: https://...

Related Tickets:
    - OMN-2448: Initial implementation

.. versionadded:: 0.2.3
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path bootstrap — allow importing pipeline_slack_notifier from the same lib/
# directory when this module is run standalone (e.g. during tests).
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from pipeline_slack_notifier import (  # noqa: E402
    PipelineSlackNotifier,
    SlackHandlerProtocol,
)

# =============================================================================
# Correlation prefix helper
# =============================================================================

_EPIC_TEAM_SEGMENT = "epic-team"


def _make_prefix(epic_id: str, run_id: str) -> str:
    """Format the correlation prefix for epic-team Slack messages.

    Format: [OMN-XXXX][epic-team][run:abcd-1234]
    """
    return f"[{epic_id}][{_EPIC_TEAM_SEGMENT}][run:{run_id}]"


# =============================================================================
# Internal helper: run async in a sync context
# =============================================================================


def _run(coro: Any) -> Any:  # type: ignore[return]
    """Run an async coroutine from a synchronous context.

    Handles both cases:
    - No running event loop → asyncio.run()
    - Already inside an event loop → ThreadPoolExecutor to avoid nesting
    """
    try:
        # Raises RuntimeError if no loop is running — that's the signal we need.
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=5)
    except RuntimeError:
        return asyncio.run(coro)


# =============================================================================
# Internal helper: build a per-call PipelineSlackNotifier
# =============================================================================


def _make_notifier(
    epic_id: str,
    run_id: str,
    *,
    handler: SlackHandlerProtocol | None = None,
) -> PipelineSlackNotifier:
    """Construct a PipelineSlackNotifier scoped to one epic-team message.

    Uses epic_id as the ticket_id so the correlation prefix shows the epic.
    """
    return PipelineSlackNotifier(
        ticket_id=epic_id,
        run_id=run_id,
        handler=handler,
    )


# =============================================================================
# Public API
# =============================================================================


def notify_ticket_completed(
    epic_id: str,
    run_id: str,
    ticket_id: str,
    repo: str,
    pr_url: str | None = None,
    thread_ts: str | None = None,
    *,
    _handler: SlackHandlerProtocol | None = None,
) -> str | None:
    """Notify that a ticket has been completed within an epic run.

    Posts (or threads) a Slack message announcing the ticket completion.
    Optionally includes a PR URL in the message.

    This is one of the four permitted Slack events in the epic-team flow.
    Do NOT call this inside a polling loop.

    Args:
        epic_id: The Linear epic identifier (e.g. "OMN-2400").
        run_id:  Unique run identifier for this epic execution (e.g. "abcd-1234").
        ticket_id: The completed ticket (e.g. "OMN-2401").
        repo:    Repository name where the work was done.
        pr_url:  Optional PR URL to include in the message.
        thread_ts: Existing Slack thread timestamp. None → new root message.

    Returns:
        The Slack thread timestamp to persist for future calls.
        Returns the original thread_ts (not None) if the Slack call fails,
        so the caller's thread state is preserved.
    """
    prefix = _make_prefix(epic_id, run_id)
    summary_parts = [f"Ticket {ticket_id} completed"]
    if pr_url:
        summary_parts.append(f"PR: {pr_url}")
    summary = " — ".join(summary_parts)

    message = f"{prefix}\n{summary}"
    logger.info(message)

    notifier = _make_notifier(epic_id, run_id, handler=_handler)

    try:
        result_ts: str | None = _run(
            notifier.notify_phase_completed(
                phase=_EPIC_TEAM_SEGMENT,
                summary=f"Ticket {ticket_id} completed",
                thread_ts=thread_ts,
                pr_url=pr_url,
            )
        )
        # Preserve non-None thread_ts on failure (result_ts may be None)
        return result_ts if result_ts is not None else thread_ts
    except Exception as exc:
        logger.warning("notify_ticket_completed failed (non-fatal): %s", exc)
        return thread_ts


def notify_ticket_failed(
    epic_id: str,
    run_id: str,
    ticket_id: str,
    repo: str,
    reason: str,
    thread_ts: str | None = None,
    *,
    _handler: SlackHandlerProtocol | None = None,
) -> str | None:
    """Notify that a ticket has failed within an epic run.

    Posts (or threads) a Slack message announcing the ticket failure with
    the provided reason.

    This is one of the four permitted Slack events in the epic-team flow.
    Do NOT call this inside a polling loop.

    Args:
        epic_id:   The Linear epic identifier.
        run_id:    Unique run identifier for this epic execution.
        ticket_id: The failed ticket.
        repo:      Repository name where the work was attempted.
        reason:    Human-readable reason for the failure.
        thread_ts: Existing Slack thread timestamp. None → new root message.

    Returns:
        The Slack thread timestamp to persist for future calls.
        Returns the original thread_ts (not None) if the Slack call fails.
    """
    prefix = _make_prefix(epic_id, run_id)
    message = f"{prefix}\nTicket {ticket_id} failed — {reason}"
    logger.warning(message)

    notifier = _make_notifier(epic_id, run_id, handler=_handler)

    try:
        result_ts = _run(
            notifier.notify_blocked(
                phase=_EPIC_TEAM_SEGMENT,
                reason=f"Ticket {ticket_id} failed — {reason}",
                block_kind="failed_exception",
                thread_ts=thread_ts,
            )
        )
        return result_ts if result_ts is not None else thread_ts
    except Exception as exc:
        logger.warning("notify_ticket_failed failed (non-fatal): %s", exc)
        return thread_ts


def notify_epic_done(
    epic_id: str,
    run_id: str,
    completed: list[str],
    failed: list[str],
    prs: list[str],
    thread_ts: str | None = None,
    *,
    _handler: SlackHandlerProtocol | None = None,
) -> str | None:
    """Notify that all tickets in an epic run have been processed.

    Posts (or threads) a final summary Slack message for the entire epic run,
    listing completed tickets, failed tickets, and associated PRs.

    This is one of the four permitted Slack events in the epic-team flow.
    Do NOT call this inside a polling loop.

    Args:
        epic_id:   The Linear epic identifier.
        run_id:    Unique run identifier for this epic execution.
        completed: List of ticket IDs that completed successfully.
        failed:    List of ticket IDs that failed.
        prs:       List of PR URLs produced during this run.
        thread_ts: Existing Slack thread timestamp. None → new root message.

    Returns:
        The Slack thread timestamp to persist for future calls.
        Returns the original thread_ts (not None) if the Slack call fails.
    """
    prefix = _make_prefix(epic_id, run_id)

    lines: list[str] = [f"{prefix}", "Epic run complete"]
    if completed:
        lines.append(f"Completed ({len(completed)}): {', '.join(completed)}")
    if failed:
        lines.append(f"Failed ({len(failed)}): {', '.join(failed)}")
    if prs:
        lines.append(f"PRs: {', '.join(prs)}")

    summary = "\n".join(lines[1:])  # everything after the prefix line
    logger.info("\n".join(lines))

    notifier = _make_notifier(epic_id, run_id, handler=_handler)

    try:
        result_ts = _run(
            notifier.notify_phase_completed(
                phase=_EPIC_TEAM_SEGMENT,
                summary=summary,
                thread_ts=thread_ts,
            )
        )
        return result_ts if result_ts is not None else thread_ts
    except Exception as exc:
        logger.warning("notify_epic_done failed (non-fatal): %s", exc)
        return thread_ts


__all__ = [
    "notify_epic_done",
    "notify_ticket_completed",
    "notify_ticket_failed",
]
