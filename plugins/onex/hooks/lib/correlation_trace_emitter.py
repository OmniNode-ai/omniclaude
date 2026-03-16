# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Correlation trace span emitter -- adapter layer for trace span emission.

Emits trace span events via the emit daemon for the omnidash /trace page.
Each span represents a unit of work during a Claude Code session (hook
invocation, tool execution, routing decision, etc.) and can be nested
via parent_span_id to form a span tree.

Architecture (three-layer separation):
    - Schema (omniclaude.hooks.schemas): ModelCorrelationTraceSpanPayload -- pure data
    - Adapter layer (this module): Owns daemon integration -- validates payload,
      calls emit_event(), provides convenience helpers
    - Emit daemon (omniclaude publisher): Routes flat JSON to Kafka topic

INVARIANT: This function MUST fail open and NEVER block hook/session execution.
If Kafka/daemon is unavailable, log warning and return False.

Related Tickets:
    - OMN-5047: Correlation trace span emitter for omnidash /trace page
    - OMN-5053: Epic -- /trace page wire session integration

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


def emit_trace_span(
    *,
    span_kind: str,
    operation_name: str,
    status: str,
    started_at: datetime,
    trace_id: UUID | None = None,
    span_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    correlation_id: UUID | None = None,
    session_id: str | None = None,
    ended_at: datetime | None = None,
    duration_ms: int | None = None,
    metadata: dict[str, str] | None = None,
    error_message: str | None = None,
) -> bool:
    """Emit a correlation trace span event via the emit daemon (non-blocking, fail-open).

    Validates input via ModelCorrelationTraceSpanPayload (frozen Pydantic model),
    serializes to dict, and sends through the emit daemon to Kafka.

    INVARIANT: This function MUST fail open and NEVER block session execution.

    Args:
        span_kind: Kind of span (session, hook, tool_use, routing, etc.).
            Must be a valid EnumTraceSpanKind value.
        operation_name: Human-readable name of the operation (max 500 chars).
        status: Span completion status (ok, error, timeout, skipped).
            Must be a valid EnumTraceSpanStatus value.
        started_at: When the span started (UTC, timezone-aware).
        trace_id: Groups all spans in a single trace. Defaults to a new UUID.
        span_id: Unique identifier for this span. Defaults to a new UUID.
        parent_span_id: ID of the parent span (None for root spans).
        correlation_id: Correlation ID for distributed tracing. Defaults to trace_id.
        session_id: Session ID. Defaults to SESSION_ID env var or "unknown".
        ended_at: When the span ended (UTC, None if still in progress).
        duration_ms: Duration in milliseconds (None if still in progress).
        metadata: Key-value metadata for the span. Must not contain secrets.
        error_message: Error message if status is ERROR (max 500 chars).

    Returns:
        True if successfully emitted to daemon socket, False otherwise.
        Note: True means accepted by daemon, not delivered to Kafka.
    """
    try:
        from omniclaude.hooks.schemas import (
            EnumTraceSpanKind,
            EnumTraceSpanStatus,
            ModelCorrelationTraceSpanPayload,
        )

        # Validate enums (fail-open on invalid)
        try:
            validated_kind = EnumTraceSpanKind(span_kind)
        except ValueError:
            valid_kinds = [k.value for k in EnumTraceSpanKind]
            logger.error(
                "Invalid span_kind: %r (valid: %s)",
                span_kind,
                valid_kinds,
            )
            return False

        try:
            validated_status = EnumTraceSpanStatus(status)
        except ValueError:
            valid_statuses = [s.value for s in EnumTraceSpanStatus]
            logger.error(
                "Invalid span status: %r (valid: %s)",
                status,
                valid_statuses,
            )
            return False

        # Resolve defaults
        resolved_span_id = span_id if span_id is not None else uuid4()
        resolved_trace_id = trace_id if trace_id is not None else uuid4()
        resolved_correlation_id = (
            correlation_id if correlation_id is not None else resolved_trace_id
        )
        resolved_session_id = (
            session_id
            if session_id is not None
            else os.environ.get("SESSION_ID", "unknown")
        )

        # Build validated payload -- Pydantic enforces all constraints
        payload_model = ModelCorrelationTraceSpanPayload(
            span_id=resolved_span_id,
            trace_id=resolved_trace_id,
            parent_span_id=parent_span_id,
            correlation_id=resolved_correlation_id,
            session_id=resolved_session_id,
            span_kind=validated_kind,
            operation_name=operation_name,
            status=validated_status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            metadata=metadata or {},
            error_message=error_message,
        )

        # Serialize to flat dict for daemon transport
        payload = payload_model.model_dump(mode="json")

        from .emit_client_wrapper import emit_event

        return emit_event("correlation.trace.span", payload)

    except Exception:
        # Fail open -- trace emission must never crash a hook or session
        logger.warning(
            "correlation_trace_span_emit_failed",
            exc_info=True,
        )
        return False


def emit_trace_span_from_hook(
    *,
    hook_name: str,
    started_at: datetime,
    trace_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    correlation_id: UUID | None = None,
    session_id: str | None = None,
    ended_at: datetime | None = None,
    duration_ms: int | None = None,
    status: str = "ok",
    error_message: str | None = None,
    metadata: dict[str, str] | None = None,
) -> bool:
    """Convenience wrapper for emitting a hook-type trace span.

    Suitable for calling from hook scripts (SessionStart, UserPromptSubmit,
    PostToolUse, SessionEnd) to record their execution as a trace span.

    Args:
        hook_name: Name of the hook (e.g., "SessionStart", "UserPromptSubmit").
        started_at: When the hook started (UTC, timezone-aware).
        trace_id: Groups all spans in a single trace.
        parent_span_id: ID of the parent span (None for root spans).
        correlation_id: Correlation ID for distributed tracing.
        session_id: Session ID.
        ended_at: When the hook completed (UTC).
        duration_ms: Hook duration in milliseconds.
        status: Completion status (default: "ok").
        error_message: Error message if status is "error".
        metadata: Additional metadata.

    Returns:
        True if successfully emitted, False otherwise.
    """
    now = datetime.now(UTC)
    resolved_ended_at = ended_at if ended_at is not None else now
    resolved_duration_ms = duration_ms
    if resolved_duration_ms is None and resolved_ended_at is not None:
        delta = resolved_ended_at - started_at
        resolved_duration_ms = max(0, int(delta.total_seconds() * 1000))

    return emit_trace_span(
        span_kind="hook",
        operation_name=hook_name,
        status=status,
        started_at=started_at,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        correlation_id=correlation_id,
        session_id=session_id,
        ended_at=resolved_ended_at,
        duration_ms=resolved_duration_ms,
        metadata=metadata,
        error_message=error_message,
    )


def emit_trace_span_from_tool(
    *,
    tool_name: str,
    started_at: datetime,
    success: bool = True,
    trace_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    correlation_id: UUID | None = None,
    session_id: str | None = None,
    ended_at: datetime | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    metadata: dict[str, str] | None = None,
) -> bool:
    """Convenience wrapper for emitting a tool_use-type trace span.

    Suitable for calling from PostToolUse hooks to record tool executions
    as trace spans.

    Args:
        tool_name: Name of the tool (e.g., "Read", "Bash", "Edit").
        started_at: When the tool execution started (UTC, timezone-aware).
        success: Whether the tool execution succeeded.
        trace_id: Groups all spans in a single trace.
        parent_span_id: ID of the parent span (None for root spans).
        correlation_id: Correlation ID for distributed tracing.
        session_id: Session ID.
        ended_at: When the tool execution completed (UTC).
        duration_ms: Tool execution duration in milliseconds.
        error_message: Error message if tool failed.
        metadata: Additional metadata.

    Returns:
        True if successfully emitted, False otherwise.
    """
    status = "ok" if success else "error"
    now = datetime.now(UTC)
    resolved_ended_at = ended_at if ended_at is not None else now
    resolved_duration_ms = duration_ms
    if resolved_duration_ms is None and resolved_ended_at is not None:
        delta = resolved_ended_at - started_at
        resolved_duration_ms = max(0, int(delta.total_seconds() * 1000))

    return emit_trace_span(
        span_kind="tool_use",
        operation_name=tool_name,
        status=status,
        started_at=started_at,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        correlation_id=correlation_id,
        session_id=session_id,
        ended_at=resolved_ended_at,
        duration_ms=resolved_duration_ms,
        metadata=metadata,
        error_message=error_message,
    )
