"""
Tests for Pattern Quality Backfill Process

Tests the backfill script that scores all Qdrant patterns and populates
the pattern_quality_metrics table with comprehensive edge case coverage.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock qdrant_client before importing backfill script
sys_modules_backup = {}


@pytest.fixture(autouse=True)
def mock_qdrant_client():
    """Mock qdrant_client for all tests."""
    mock_client = MagicMock()

    with patch.dict(
        "sys.modules",
        {"qdrant_client": mock_client, "qdrant_client.models": MagicMock()},
    ):
        yield mock_client


# ============================================================================
# Test UUID Conversion for Pattern IDs
# ============================================================================


def test_uuid_conversion_from_integer_id():
    """Test deterministic UUID generation from integer Qdrant IDs."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    # Mock record with integer ID
    record = Mock()
    record.id = 12345
    record.payload = {"pattern_name": "TestPattern", "code": "def test(): pass"}

    pattern = extract_pattern_from_record(record)

    # Should generate valid UUID
    assert pattern["pattern_id"]
    uuid.UUID(pattern["pattern_id"])  # Validates UUID format

    # Should be deterministic (same input = same UUID)
    pattern2 = extract_pattern_from_record(record)
    assert pattern["pattern_id"] == pattern2["pattern_id"]


def test_uuid_conversion_from_uuid_string():
    """Test UUID passthrough when Qdrant ID is already UUID."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    test_uuid = str(uuid.uuid4())
    record = Mock()
    record.id = test_uuid
    record.payload = {"pattern_name": "TestPattern"}

    pattern = extract_pattern_from_record(record)

    # Should preserve original UUID
    assert pattern["pattern_id"] == test_uuid


def test_uuid_conversion_consistency_across_collections():
    """Test same integer ID generates same UUID across different collections."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    record1 = Mock()
    record1.id = 999
    record1.payload = {"pattern_name": "Pattern1", "code": "code1"}

    record2 = Mock()
    record2.id = 999
    record2.payload = {"pattern_name": "Pattern2", "code": "code2"}

    pattern1 = extract_pattern_from_record(record1)
    pattern2 = extract_pattern_from_record(record2)

    # Same ID should generate same UUID
    assert pattern1["pattern_id"] == pattern2["pattern_id"]


# ============================================================================
# Test Database Constraint Handling
# ============================================================================


@pytest.mark.asyncio
async def test_store_quality_metrics_with_unique_constraint_violation():
    """Test handling of unique constraint violation on pattern_id."""
    import psycopg2.errors

    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    scorer = PatternQualityScorer()
    score = PatternQualityScore(
        pattern_id="test-duplicate",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    # Simulate unique constraint violation
    mock_cursor.execute.side_effect = psycopg2.errors.UniqueViolation(
        "duplicate key value violates unique constraint"
    )
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.errors.UniqueViolation = psycopg2.errors.UniqueViolation

        # Should handle gracefully (ON CONFLICT should prevent this, but test defensive handling)
        with pytest.raises(Exception):
            await scorer.store_quality_metrics(score, "postgresql://test")

        # Verify rollback was called
        mock_conn.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_store_quality_metrics_upsert_replaces_existing():
    """Test ON CONFLICT DO UPDATE replaces existing pattern score."""
    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    scorer = PatternQualityScorer()
    pattern_id = str(uuid.uuid4())

    # First score
    score1 = PatternQualityScore(
        pattern_id=pattern_id,
        pattern_name="TestPattern",
        composite_score=0.70,
        completeness_score=0.70,
        documentation_score=0.70,
        onex_compliance_score=0.70,
        metadata_richness_score=0.70,
        complexity_score=0.70,
        confidence=0.80,
        measurement_timestamp=datetime.now(UTC),
    )

    # Updated score (should replace first)
    score2 = PatternQualityScore(
        pattern_id=pattern_id,
        pattern_name="TestPattern",
        composite_score=0.90,
        completeness_score=0.90,
        documentation_score=0.90,
        onex_compliance_score=0.90,
        metadata_richness_score=0.90,
        complexity_score=0.90,
        confidence=0.95,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_psycopg2.connect.return_value = mock_conn

        # Store both scores (second should upsert)
        await scorer.store_quality_metrics(score1, "postgresql://test")
        await scorer.store_quality_metrics(score2, "postgresql://test")

        # Should have been called twice
        assert mock_cursor.execute.call_count == 2
        assert mock_conn.commit.call_count == 2


@pytest.mark.asyncio
async def test_store_quality_metrics_with_invalid_uuid_format():
    """Test error handling when pattern_id is invalid UUID format."""
    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    scorer = PatternQualityScorer()
    score = PatternQualityScore(
        pattern_id="not-a-valid-uuid",  # Invalid UUID format
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("invalid input syntax for type uuid")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_psycopg2.connect.return_value = mock_conn

        with pytest.raises(Exception) as exc_info:
            await scorer.store_quality_metrics(score, "postgresql://test")

        assert "Failed to store quality metrics" in str(exc_info.value)


# ============================================================================
# Test Batch Processing
# ============================================================================


@pytest.mark.asyncio
async def test_backfill_batch_processing_rate_limiting():
    """Test batch processing with rate limiting delays."""
    from agents.lib.pattern_quality_scorer import PatternQualityScore
    from scripts.backfill_pattern_quality import store_scores_to_database

    # Create 250 mock scores (2.5 batches of 100)
    scores = [
        PatternQualityScore(
            pattern_id=str(uuid.uuid4()),
            pattern_name=f"Pattern{i}",
            composite_score=0.8,
            completeness_score=0.8,
            documentation_score=0.8,
            onex_compliance_score=0.8,
            metadata_richness_score=0.8,
            complexity_score=0.8,
            confidence=0.8,
            measurement_timestamp=datetime.now(UTC),
        )
        for i in range(250)
    ]

    with patch(
        "agents.lib.pattern_quality_scorer.PatternQualityScorer.store_quality_metrics"
    ) as mock_store:
        mock_store.return_value = None

        with patch("asyncio.sleep") as mock_sleep:
            await store_scores_to_database(
                scores,
                database_url="postgresql://test",
                batch_size=100,
                delay=0.5,
                dry_run=False,
            )

            # Should have slept 2 times (not after last batch)
            assert mock_sleep.call_count == 2
            # Each sleep should be 0.5 seconds
            mock_sleep.assert_called_with(0.5)


@pytest.mark.asyncio
async def test_backfill_continues_on_individual_failures():
    """Test backfill continues processing even if individual patterns fail."""
    from agents.lib.pattern_quality_scorer import PatternQualityScore
    from scripts.backfill_pattern_quality import store_scores_to_database

    scores = [
        PatternQualityScore(
            pattern_id=str(uuid.uuid4()),
            pattern_name=f"Pattern{i}",
            composite_score=0.8,
            completeness_score=0.8,
            documentation_score=0.8,
            onex_compliance_score=0.8,
            metadata_richness_score=0.8,
            complexity_score=0.8,
            confidence=0.8,
            measurement_timestamp=datetime.now(UTC),
        )
        for i in range(10)
    ]

    call_count = 0

    async def mock_store_with_failures(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fail on patterns 3, 5, 7
        if call_count in [3, 5, 7]:
            raise Exception("Database error")

    with patch(
        "agents.lib.pattern_quality_scorer.PatternQualityScorer.store_quality_metrics",
        side_effect=mock_store_with_failures,
    ):
        # Should not raise, should continue
        await store_scores_to_database(
            scores,
            database_url="postgresql://test",
            batch_size=5,
            delay=0.0,
            dry_run=False,
        )

        # Should have attempted all 10
        assert call_count == 10


# ============================================================================
# Test Pattern Extraction Edge Cases
# ============================================================================


def test_extract_pattern_handles_missing_payload():
    """Test pattern extraction with missing payload."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    record = Mock()
    record.id = str(uuid.uuid4())
    record.payload = None

    pattern = extract_pattern_from_record(record)

    # Should handle gracefully with defaults
    assert pattern["pattern_name"] == "unnamed_pattern"
    assert pattern["code"] == ""
    assert pattern["metadata"] == {}


def test_extract_pattern_handles_different_field_names():
    """Test pattern extraction handles different collection schemas."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    # Test archon_vectors collection schema
    record1 = Mock()
    record1.id = 1
    record1.payload = {
        "pattern_name": "ArchonPattern",
        "content_preview": "archon code",  # Different field name
        "pattern_confidence": 0.95,  # Different field name
    }

    pattern1 = extract_pattern_from_record(record1)
    assert pattern1["code"] == "archon code"
    assert pattern1["confidence"] == 0.95

    # Test code_patterns collection schema
    record2 = Mock()
    record2.id = str(uuid.uuid4())
    record2.payload = {
        "pattern_name": "CodePattern",
        "code": "code pattern",  # Standard field name
        "confidence": 0.90,
    }

    pattern2 = extract_pattern_from_record(record2)
    assert pattern2["code"] == "code pattern"
    assert pattern2["confidence"] == 0.90


def test_extract_pattern_handles_node_types_array():
    """Test pattern extraction handles node_types as array vs single value."""
    from scripts.backfill_pattern_quality import extract_pattern_from_record

    # Single node_type
    record1 = Mock()
    record1.id = str(uuid.uuid4())
    record1.payload = {"node_type": "effect"}

    pattern1 = extract_pattern_from_record(record1)
    assert pattern1["node_type"] == "effect"

    # Array of node_types (take first)
    record2 = Mock()
    record2.id = str(uuid.uuid4())
    record2.payload = {"node_types": ["compute", "reducer"]}

    pattern2 = extract_pattern_from_record(record2)
    assert pattern2["node_type"] == "compute"


# ============================================================================
# Test Query Performance
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_query_patterns_performance_with_pagination():
    """Test pattern querying handles large collections efficiently."""
    from qdrant_client.models import ScrollResult

    from scripts.backfill_pattern_quality import query_patterns

    # Mock Qdrant client with pagination
    mock_client = Mock()
    mock_collections = Mock()
    mock_collections.collections = [Mock(name="code_patterns")]
    mock_client.get_collections.return_value = mock_collections

    # Simulate 3 pages of results (100 per page)
    page_results = []
    for page in range(3):
        records = []
        for i in range(100):
            record = Mock()
            record.id = str(uuid.uuid4())
            record.payload = {
                "pattern_name": f"Pattern{page}_{i}",
                "code": "def test(): pass",
                "confidence": 0.8,
            }
            records.append(record)

        # Last page has offset=None to stop pagination
        offset = f"page_{page+1}" if page < 2 else None
        page_results.append(ScrollResult(points=records, next_page_offset=offset))

    mock_client.scroll.side_effect = page_results

    patterns = await query_patterns(
        mock_client, collection_name="code_patterns", min_confidence=0.5, limit=None
    )

    # Should have collected all 300 patterns
    assert len(patterns) == 300
    # Should have made 3 scroll calls
    assert mock_client.scroll.call_count == 3


@pytest.mark.asyncio
async def test_query_patterns_respects_limit():
    """Test pattern querying respects limit parameter."""
    from qdrant_client.models import ScrollResult

    from scripts.backfill_pattern_quality import query_patterns

    mock_client = Mock()
    mock_collections = Mock()
    mock_collections.collections = [Mock(name="code_patterns")]
    mock_client.get_collections.return_value = mock_collections

    # Return 150 patterns
    records = [
        Mock(
            id=str(uuid.uuid4()),
            payload={"pattern_name": f"Pattern{i}", "confidence": 0.8},
        )
        for i in range(150)
    ]
    mock_client.scroll.return_value = ScrollResult(
        points=records, next_page_offset=None
    )

    patterns = await query_patterns(
        mock_client,
        collection_name="code_patterns",
        min_confidence=0.5,
        limit=50,  # Limit to 50
    )

    # Should return only 50
    assert len(patterns) == 50


# ============================================================================
# Test Dry Run Mode
# ============================================================================


@pytest.mark.asyncio
async def test_backfill_dry_run_mode():
    """Test dry run mode doesn't write to database."""
    from agents.lib.pattern_quality_scorer import PatternQualityScore
    from scripts.backfill_pattern_quality import store_scores_to_database

    scores = [
        PatternQualityScore(
            pattern_id=str(uuid.uuid4()),
            pattern_name=f"Pattern{i}",
            composite_score=0.8,
            completeness_score=0.8,
            documentation_score=0.8,
            onex_compliance_score=0.8,
            metadata_richness_score=0.8,
            complexity_score=0.8,
            confidence=0.8,
            measurement_timestamp=datetime.now(UTC),
        )
        for i in range(10)
    ]

    with patch(
        "agents.lib.pattern_quality_scorer.PatternQualityScorer.store_quality_metrics"
    ) as mock_store:
        await store_scores_to_database(
            scores,
            database_url="postgresql://test",
            batch_size=5,
            delay=0.0,
            dry_run=True,  # Dry run mode
        )

        # Should NOT have called store
        mock_store.assert_not_called()


# ============================================================================
# Test Statistics Collection
# ============================================================================


def test_quality_stats_distribution():
    """Test quality statistics correctly categorize patterns."""
    from agents.lib.pattern_quality_scorer import PatternQualityScore
    from scripts.backfill_pattern_quality import QualityStats

    stats = QualityStats()

    # Add patterns across quality spectrum
    scores = [
        PatternQualityScore(
            pattern_id="1",
            pattern_name="Excellent",
            composite_score=0.95,
            completeness_score=0.95,
            documentation_score=0.95,
            onex_compliance_score=0.95,
            metadata_richness_score=0.95,
            complexity_score=0.95,
            confidence=0.95,
            measurement_timestamp=datetime.now(UTC),
        ),
        PatternQualityScore(
            pattern_id="2",
            pattern_name="Good",
            composite_score=0.75,
            completeness_score=0.75,
            documentation_score=0.75,
            onex_compliance_score=0.75,
            metadata_richness_score=0.75,
            complexity_score=0.75,
            confidence=0.75,
            measurement_timestamp=datetime.now(UTC),
        ),
        PatternQualityScore(
            pattern_id="3",
            pattern_name="Fair",
            composite_score=0.55,
            completeness_score=0.55,
            documentation_score=0.55,
            onex_compliance_score=0.55,
            metadata_richness_score=0.55,
            complexity_score=0.55,
            confidence=0.55,
            measurement_timestamp=datetime.now(UTC),
        ),
        PatternQualityScore(
            pattern_id="4",
            pattern_name="Poor",
            composite_score=0.35,
            completeness_score=0.35,
            documentation_score=0.35,
            onex_compliance_score=0.35,
            metadata_richness_score=0.35,
            complexity_score=0.35,
            confidence=0.35,
            measurement_timestamp=datetime.now(UTC),
        ),
    ]

    for score in scores:
        stats.add_score(score)

    # Verify distribution
    assert stats.excellent_count == 1
    assert stats.good_count == 1
    assert stats.fair_count == 1
    assert stats.poor_count == 1


# ============================================================================
# Test Connection String Handling
# ============================================================================


def test_database_url_environment_variable_priority():
    """Test DATABASE_URL environment variable resolution priority."""
    import os

    # Test HOST_DATABASE_URL takes priority
    with patch.dict(
        os.environ,
        {
            "HOST_DATABASE_URL": "postgresql://host_url",
            "DATABASE_URL": "postgresql://default_url",
        },
    ):
        from scripts.backfill_pattern_quality import parse_args

        args = parse_args(["--dry-run"])
        assert args.database_url == "postgresql://host_url"

    # Test DATABASE_URL fallback
    with patch.dict(
        os.environ, {"DATABASE_URL": "postgresql://default_url"}, clear=True
    ):
        args = parse_args(["--dry-run"])
        assert args.database_url == "postgresql://default_url"


# ============================================================================
# Integration Test (requires real services)
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_backfill_workflow_integration():
    """
    Integration test for full backfill workflow.

    Requires:
    - Qdrant running at localhost:6333
    - PostgreSQL at connection string from env
    - Test patterns in code_patterns collection
    """
    pytest.skip("Integration test - requires real services")

    # This would test the actual end-to-end flow:
    # 1. Connect to real Qdrant
    # 2. Query real patterns
    # 3. Score patterns
    # 4. Store to real database
    # 5. Verify database records
