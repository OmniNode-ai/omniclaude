"""
State Snapshot Capture Module

Captures state snapshots during workflow execution for debugging, replay, and analysis.
Supports both inline storage (small snapshots) and object storage (large snapshots).
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import get_pg_pool


class StateSnapshotCapture:
    """Captures and stores state snapshots during workflow execution."""

    def __init__(self, max_inline_size: int = 1024 * 1024):  # 1MB default
        self.max_inline_size = max_inline_size

    async def capture_snapshot(
        self,
        run_id: str,
        state_data: Dict[str, Any],
        is_success_state: bool = False,
        pii_tags: Optional[List[str]] = None,
        redaction_policy: Optional[str] = None,
        replay_safe: bool = True,
    ) -> str:
        """
        Capture a state snapshot and store it in the database.

        Args:
            run_id: Identifier for the workflow run
            state_data: The state data to capture
            is_success_state: Whether this represents a successful state
            pii_tags: Tags for PII detection
            redaction_policy: Policy for data redaction
            replay_safe: Whether this snapshot is safe for replay

        Returns:
            The snapshot ID
        """
        snapshot_id = str(uuid.uuid4())

        # Serialize state data
        state_json = json.dumps(state_data, default=str)
        state_bytes = state_json.encode("utf-8")

        # Calculate content digest
        content_digest = hashlib.sha256(state_bytes).digest()

        # Determine storage strategy
        storage_uri = None
        snapshot_content = None

        if len(state_bytes) <= self.max_inline_size:
            # Store inline in database
            snapshot_content = state_data
        else:
            # For large snapshots, we would store in object storage
            # For now, we'll store inline but this could be extended
            storage_uri = f"object-storage://snapshots/{snapshot_id}.json"
            snapshot_content = state_data

        # Store in database
        pool = await get_pg_pool()
        if pool is None:
            return snapshot_id

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO state_snapshots (
                    id, run_id, is_success_state, pii_tags, redaction_policy,
                    replay_safe, content_digest, storage_uri, snapshot
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb
                )
                """,
                snapshot_id,
                run_id,
                is_success_state,
                pii_tags,
                redaction_policy,
                replay_safe,
                content_digest,
                storage_uri,
                json.dumps(snapshot_content, default=str),
            )

        return snapshot_id

    async def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a state snapshot by ID."""
        pool = await get_pg_pool()
        if pool is None:
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT snapshot, storage_uri FROM state_snapshots WHERE id = $1", snapshot_id)

            if not row:
                return None

            if row["storage_uri"]:
                # TODO: Implement object storage retrieval
                return None
            else:
                return row["snapshot"]

    async def get_success_snapshots(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all success state snapshots for a run."""
        pool = await get_pg_pool()
        if pool is None:
            return []

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, snapshot, created_at 
                FROM state_snapshots 
                WHERE run_id = $1 AND is_success_state = true
                ORDER BY created_at DESC
                """,
                run_id,
            )

            return [dict(row) for row in rows]

    async def mark_golden_state(
        self, snapshot_id: str, approval_source: str, approval_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a snapshot as a golden state with approval metadata.

        Args:
            snapshot_id: The snapshot to mark as golden
            approval_source: Source of the approval (e.g., "human", "quorum", "automated")
            approval_metadata: Additional approval metadata

        Returns:
            True if successful, False otherwise
        """
        pool = await get_pg_pool()
        if pool is None:
            return False

        async with pool.acquire() as conn:
            # Update the snapshot with approval information
            await conn.execute(
                """
                UPDATE state_snapshots 
                SET snapshot = jsonb_set(
                    COALESCE(snapshot, '{}'::jsonb),
                    '{approval}',
                    $2::jsonb
                )
                WHERE id = $1
                """,
                snapshot_id,
                json.dumps(
                    {
                        "source": approval_source,
                        "metadata": approval_metadata or {},
                        "approved_at": datetime.now().isoformat(),
                    }
                ),
            )

            return True


# Global instance for easy access
state_capture = StateSnapshotCapture()


async def capture_workflow_state(run_id: str, phase: str, state_data: Dict[str, Any], is_success: bool = False) -> str:
    """
    Convenience function to capture workflow state at phase boundaries.

    Args:
        run_id: The workflow run ID
        phase: The current phase name
        state_data: The state data to capture
        is_success: Whether this is a successful state

    Returns:
        The snapshot ID
    """
    return await state_capture.capture_snapshot(
        run_id=run_id,
        state_data={"phase": phase, "timestamp": datetime.now().isoformat(), "state": state_data},
        is_success_state=is_success,
        replay_safe=True,
    )
