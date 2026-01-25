"""PostgreSQL storage adapter for session snapshots.

Persists session snapshots to PostgreSQL with child tables
for prompts and tools. Supports idempotent upserts.

Table Schema:
    - claude_session_snapshots: Main aggregate with session lifecycle
    - claude_session_prompts: Child table for prompt records
    - claude_session_tools: Child table for tool execution records
    - claude_session_event_idempotency: Deduplication tracking

See migrations/016_create_session_snapshots.sql for full schema.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg

from omniclaude.storage.config import ConfigSessionStorage

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)

# Idempotency domain constant
_IDEMPOTENCY_DOMAIN = "claude_session"


def _ensure_uuid(value: str | UUID | None) -> UUID | None:
    """Convert string to UUID if needed.

    Handles values that may be either string (from JSON deserialization)
    or UUID objects, converting strings to proper UUID type for database.

    Args:
        value: A string, UUID, or None.

    Returns:
        UUID object or None if input was None.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(value)


class SessionSnapshotStore:
    """PostgreSQL storage for session snapshots.

    Handles persistence of session snapshots with child tables
    for prompts and tool executions. Uses asyncpg for async operations
    and connection pooling.

    Thread Safety:
        This class is thread-safe. The asyncpg pool handles connection
        management internally.

    Example:
        >>> config = ConfigSessionStorage(postgres_password=SecretStr("secret"))
        >>> store = SessionSnapshotStore(config)
        >>> await store.initialize()
        >>> try:
        ...     snapshot_id = await store.save_snapshot(snapshot_data, correlation_id)
        ... finally:
        ...     await store.close()
    """

    def __init__(self, config: ConfigSessionStorage) -> None:
        """Initialize store with configuration.

        Args:
            config: PostgreSQL connection configuration.
        """
        self._config = config
        self._pool: Pool | None = None

    @property
    def is_initialized(self) -> bool:
        """Check if the store is initialized and ready for use."""
        return self._pool is not None

    async def initialize(self) -> None:
        """Initialize connection pool.

        Creates an asyncpg connection pool with the configured parameters.
        Must be called before any other operations.

        Raises:
            asyncpg.PostgresError: If connection fails.
        """
        if self._pool is not None:
            logger.warning("SessionSnapshotStore already initialized, skipping")
            return

        self._pool = await asyncpg.create_pool(
            dsn=self._config.dsn,
            min_size=self._config.pool_min_size,
            max_size=self._config.pool_max_size,
            command_timeout=self._config.query_timeout_seconds,
        )
        logger.info(
            "SessionSnapshotStore initialized",
            extra={
                "pool_min_size": self._config.pool_min_size,
                "pool_max_size": self._config.pool_max_size,
                "timeout_seconds": self._config.query_timeout_seconds,
            },
        )

    async def close(self) -> None:
        """Close connection pool.

        Releases all connections back to the pool and closes them.
        Safe to call multiple times.
        """
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("SessionSnapshotStore closed")

    def _require_pool(self) -> Pool:
        """Get pool or raise if not initialized.

        Returns:
            The connection pool.

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._pool is None:
            raise RuntimeError(
                "SessionSnapshotStore not initialized. Call initialize() first."
            )
        return self._pool

    # =========================================================================
    # Public API - CRUD Operations
    # =========================================================================

    async def save_snapshot(
        self,
        snapshot: dict[str, Any],
        correlation_id: UUID,
    ) -> UUID:
        """Save or update a session snapshot.

        Uses upsert semantics - updates existing snapshot if session_id exists.
        Handles child tables (prompts, tools) in a transaction.

        Args:
            snapshot: Snapshot data containing:
                - session_id: Required session identifier
                - status: Session status (orphan, active, ended, timed_out)
                - started_at: Session start time
                - ended_at: Session end time (optional)
                - duration_seconds: Session duration (optional)
                - working_directory: Working directory path
                - git_branch: Git branch name (optional)
                - hook_source: How session was detected
                - end_reason: Why session ended (optional)
                - prompt_count: Number of prompts
                - tool_count: Number of tool executions
                - tools_used_count: Unique tools used
                - event_count: Total events processed
                - last_event_at: Timestamp of last event
                - schema_version: Schema version
                - prompts: List of prompt records (optional)
                - tools: List of tool records (optional)
            correlation_id: Correlation ID for tracing.

        Returns:
            The snapshot_id (UUID) of the saved snapshot.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Upsert main snapshot first (required for foreign key references)
                snapshot_id = await self._upsert_snapshot(conn, snapshot)

                # Sync child tables in parallel if provided.
                # This is safe because:
                # 1. Both operations are within the same transaction (atomicity preserved)
                # 2. prompts and tools tables are independent (no cross-table constraints)
                # 3. Both reference the same snapshot_id but don't conflict with each other
                prompts = snapshot.get("prompts", [])
                tools = snapshot.get("tools", [])

                if prompts or tools:
                    async with asyncio.TaskGroup() as tg:
                        if prompts:
                            tg.create_task(
                                self._sync_prompts(conn, snapshot_id, prompts)
                            )
                        if tools:
                            tg.create_task(
                                self._sync_tools(conn, snapshot_id, tools)
                            )

                logger.debug(
                    "Saved session snapshot",
                    extra={
                        "snapshot_id": str(snapshot_id),
                        "session_id": snapshot.get("session_id"),
                        "correlation_id": str(correlation_id),
                        "prompt_count": len(prompts),
                        "tool_count": len(tools),
                    },
                )

                return snapshot_id

    async def get_snapshot(
        self,
        session_id: str,
        correlation_id: UUID,
    ) -> dict[str, Any] | None:
        """Get snapshot by session_id.

        Includes prompts and tools as nested lists.

        Args:
            session_id: The session identifier.
            correlation_id: Correlation ID for tracing.

        Returns:
            Snapshot dict with prompts and tools, or None if not found.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            # Fetch main snapshot
            row = await conn.fetchrow(
                """
                SELECT
                    snapshot_id, session_id, correlation_id, status,
                    started_at, ended_at, duration_seconds,
                    working_directory, git_branch, hook_source, end_reason,
                    prompt_count, tool_count, tools_used_count, event_count,
                    last_event_at, schema_version, created_at, updated_at
                FROM claude_session_snapshots
                WHERE session_id = $1
                """,
                session_id,
            )

            if row is None:
                logger.debug(
                    "Snapshot not found",
                    extra={
                        "session_id": session_id,
                        "correlation_id": str(correlation_id),
                    },
                )
                return None

            snapshot = dict(row)
            snapshot_id = snapshot["snapshot_id"]

            # Fetch child records
            snapshot["prompts"] = await self._fetch_prompts(conn, snapshot_id)
            snapshot["tools"] = await self._fetch_tools(conn, snapshot_id)

            logger.debug(
                "Retrieved session snapshot",
                extra={
                    "snapshot_id": str(snapshot_id),
                    "session_id": session_id,
                    "correlation_id": str(correlation_id),
                },
            )

            return snapshot

    async def get_snapshot_by_id(
        self,
        snapshot_id: UUID,
        correlation_id: UUID,
    ) -> dict[str, Any] | None:
        """Get snapshot by snapshot_id (UUID).

        Includes prompts and tools as nested lists.

        Args:
            snapshot_id: The snapshot UUID.
            correlation_id: Correlation ID for tracing.

        Returns:
            Snapshot dict with prompts and tools, or None if not found.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            # Fetch main snapshot
            row = await conn.fetchrow(
                """
                SELECT
                    snapshot_id, session_id, correlation_id, status,
                    started_at, ended_at, duration_seconds,
                    working_directory, git_branch, hook_source, end_reason,
                    prompt_count, tool_count, tools_used_count, event_count,
                    last_event_at, schema_version, created_at, updated_at
                FROM claude_session_snapshots
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )

            if row is None:
                logger.debug(
                    "Snapshot not found by ID",
                    extra={
                        "snapshot_id": str(snapshot_id),
                        "correlation_id": str(correlation_id),
                    },
                )
                return None

            snapshot = dict(row)

            # Fetch child records
            snapshot["prompts"] = await self._fetch_prompts(conn, snapshot_id)
            snapshot["tools"] = await self._fetch_tools(conn, snapshot_id)

            logger.debug(
                "Retrieved session snapshot by ID",
                extra={
                    "snapshot_id": str(snapshot_id),
                    "session_id": snapshot.get("session_id"),
                    "correlation_id": str(correlation_id),
                },
            )

            return snapshot

    async def list_snapshots(
        self,
        status: str | None = None,
        working_directory: str | None = None,
        limit: int = 100,
        offset: int = 0,
        correlation_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """List snapshots with optional filters.

        Does NOT include prompts/tools (use get_snapshot for full data).

        Args:
            status: Filter by session status (orphan, active, ended, timed_out).
            working_directory: Filter by working directory (exact match).
            limit: Maximum number of results (default 100, max 1000).
            offset: Number of results to skip (for pagination).
            correlation_id: Correlation ID for tracing.

        Returns:
            List of snapshot dicts (without child records).

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        # Clamp limit to prevent excessive queries
        limit = min(limit, 1000)

        # Build query with optional filters
        conditions: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if status is not None:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if working_directory is not None:
            conditions.append(f"working_directory = ${param_idx}")
            params.append(working_directory)
            param_idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Add limit and offset
        params.append(limit)
        params.append(offset)

        query = f"""
            SELECT
                snapshot_id, session_id, correlation_id, status,
                started_at, ended_at, duration_seconds,
                working_directory, git_branch, hook_source, end_reason,
                prompt_count, tool_count, tools_used_count, event_count,
                last_event_at, schema_version, created_at, updated_at
            FROM claude_session_snapshots
            {where_clause}
            ORDER BY last_event_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        snapshots = [dict(row) for row in rows]

        logger.debug(
            "Listed session snapshots",
            extra={
                "count": len(snapshots),
                "status_filter": status,
                "working_directory_filter": working_directory,
                "limit": limit,
                "offset": offset,
                "correlation_id": str(correlation_id) if correlation_id else None,
            },
        )

        return snapshots

    async def delete_snapshot(
        self,
        session_id: str,
        correlation_id: UUID,
    ) -> bool:
        """Delete a snapshot and its children.

        Child records (prompts, tools) are deleted automatically via CASCADE.

        Args:
            session_id: The session identifier.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if deleted, False if not found.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM claude_session_snapshots WHERE session_id = $1",
                session_id,
            )

        # Parse result string (e.g., "DELETE 1" or "DELETE 0")
        deleted = self._parse_row_count(result) > 0

        logger.debug(
            "Delete snapshot result",
            extra={
                "session_id": session_id,
                "deleted": deleted,
                "correlation_id": str(correlation_id),
            },
        )

        return deleted

    # =========================================================================
    # Public API - Idempotency Operations
    # =========================================================================

    async def check_idempotency(
        self,
        message_id: UUID,
        correlation_id: UUID,
    ) -> bool:
        """Check if message was already processed.

        Uses SELECT to check if message_id exists in idempotency table.

        Args:
            message_id: The unique message identifier.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if processed (duplicate), False if new.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT message_id FROM claude_session_event_idempotency
                WHERE message_id = $1 AND domain = $2
                """,
                message_id,
                _IDEMPOTENCY_DOMAIN,
            )

        is_duplicate = row is not None

        if is_duplicate:
            logger.debug(
                "Duplicate message detected",
                extra={
                    "message_id": str(message_id),
                    "correlation_id": str(correlation_id),
                },
            )

        return is_duplicate

    async def record_idempotency(
        self,
        message_id: UUID,
        correlation_id: UUID,
    ) -> None:
        """Record message as processed for idempotency.

        Uses INSERT ... ON CONFLICT DO NOTHING to handle races.

        Args:
            message_id: The unique message identifier.
            correlation_id: Correlation ID for tracing.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO claude_session_event_idempotency (message_id, domain)
                VALUES ($1, $2)
                ON CONFLICT (message_id) DO NOTHING
                """,
                message_id,
                _IDEMPOTENCY_DOMAIN,
            )

        logger.debug(
            "Recorded idempotency",
            extra={
                "message_id": str(message_id),
                "correlation_id": str(correlation_id),
            },
        )

    async def cleanup_expired_idempotency(
        self,
        correlation_id: UUID,
    ) -> int:
        """Remove expired idempotency records.

        Deletes records where expires_at < NOW().

        Args:
            correlation_id: Correlation ID for tracing.

        Returns:
            Count of removed records.

        Raises:
            RuntimeError: If store not initialized.
            asyncpg.PostgresError: If database operation fails.
        """
        pool = self._require_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM claude_session_event_idempotency
                WHERE expires_at < NOW() AND domain = $1
                """,
                _IDEMPOTENCY_DOMAIN,
            )

        count = self._parse_row_count(result)

        if count > 0:
            logger.info(
                "Cleaned up expired idempotency records",
                extra={
                    "deleted_count": count,
                    "correlation_id": str(correlation_id),
                },
            )

        return count

    # =========================================================================
    # Private Helpers - Snapshot Operations
    # =========================================================================

    async def _upsert_snapshot(
        self,
        conn: Connection,
        snapshot: dict[str, Any],
    ) -> UUID:
        """Upsert main snapshot record.

        Args:
            conn: Database connection (within transaction).
            snapshot: Snapshot data.

        Returns:
            The snapshot_id.
        """
        # Extract required fields
        session_id = snapshot["session_id"]
        status = snapshot.get("status", "active")
        working_directory = snapshot["working_directory"]
        hook_source = snapshot["hook_source"]
        last_event_at = snapshot.get("last_event_at", datetime.now(UTC))

        # Extract optional fields
        correlation_id = snapshot.get("correlation_id")
        started_at = snapshot.get("started_at")
        ended_at = snapshot.get("ended_at")
        duration_seconds = snapshot.get("duration_seconds")
        git_branch = snapshot.get("git_branch")
        end_reason = snapshot.get("end_reason")
        prompt_count = snapshot.get("prompt_count", 0)
        tool_count = snapshot.get("tool_count", 0)
        tools_used_count = snapshot.get("tools_used_count", 0)
        event_count = snapshot.get("event_count", 0)
        schema_version = snapshot.get("schema_version", "1.0.0")

        row = await conn.fetchrow(
            """
            INSERT INTO claude_session_snapshots (
                session_id, correlation_id, status, started_at, ended_at,
                duration_seconds, working_directory, git_branch, hook_source,
                end_reason, prompt_count, tool_count, tools_used_count,
                event_count, last_event_at, schema_version
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (session_id) DO UPDATE SET
                status = EXCLUDED.status,
                ended_at = COALESCE(EXCLUDED.ended_at, claude_session_snapshots.ended_at),
                duration_seconds = COALESCE(EXCLUDED.duration_seconds, claude_session_snapshots.duration_seconds),
                end_reason = COALESCE(EXCLUDED.end_reason, claude_session_snapshots.end_reason),
                prompt_count = EXCLUDED.prompt_count,
                tool_count = EXCLUDED.tool_count,
                tools_used_count = EXCLUDED.tools_used_count,
                event_count = EXCLUDED.event_count,
                last_event_at = EXCLUDED.last_event_at,
                schema_version = EXCLUDED.schema_version
            RETURNING snapshot_id
            """,
            session_id,
            correlation_id,
            status,
            started_at,
            ended_at,
            duration_seconds,
            working_directory,
            git_branch,
            hook_source,
            end_reason,
            prompt_count,
            tool_count,
            tools_used_count,
            event_count,
            last_event_at,
            schema_version,
        )

        # row is guaranteed to exist due to RETURNING clause
        snapshot_id: UUID = row["snapshot_id"]
        return snapshot_id

    async def _sync_prompts(
        self,
        conn: Connection,
        snapshot_id: UUID,
        prompts: list[dict[str, Any]],
    ) -> None:
        """Sync prompt records for snapshot.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotent writes.

        Args:
            conn: Database connection (within transaction).
            snapshot_id: Parent snapshot UUID.
            prompts: List of prompt records.
        """
        if not prompts:
            return

        # Use executemany with ON CONFLICT for efficiency
        await conn.executemany(
            """
            INSERT INTO claude_session_prompts (
                snapshot_id, prompt_id, emitted_at, prompt_preview,
                prompt_length, detected_intent, causation_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (snapshot_id, prompt_id) DO NOTHING
            """,
            [
                (
                    snapshot_id,
                    _ensure_uuid(p["prompt_id"]),
                    p["emitted_at"],
                    p.get("prompt_preview"),
                    p["prompt_length"],
                    p.get("detected_intent"),
                    _ensure_uuid(p.get("causation_id")),
                )
                for p in prompts
            ],
        )

    async def _sync_tools(
        self,
        conn: Connection,
        snapshot_id: UUID,
        tools: list[dict[str, Any]],
    ) -> None:
        """Sync tool records for snapshot.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotent writes.

        Args:
            conn: Database connection (within transaction).
            snapshot_id: Parent snapshot UUID.
            tools: List of tool records.
        """
        if not tools:
            return

        # Use executemany with ON CONFLICT for efficiency
        await conn.executemany(
            """
            INSERT INTO claude_session_tools (
                snapshot_id, tool_execution_id, emitted_at, tool_name,
                success, duration_ms, summary, causation_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (snapshot_id, tool_execution_id) DO NOTHING
            """,
            [
                (
                    snapshot_id,
                    _ensure_uuid(t["tool_execution_id"]),
                    t["emitted_at"],
                    t["tool_name"],
                    t["success"],
                    t["duration_ms"],
                    t.get("summary"),
                    _ensure_uuid(t.get("causation_id")),
                )
                for t in tools
            ],
        )

    async def _fetch_prompts(
        self,
        conn: Connection,
        snapshot_id: UUID,
    ) -> list[dict[str, Any]]:
        """Fetch prompt records for snapshot.

        Args:
            conn: Database connection.
            snapshot_id: Parent snapshot UUID.

        Returns:
            List of prompt dicts.
        """
        rows = await conn.fetch(
            """
            SELECT
                id, prompt_id, emitted_at, prompt_preview,
                prompt_length, detected_intent, causation_id
            FROM claude_session_prompts
            WHERE snapshot_id = $1
            ORDER BY emitted_at ASC
            """,
            snapshot_id,
        )
        return [dict(row) for row in rows]

    async def _fetch_tools(
        self,
        conn: Connection,
        snapshot_id: UUID,
    ) -> list[dict[str, Any]]:
        """Fetch tool records for snapshot.

        Args:
            conn: Database connection.
            snapshot_id: Parent snapshot UUID.

        Returns:
            List of tool dicts.
        """
        rows = await conn.fetch(
            """
            SELECT
                id, tool_execution_id, emitted_at, tool_name,
                success, duration_ms, summary, causation_id
            FROM claude_session_tools
            WHERE snapshot_id = $1
            ORDER BY emitted_at ASC
            """,
            snapshot_id,
        )
        return [dict(row) for row in rows]

    def _parse_row_count(self, result: str) -> int:
        """Parse row count from asyncpg execute result string.

        asyncpg returns strings like:
        - "INSERT 0 1" -> 1 row inserted
        - "UPDATE 5" -> 5 rows updated
        - "DELETE 3" -> 3 rows deleted

        Args:
            result: Result string from execute().

        Returns:
            Number of affected rows.
        """
        try:
            parts = result.split()
            if len(parts) >= 2:
                return int(parts[-1])
        except (ValueError, IndexError):
            pass
        return 0


__all__ = ["SessionSnapshotStore"]
