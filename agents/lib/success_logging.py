"""
Success Event Logging Module

Captures and logs success events during workflow execution for debugging and analysis.
Integrates with the error_success_maps for correlation tracking and golden state management.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from .db import get_pg_pool


async def log_success_event(
    run_id: str,
    task_id: Optional[str] = None,
    approval_source: str = "auto",
    is_golden: bool = False,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Log a success event to the database.
    
    Args:
        run_id: The workflow run ID
        task_id: Optional task ID that succeeded
        approval_source: Source of approval (e.g., "auto", "human", "quorum")
        is_golden: Whether this represents a golden state
        correlation_id: Optional correlation ID for linking related events
        metadata: Additional success metadata as JSON
        
    Returns:
        The success event ID
    """
    success_id = str(uuid.uuid4())
    
    pool = await get_pg_pool()
    if pool is None:
        return success_id
        
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO success_events (
                id, run_id, task_id, correlation_id, approval_source, is_golden
            ) VALUES (
                $1, $2, $3, $4, $5, $6
            )
            """,
            success_id,
            run_id,
            task_id,
            correlation_id,
            approval_source,
            is_golden
        )
    
    return success_id


async def log_phase_success(
    run_id: str,
    phase: str,
    duration_ms: float,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Log a phase completion success event."""
    return await log_success_event(
        run_id=run_id,
        task_id=f"phase_{phase}",
        approval_source="auto",
        is_golden=False,
        metadata={
            "phase": phase,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }
    )


async def log_task_success(
    run_id: str,
    task_id: str,
    agent: str,
    duration_ms: float,
    is_golden: bool = False,
    approval_source: str = "auto",
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Log a task completion success event."""
    return await log_success_event(
        run_id=run_id,
        task_id=task_id,
        approval_source=approval_source,
        is_golden=is_golden,
        metadata={
            "agent": agent,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }
    )


async def log_quorum_success(
    run_id: str,
    phase: str,
    confidence: float,
    decision: str,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Log a quorum validation success event."""
    return await log_success_event(
        run_id=run_id,
        task_id=f"quorum_{phase}",
        approval_source="quorum",
        is_golden=True,
        metadata={
            "phase": phase,
            "confidence": confidence,
            "decision": decision,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }
    )


async def mark_golden_state(
    success_id: str,
    approval_source: str = "human",
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Mark a success event as a golden state.
    
    Args:
        success_id: The success event ID to mark as golden
        approval_source: Source of the golden state approval
        metadata: Additional approval metadata
        
    Returns:
        True if successful, False otherwise
    """
    pool = await get_pg_pool()
    if pool is None:
        return False
        
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE success_events 
            SET is_golden = true, approval_source = $2
            WHERE id = $1
            """,
            success_id,
            approval_source
        )
        
        return True


async def get_success_events_for_run(run_id: str) -> list:
    """Get all success events for a specific run."""
    pool = await get_pg_pool()
    if pool is None:
        return []
        
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task_id, approval_source, is_golden, created_at
            FROM success_events
            WHERE run_id = $1
            ORDER BY created_at DESC
            """,
            run_id
        )
        
        return [dict(row) for row in rows]


async def get_golden_states_for_run(run_id: str) -> list:
    """Get all golden state success events for a specific run."""
    pool = await get_pg_pool()
    if pool is None:
        return []
        
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task_id, approval_source, created_at
            FROM success_events
            WHERE run_id = $1 AND is_golden = true
            ORDER BY created_at DESC
            """,
            run_id
        )
        
        return [dict(row) for row in rows]
