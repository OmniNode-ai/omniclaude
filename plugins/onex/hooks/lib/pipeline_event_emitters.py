#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pipeline event emitters for Wave 2 observability topics (OMN-2922).

Provides fire-and-forget emit helpers for:
    epic.run.updated       → onex.evt.omniclaude.epic-run-updated.v1
    pr.watch.updated       → onex.evt.omniclaude.pr-watch-updated.v1
    gate.decision          → onex.evt.omniclaude.gate-decision.v1
    budget.cap.hit         → onex.evt.omniclaude.budget-cap-hit.v1
    circuit.breaker.tripped → onex.evt.omniclaude.circuit-breaker-tripped.v1

These helpers are called at terminal outcome points in the epic-team, pr-watch,
slack-gate, and ticket-pipeline skill orchestration flows. All emitters are
non-blocking and never raise exceptions.

Usage (from epic-team or pr-watch skill invocation context):
    from plugins.onex.hooks.lib.pipeline_event_emitters import (
        emit_epic_run_updated,
        emit_pr_watch_updated,
        emit_gate_decision,
        emit_budget_cap_hit,
        emit_circuit_breaker_tripped,
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

    emit_gate_decision(
        gate_id="gate-abc123",
        decision="ACCEPTED",
        ticket_id="OMN-2922",
        gate_type="HIGH_RISK",
        wait_seconds=120.5,
        responder="jonah",
        correlation_id="...",
    )

    emit_budget_cap_hit(
        run_id="...",
        tokens_used=50000,
        tokens_budget=40000,
        cap_reason="max_tokens_injected exceeded",
        correlation_id="...",
    )

    emit_circuit_breaker_tripped(
        session_id="sess-abc",
        failure_count=5,
        threshold=3,
        reset_timeout_seconds=30.0,
        last_error="Connection refused",
        correlation_id="...",
    )

    emit_hostile_reviewer_completed(
        mode="file",
        target="docs/plans/my-plan.md",
        models_attempted=["claude-sonnet-4-20250514"],
        models_succeeded=["claude-sonnet-4-20250514"],
        verdict="risks_noted",
        total_findings=3,
        critical_count=0,
        major_count=1,
        correlation_id="...",
    )
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OMN-6907: Sentinel / empty-string validation helpers
# ---------------------------------------------------------------------------

_SENTINEL_VALUES: frozenset[str] = frozenset({"", "unknown", "none", "null"})


def _validate_required_field(field_name: str, value: str, event_type: str) -> bool:
    """Return True if value is non-empty and not a sentinel.

    Logs a warning and returns False when the value is empty or a known
    sentinel, indicating the caller failed to propagate real data.
    """
    if not value or value.strip().lower() in _SENTINEL_VALUES:
        logger.warning(
            "%s is empty or sentinel (%r) for event %s — skipping emit "
            "(OMN-6907: fix caller to propagate real value)",
            field_name,
            value,
            event_type,
        )
        return False
    return True


def _warn_empty_correlation_id(event_type: str) -> None:
    """Log a warning when correlation_id is empty (non-fatal, event still emits)."""
    logger.warning(
        "correlation_id is empty for event %s — downstream tracing will be "
        "degraded (OMN-6907: fix caller to propagate correlation_id)",
        event_type,
    )


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
    # OMN-6907: Reject empty run_id — downstream upserts key on it
    if not _validate_required_field("run_id", run_id, "epic.run.updated"):
        return
    if not correlation_id:
        _warn_empty_correlation_id("epic.run.updated")
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
    # OMN-6907: Reject empty run_id — downstream upserts key on it
    if not _validate_required_field("run_id", run_id, "pr.watch.updated"):
        return
    if not correlation_id:
        _warn_empty_correlation_id("pr.watch.updated")
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


def emit_gate_decision(
    *,
    gate_id: str,
    decision: Literal["ACCEPTED", "REJECTED", "TIMEOUT"],
    ticket_id: str,
    gate_type: Literal["HIGH_RISK", "MEDIUM_RISK"] = "HIGH_RISK",
    wait_seconds: float = 0.0,
    responder: str | None = None,
    correlation_id: str = "",
    session_id: str | None = None,
) -> None:
    """Emit a gate.decision event (fire-and-forget, never raises).

    Consumers append to gate_decisions keyed by gate_id.
    Consumed by the omnidash /gate-decisions view.

    Args:
        gate_id: Unique identifier for the gate invocation.
        decision: Gate outcome — exactly one of ACCEPTED, REJECTED, TIMEOUT.
        ticket_id: Linear ticket identifier for which the gate was raised.
        gate_type: Gate risk level (HIGH_RISK, MEDIUM_RISK).
        wait_seconds: Wall-clock seconds from gate posting to decision.
        responder: Slack user who responded (None on TIMEOUT).
        correlation_id: End-to-end correlation identifier.
        session_id: Optional Claude Code session identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        now_iso = datetime.now(UTC).isoformat()
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "gate_id": gate_id,
            "decision": decision,
            "ticket_id": ticket_id,
            "gate_type": gate_type,
            "wait_seconds": wait_seconds,
            "correlation_id": correlation_id,
            "emitted_at": now_iso,
            # OMN-6902: projector-compatible field aliases — omnidash read-model
            # consumer reads data.outcome, data.gate_name, data.blocking, data.details
            "outcome": decision,
            "gate_name": gate_type,
            "blocking": decision == "REJECTED",
            "details": f"{gate_type} gate {decision.lower()} after {wait_seconds:.0f}s",
            "timestamp": now_iso,
            "created_at": now_iso,
        }
        if responder is not None:
            payload["responder"] = responder
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("gate.decision", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_budget_cap_hit(
    *,
    run_id: str,
    tokens_used: int,
    tokens_budget: int,
    cap_reason: str = "max_tokens_injected exceeded",
    correlation_id: str = "",
    session_id: str | None = None,
) -> None:
    """Emit a budget.cap.hit event (fire-and-forget, never raises).

    Consumers upsert into pipeline_budget_state keyed by run_id.
    Consumed by the omnidash /pipeline-budget view.

    Args:
        run_id: Pipeline run identifier — upsert key for pipeline_budget_state.
        tokens_used: Actual tokens used at the time of cap.
        tokens_budget: Configured token budget limit.
        cap_reason: Human-readable reason for the cap.
        correlation_id: End-to-end correlation identifier.
        session_id: Optional Claude Code session identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    # OMN-6907: Reject empty run_id — downstream upserts key on it
    if not _validate_required_field("run_id", run_id, "budget.cap.hit"):
        return
    if not correlation_id:
        _warn_empty_correlation_id("budget.cap.hit")
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "run_id": run_id,
            "tokens_used": tokens_used,
            "tokens_budget": tokens_budget,
            "cap_reason": cap_reason,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("budget.cap.hit", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_circuit_breaker_tripped(
    *,
    session_id: str,
    failure_count: int,
    threshold: int,
    reset_timeout_seconds: float,
    last_error: str | None = None,
    correlation_id: str = "",
) -> None:
    """Emit a circuit.breaker.tripped event (fire-and-forget, never raises).

    Consumers append to circuit_breaker_events (event table, keyed by event_id).
    Provides visibility into Kafka connectivity issues during Claude Code sessions.

    Args:
        session_id: Claude Code session identifier.
        failure_count: Number of consecutive failures that triggered the trip.
        threshold: Configured failure threshold.
        reset_timeout_seconds: Seconds until the breaker will attempt HALF_OPEN.
        last_error: String representation of the last error (if available).
        correlation_id: End-to-end correlation identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "failure_count": failure_count,
            "threshold": threshold,
            "reset_timeout_seconds": reset_timeout_seconds,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if last_error is not None:
            payload["last_error"] = last_error
        emit_fn("circuit.breaker.tripped", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_hostile_reviewer_completed(
    *,
    mode: Literal["pr", "file"],
    target: str,
    models_attempted: list[str] | None = None,
    models_succeeded: list[str] | None = None,
    verdict: Literal["clean", "risks_noted", "blocking_issue", "degraded"],
    total_findings: int = 0,
    critical_count: int = 0,
    major_count: int = 0,
    correlation_id: str = "",
    session_id: str | None = None,
) -> None:
    """Emit a hostile.reviewer.completed event (fire-and-forget, never raises).

    Consumers append to hostile_reviewer_runs (event table, keyed by event_id).
    Consumed by the omnidash /hostile-reviewer view.

    Args:
        mode: Review mode — "pr" or "file".
        target: PR number or file path reviewed.
        models_attempted: LLM models attempted during the review.
        models_succeeded: LLM models that returned usable results.
        verdict: Review outcome.
        total_findings: Total number of findings across all models.
        critical_count: Number of critical-severity findings.
        major_count: Number of major-severity findings.
        correlation_id: End-to-end correlation identifier.
        session_id: Optional Claude Code session identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "mode": mode,
            "target": target,
            "models_attempted": models_attempted or [],
            "models_succeeded": models_succeeded or [],
            "verdict": verdict,
            "total_findings": total_findings,
            "critical_count": critical_count,
            "major_count": major_count,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("hostile.reviewer.completed", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_plan_review_completed(
    *,
    session_id: str,
    plan_file: str,
    total_rounds: int,
    final_status: Literal[
        "converged", "capped", "partially_converged", "not_converged"
    ],
    findings_by_severity: dict[str, int] | None = None,
    models_used: list[str] | None = None,
    correlation_id: str = "",
) -> None:
    """Emit a plan.review.completed event (fire-and-forget, never raises).

    Consumers append to plan_review_runs (event table, keyed by event_id).
    Consumed by the omnidash /plan-reviewer page.

    Args:
        session_id: Claude Code session identifier.
        plan_file: Path of the plan file reviewed.
        total_rounds: Total convergence passes completed.
        final_status: Convergence outcome.
        findings_by_severity: Counts keyed by severity (CRITICAL, MAJOR, MINOR, NIT).
        models_used: LLM models used during the review.
        correlation_id: End-to-end correlation identifier.
    """
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "plan_file": plan_file,
            "total_rounds": total_rounds,
            "final_status": final_status,
            "findings_by_severity": findings_by_severity or {},
            "models_used": models_used or [],
            "correlation_id": correlation_id,
            "completed_at": datetime.now(UTC).isoformat(),
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        emit_fn("plan.review.completed", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


def emit_dod_sweep_completed(
    *,
    run_id: str,
    overall_status: str,
    total_tickets: int,
    passed: int,
    failed: int,
    exempted: int,
    lookback_days: int,
    correlation_id: str | None = None,
) -> None:
    """Emit dod.sweep.completed event. Fire-and-forget; never blocks."""
    emit_fn = _get_emit_fn()
    if emit_fn is None:
        return
    # OMN-6907: Reject empty run_id — downstream upserts key on it
    if not _validate_required_field("run_id", run_id, "dod.sweep.completed"):
        return
    try:
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "run_id": run_id,
            "overall_status": overall_status,
            "total_tickets": total_tickets,
            "passed": passed,
            "failed": failed,
            "exempted": exempted,
            "lookback_days": lookback_days,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        emit_fn("dod.sweep.completed", payload)  # type: ignore[operator]
    except Exception:
        pass  # Telemetry must never block pipeline execution


__all__ = [
    "emit_epic_run_updated",
    "emit_pr_watch_updated",
    "emit_gate_decision",
    "emit_budget_cap_hit",
    "emit_circuit_breaker_tripped",
    "emit_hostile_reviewer_completed",
    "emit_plan_review_completed",
    "emit_dod_sweep_completed",
]
