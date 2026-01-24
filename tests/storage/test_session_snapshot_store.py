# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for SessionSnapshotStore.

Unit tests for the PostgreSQL storage adapter for session snapshots.
All database interactions are mocked via asyncpg mock objects.

Test Categories:
    - Initialization: Pool creation, closure, state management
    - Save Snapshot: Upsert operations, child table syncing, transactions
    - Get Snapshot: Retrieval by session_id and snapshot_id
    - List Snapshots: Filtering, pagination, limit clamping
    - Delete Snapshot: Removal and not-found handling
    - Idempotency: Duplicate detection, recording, cleanup

Note:
    These are unit tests that mock asyncpg. Integration tests with real
    PostgreSQL are separate and require STORAGE_INTEGRATION_TESTS=1.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from omniclaude.storage import ConfigSessionStorage, SessionSnapshotStore


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def config() -> ConfigSessionStorage:
    """Create a test configuration with minimal settings."""
    return ConfigSessionStorage(
        postgres_host="localhost",
        postgres_port=5432,
        postgres_database="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        pool_min_size=1,
        pool_max_size=5,
        query_timeout_seconds=10,
    )


@pytest.fixture
def store(config: ConfigSessionStorage) -> SessionSnapshotStore:
    """Create an uninitialized store instance."""
    return SessionSnapshotStore(config)


@pytest.fixture
def mock_pool() -> AsyncMock:
    """Create a mock asyncpg pool.

    The pool supports:
    - acquire() as async context manager returning connection
    - close() async method
    """
    pool = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock asyncpg connection.

    The connection supports:
    - fetchrow() for single row queries
    - fetch() for multi-row queries
    - execute() for DML statements
    - executemany() for batch operations
    - transaction() as context manager
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()

    # Mock transaction context manager
    @asynccontextmanager
    async def mock_transaction() -> AsyncGenerator[None, None]:
        yield

    conn.transaction = mock_transaction
    return conn


def setup_pool_with_connection(pool: AsyncMock, conn: AsyncMock) -> None:
    """Configure pool.acquire() to return connection via async context manager."""

    @asynccontextmanager
    async def mock_acquire() -> AsyncGenerator[AsyncMock, None]:
        yield conn

    pool.acquire = mock_acquire


def create_test_snapshot_data(
    session_id: str | None = None,
    include_prompts: bool = False,
    include_tools: bool = False,
) -> dict[str, Any]:
    """Create test snapshot data dictionary."""
    data: dict[str, Any] = {
        "session_id": session_id or f"session-{uuid4().hex[:8]}",
        "status": "active",
        "working_directory": "/workspace/test",
        "hook_source": "startup",
        "last_event_at": datetime.now(UTC),
        "git_branch": "main",
        "prompt_count": 0,
        "tool_count": 0,
        "tools_used_count": 0,
        "event_count": 0,
        "schema_version": "1.0.0",
    }

    if include_prompts:
        data["prompts"] = [
            {
                "prompt_id": uuid4(),
                "emitted_at": datetime.now(UTC),
                "prompt_preview": "Test prompt...",
                "prompt_length": 100,
                "detected_intent": "debug",
                "causation_id": uuid4(),
            }
        ]
        data["prompt_count"] = 1

    if include_tools:
        data["tools"] = [
            {
                "tool_execution_id": uuid4(),
                "emitted_at": datetime.now(UTC),
                "tool_name": "Read",
                "success": True,
                "duration_ms": 50,
                "summary": "Read file contents",
                "causation_id": uuid4(),
            }
        ]
        data["tool_count"] = 1
        data["tools_used_count"] = 1

    return data


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Tests for store initialization and lifecycle."""

    def test_store_starts_uninitialized(self, store: SessionSnapshotStore) -> None:
        """Store should not be initialized on construction."""
        assert store.is_initialized is False

    @pytest.mark.asyncio
    async def test_initialize_creates_pool(self, store: SessionSnapshotStore) -> None:
        """initialize() should create asyncpg connection pool."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()

        # create_pool is async, so we need AsyncMock that returns the pool
        with patch(
            "omniclaude.storage.session_snapshot_store.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ) as mock_create:
            await store.initialize()

            mock_create.assert_called_once()
            assert store.is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_uses_config_dsn(
        self, config: ConfigSessionStorage
    ) -> None:
        """initialize() should use DSN from config."""
        store = SessionSnapshotStore(config)
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()

        with patch(
            "omniclaude.storage.session_snapshot_store.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ) as mock_create:
            await store.initialize()

            # Verify DSN was passed
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["dsn"] == config.dsn
            assert call_kwargs["min_size"] == config.pool_min_size
            assert call_kwargs["max_size"] == config.pool_max_size
            assert call_kwargs["command_timeout"] == config.query_timeout_seconds

    @pytest.mark.asyncio
    async def test_initialize_skips_if_already_initialized(
        self, store: SessionSnapshotStore
    ) -> None:
        """initialize() should skip if already initialized."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()

        with patch(
            "omniclaude.storage.session_snapshot_store.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ) as mock_create:
            await store.initialize()
            await store.initialize()  # Second call should skip

            # Should only be called once
            assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_close_closes_pool(self, store: SessionSnapshotStore) -> None:
        """close() should close the connection pool."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()

        with patch(
            "omniclaude.storage.session_snapshot_store.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await store.initialize()
            assert store.is_initialized is True

            await store.close()

            mock_pool.close.assert_called_once()
            assert store.is_initialized is False

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, store: SessionSnapshotStore) -> None:
        """close() should be safe to call multiple times."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()

        with patch(
            "omniclaude.storage.session_snapshot_store.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            await store.initialize()
            await store.close()
            await store.close()  # Should not raise

            # close() only called once since pool is None after first close
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_initialize_is_safe(
        self, store: SessionSnapshotStore
    ) -> None:
        """close() should be safe to call before initialize()."""
        await store.close()  # Should not raise
        assert store.is_initialized is False

    @pytest.mark.asyncio
    async def test_require_pool_raises_when_not_initialized(
        self, store: SessionSnapshotStore
    ) -> None:
        """_require_pool() should raise RuntimeError when not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            store._require_pool()


# =============================================================================
# Save Snapshot Tests
# =============================================================================


class TestSaveSnapshot:
    """Tests for save_snapshot method."""

    @pytest.mark.asyncio
    async def test_save_snapshot_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """save_snapshot should raise if store not initialized."""
        snapshot = create_test_snapshot_data()

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.save_snapshot(snapshot, uuid4())

    @pytest.mark.asyncio
    async def test_save_snapshot_returns_uuid(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should return snapshot UUID."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data()
        result = await store.save_snapshot(snapshot, uuid4())

        assert result == snapshot_id
        assert isinstance(result, UUID)

    @pytest.mark.asyncio
    async def test_save_snapshot_calls_upsert(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should execute upsert SQL."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data(session_id="test-session-123")
        await store.save_snapshot(snapshot, uuid4())

        # Verify fetchrow was called (upsert uses RETURNING)
        mock_connection.fetchrow.assert_called_once()
        call_args = mock_connection.fetchrow.call_args
        sql = call_args[0][0]

        # Verify SQL contains expected clauses
        assert "INSERT INTO claude_session_snapshots" in sql
        assert "ON CONFLICT (session_id) DO UPDATE" in sql
        assert "RETURNING snapshot_id" in sql

    @pytest.mark.asyncio
    async def test_save_snapshot_syncs_prompts(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should sync prompts to child table."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data(include_prompts=True)
        await store.save_snapshot(snapshot, uuid4())

        # Verify executemany was called for prompts
        mock_connection.executemany.assert_called()
        # Check first executemany call (prompts)
        prompt_call = mock_connection.executemany.call_args_list[0]
        sql = prompt_call[0][0]
        assert "INSERT INTO claude_session_prompts" in sql

    @pytest.mark.asyncio
    async def test_save_snapshot_syncs_tools(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should sync tools to child table."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data(include_tools=True)
        await store.save_snapshot(snapshot, uuid4())

        # Verify executemany was called for tools
        mock_connection.executemany.assert_called()
        # Check last executemany call (tools)
        tool_call = mock_connection.executemany.call_args_list[-1]
        sql = tool_call[0][0]
        assert "INSERT INTO claude_session_tools" in sql

    @pytest.mark.asyncio
    async def test_save_snapshot_with_prompts_and_tools(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should handle both prompts and tools."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data(include_prompts=True, include_tools=True)
        await store.save_snapshot(snapshot, uuid4())

        # Should have two executemany calls (prompts and tools)
        assert mock_connection.executemany.call_count == 2

    @pytest.mark.asyncio
    async def test_save_snapshot_skips_empty_children(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """save_snapshot should skip sync for empty prompts/tools lists."""
        snapshot_id = uuid4()
        mock_connection.fetchrow.return_value = {"snapshot_id": snapshot_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        snapshot = create_test_snapshot_data()  # No prompts or tools
        await store.save_snapshot(snapshot, uuid4())

        # executemany should not be called
        mock_connection.executemany.assert_not_called()


# =============================================================================
# Get Snapshot Tests
# =============================================================================


class TestGetSnapshot:
    """Tests for get_snapshot and get_snapshot_by_id methods."""

    @pytest.mark.asyncio
    async def test_get_snapshot_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """get_snapshot should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.get_snapshot("test-session", uuid4())

    @pytest.mark.asyncio
    async def test_get_snapshot_returns_none_for_missing(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """get_snapshot should return None when session not found."""
        mock_connection.fetchrow.return_value = None
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.get_snapshot("nonexistent-session", uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_returns_snapshot_dict(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """get_snapshot should return snapshot dict when found."""
        snapshot_id = uuid4()
        session_id = "test-session-123"
        mock_row = {
            "snapshot_id": snapshot_id,
            "session_id": session_id,
            "correlation_id": uuid4(),
            "status": "active",
            "started_at": datetime.now(UTC),
            "ended_at": None,
            "duration_seconds": None,
            "working_directory": "/workspace",
            "git_branch": "main",
            "hook_source": "startup",
            "end_reason": None,
            "prompt_count": 0,
            "tool_count": 0,
            "tools_used_count": 0,
            "event_count": 0,
            "last_event_at": datetime.now(UTC),
            "schema_version": "1.0.0",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_connection.fetchrow.return_value = mock_row
        mock_connection.fetch.return_value = []  # Empty prompts/tools
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.get_snapshot(session_id, uuid4())

        assert result is not None
        assert result["session_id"] == session_id
        assert result["snapshot_id"] == snapshot_id
        assert "prompts" in result
        assert "tools" in result

    @pytest.mark.asyncio
    async def test_get_snapshot_includes_prompts_and_tools(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """get_snapshot should include child records."""
        snapshot_id = uuid4()
        mock_row = {
            "snapshot_id": snapshot_id,
            "session_id": "test",
            "correlation_id": uuid4(),
            "status": "active",
            "started_at": datetime.now(UTC),
            "ended_at": None,
            "duration_seconds": None,
            "working_directory": "/workspace",
            "git_branch": None,
            "hook_source": "startup",
            "end_reason": None,
            "prompt_count": 1,
            "tool_count": 1,
            "tools_used_count": 1,
            "event_count": 2,
            "last_event_at": datetime.now(UTC),
            "schema_version": "1.0.0",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_prompts = [
            {
                "id": uuid4(),
                "prompt_id": uuid4(),
                "emitted_at": datetime.now(UTC),
                "prompt_preview": "Test...",
                "prompt_length": 50,
                "detected_intent": "debug",
                "causation_id": uuid4(),
            }
        ]
        mock_tools = [
            {
                "id": uuid4(),
                "tool_execution_id": uuid4(),
                "emitted_at": datetime.now(UTC),
                "tool_name": "Read",
                "success": True,
                "duration_ms": 100,
                "summary": "Read file",
                "causation_id": uuid4(),
            }
        ]

        # Configure mock to return different values on consecutive calls
        mock_connection.fetchrow.return_value = mock_row
        mock_connection.fetch.side_effect = [mock_prompts, mock_tools]
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.get_snapshot("test", uuid4())

        assert result is not None
        assert len(result["prompts"]) == 1
        assert len(result["tools"]) == 1
        assert result["prompts"][0]["prompt_preview"] == "Test..."
        assert result["tools"][0]["tool_name"] == "Read"

    @pytest.mark.asyncio
    async def test_get_snapshot_by_id_returns_none_for_missing(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """get_snapshot_by_id should return None when not found."""
        mock_connection.fetchrow.return_value = None
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.get_snapshot_by_id(uuid4(), uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_by_id_returns_snapshot_dict(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """get_snapshot_by_id should return snapshot when found."""
        snapshot_id = uuid4()
        mock_row = {
            "snapshot_id": snapshot_id,
            "session_id": "test",
            "correlation_id": uuid4(),
            "status": "ended",
            "started_at": datetime.now(UTC),
            "ended_at": datetime.now(UTC),
            "duration_seconds": 3600.0,
            "working_directory": "/workspace",
            "git_branch": "feature",
            "hook_source": "startup",
            "end_reason": "clear",
            "prompt_count": 5,
            "tool_count": 10,
            "tools_used_count": 3,
            "event_count": 15,
            "last_event_at": datetime.now(UTC),
            "schema_version": "1.0.0",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        mock_connection.fetchrow.return_value = mock_row
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.get_snapshot_by_id(snapshot_id, uuid4())

        assert result is not None
        assert result["snapshot_id"] == snapshot_id
        assert result["status"] == "ended"


# =============================================================================
# List Snapshots Tests
# =============================================================================


class TestListSnapshots:
    """Tests for list_snapshots method."""

    @pytest.mark.asyncio
    async def test_list_snapshots_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """list_snapshots should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.list_snapshots()

    @pytest.mark.asyncio
    async def test_list_snapshots_returns_empty_list(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should return empty list when no snapshots."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.list_snapshots()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_snapshots_returns_snapshot_list(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should return list of snapshot dicts."""
        mock_rows = [
            {
                "snapshot_id": uuid4(),
                "session_id": "session-1",
                "correlation_id": uuid4(),
                "status": "active",
                "started_at": datetime.now(UTC),
                "ended_at": None,
                "duration_seconds": None,
                "working_directory": "/workspace/1",
                "git_branch": "main",
                "hook_source": "startup",
                "end_reason": None,
                "prompt_count": 1,
                "tool_count": 2,
                "tools_used_count": 1,
                "event_count": 3,
                "last_event_at": datetime.now(UTC),
                "schema_version": "1.0.0",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
            {
                "snapshot_id": uuid4(),
                "session_id": "session-2",
                "correlation_id": uuid4(),
                "status": "ended",
                "started_at": datetime.now(UTC),
                "ended_at": datetime.now(UTC),
                "duration_seconds": 1800.0,
                "working_directory": "/workspace/2",
                "git_branch": "develop",
                "hook_source": "resume",
                "end_reason": "clear",
                "prompt_count": 5,
                "tool_count": 10,
                "tools_used_count": 4,
                "event_count": 15,
                "last_event_at": datetime.now(UTC),
                "schema_version": "1.0.0",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        ]
        mock_connection.fetch.return_value = mock_rows
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.list_snapshots()

        assert len(result) == 2
        assert result[0]["session_id"] == "session-1"
        assert result[1]["session_id"] == "session-2"

    @pytest.mark.asyncio
    async def test_list_snapshots_with_status_filter(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should filter by status."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.list_snapshots(status="active")

        # Verify SQL contains status filter
        call_args = mock_connection.fetch.call_args
        sql = call_args[0][0]
        assert "status = $1" in sql
        # Verify status value was passed
        assert call_args[0][1] == "active"

    @pytest.mark.asyncio
    async def test_list_snapshots_with_working_directory_filter(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should filter by working_directory."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.list_snapshots(working_directory="/workspace/project")

        # Verify SQL contains working_directory filter
        call_args = mock_connection.fetch.call_args
        sql = call_args[0][0]
        assert "working_directory = $1" in sql
        assert call_args[0][1] == "/workspace/project"

    @pytest.mark.asyncio
    async def test_list_snapshots_with_combined_filters(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should combine multiple filters."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.list_snapshots(
            status="active",
            working_directory="/workspace",
        )

        # Verify SQL contains both filters
        call_args = mock_connection.fetch.call_args
        sql = call_args[0][0]
        assert "status = $1" in sql
        assert "working_directory = $2" in sql

    @pytest.mark.asyncio
    async def test_list_snapshots_with_pagination(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should support limit and offset."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.list_snapshots(limit=10, offset=20)

        # Verify SQL contains LIMIT and OFFSET
        call_args = mock_connection.fetch.call_args
        sql = call_args[0][0]
        assert "LIMIT $1" in sql or "LIMIT $2" in sql
        assert "OFFSET" in sql

    @pytest.mark.asyncio
    async def test_list_snapshots_clamps_limit_to_1000(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """list_snapshots should clamp limit to maximum of 1000."""
        mock_connection.fetch.return_value = []
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.list_snapshots(limit=5000)

        # Verify limit was clamped
        call_args = mock_connection.fetch.call_args
        params = call_args[0][1:]  # Skip SQL
        # Last two params are limit and offset
        assert 1000 in params  # limit should be clamped


# =============================================================================
# Delete Snapshot Tests
# =============================================================================


class TestDeleteSnapshot:
    """Tests for delete_snapshot method."""

    @pytest.mark.asyncio
    async def test_delete_snapshot_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """delete_snapshot should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.delete_snapshot("test-session", uuid4())

    @pytest.mark.asyncio
    async def test_delete_snapshot_returns_true_on_success(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """delete_snapshot should return True when row deleted."""
        mock_connection.execute.return_value = "DELETE 1"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.delete_snapshot("test-session", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_snapshot_returns_false_for_missing(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """delete_snapshot should return False when session not found."""
        mock_connection.execute.return_value = "DELETE 0"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.delete_snapshot("nonexistent-session", uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_snapshot_executes_correct_sql(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """delete_snapshot should execute DELETE with correct session_id."""
        mock_connection.execute.return_value = "DELETE 1"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        session_id = "session-to-delete"
        await store.delete_snapshot(session_id, uuid4())

        # Verify SQL
        call_args = mock_connection.execute.call_args
        sql = call_args[0][0]
        assert "DELETE FROM claude_session_snapshots" in sql
        assert "WHERE session_id = $1" in sql
        assert call_args[0][1] == session_id


# =============================================================================
# Idempotency Tests
# =============================================================================


class TestIdempotency:
    """Tests for idempotency methods."""

    @pytest.mark.asyncio
    async def test_check_idempotency_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """check_idempotency should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.check_idempotency(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_check_idempotency_returns_false_for_new(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """check_idempotency should return False for new (not duplicate) message."""
        # None means message_id not found -> not a duplicate
        mock_connection.fetchrow.return_value = None
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.check_idempotency(uuid4(), uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_check_idempotency_returns_true_for_duplicate(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """check_idempotency should return True for duplicate message."""
        # Row returned means message_id exists -> is a duplicate
        message_id = uuid4()
        mock_connection.fetchrow.return_value = {"message_id": message_id}
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.check_idempotency(message_id, uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_check_idempotency_queries_correct_table(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """check_idempotency should query idempotency table with correct params."""
        mock_connection.fetchrow.return_value = None
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        message_id = uuid4()
        await store.check_idempotency(message_id, uuid4())

        # Verify SQL
        call_args = mock_connection.fetchrow.call_args
        sql = call_args[0][0]
        assert "SELECT message_id FROM claude_session_event_idempotency" in sql
        assert "WHERE message_id = $1 AND domain = $2" in sql
        assert call_args[0][1] == message_id

    @pytest.mark.asyncio
    async def test_record_idempotency_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """record_idempotency should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.record_idempotency(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_record_idempotency_inserts_record(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """record_idempotency should insert into idempotency table."""
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        message_id = uuid4()
        await store.record_idempotency(message_id, uuid4())

        # Verify SQL
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        sql = call_args[0][0]
        assert "INSERT INTO claude_session_event_idempotency" in sql
        assert "ON CONFLICT (message_id) DO NOTHING" in sql
        assert call_args[0][1] == message_id

    @pytest.mark.asyncio
    async def test_cleanup_expired_idempotency_requires_initialization(
        self, store: SessionSnapshotStore
    ) -> None:
        """cleanup_expired_idempotency should raise if store not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.cleanup_expired_idempotency(uuid4())

    @pytest.mark.asyncio
    async def test_cleanup_expired_idempotency_returns_count(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """cleanup_expired_idempotency should return count of deleted records."""
        mock_connection.execute.return_value = "DELETE 5"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.cleanup_expired_idempotency(uuid4())

        assert result == 5

    @pytest.mark.asyncio
    async def test_cleanup_expired_idempotency_returns_zero_when_none(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """cleanup_expired_idempotency should return 0 when no expired records."""
        mock_connection.execute.return_value = "DELETE 0"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        result = await store.cleanup_expired_idempotency(uuid4())

        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_idempotency_executes_correct_sql(
        self,
        store: SessionSnapshotStore,
        mock_pool: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """cleanup_expired_idempotency should delete expired records."""
        mock_connection.execute.return_value = "DELETE 0"
        setup_pool_with_connection(mock_pool, mock_connection)
        store._pool = mock_pool

        await store.cleanup_expired_idempotency(uuid4())

        # Verify SQL
        call_args = mock_connection.execute.call_args
        sql = call_args[0][0]
        assert "DELETE FROM claude_session_event_idempotency" in sql
        assert "WHERE expires_at < NOW()" in sql


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods:
    """Tests for private helper methods."""

    def test_parse_row_count_handles_insert(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should parse INSERT result."""
        result = store._parse_row_count("INSERT 0 1")
        assert result == 1

    def test_parse_row_count_handles_update(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should parse UPDATE result."""
        result = store._parse_row_count("UPDATE 5")
        assert result == 5

    def test_parse_row_count_handles_delete(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should parse DELETE result."""
        result = store._parse_row_count("DELETE 3")
        assert result == 3

    def test_parse_row_count_handles_zero(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should handle zero rows."""
        result = store._parse_row_count("DELETE 0")
        assert result == 0

    def test_parse_row_count_handles_invalid_format(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should return 0 for invalid format."""
        result = store._parse_row_count("INVALID")
        assert result == 0

    def test_parse_row_count_handles_empty_string(
        self, store: SessionSnapshotStore
    ) -> None:
        """_parse_row_count should return 0 for empty string."""
        result = store._parse_row_count("")
        assert result == 0


# =============================================================================
# Config Tests
# =============================================================================


class TestConfigSessionStorage:
    """Tests for ConfigSessionStorage configuration class."""

    def test_config_has_default_values(self) -> None:
        """Config should have sensible defaults."""
        config = ConfigSessionStorage(
            postgres_password=SecretStr("test"),
        )
        assert config.postgres_host == "192.168.86.200"
        assert config.postgres_port == 5436
        assert config.postgres_database == "omninode_bridge"
        assert config.postgres_user == "postgres"
        assert config.pool_min_size == 2
        assert config.pool_max_size == 10
        assert config.query_timeout_seconds == 30

    def test_config_dsn_property(self) -> None:
        """Config DSN should be properly formatted."""
        config = ConfigSessionStorage(
            postgres_host="localhost",
            postgres_port=5432,
            postgres_database="test_db",
            postgres_user="test_user",
            postgres_password=SecretStr("test_password"),
        )
        dsn = config.dsn
        assert dsn == "postgresql://test_user:test_password@localhost:5432/test_db"

    def test_config_dsn_async_property(self) -> None:
        """Config async DSN should use asyncpg scheme."""
        config = ConfigSessionStorage(
            postgres_host="localhost",
            postgres_port=5432,
            postgres_database="test_db",
            postgres_user="test_user",
            postgres_password=SecretStr("test_password"),
        )
        dsn = config.dsn_async
        assert dsn == (
            "postgresql+asyncpg://test_user:test_password@localhost:5432/test_db"
        )

    def test_config_port_validation(self) -> None:
        """Config port should be validated."""
        # Valid port
        config = ConfigSessionStorage(
            postgres_port=5432,
            postgres_password=SecretStr("test"),
        )
        assert config.postgres_port == 5432

    def test_config_pool_size_validation(self) -> None:
        """Config pool sizes should be validated."""
        config = ConfigSessionStorage(
            pool_min_size=5,
            pool_max_size=50,
            postgres_password=SecretStr("test"),
        )
        assert config.pool_min_size == 5
        assert config.pool_max_size == 50


# =============================================================================
# Import Tests
# =============================================================================


class TestImports:
    """Tests for module imports."""

    def test_session_snapshot_store_importable(self) -> None:
        """SessionSnapshotStore should be importable from package."""
        from omniclaude.storage import SessionSnapshotStore

        assert SessionSnapshotStore is not None

    def test_config_importable(self) -> None:
        """ConfigSessionStorage should be importable from package."""
        from omniclaude.storage import ConfigSessionStorage

        assert ConfigSessionStorage is not None
