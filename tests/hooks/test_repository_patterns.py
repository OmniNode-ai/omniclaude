# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for PatternRepository.

Tests verify the repository:
1. Creates patterns with proper validation
2. Queries patterns with domain filtering
3. Includes "general" domain patterns when filtering
4. Filters by confidence threshold
5. Filters by project scope
6. Sorts by confidence descending
7. Upserts patterns correctly
8. Increments usage statistics
9. Deletes patterns
10. Handles errors gracefully
11. Builds correct envelopes for HandlerDb

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from omniclaude.hooks.repository_patterns import (
    DbPatternRecord,
    PatternNotFoundError,
    PatternRepository,
    PatternRepositoryError,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test Data
# =============================================================================

SAMPLE_UUID = UUID("12345678-1234-1234-1234-123456789012")
SAMPLE_TIMESTAMP = datetime(2026, 1, 26, 12, 0, 0, tzinfo=UTC)


def make_pattern_record(
    pattern_id: str = "pat-001",
    domain: str = "testing",
    title: str = "Test Pattern",
    confidence: float = 0.9,
    **overrides: Any,
) -> DbPatternRecord:
    """Factory to create DbPatternRecord for tests."""
    defaults = {
        "id": uuid4(),
        "pattern_id": pattern_id,
        "domain": domain,
        "title": title,
        "description": "Test description",
        "confidence": confidence,
        "usage_count": 10,
        "success_rate": 0.85,
        "example_reference": None,
        "project_scope": None,
        "created_at": SAMPLE_TIMESTAMP,
        "updated_at": SAMPLE_TIMESTAMP,
    }
    defaults.update(overrides)
    return DbPatternRecord(**defaults)


def make_db_row(
    id: UUID | None = None,
    pattern_id: str = "pat-001",
    domain: str = "testing",
    title: str = "Test Pattern",
    confidence: float = 0.9,
    **overrides: Any,
) -> dict[str, Any]:
    """Factory to create mock database row dict.

    HandlerDb returns rows as list[dict[str, object]], not asyncpg Record objects.
    """
    defaults: dict[str, Any] = {
        "id": id or uuid4(),
        "pattern_id": pattern_id,
        "domain": domain,
        "title": title,
        "description": "Test description",
        "confidence": confidence,
        "usage_count": 10,
        "success_rate": 0.85,
        "example_reference": None,
        "project_scope": None,
        "created_at": SAMPLE_TIMESTAMP,
        "updated_at": SAMPLE_TIMESTAMP,
    }
    defaults.update(overrides)
    return defaults


def make_handler_output(
    rows: list[dict[str, Any]] | None = None,
    row_count: int | None = None,
) -> MagicMock:
    """Create a mock ModelHandlerOutput[ModelDbQueryResponse].

    Simulates the return value of HandlerDb.execute() with proper structure:
    - result.result.payload.rows -> list[dict[str, object]]
    - result.result.payload.row_count -> int

    Args:
        rows: List of row dicts to return. Defaults to empty list.
        row_count: Number of rows. Defaults to len(rows).

    Returns:
        MagicMock configured to mimic ModelHandlerOutput structure.
    """
    if rows is None:
        rows = []
    if row_count is None:
        row_count = len(rows)

    # Build nested structure: output.result.payload.rows
    payload = MagicMock()
    payload.rows = rows
    payload.row_count = row_count

    result = MagicMock()
    result.payload = payload

    output = MagicMock()
    output.result = result

    return output


# =============================================================================
# DbPatternRecord Tests
# =============================================================================


class TestDbPatternRecord:
    """Tests for DbPatternRecord dataclass."""

    def test_create_valid_pattern(self) -> None:
        """DbPatternRecord is created with valid values."""
        pattern = make_pattern_record()
        assert pattern.pattern_id == "pat-001"
        assert pattern.domain == "testing"
        assert pattern.confidence == 0.9

    def test_confidence_validation_lower_bound(self) -> None:
        """DbPatternRecord rejects confidence below 0.0."""
        with pytest.raises(ValueError, match="confidence must be between"):
            make_pattern_record(confidence=-0.1)

    def test_confidence_validation_upper_bound(self) -> None:
        """DbPatternRecord rejects confidence above 1.0."""
        with pytest.raises(ValueError, match="confidence must be between"):
            make_pattern_record(confidence=1.1)

    def test_success_rate_validation_lower_bound(self) -> None:
        """DbPatternRecord rejects success_rate below 0.0."""
        with pytest.raises(ValueError, match="success_rate must be between"):
            make_pattern_record(success_rate=-0.1)

    def test_success_rate_validation_upper_bound(self) -> None:
        """DbPatternRecord rejects success_rate above 1.0."""
        with pytest.raises(ValueError, match="success_rate must be between"):
            make_pattern_record(success_rate=1.1)

    def test_usage_count_validation(self) -> None:
        """DbPatternRecord rejects negative usage_count."""
        with pytest.raises(ValueError, match="usage_count must be non-negative"):
            make_pattern_record(usage_count=-1)

    def test_pattern_is_frozen(self) -> None:
        """DbPatternRecord is immutable (frozen)."""
        pattern = make_pattern_record()
        with pytest.raises(AttributeError):
            pattern.confidence = 0.5  # type: ignore[misc]

    def test_to_api_dict(self) -> None:
        """DbPatternRecord.to_api_dict returns correct 8-field dict."""
        pattern = make_pattern_record(
            pattern_id="test-123",
            domain="code_review",
            title="API Pattern",
            description="Test desc",
            confidence=0.75,
            usage_count=5,
            success_rate=0.8,
            example_reference="file.py:10",
        )
        api_dict = pattern.to_api_dict()

        assert api_dict["pattern_id"] == "test-123"
        assert api_dict["domain"] == "code_review"
        assert api_dict["title"] == "API Pattern"
        assert api_dict["description"] == "Test desc"
        assert api_dict["confidence"] == 0.75
        assert api_dict["usage_count"] == 5
        assert api_dict["success_rate"] == 0.8
        assert api_dict["example_reference"] == "file.py:10"

        # Should NOT include database-specific fields
        assert "id" not in api_dict
        assert "project_scope" not in api_dict
        assert "created_at" not in api_dict
        assert "updated_at" not in api_dict


# =============================================================================
# PatternRepository.create_new_pattern Tests
# =============================================================================


class TestCreateNewPattern:
    """Tests for PatternRepository.create_new_pattern factory."""

    def test_creates_pattern_with_defaults(self) -> None:
        """create_new_pattern sets sensible defaults."""
        pattern = PatternRepository.create_new_pattern(
            pattern_id="pat-new",
            domain="testing",
            title="New Pattern",
            description="Description",
        )
        assert pattern.pattern_id == "pat-new"
        assert pattern.domain == "testing"
        assert pattern.confidence == 0.5  # default
        assert pattern.usage_count == 0  # default
        assert pattern.success_rate == 0.0  # default
        assert pattern.project_scope is None  # default

    def test_creates_pattern_with_custom_values(self) -> None:
        """create_new_pattern accepts custom values."""
        pattern = PatternRepository.create_new_pattern(
            pattern_id="pat-custom",
            domain="code_review",
            title="Custom Pattern",
            description="Custom description",
            confidence=0.9,
            usage_count=100,
            success_rate=0.95,
            example_reference="example.py:10",
            project_scope="my-project",
        )
        assert pattern.confidence == 0.9
        assert pattern.usage_count == 100
        assert pattern.success_rate == 0.95
        assert pattern.example_reference == "example.py:10"
        assert pattern.project_scope == "my-project"

    def test_creates_unique_id(self) -> None:
        """create_new_pattern generates unique UUIDs."""
        pattern1 = PatternRepository.create_new_pattern(
            pattern_id="pat-1", domain="d", title="t", description="d"
        )
        pattern2 = PatternRepository.create_new_pattern(
            pattern_id="pat-2", domain="d", title="t", description="d"
        )
        assert pattern1.id != pattern2.id


# =============================================================================
# PatternRepository Tests with Mocked HandlerDb
# =============================================================================


class TestPatternRepositoryGetPatterns:
    """Tests for PatternRepository.get_patterns method."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_get_patterns_returns_list(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns returns list of DbPatternRecord."""
        rows = [
            make_db_row(pattern_id="pat-1"),
            make_db_row(pattern_id="pat-2"),
        ]
        mock_handler.execute.return_value = make_handler_output(rows=rows)

        patterns = await repository.get_patterns()

        assert len(patterns) == 2
        assert patterns[0].pattern_id == "pat-1"
        assert patterns[1].pattern_id == "pat-2"

    @pytest.mark.asyncio
    async def test_get_patterns_builds_correct_envelope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns builds correct envelope structure for HandlerDb."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(min_confidence=0.7, limit=50)

        # Verify envelope structure
        call_args = mock_handler.execute.call_args[0][0]
        assert call_args["operation"] == "db.query"
        assert "SELECT" in call_args["payload"]["sql"]
        assert call_args["payload"]["parameters"][0] == 0.7  # min_confidence
        assert call_args["payload"]["parameters"][-1] == 50  # limit
        assert "correlation_id" in call_args

    @pytest.mark.asyncio
    async def test_get_patterns_with_domain_filter(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns applies domain filter in query."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(domain="testing")

        call_args = mock_handler.execute.call_args[0][0]
        query = call_args["payload"]["sql"]
        params = call_args["payload"]["parameters"]

        # Query should have domain filter
        assert "domain" in query
        # Domain should be in parameters
        assert "testing" in params

    @pytest.mark.asyncio
    async def test_get_patterns_includes_general_domain(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns includes 'general' domain by default when filtering."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(domain="testing", include_general=True)

        call_args = mock_handler.execute.call_args[0][0]
        query = call_args["payload"]["sql"]

        # Query should have OR general clause
        assert "general" in query

    @pytest.mark.asyncio
    async def test_get_patterns_excludes_general_when_disabled(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns excludes 'general' domain when include_general=False."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(domain="testing", include_general=False)

        call_args = mock_handler.execute.call_args[0][0]
        query = call_args["payload"]["sql"]

        # Should not have OR general clause
        assert "OR domain = 'general'" not in query

    @pytest.mark.asyncio
    async def test_get_patterns_with_min_confidence(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns passes min_confidence to query."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(min_confidence=0.7)

        call_args = mock_handler.execute.call_args[0][0]
        # First parameter is min_confidence
        assert call_args["payload"]["parameters"][0] == 0.7

    @pytest.mark.asyncio
    async def test_get_patterns_with_limit(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns passes limit to query."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(limit=50)

        call_args = mock_handler.execute.call_args[0][0]
        # Last parameter is limit
        assert call_args["payload"]["parameters"][-1] == 50

    @pytest.mark.asyncio
    async def test_get_patterns_with_project_scope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns filters by project_scope when provided."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns(project_scope="/my/project")

        call_args = mock_handler.execute.call_args[0][0]
        query = call_args["payload"]["sql"]
        params = call_args["payload"]["parameters"]

        # Query should have project scope filter
        assert "project_scope" in query
        # Project scope should be in parameters
        assert "/my/project" in params

    @pytest.mark.asyncio
    async def test_get_patterns_empty_result(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns returns empty list when no patterns found."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        patterns = await repository.get_patterns()

        assert patterns == []

    @pytest.mark.asyncio
    async def test_get_patterns_converts_rows_to_records(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns converts row dicts to DbPatternRecord objects."""
        row_id = uuid4()
        rows = [
            make_db_row(
                id=row_id,
                pattern_id="p-001",
                domain="testing",
                title="Test Pattern",
                description="A test",
                confidence=0.8,
                usage_count=5,
                success_rate=0.9,
                example_reference="file.py:10",
                project_scope=None,
            )
        ]
        mock_handler.execute.return_value = make_handler_output(rows=rows)

        patterns = await repository.get_patterns()

        assert len(patterns) == 1
        pattern = patterns[0]
        assert isinstance(pattern, DbPatternRecord)
        assert pattern.id == row_id
        assert pattern.pattern_id == "p-001"
        assert pattern.domain == "testing"
        assert pattern.title == "Test Pattern"
        assert pattern.confidence == 0.8
        assert pattern.usage_count == 5
        assert pattern.success_rate == 0.9
        assert pattern.example_reference == "file.py:10"

    @pytest.mark.asyncio
    async def test_get_patterns_handles_handler_error(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_patterns wraps handler errors in PatternRepositoryError."""
        mock_handler.execute.side_effect = RuntimeError("Handler connection failed")

        with pytest.raises(PatternRepositoryError, match="Failed to query patterns"):
            await repository.get_patterns()


class TestPatternRepositoryGetPatternById:
    """Tests for PatternRepository.get_pattern_by_id method."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_get_pattern_by_id_found(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_pattern_by_id returns pattern when found."""
        row = make_db_row(pattern_id="pat-123")
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        result = await repository.get_pattern_by_id("pat-123")

        assert result is not None
        assert result.pattern_id == "pat-123"

    @pytest.mark.asyncio
    async def test_get_pattern_by_id_not_found(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_pattern_by_id returns None when not found."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        result = await repository.get_pattern_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_pattern_by_id_builds_correct_envelope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """get_pattern_by_id builds correct envelope."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_pattern_by_id("pat-123")

        call_args = mock_handler.execute.call_args[0][0]
        assert call_args["operation"] == "db.query"
        assert "pattern_id = $1" in call_args["payload"]["sql"]
        assert call_args["payload"]["parameters"] == ["pat-123"]


class TestPatternRepositoryUpsert:
    """Tests for PatternRepository.upsert_pattern method."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_upsert_returns_pattern(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """upsert_pattern returns the upserted DbPatternRecord."""
        pattern = make_pattern_record()
        row = make_db_row(pattern_id=pattern.pattern_id)
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        result = await repository.upsert_pattern(pattern)

        assert result.pattern_id == pattern.pattern_id

    @pytest.mark.asyncio
    async def test_upsert_builds_correct_envelope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """upsert_pattern builds correct envelope with all fields."""
        pattern = make_pattern_record(
            pattern_id="upsert-test",
            domain="testing",
            title="Upsert Pattern",
            confidence=0.85,
        )
        row = make_db_row(pattern_id=pattern.pattern_id)
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        await repository.upsert_pattern(pattern)

        call_args = mock_handler.execute.call_args[0][0]
        assert call_args["operation"] == "db.query"
        assert "INSERT INTO learned_patterns" in call_args["payload"]["sql"]
        assert "ON CONFLICT" in call_args["payload"]["sql"]

        # Verify parameters include pattern fields
        params = call_args["payload"]["parameters"]
        assert pattern.id in params
        assert "upsert-test" in params
        assert "testing" in params
        assert "Upsert Pattern" in params

    @pytest.mark.asyncio
    async def test_upsert_raises_on_no_return(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """upsert_pattern raises error if no row returned."""
        pattern = make_pattern_record()
        mock_handler.execute.return_value = make_handler_output(rows=[])

        with pytest.raises(PatternRepositoryError, match="Upsert returned no row"):
            await repository.upsert_pattern(pattern)


class TestPatternRepositoryIncrementUsage:
    """Tests for PatternRepository.increment_usage method."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_increment_usage_success(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """increment_usage returns new counts on success."""
        row = {"usage_count": 11, "success_rate": 0.86}
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        count, rate = await repository.increment_usage("pat-001", success=True)

        assert count == 11
        assert rate == 0.86

    @pytest.mark.asyncio
    async def test_increment_usage_builds_correct_envelope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """increment_usage builds correct envelope."""
        row = {"usage_count": 11, "success_rate": 0.86}
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        await repository.increment_usage("pat-001", success=True)

        call_args = mock_handler.execute.call_args[0][0]
        assert call_args["operation"] == "db.query"
        assert "UPDATE learned_patterns" in call_args["payload"]["sql"]
        assert "usage_count = usage_count + 1" in call_args["payload"]["sql"]
        assert call_args["payload"]["parameters"] == ["pat-001", True]

    @pytest.mark.asyncio
    async def test_increment_usage_not_found(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """increment_usage raises PatternNotFoundError when pattern missing."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        with pytest.raises(PatternNotFoundError, match="Pattern not found"):
            await repository.increment_usage("nonexistent", success=True)


class TestPatternRepositoryDelete:
    """Tests for PatternRepository.delete_pattern method."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_deleted(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """delete_pattern returns True when pattern deleted."""
        row = {"id": SAMPLE_UUID}
        mock_handler.execute.return_value = make_handler_output(rows=[row])

        result = await repository.delete_pattern("pat-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """delete_pattern returns False when pattern not found."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        result = await repository.delete_pattern("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_builds_correct_envelope(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """delete_pattern builds correct envelope."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.delete_pattern("pat-001")

        call_args = mock_handler.execute.call_args[0][0]
        assert call_args["operation"] == "db.query"
        assert "DELETE FROM learned_patterns" in call_args["payload"]["sql"]
        assert call_args["payload"]["parameters"] == ["pat-001"]


# =============================================================================
# Error Classes Tests
# =============================================================================


class TestPatternRepositoryErrors:
    """Tests for custom error classes."""

    def test_pattern_repository_error_with_correlation_id(self) -> None:
        """PatternRepositoryError stores correlation_id."""
        error = PatternRepositoryError(
            "Test error",
            correlation_id=SAMPLE_UUID,
            operation="test_op",
        )
        assert error.correlation_id == SAMPLE_UUID
        assert error.operation == "test_op"

    def test_pattern_not_found_error_is_repository_error(self) -> None:
        """PatternNotFoundError inherits from PatternRepositoryError."""
        error = PatternNotFoundError("Not found")
        assert isinstance(error, PatternRepositoryError)


# =============================================================================
# Row Conversion Tests
# =============================================================================


class TestRowConversion:
    """Tests for _row_to_pattern conversion method."""

    def test_row_to_pattern_full_row(self) -> None:
        """_row_to_pattern converts complete row dict to DbPatternRecord."""
        row_id = uuid4()
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        updated_at = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)

        row = {
            "id": row_id,
            "pattern_id": "test-row",
            "domain": "conversion",
            "title": "Conversion Test",
            "description": "Testing row conversion",
            "confidence": 0.75,
            "usage_count": 15,
            "success_rate": 0.88,
            "example_reference": "test.py:42",
            "project_scope": "/my/project",
            "created_at": created_at,
            "updated_at": updated_at,
        }

        pattern = PatternRepository._row_to_pattern(row)

        assert pattern.id == row_id
        assert pattern.pattern_id == "test-row"
        assert pattern.domain == "conversion"
        assert pattern.title == "Conversion Test"
        assert pattern.description == "Testing row conversion"
        assert pattern.confidence == 0.75
        assert pattern.usage_count == 15
        assert pattern.success_rate == 0.88
        assert pattern.example_reference == "test.py:42"
        assert pattern.project_scope == "/my/project"
        assert pattern.created_at == created_at
        assert pattern.updated_at == updated_at

    def test_row_to_pattern_with_none_optional_fields(self) -> None:
        """_row_to_pattern handles None for optional fields."""
        row = make_db_row(
            example_reference=None,
            project_scope=None,
        )

        pattern = PatternRepository._row_to_pattern(row)

        assert pattern.example_reference is None
        assert pattern.project_scope is None


# =============================================================================
# Envelope Structure Tests
# =============================================================================


class TestEnvelopeStructure:
    """Tests verifying correct envelope structure for HandlerDb."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create mock HandlerDb."""
        handler = MagicMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.fixture
    def repository(self, mock_handler: MagicMock) -> PatternRepository:
        """Create repository with mock handler."""
        return PatternRepository(mock_handler)

    @pytest.mark.asyncio
    async def test_envelope_has_required_fields(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """Envelope has operation, payload, and correlation_id."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns()

        envelope = mock_handler.execute.call_args[0][0]
        assert "operation" in envelope
        assert "payload" in envelope
        assert "correlation_id" in envelope

    @pytest.mark.asyncio
    async def test_payload_has_sql_and_parameters(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """Payload has sql and parameters fields."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns()

        envelope = mock_handler.execute.call_args[0][0]
        payload = envelope["payload"]
        assert "sql" in payload
        assert "parameters" in payload
        assert isinstance(payload["sql"], str)
        assert isinstance(payload["parameters"], list)

    @pytest.mark.asyncio
    async def test_correlation_id_is_string(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """Correlation ID is serialized as string."""
        mock_handler.execute.return_value = make_handler_output(rows=[])

        await repository.get_patterns()

        envelope = mock_handler.execute.call_args[0][0]
        assert isinstance(envelope["correlation_id"], str)

    @pytest.mark.asyncio
    async def test_custom_correlation_id_is_used(
        self, repository: PatternRepository, mock_handler: MagicMock
    ) -> None:
        """Custom correlation_id is passed to envelope."""
        mock_handler.execute.return_value = make_handler_output(rows=[])
        custom_id = uuid4()

        await repository.get_patterns(correlation_id=custom_id)

        envelope = mock_handler.execute.call_args[0][0]
        assert envelope["correlation_id"] == str(custom_id)
