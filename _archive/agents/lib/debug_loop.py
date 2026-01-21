from datetime import datetime
from typing import Any

from .db import get_pg_pool


async def record_workflow_step(
    *,
    run_id: str,
    step_index: int,
    phase: str,
    started_at: str,
    completed_at: str,
    duration_ms: float,
    success: bool,
    error: str | None = None,
    correlation_id: str | None = None,
    applied_tf_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a workflow_steps row if Postgres is configured.

    This is a no-op when PG is not configured.
    """
    pool = await get_pg_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        # Convert string timestamps to datetime objects
        started_dt = (
            datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if isinstance(started_at, str)
            else started_at
        )
        completed_dt = (
            datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            if isinstance(completed_at, str)
            else completed_at
        )

        await conn.execute(
            """
            INSERT INTO workflow_steps (
                id, run_id, step_index, phase, correlation_id,
                applied_tf_id, started_at, completed_at, duration_ms, success, error
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8::int, $9, $10
            )
            """,
            run_id,
            step_index,
            phase,
            correlation_id,
            applied_tf_id,
            started_dt,
            completed_dt,
            int(duration_ms),
            success,
            error,
        )
