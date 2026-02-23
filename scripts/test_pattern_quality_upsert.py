#!/usr/bin/env python3
"""
Test pattern quality upsert to reproduce ON CONFLICT error.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.lib.pattern_quality_scorer import PatternQualityScore, PatternQualityScorer

from config import settings


async def test_upsert():
    """Test storing a pattern quality score."""

    # Create a test score
    score = PatternQualityScore(
        pattern_id="123e4567-e89b-12d3-a456-426614174001",  # Valid UUID
        pattern_name="test_pattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
        version="1.0.0",
    )

    # Database connection string from Pydantic settings
    database_url = settings.get_postgres_dsn()
    print(f"Using database URL: {database_url}")

    # Store the score
    scorer = PatternQualityScorer()

    try:
        print(f"Storing pattern quality score for pattern_id: {score.pattern_id}")
        await scorer.store_quality_metrics(score, database_url)
        print("✓ Successfully stored quality metrics (first insert)")

        # Try again to test upsert
        score.composite_score = 0.95
        await scorer.store_quality_metrics(score, database_url)
        print("✓ Successfully updated quality metrics (upsert)")

    except Exception as e:
        print(f"✗ Failed to store quality metrics: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(test_upsert())
    sys.exit(exit_code)
