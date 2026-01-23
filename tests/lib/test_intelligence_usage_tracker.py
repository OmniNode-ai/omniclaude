# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for IntelligenceUsageTracker and IntelligenceUsageRecord.

These tests verify:
- IntelligenceUsageRecord dataclass field defaults and __post_init__ behavior
- IntelligenceUsageTracker initialization and configuration
- Tracking methods with mocked database operations
- Singleton pattern via get_tracker()
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestIntelligenceUsageRecord:
    """Tests for IntelligenceUsageRecord dataclass."""

    def test_required_field_correlation_id(self) -> None:
        """Test that correlation_id is required."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        correlation_id = uuid4()
        record = IntelligenceUsageRecord(correlation_id=correlation_id)

        assert record.correlation_id == correlation_id

    def test_default_values_for_optional_fields(self) -> None:
        """Test that optional fields have correct defaults."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        correlation_id = uuid4()
        record = IntelligenceUsageRecord(correlation_id=correlation_id)

        # UUID fields default to None
        assert record.execution_id is None
        assert record.manifest_injection_id is None
        assert record.prompt_id is None
        assert record.intelligence_id is None

        # String fields with defaults
        assert record.agent_name == "unknown"
        assert record.intelligence_type == "pattern"
        assert record.intelligence_source == "qdrant"
        assert record.usage_context == "reference"

        # Optional string fields
        assert record.intelligence_name is None
        assert record.collection_name is None
        assert record.intelligence_summary is None
        assert record.query_used is None

        # Numeric fields
        assert record.usage_count == 1
        assert record.confidence_score is None
        assert record.query_time_ms is None
        assert record.query_results_rank is None
        assert record.quality_impact is None

        # Boolean fields
        assert record.was_applied is False
        assert record.contributed_to_success is None

        # Dict/List fields
        assert record.intelligence_snapshot is None
        assert record.application_details is None
        assert record.file_operations_using_this is None

    def test_post_init_sets_created_at(self) -> None:
        """Test that __post_init__ sets created_at to current time."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        before = datetime.now(UTC)
        record = IntelligenceUsageRecord(correlation_id=uuid4())
        after = datetime.now(UTC)

        assert record.created_at is not None
        assert before <= record.created_at <= after

    def test_post_init_does_not_override_explicit_created_at(self) -> None:
        """Test that __post_init__ preserves explicit created_at value."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        explicit_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        record = IntelligenceUsageRecord(
            correlation_id=uuid4(),
            created_at=explicit_time,
        )

        assert record.created_at == explicit_time

    def test_post_init_sets_metadata_to_empty_dict(self) -> None:
        """Test that __post_init__ sets metadata to empty dict when None."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        record = IntelligenceUsageRecord(correlation_id=uuid4())

        assert record.metadata == {}
        assert record.metadata is not None

    def test_post_init_does_not_override_explicit_metadata(self) -> None:
        """Test that __post_init__ preserves explicit metadata value."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        explicit_metadata = {"key": "value", "count": 42}
        record = IntelligenceUsageRecord(
            correlation_id=uuid4(),
            metadata=explicit_metadata,
        )

        assert record.metadata == explicit_metadata

    def test_applied_at_defaults_to_none(self) -> None:
        """Test that applied_at defaults to None (set when application is tracked)."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        record = IntelligenceUsageRecord(correlation_id=uuid4())

        assert record.applied_at is None

    def test_all_fields_can_be_set_explicitly(self) -> None:
        """Test that all fields can be set with explicit values."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageRecord

        correlation_id = uuid4()
        execution_id = uuid4()
        manifest_injection_id = uuid4()
        prompt_id = uuid4()
        intelligence_id = uuid4()
        file_op_id = uuid4()
        created_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        applied_at = datetime(2025, 1, 15, 10, 35, 0, tzinfo=UTC)

        record = IntelligenceUsageRecord(
            correlation_id=correlation_id,
            execution_id=execution_id,
            manifest_injection_id=manifest_injection_id,
            prompt_id=prompt_id,
            agent_name="test-agent",
            intelligence_type="schema",
            intelligence_source="memgraph",
            intelligence_id=intelligence_id,
            intelligence_name="Test Schema",
            collection_name="schemas",
            usage_context="implementation",
            usage_count=5,
            confidence_score=0.95,
            intelligence_snapshot={"schema": "data"},
            intelligence_summary="A test schema",
            query_used="MATCH (n) RETURN n",
            query_time_ms=150,
            query_results_rank=1,
            was_applied=True,
            application_details={"action": "created_file"},
            file_operations_using_this=[file_op_id],
            contributed_to_success=True,
            quality_impact=0.85,
            metadata={"custom": "data"},
            created_at=created_at,
            applied_at=applied_at,
        )

        assert record.correlation_id == correlation_id
        assert record.execution_id == execution_id
        assert record.manifest_injection_id == manifest_injection_id
        assert record.prompt_id == prompt_id
        assert record.agent_name == "test-agent"
        assert record.intelligence_type == "schema"
        assert record.intelligence_source == "memgraph"
        assert record.intelligence_id == intelligence_id
        assert record.intelligence_name == "Test Schema"
        assert record.collection_name == "schemas"
        assert record.usage_context == "implementation"
        assert record.usage_count == 5
        assert record.confidence_score == 0.95
        assert record.intelligence_snapshot == {"schema": "data"}
        assert record.intelligence_summary == "A test schema"
        assert record.query_used == "MATCH (n) RETURN n"
        assert record.query_time_ms == 150
        assert record.query_results_rank == 1
        assert record.was_applied is True
        assert record.application_details == {"action": "created_file"}
        assert record.file_operations_using_this == [file_op_id]
        assert record.contributed_to_success is True
        assert record.quality_impact == 0.85
        assert record.metadata == {"custom": "data"}
        assert record.created_at == created_at
        assert record.applied_at == applied_at


class TestIntelligenceUsageTrackerInit:
    """Tests for IntelligenceUsageTracker initialization."""

    def test_init_with_explicit_db_params(self) -> None:
        """Test initialization with explicit database parameters."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )

        assert tracker.db_host == "test-host"
        assert tracker.db_port == 5432
        assert tracker.db_name == "test_db"
        assert tracker.db_user == "test_user"
        assert tracker.db_password == "test_password"
        assert tracker.enable_tracking is True
        assert tracker._pool is None

    def test_init_with_settings_fallback(self) -> None:
        """Test initialization uses settings when params not provided."""
        mock_settings = MagicMock()
        mock_settings.postgres_host = "settings-host"
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "settings_db"
        mock_settings.postgres_user = "settings_user"
        mock_settings.get_effective_postgres_password.return_value = "settings_password"

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import (
                IntelligenceUsageTracker,
            )

            tracker = IntelligenceUsageTracker()

            assert tracker.db_host == "settings-host"
            assert tracker.db_port == 5436
            assert tracker.db_name == "settings_db"
            assert tracker.db_user == "settings_user"
            assert tracker.db_password == "settings_password"

    def test_init_disables_tracking_when_db_config_incomplete(self) -> None:
        """Test that tracking is disabled when database config is incomplete."""
        mock_settings = MagicMock()
        mock_settings.postgres_host = ""  # Missing host
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "test_db"
        mock_settings.postgres_user = "test_user"
        mock_settings.get_effective_postgres_password.return_value = "password"

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import (
                IntelligenceUsageTracker,
            )

            tracker = IntelligenceUsageTracker()

            assert tracker.enable_tracking is False

    def test_init_disables_tracking_when_password_missing(self) -> None:
        """Test that tracking is disabled when password is missing."""
        mock_settings = MagicMock()
        mock_settings.postgres_host = "test-host"
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "test_db"
        mock_settings.postgres_user = "test_user"
        mock_settings.get_effective_postgres_password.return_value = ""  # Missing password

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import (
                IntelligenceUsageTracker,
            )

            tracker = IntelligenceUsageTracker()

            assert tracker.enable_tracking is False

    def test_init_with_enable_tracking_false(self) -> None:
        """Test initialization with explicit enable_tracking=False."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        assert tracker.enable_tracking is False

    def test_init_sets_pool_config(self) -> None:
        """Test that initialization sets pool configuration."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
        )

        assert tracker._pool_min_size == 2
        assert tracker._pool_max_size == 10
        assert tracker._pending_records == []
        assert tracker._max_pending == 100


class TestIntelligenceUsageTrackerTrackingDisabled:
    """Tests for IntelligenceUsageTracker when tracking is disabled."""

    @pytest.mark.asyncio
    async def test_track_retrieval_returns_false_when_disabled(self) -> None:
        """Test that track_retrieval returns False when tracking is disabled."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        result = await tracker.track_retrieval(
            correlation_id=uuid4(),
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_track_application_returns_false_when_disabled(self) -> None:
        """Test that track_application returns False when tracking is disabled."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        result = await tracker.track_application(
            correlation_id=uuid4(),
            intelligence_name="Test Pattern",
            was_applied=True,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_get_usage_stats_returns_error_when_disabled(self) -> None:
        """Test that get_usage_stats returns error dict when tracking is disabled."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        result = await tracker.get_usage_stats()

        assert result == {"error": "Tracking disabled"}

    @pytest.mark.asyncio
    async def test_store_record_returns_true_when_disabled(self) -> None:
        """Test that _store_record returns True (no-op) when tracking is disabled."""
        from omniclaude.lib.intelligence_usage_tracker import (
            IntelligenceUsageRecord,
            IntelligenceUsageTracker,
        )

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        record = IntelligenceUsageRecord(correlation_id=uuid4())
        result = await tracker._store_record(record)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_application_returns_true_when_disabled(self) -> None:
        """Test that _update_application returns True (no-op) when tracking is disabled."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=False,
        )

        result = await tracker._update_application(
            correlation_id=uuid4(),
            intelligence_name="Test Pattern",
            was_applied=True,
            application_details=None,
            file_operations_using_this=None,
            contributed_to_success=None,
            quality_impact=None,
        )

        assert result is True


class _MockAsyncContextManager:
    """Helper class to create a proper async context manager mock."""

    def __init__(self, return_value: Any) -> None:
        self._return_value = return_value

    async def __aenter__(self) -> Any:
        return self._return_value

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class TestIntelligenceUsageTrackerWithMockedDatabase:
    """Tests for IntelligenceUsageTracker with mocked database operations."""

    @pytest.fixture
    def mock_conn(self) -> AsyncMock:
        """Create a mock asyncpg connection."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "total_retrievals": 10,
                "times_applied": 5,
                "application_rate_percent": 50.0,
                "avg_confidence": 0.85,
                "avg_quality_impact": 0.75,
                "success_contributions": 3,
                "avg_query_time_ms": 120.0,
                "agents_using_this": ["agent1", "agent2"],
                "sources": ["qdrant"],
                "first_used": datetime(2025, 1, 1, tzinfo=UTC),
                "last_used": datetime(2025, 1, 15, tzinfo=UTC),
            }
        )
        return mock_conn

    @pytest.fixture
    def mock_pool(self, mock_conn: AsyncMock) -> MagicMock:
        """Create a mock asyncpg connection pool."""
        # pool.acquire() returns an async context manager directly (not a coroutine)
        # So we use MagicMock for pool and return our custom async context manager
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = _MockAsyncContextManager(mock_conn)
        mock_pool.close = AsyncMock()

        return mock_pool

    @pytest.fixture
    def tracker_with_mock_pool(self, mock_pool: AsyncMock) -> Any:
        """Create a tracker with a pre-configured mock pool."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )
        tracker._pool = mock_pool
        return tracker

    @pytest.mark.asyncio
    async def test_track_retrieval_creates_record_and_stores(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_retrieval creates a record and stores it in database."""
        correlation_id = uuid4()
        intelligence_id = uuid4()

        result = await tracker_with_mock_pool.track_retrieval(
            correlation_id=correlation_id,
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="Test Pattern",
            collection_name="execution_patterns",
            intelligence_id=intelligence_id,
            confidence_score=0.95,
            query_time_ms=150,
            query_used="test query",
            query_results_rank=1,
            intelligence_snapshot={"key": "value"},
            intelligence_summary="A test pattern",
            metadata={"custom": "data"},
        )

        assert result is True
        # Verify execute was called (INSERT)
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_retrieval_returns_false_on_database_error(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_retrieval returns False when database fails."""
        mock_conn.execute.side_effect = Exception("Database error")

        result = await tracker_with_mock_pool.track_retrieval(
            correlation_id=uuid4(),
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_track_retrieval_returns_false_on_zero_rows_inserted(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_retrieval returns False when no rows inserted."""
        mock_conn.execute.return_value = "INSERT 0 0"

        result = await tracker_with_mock_pool.track_retrieval(
            correlation_id=uuid4(),
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_track_application_updates_record(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_application updates existing record."""
        mock_conn.execute.return_value = "UPDATE 1"

        correlation_id = uuid4()
        file_op_id = uuid4()

        result = await tracker_with_mock_pool.track_application(
            correlation_id=correlation_id,
            intelligence_name="Test Pattern",
            was_applied=True,
            application_details={"action": "created_file"},
            file_operations_using_this=[file_op_id],
            contributed_to_success=True,
            quality_impact=0.85,
        )

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_application_returns_false_on_no_rows_updated(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_application returns False when no rows updated."""
        mock_conn.execute.return_value = "UPDATE 0"

        result = await tracker_with_mock_pool.track_application(
            correlation_id=uuid4(),
            intelligence_name="Nonexistent Pattern",
            was_applied=True,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_track_application_returns_false_on_database_error(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that track_application returns False when database fails."""
        mock_conn.execute.side_effect = Exception("Database error")

        result = await tracker_with_mock_pool.track_application(
            correlation_id=uuid4(),
            intelligence_name="Test Pattern",
            was_applied=True,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_get_usage_stats_returns_statistics(
        self, tracker_with_mock_pool: Any, _mock_conn: AsyncMock
    ) -> None:
        """Test that get_usage_stats returns statistics from database."""
        result = await tracker_with_mock_pool.get_usage_stats()

        assert result["total_retrievals"] == 10
        assert result["times_applied"] == 5
        assert result["application_rate_percent"] == 50.0
        assert result["avg_confidence"] == 0.85
        assert result["avg_quality_impact"] == 0.75
        assert result["success_contributions"] == 3

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_filters(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that get_usage_stats passes filters to query."""
        await tracker_with_mock_pool.get_usage_stats(
            intelligence_name="Test Pattern",
            intelligence_type="pattern",
        )

        mock_conn.fetchrow.assert_called_once()
        # Verify filters were passed as parameters
        call_args = mock_conn.fetchrow.call_args
        assert "Test Pattern" in call_args.args
        assert "pattern" in call_args.args

    @pytest.mark.asyncio
    async def test_get_usage_stats_returns_error_on_database_failure(
        self, tracker_with_mock_pool: Any, mock_conn: AsyncMock
    ) -> None:
        """Test that get_usage_stats returns error dict on database failure."""
        mock_conn.fetchrow.side_effect = Exception("Database error")

        result = await tracker_with_mock_pool.get_usage_stats()

        assert "error" in result
        assert "Database error" in result["error"]

    @pytest.mark.asyncio
    async def test_close_closes_pool(
        self, tracker_with_mock_pool: Any, mock_pool: AsyncMock
    ) -> None:
        """Test that close() closes the connection pool."""
        await tracker_with_mock_pool.close()

        mock_pool.close.assert_called_once()
        assert tracker_with_mock_pool._pool is None

    @pytest.mark.asyncio
    async def test_close_handles_error_gracefully(
        self, tracker_with_mock_pool: Any, mock_pool: AsyncMock
    ) -> None:
        """Test that close() handles pool close errors gracefully."""
        mock_pool.close.side_effect = Exception("Close error")

        # Should not raise
        await tracker_with_mock_pool.close()

        # Pool should be set to None even on error
        assert tracker_with_mock_pool._pool is None


class TestIntelligenceUsageTrackerPoolCreation:
    """Tests for IntelligenceUsageTracker connection pool creation."""

    @pytest.mark.asyncio
    async def test_get_pool_creates_pool_on_first_call(self) -> None:
        """Test that _get_pool creates pool on first call."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_pool = AsyncMock()
        mock_create_pool = AsyncMock(return_value=mock_pool)

        with patch(
            "omniclaude.lib.intelligence_usage_tracker.asyncpg.create_pool",
            mock_create_pool,
        ):
            tracker = IntelligenceUsageTracker(
                db_host="test-host",
                db_port=5432,
                db_name="test_db",
                db_user="test_user",
                db_password="test_password",
                enable_tracking=True,
            )

            pool = await tracker._get_pool()

            assert pool is mock_pool
            mock_create_pool.assert_called_once_with(
                host="test-host",
                port=5432,
                database="test_db",
                user="test_user",
                password="test_password",
                min_size=2,
                max_size=10,
            )

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing_pool(self) -> None:
        """Test that _get_pool reuses existing pool on subsequent calls."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_pool = AsyncMock()
        mock_create_pool = AsyncMock(return_value=mock_pool)

        with patch(
            "omniclaude.lib.intelligence_usage_tracker.asyncpg.create_pool",
            mock_create_pool,
        ):
            tracker = IntelligenceUsageTracker(
                db_host="test-host",
                db_port=5432,
                db_name="test_db",
                db_user="test_user",
                db_password="test_password",
                enable_tracking=True,
            )

            pool1 = await tracker._get_pool()
            pool2 = await tracker._get_pool()

            assert pool1 is pool2
            assert mock_create_pool.call_count == 1

    @pytest.mark.asyncio
    async def test_get_pool_raises_on_connection_failure(self) -> None:
        """Test that _get_pool raises on pool creation failure."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_create_pool = AsyncMock(side_effect=Exception("Connection failed"))

        with patch(
            "omniclaude.lib.intelligence_usage_tracker.asyncpg.create_pool",
            mock_create_pool,
        ):
            tracker = IntelligenceUsageTracker(
                db_host="test-host",
                db_port=5432,
                db_name="test_db",
                db_user="test_user",
                db_password="test_password",
                enable_tracking=True,
            )

            with pytest.raises(Exception, match="Connection failed"):
                await tracker._get_pool()


class TestGetTrackerSingleton:
    """Tests for get_tracker() singleton function."""

    def test_get_tracker_returns_tracker_instance(self) -> None:
        """Test that get_tracker returns an IntelligenceUsageTracker instance."""
        # Reset singleton for test isolation
        import omniclaude.lib.intelligence_usage_tracker as module

        module._tracker_instance = None

        mock_settings = MagicMock()
        mock_settings.postgres_host = "test-host"
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "test_db"
        mock_settings.postgres_user = "test_user"
        mock_settings.get_effective_postgres_password.return_value = "test_password"

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import (
                IntelligenceUsageTracker,
                get_tracker,
            )

            tracker = get_tracker()

            assert isinstance(tracker, IntelligenceUsageTracker)

    def test_get_tracker_returns_same_instance(self) -> None:
        """Test that get_tracker returns the same singleton instance."""
        # Reset singleton for test isolation
        import omniclaude.lib.intelligence_usage_tracker as module

        module._tracker_instance = None

        mock_settings = MagicMock()
        mock_settings.postgres_host = "test-host"
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "test_db"
        mock_settings.postgres_user = "test_user"
        mock_settings.get_effective_postgres_password.return_value = "test_password"

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import get_tracker

            tracker1 = get_tracker()
            tracker2 = get_tracker()

            assert tracker1 is tracker2

    def test_get_tracker_creates_new_instance_after_reset(self) -> None:
        """Test that get_tracker creates new instance after singleton is reset."""
        import omniclaude.lib.intelligence_usage_tracker as module

        mock_settings = MagicMock()
        mock_settings.postgres_host = "test-host"
        mock_settings.postgres_port = 5436
        mock_settings.postgres_database = "test_db"
        mock_settings.postgres_user = "test_user"
        mock_settings.get_effective_postgres_password.return_value = "test_password"

        with patch("omniclaude.lib.intelligence_usage_tracker.settings", mock_settings):
            from omniclaude.lib.intelligence_usage_tracker import get_tracker

            # First get
            module._tracker_instance = None
            tracker1 = get_tracker()

            # Reset and get again
            module._tracker_instance = None
            tracker2 = get_tracker()

            # Should be different instances after reset
            assert tracker1 is not tracker2


class TestIntelligenceUsageTrackerEdgeCases:
    """Tests for edge cases and error handling."""

    def _create_mock_pool_with_conn(self, mock_conn: AsyncMock) -> MagicMock:
        """Helper to create a properly configured mock pool."""
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = _MockAsyncContextManager(mock_conn)
        mock_pool.close = AsyncMock()

        return mock_pool

    @pytest.mark.asyncio
    async def test_track_retrieval_handles_none_metadata(self) -> None:
        """Test that track_retrieval handles None metadata correctly."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_pool = self._create_mock_pool_with_conn(mock_conn)

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )
        tracker._pool = mock_pool

        # Call with metadata=None (should default to {})
        result = await tracker.track_retrieval(
            correlation_id=uuid4(),
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
            metadata=None,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_track_application_with_minimal_params(self) -> None:
        """Test track_application with only required parameters."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = self._create_mock_pool_with_conn(mock_conn)

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )
        tracker._pool = mock_pool

        result = await tracker.track_application(
            correlation_id=uuid4(),
            intelligence_name="Test Pattern",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_close_when_pool_is_none(self) -> None:
        """Test that close() handles None pool gracefully."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )

        # Pool is None by default
        assert tracker._pool is None

        # Should not raise
        await tracker.close()

        assert tracker._pool is None

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_empty_result(self) -> None:
        """Test get_usage_stats when database returns empty result."""
        from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = self._create_mock_pool_with_conn(mock_conn)

        tracker = IntelligenceUsageTracker(
            db_host="test-host",
            db_port=5432,
            db_name="test_db",
            db_user="test_user",
            db_password="test_password",
            enable_tracking=True,
        )
        tracker._pool = mock_pool

        result = await tracker.get_usage_stats()

        assert result == {}
