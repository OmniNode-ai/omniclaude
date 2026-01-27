# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for HandlerPatternStoragePostgres (OMN-1403 Phase 10).

Tests cover:
    - _build_db_query_envelope helper produces correct envelope shape
    - query_patterns builds correct SQL and converts rows to models
    - upsert_pattern correctly interprets xmax=0 as insert vs update
    - Error handling returns failed result with error message

All tests use mocked HandlerDb to verify envelope structure and response handling.
No database connections are made.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from omnibase_infra.enums import EnumResponseStatus
from omnibase_infra.handlers.models import ModelDbQueryPayload, ModelDbQueryResponse

from omniclaude.handlers.pattern_storage_postgres import HandlerPatternStoragePostgres
from omniclaude.handlers.pattern_storage_postgres.handler_pattern_storage_postgres import (
    _build_db_query_envelope,
)
from omniclaude.nodes.node_pattern_persistence_effect.models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternRecord,
)

if TYPE_CHECKING:
    from omnibase_core.models.dispatch import ModelHandlerOutput

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_container() -> MagicMock:
    """Create a mock ONEX container."""
    return MagicMock()


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create a mock HandlerDb instance."""
    return AsyncMock()


@pytest.fixture
def correlation_id() -> UUID:
    """Create a correlation ID for tests."""
    return uuid4()


@pytest.fixture
def sample_pattern_record() -> ModelLearnedPatternRecord:
    """Create a sample pattern record for testing."""
    return ModelLearnedPatternRecord(
        pattern_id="testing.pytest_fixtures",
        domain="testing",
        title="Pytest Fixture Patterns",
        description="Use pytest fixtures for test setup and teardown with proper scoping.",
        confidence=0.9,
        usage_count=15,
        success_rate=0.95,
        example_reference="tests/conftest.py",
    )


def make_db_response(
    rows: list[dict[str, object]],
    status: EnumResponseStatus = EnumResponseStatus.SUCCESS,
    correlation_id: UUID | None = None,
) -> ModelHandlerOutput[ModelDbQueryResponse]:
    """Create a mock database response.

    Args:
        rows: List of row dictionaries to return
        status: Response status (default: SUCCESS)
        correlation_id: Correlation ID for the response

    Returns:
        Mock ModelHandlerOutput with proper result structure
    """
    cid = correlation_id or uuid4()
    payload = ModelDbQueryPayload(rows=rows, row_count=len(rows))
    result = ModelDbQueryResponse(
        status=status,
        payload=payload,
        correlation_id=cid,
    )

    # Create mock output with result attribute
    mock_output = MagicMock()
    mock_output.result = result
    return mock_output


# =============================================================================
# Tests for _build_db_query_envelope
# =============================================================================


class TestBuildDbQueryEnvelope:
    """Tests for _build_db_query_envelope helper function."""

    def test_envelope_has_correct_operation(self) -> None:
        """Envelope always has operation 'db.query'."""
        envelope = _build_db_query_envelope(
            sql="SELECT 1",
            params=[],
            correlation_id=uuid4(),
        )
        assert envelope["operation"] == "db.query"

    def test_envelope_has_sql_in_payload(self) -> None:
        """Envelope contains SQL in payload."""
        sql = "SELECT * FROM learned_patterns WHERE domain = $1"
        envelope = _build_db_query_envelope(
            sql=sql,
            params=["testing"],
            correlation_id=uuid4(),
        )
        assert envelope["payload"]["sql"] == sql

    def test_envelope_has_parameters_in_payload(self) -> None:
        """Envelope contains parameters in payload."""
        params = ["testing", 0.7, 50, 0]
        envelope = _build_db_query_envelope(
            sql="SELECT * FROM patterns",
            params=params,
            correlation_id=uuid4(),
        )
        assert envelope["payload"]["parameters"] == params

    def test_envelope_has_correlation_id(self) -> None:
        """Envelope contains correlation_id at top level."""
        cid = uuid4()
        envelope = _build_db_query_envelope(
            sql="SELECT 1",
            params=[],
            correlation_id=cid,
        )
        assert envelope["correlation_id"] == cid

    def test_envelope_structure_matches_handler_db_spec(self) -> None:
        """Envelope matches HandlerDb expected structure."""
        cid = uuid4()
        envelope = _build_db_query_envelope(
            sql="SELECT id FROM table",
            params=[1, "test"],
            correlation_id=cid,
        )

        # Verify all required fields
        assert set(envelope.keys()) == {"operation", "payload", "correlation_id"}
        assert set(envelope["payload"].keys()) == {"sql", "parameters"}  # type: ignore[union-attr]
        assert isinstance(envelope["correlation_id"], UUID)


# =============================================================================
# Tests for query_patterns
# =============================================================================


class TestQueryPatterns:
    """Tests for HandlerPatternStoragePostgres.query_patterns method."""

    @pytest.mark.asyncio
    async def test_query_patterns_returns_success_with_records(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """Successful query returns result with records."""
        # Setup
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        # Mock count query response
        count_response = make_db_response(
            rows=[{"cnt": 2}],
            correlation_id=correlation_id,
        )

        # Mock data query response
        data_response = make_db_response(
            rows=[
                {
                    "pattern_id": "testing.fixtures",
                    "domain": "testing",
                    "title": "Test Fixtures",
                    "description": "Use fixtures for setup",
                    "confidence": 0.9,
                    "usage_count": 10,
                    "success_rate": 0.95,
                    "example_reference": None,
                },
                {
                    "pattern_id": "testing.mocks",
                    "domain": "testing",
                    "title": "Mock Patterns",
                    "description": "Use mocks effectively",
                    "confidence": 0.85,
                    "usage_count": 8,
                    "success_rate": 0.9,
                    "example_reference": "tests/test_mocks.py",
                },
            ],
            correlation_id=correlation_id,
        )

        mock_db.execute.side_effect = [count_response, data_response]

        # Execute
        query = ModelLearnedPatternQuery(domain="testing", min_confidence=0.7)
        result = await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify
        assert result.success is True
        assert len(result.records) == 2
        assert result.total_count == 2
        assert result.records[0].pattern_id == "testing.fixtures"
        assert result.records[1].pattern_id == "testing.mocks"
        assert result.correlation_id == correlation_id
        assert result.backend_type == "postgresql"

    @pytest.mark.asyncio
    async def test_query_patterns_builds_correct_sql_for_domain_filter(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """Domain filter generates correct WHERE clause."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        # Setup responses
        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]

        # Execute with domain filter
        query = ModelLearnedPatternQuery(domain="api", include_general=False)
        await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify SQL contains domain filter
        calls = mock_db.execute.call_args_list
        count_envelope = calls[0][0][0]
        assert "domain = $1" in count_envelope["payload"]["sql"]
        assert count_envelope["payload"]["parameters"][0] == "api"

    @pytest.mark.asyncio
    async def test_query_patterns_includes_general_domain(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """include_general=True adds OR domain = 'general' clause."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]

        # Execute with include_general
        query = ModelLearnedPatternQuery(domain="testing", include_general=True)
        await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify SQL includes general domain
        calls = mock_db.execute.call_args_list
        count_envelope = calls[0][0][0]
        sql = count_envelope["payload"]["sql"]
        assert "(domain = $1 OR domain = 'general')" in sql

    @pytest.mark.asyncio
    async def test_query_patterns_builds_correct_sql_for_min_confidence(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """min_confidence filter generates correct WHERE clause."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]

        # Execute with min_confidence only (no domain)
        query = ModelLearnedPatternQuery(min_confidence=0.8)
        await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify SQL contains confidence filter
        calls = mock_db.execute.call_args_list
        count_envelope = calls[0][0][0]
        assert "confidence >= $1" in count_envelope["payload"]["sql"]
        assert count_envelope["payload"]["parameters"][0] == 0.8

    @pytest.mark.asyncio
    async def test_query_patterns_applies_limit_and_offset(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """limit and offset are applied to data query."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 100}]),
            make_db_response([]),
        ]

        # Execute with limit and offset
        query = ModelLearnedPatternQuery(limit=20, offset=40)
        await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify data query has LIMIT and OFFSET
        calls = mock_db.execute.call_args_list
        data_envelope = calls[1][0][0]
        sql = data_envelope["payload"]["sql"]
        assert "LIMIT" in sql
        assert "OFFSET" in sql
        params = data_envelope["payload"]["parameters"]
        assert 20 in params  # limit
        assert 40 in params  # offset

    @pytest.mark.asyncio
    async def test_query_patterns_returns_error_on_db_failure(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """Database failure returns failed result."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        # Mock count query with error status
        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([], status=EnumResponseStatus.ERROR),
        ]

        query = ModelLearnedPatternQuery(domain="testing")
        result = await handler.query_patterns(query, correlation_id=correlation_id)

        assert result.success is False
        assert result.error == "Database query failed"
        assert result.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_query_patterns_handles_exception(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """Exception during query returns failed result with error message."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = Exception("Connection lost")

        query = ModelLearnedPatternQuery()
        result = await handler.query_patterns(query, correlation_id=correlation_id)

        assert result.success is False
        assert "Connection lost" in (result.error or "")
        assert result.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_query_patterns_orders_by_confidence_desc(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        correlation_id: UUID,
    ) -> None:
        """Results are ordered by confidence DESC, usage_count DESC."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]

        query = ModelLearnedPatternQuery()
        await handler.query_patterns(query, correlation_id=correlation_id)

        # Verify ORDER BY clause
        calls = mock_db.execute.call_args_list
        data_envelope = calls[1][0][0]
        sql = data_envelope["payload"]["sql"]
        assert "ORDER BY confidence DESC, usage_count DESC" in sql


# =============================================================================
# Tests for upsert_pattern
# =============================================================================


class TestUpsertPattern:
    """Tests for HandlerPatternStoragePostgres.upsert_pattern method."""

    @pytest.mark.asyncio
    async def test_upsert_pattern_returns_insert_when_xmax_zero(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """xmax=0 indicates INSERT (new row)."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        # Mock response with inserted=True (xmax=0)
        mock_db.execute.return_value = make_db_response(
            rows=[{"inserted": True}],
            correlation_id=correlation_id,
        )

        result = await handler.upsert_pattern(
            sample_pattern_record,
            correlation_id=correlation_id,
        )

        assert result.success is True
        assert result.operation == "insert"
        assert result.pattern_id == sample_pattern_record.pattern_id
        assert result.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_upsert_pattern_returns_update_when_xmax_nonzero(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """xmax>0 indicates UPDATE (existing row modified)."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        # Mock response with inserted=False (xmax > 0)
        mock_db.execute.return_value = make_db_response(
            rows=[{"inserted": False}],
            correlation_id=correlation_id,
        )

        result = await handler.upsert_pattern(
            sample_pattern_record,
            correlation_id=correlation_id,
        )

        assert result.success is True
        assert result.operation == "update"
        assert result.pattern_id == sample_pattern_record.pattern_id

    @pytest.mark.asyncio
    async def test_upsert_pattern_builds_correct_sql(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """Upsert SQL uses INSERT...ON CONFLICT UPDATE with RETURNING."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.return_value = make_db_response(
            rows=[{"inserted": True}],
        )

        await handler.upsert_pattern(
            sample_pattern_record, correlation_id=correlation_id
        )

        # Verify SQL structure
        envelope = mock_db.execute.call_args[0][0]
        sql = envelope["payload"]["sql"]

        assert "INSERT INTO learned_patterns" in sql
        assert "ON CONFLICT (pattern_id) DO UPDATE SET" in sql
        assert "RETURNING (xmax = 0) as inserted" in sql

    @pytest.mark.asyncio
    async def test_upsert_pattern_passes_all_fields_as_parameters(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """All pattern fields are passed as SQL parameters."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.return_value = make_db_response(
            rows=[{"inserted": True}],
        )

        await handler.upsert_pattern(
            sample_pattern_record, correlation_id=correlation_id
        )

        # Verify parameters
        envelope = mock_db.execute.call_args[0][0]
        params = envelope["payload"]["parameters"]

        assert params[0] == sample_pattern_record.pattern_id
        assert params[1] == sample_pattern_record.domain
        assert params[2] == sample_pattern_record.title
        assert params[3] == sample_pattern_record.description
        assert params[4] == sample_pattern_record.confidence
        assert params[5] == sample_pattern_record.usage_count
        assert params[6] == sample_pattern_record.success_rate
        assert params[7] == sample_pattern_record.example_reference

    @pytest.mark.asyncio
    async def test_upsert_pattern_returns_error_on_db_failure(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """Database failure returns failed result."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.return_value = make_db_response(
            rows=[],
            status=EnumResponseStatus.ERROR,
        )

        result = await handler.upsert_pattern(
            sample_pattern_record,
            correlation_id=correlation_id,
        )

        assert result.success is False
        assert result.error == "Database upsert failed"

    @pytest.mark.asyncio
    async def test_upsert_pattern_handles_exception(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
        correlation_id: UUID,
    ) -> None:
        """Exception during upsert returns failed result."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.side_effect = Exception("Constraint violation")

        result = await handler.upsert_pattern(
            sample_pattern_record,
            correlation_id=correlation_id,
        )

        assert result.success is False
        assert "Constraint violation" in (result.error or "")
        assert result.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_upsert_pattern_generates_correlation_id_if_not_provided(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
        sample_pattern_record: ModelLearnedPatternRecord,
    ) -> None:
        """Correlation ID is auto-generated when not provided."""
        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db

        mock_db.execute.return_value = make_db_response(
            rows=[{"inserted": True}],
        )

        result = await handler.upsert_pattern(sample_pattern_record)

        assert result.correlation_id is not None
        assert isinstance(result.correlation_id, UUID)


# =============================================================================
# Tests for lazy HandlerDb initialization
# =============================================================================


class TestLazyDbInitialization:
    """Tests for lazy HandlerDb initialization via container."""

    @pytest.mark.asyncio
    async def test_handler_lazily_resolves_db_from_container(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
    ) -> None:
        """HandlerDb is resolved from container on first use."""
        mock_container.get_service_async = AsyncMock(return_value=mock_db)
        mock_db.execute.return_value = make_db_response([{"cnt": 0}])

        handler = HandlerPatternStoragePostgres(mock_container)

        # DB should not be resolved yet
        assert handler._db is None

        # First call should trigger resolution
        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]
        await handler.query_patterns(ModelLearnedPatternQuery())

        # Verify container was called
        mock_container.get_service_async.assert_called_once()
        assert handler._db is mock_db

    @pytest.mark.asyncio
    async def test_handler_reuses_db_on_subsequent_calls(
        self,
        mock_container: MagicMock,
        mock_db: AsyncMock,
    ) -> None:
        """HandlerDb is only resolved once and reused."""
        mock_container.get_service_async = AsyncMock(return_value=mock_db)

        handler = HandlerPatternStoragePostgres(mock_container)
        handler._db = mock_db  # Pre-set to simulate already initialized

        mock_db.execute.side_effect = [
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
            make_db_response([{"cnt": 0}]),
            make_db_response([]),
        ]

        # Multiple calls
        await handler.query_patterns(ModelLearnedPatternQuery())
        await handler.query_patterns(ModelLearnedPatternQuery())

        # Container should not be called (DB was already set)
        mock_container.get_service_async.assert_not_called()


# =============================================================================
# Tests for handler_key attribute
# =============================================================================


class TestHandlerKey:
    """Tests for handler_key attribute."""

    def test_handler_key_is_postgresql(self, mock_container: MagicMock) -> None:
        """handler_key identifies backend as 'postgresql'."""
        handler = HandlerPatternStoragePostgres(mock_container)
        assert handler.handler_key == "postgresql"
