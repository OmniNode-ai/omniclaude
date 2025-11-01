"""
Database Integration Tests for Pattern Quality Metrics

Tests the actual database operations, constraints, and upsert behavior
for the pattern_quality_metrics table. These tests help prevent regressions
related to constraint errors, type casting issues, and transaction handling.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest

# Skip all tests if no database connection available
pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") and not os.getenv("POSTGRES_PASSWORD"),
    reason="Database connection not configured",
)


@pytest.fixture
def db_connection_string():
    """Get database connection string from environment."""
    # Priority: DATABASE_URL > construct from POSTGRES_PASSWORD
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")

    password = os.getenv("POSTGRES_PASSWORD", "***REDACTED***")
    host = os.getenv("POSTGRES_HOST", "192.168.86.200")
    port = os.getenv("POSTGRES_PORT", "5436")
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
    user = os.getenv("POSTGRES_USER", "postgres")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
def test_pattern_id():
    """Generate unique test pattern ID."""
    return str(uuid.uuid4())


@pytest.fixture
async def cleanup_test_pattern(db_connection_string):
    """Fixture to cleanup test patterns after each test."""
    test_pattern_ids = []

    # Yield control to test
    yield test_pattern_ids

    # Cleanup after test
    try:
        import psycopg2

        conn = psycopg2.connect(db_connection_string)
        cursor = conn.cursor()

        for pattern_id in test_pattern_ids:
            cursor.execute(
                "DELETE FROM pattern_quality_metrics WHERE pattern_id = %s",
                (pattern_id,),
            )

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Cleanup failed: {e}")


# ============================================================================
# Test Database Constraints
# ============================================================================


@pytest.mark.database
@pytest.mark.asyncio
async def test_unique_constraint_exists(db_connection_string):
    """Test pattern_quality_metrics table has UNIQUE constraint on pattern_id."""
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        # Query for UNIQUE constraints
        cursor.execute(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_name = 'pattern_quality_metrics'
            AND constraint_type = 'UNIQUE'
            AND constraint_name = 'pattern_quality_metrics_pattern_id_unique'
        """
        )

        result = cursor.fetchone()

        # Constraint must exist
        assert result is not None, "UNIQUE constraint on pattern_id not found"
        assert result[0] == "pattern_quality_metrics_pattern_id_unique"
        assert result[1] == "UNIQUE"

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_check_constraints_exist(db_connection_string):
    """Test pattern_quality_metrics table has proper CHECK constraints."""
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        # Query for CHECK constraints
        cursor.execute(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'pattern_quality_metrics'
            AND constraint_type = 'CHECK'
        """
        )

        constraints = [row[0] for row in cursor.fetchall()]

        # Should have constraints for quality_score and confidence
        assert any(
            "quality_score" in c for c in constraints
        ), "quality_score CHECK constraint not found"
        assert any(
            "confidence" in c for c in constraints
        ), "confidence CHECK constraint not found"

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_insert_with_valid_uuid(
    db_connection_string, test_pattern_id, cleanup_test_pattern
):
    """Test inserting quality metrics with valid UUID pattern_id."""
    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    cleanup_test_pattern.append(test_pattern_id)
    scorer = PatternQualityScorer()

    score = PatternQualityScore(
        pattern_id=test_pattern_id,
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

    # Should not raise
    await scorer.store_quality_metrics(score, db_connection_string)

    # Verify it was stored
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT pattern_id, quality_score FROM pattern_quality_metrics WHERE pattern_id = %s",
            (test_pattern_id,),
        )
        result = cursor.fetchone()

        assert result is not None
        assert str(result[0]) == test_pattern_id
        assert result[1] == 0.85

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_upsert_updates_existing_record(
    db_connection_string, test_pattern_id, cleanup_test_pattern
):
    """Test ON CONFLICT DO UPDATE actually updates existing record."""
    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    cleanup_test_pattern.append(test_pattern_id)
    scorer = PatternQualityScorer()

    # Insert first score
    score1 = PatternQualityScore(
        pattern_id=test_pattern_id,
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

    await scorer.store_quality_metrics(score1, db_connection_string)

    # Upsert with better score
    score2 = PatternQualityScore(
        pattern_id=test_pattern_id,
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

    await scorer.store_quality_metrics(score2, db_connection_string)

    # Verify only one record exists with updated score
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT COUNT(*), MAX(quality_score) FROM pattern_quality_metrics WHERE pattern_id = %s",
            (test_pattern_id,),
        )
        count, max_score = cursor.fetchone()

        assert count == 1, f"Expected 1 record, found {count}"
        assert max_score == 0.90, f"Expected score 0.90, found {max_score}"

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_constraint_violation_on_invalid_score_range(
    db_connection_string, test_pattern_id, cleanup_test_pattern
):
    """Test CHECK constraint prevents invalid score values."""
    import psycopg2

    cleanup_test_pattern.append(test_pattern_id)
    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        # Try to insert score > 1.0 (should fail)
        cursor.execute(
            """
            INSERT INTO pattern_quality_metrics (
                pattern_id, quality_score, confidence, measurement_timestamp
            ) VALUES (%s, %s, %s, %s)
        """,
            (test_pattern_id, 1.5, 0.9, datetime.now(UTC)),
        )

        conn.commit()

        # Should not reach here
        pytest.fail("CHECK constraint did not prevent invalid score")

    except psycopg2.errors.CheckViolation:
        # Expected - constraint prevented invalid data
        conn.rollback()

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_concurrent_upserts_handle_conflicts(
    db_connection_string, cleanup_test_pattern
):
    """Test concurrent upserts for same pattern_id don't cause deadlocks."""
    import asyncio

    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    test_pattern_id = str(uuid.uuid4())
    cleanup_test_pattern.append(test_pattern_id)

    scorer = PatternQualityScorer()

    # Create 10 concurrent upserts for same pattern
    async def store_score(score_value):
        score = PatternQualityScore(
            pattern_id=test_pattern_id,
            pattern_name="TestPattern",
            composite_score=score_value,
            completeness_score=score_value,
            documentation_score=score_value,
            onex_compliance_score=score_value,
            metadata_richness_score=score_value,
            complexity_score=score_value,
            confidence=score_value,
            measurement_timestamp=datetime.now(UTC),
        )
        await scorer.store_quality_metrics(score, db_connection_string)

    # Run concurrently
    scores_to_store = [0.70 + i * 0.01 for i in range(10)]
    await asyncio.gather(*[store_score(s) for s in scores_to_store])

    # Verify only one record exists
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT COUNT(*) FROM pattern_quality_metrics WHERE pattern_id = %s",
            (test_pattern_id,),
        )
        count = cursor.fetchone()[0]

        # Should still have only 1 record (last upsert wins)
        assert count == 1, f"Expected 1 record, found {count}"

    finally:
        cursor.close()
        conn.close()


# ============================================================================
# Test Type Casting (UUID Handling)
# ============================================================================


@pytest.mark.database
@pytest.mark.asyncio
async def test_uuid_type_casting_in_query(
    db_connection_string, test_pattern_id, cleanup_test_pattern
):
    """Test UUID type casting doesn't interfere with constraint resolution."""
    import psycopg2
    from psycopg2.extras import Json

    cleanup_test_pattern.append(test_pattern_id)
    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        # Test both with and without ::uuid cast
        queries = [
            # Without explicit cast (psycopg2 handles it)
            """
            INSERT INTO pattern_quality_metrics (
                pattern_id, quality_score, confidence, measurement_timestamp, version, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (pattern_id) DO UPDATE SET
                quality_score = EXCLUDED.quality_score
            """,
            # With explicit cast (current implementation)
            """
            INSERT INTO pattern_quality_metrics (
                pattern_id, quality_score, confidence, measurement_timestamp, version, metadata
            ) VALUES (%s::uuid, %s, %s, %s, %s, %s)
            ON CONFLICT (pattern_id) DO UPDATE SET
                quality_score = EXCLUDED.quality_score
            """,
        ]

        for query_idx, query in enumerate(queries):
            # Use different score for each attempt
            score = 0.70 + query_idx * 0.10

            cursor.execute(
                query,
                (
                    test_pattern_id,
                    score,
                    0.90,
                    datetime.now(UTC),
                    "1.0.0",
                    Json({"test": "metadata"}),
                ),
            )

            conn.commit()

        # Verify final score (should be from second query)
        cursor.execute(
            "SELECT quality_score FROM pattern_quality_metrics WHERE pattern_id = %s",
            (test_pattern_id,),
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == 0.80  # Score from second upsert

    finally:
        cursor.close()
        conn.close()


@pytest.mark.database
@pytest.mark.asyncio
async def test_invalid_uuid_format_rejected(db_connection_string):
    """Test database rejects invalid UUID format."""
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        # Try to insert invalid UUID format
        cursor.execute(
            """
            INSERT INTO pattern_quality_metrics (
                pattern_id, quality_score, confidence, measurement_timestamp
            ) VALUES (%s, %s, %s, %s)
        """,
            ("not-a-valid-uuid", 0.85, 0.90, datetime.now(UTC)),
        )

        conn.commit()

        # Should not reach here
        pytest.fail("Database accepted invalid UUID format")

    except psycopg2.errors.InvalidTextRepresentation:
        # Expected - database rejected invalid UUID
        conn.rollback()

    finally:
        cursor.close()
        conn.close()


# ============================================================================
# Test Metadata JSONB Storage
# ============================================================================


@pytest.mark.database
@pytest.mark.asyncio
async def test_metadata_jsonb_storage(
    db_connection_string, test_pattern_id, cleanup_test_pattern
):
    """Test metadata is correctly stored as JSONB."""
    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    cleanup_test_pattern.append(test_pattern_id)
    scorer = PatternQualityScorer()

    score = PatternQualityScore(
        pattern_id=test_pattern_id,
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

    await scorer.store_quality_metrics(score, db_connection_string)

    # Verify metadata structure
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT metadata FROM pattern_quality_metrics WHERE pattern_id = %s",
            (test_pattern_id,),
        )
        metadata = cursor.fetchone()[0]

        # Should have all dimension scores
        assert "completeness_score" in metadata
        assert "documentation_score" in metadata
        assert "onex_compliance_score" in metadata
        assert "metadata_richness_score" in metadata
        assert "complexity_score" in metadata

        # Verify values
        assert metadata["completeness_score"] == 0.90
        assert metadata["documentation_score"] == 0.80

    finally:
        cursor.close()
        conn.close()


# ============================================================================
# Test Performance
# ============================================================================


@pytest.mark.database
@pytest.mark.asyncio
@pytest.mark.slow
async def test_bulk_upsert_performance(db_connection_string, cleanup_test_pattern):
    """Test performance of bulk pattern upserts."""
    import time

    from agents.lib.pattern_quality_scorer import (
        PatternQualityScore,
        PatternQualityScorer,
    )

    scorer = PatternQualityScorer()

    # Generate 100 test patterns
    test_pattern_ids = [str(uuid.uuid4()) for _ in range(100)]
    cleanup_test_pattern.extend(test_pattern_ids)

    scores = [
        PatternQualityScore(
            pattern_id=pattern_id,
            pattern_name=f"Pattern{i}",
            composite_score=0.80,
            completeness_score=0.80,
            documentation_score=0.80,
            onex_compliance_score=0.80,
            metadata_richness_score=0.80,
            complexity_score=0.80,
            confidence=0.80,
            measurement_timestamp=datetime.now(UTC),
        )
        for i, pattern_id in enumerate(test_pattern_ids)
    ]

    # Measure time to insert 100 patterns
    start_time = time.time()

    for score in scores:
        await scorer.store_quality_metrics(score, db_connection_string)

    elapsed = time.time() - start_time

    # Should complete in reasonable time (< 30 seconds for 100 inserts)
    assert elapsed < 30.0, f"Bulk insert took {elapsed:.2f}s (expected < 30s)"

    # Verify all were inserted
    import psycopg2

    conn = psycopg2.connect(db_connection_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT COUNT(*) FROM pattern_quality_metrics WHERE pattern_id = ANY(%s)",
            (test_pattern_ids,),
        )
        count = cursor.fetchone()[0]

        assert count == 100, f"Expected 100 records, found {count}"

    finally:
        cursor.close()
        conn.close()
