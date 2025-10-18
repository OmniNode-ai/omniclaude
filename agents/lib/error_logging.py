"""
Error Event Logging Module

Captures and logs error events during workflow execution for debugging and analysis.
Integrates with the error_success_maps for correlation tracking.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from .db import get_pg_pool


async def log_error_event(
    run_id: str,
    error_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """
    Log an error event to the database.

    Args:
        run_id: The workflow run ID
        error_type: Type of error (e.g., "VALIDATION_ERROR", "EXECUTION_ERROR", "TIMEOUT")
        message: Human-readable error message
        details: Additional error details as JSON
        correlation_id: Optional correlation ID for linking related events

    Returns:
        The error event ID
    """
    error_id = str(uuid.uuid4())

    pool = await get_pg_pool()
    if pool is None:
        return error_id

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO error_events (
                id, run_id, correlation_id, error_type, message, details
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb
            )
            """,
            error_id,
            run_id,
            correlation_id,
            error_type,
            message,
            json.dumps(details or {}, default=str),
        )

    return error_id


async def log_validation_error(
    run_id: str, phase: str, validation_type: str, message: str, details: Optional[Dict[str, Any]] = None
) -> str:
    """Log a validation error event."""
    return await log_error_event(
        run_id=run_id,
        error_type="VALIDATION_ERROR",
        message=f"[{phase}] {validation_type}: {message}",
        details={
            "phase": phase,
            "validation_type": validation_type,
            "timestamp": datetime.now().isoformat(),
            **(details or {}),
        },
    )


async def log_execution_error(
    run_id: str, phase: str, task_id: Optional[str], error: Exception, details: Optional[Dict[str, Any]] = None
) -> str:
    """Log an execution error event."""
    return await log_error_event(
        run_id=run_id,
        error_type="EXECUTION_ERROR",
        message=f"[{phase}] Task {task_id or 'unknown'}: {str(error)}",
        details={
            "phase": phase,
            "task_id": task_id,
            "error_class": error.__class__.__name__,
            "timestamp": datetime.now().isoformat(),
            **(details or {}),
        },
    )


async def log_timeout_error(
    run_id: str, phase: str, timeout_seconds: float, details: Optional[Dict[str, Any]] = None
) -> str:
    """Log a timeout error event."""
    return await log_error_event(
        run_id=run_id,
        error_type="TIMEOUT_ERROR",
        message=f"[{phase}] Operation timed out after {timeout_seconds}s",
        details={
            "phase": phase,
            "timeout_seconds": timeout_seconds,
            "timestamp": datetime.now().isoformat(),
            **(details or {}),
        },
    )


async def log_quorum_error(
    run_id: str,
    phase: str,
    quorum_decision: str,
    confidence: float,
    deficiencies: list,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Log a quorum validation error."""
    return await log_error_event(
        run_id=run_id,
        error_type="QUORUM_ERROR",
        message=f"[{phase}] Quorum validation failed: {quorum_decision} (confidence: {confidence:.2f})",
        details={
            "phase": phase,
            "quorum_decision": quorum_decision,
            "confidence": confidence,
            "deficiencies": deficiencies,
            "timestamp": datetime.now().isoformat(),
            **(details or {}),
        },
    )


async def get_error_events_for_run(run_id: str) -> list:
    """Get all error events for a specific run."""
    pool = await get_pg_pool()
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, error_type, message, details, created_at
            FROM error_events
            WHERE run_id = $1
            ORDER BY created_at DESC
            """,
            run_id,
        )

        return [dict(row) for row in rows]


async def get_error_events_by_type(error_type: str, limit: int = 100) -> list:
    """Get recent error events by type."""
    pool = await get_pg_pool()
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, run_id, error_type, message, details, created_at
            FROM error_events
            WHERE error_type = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            error_type,
            limit,
        )

        return [dict(row) for row in rows]
