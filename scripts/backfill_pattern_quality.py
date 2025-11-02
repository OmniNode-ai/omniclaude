#!/usr/bin/env python3
"""
Backfill Pattern Quality Metrics

One-time script to score all existing patterns in Qdrant
and populate pattern_quality_metrics table.

Usage:
    python3 scripts/backfill_pattern_quality.py --dry-run
    python3 scripts/backfill_pattern_quality.py --collection code_patterns
    python3 scripts/backfill_pattern_quality.py --limit 100
    python3 scripts/backfill_pattern_quality.py --min-confidence 0.7
    python3 scripts/backfill_pattern_quality.py --batch-size 50 --delay 1.0

Environment Variables:
    QDRANT_URL: Qdrant server URL (default: http://localhost:6333)
    QDRANT_API_KEY: Optional Qdrant API key
    DATABASE_URL: PostgreSQL connection string (default: postgresql://localhost/omniclaude)

Requirements:
    - qdrant-client: pip install qdrant-client
    - psycopg2-binary: Already installed
"""

import argparse
import asyncio
import os
import sys
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.lib.pattern_quality_scorer import PatternQualityScore, PatternQualityScorer

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Record, ScrollResult
except ImportError:
    print("Error: qdrant-client not installed")
    print("Install with: poetry install --with patterns")
    print("Or: pip install qdrant-client")
    sys.exit(1)

# Try to import tqdm for progress bar
try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("Note: tqdm not available, progress bar disabled")
    print("Install with: pip install tqdm")


class QualityStats:
    """Track quality score statistics during backfill."""

    def __init__(self):
        self.total_processed = 0
        self.total_failed = 0
        self.scores: List[float] = []
        self.dimension_scores: Dict[str, List[float]] = defaultdict(list)
        self.failed_patterns: List[Dict[str, str]] = []
        self.start_time = time.time()

    def add_score(self, score: PatternQualityScore):
        """Record a successful score."""
        self.total_processed += 1
        self.scores.append(score.composite_score)
        self.dimension_scores["completeness"].append(score.completeness_score)
        self.dimension_scores["documentation"].append(score.documentation_score)
        self.dimension_scores["onex_compliance"].append(score.onex_compliance_score)
        self.dimension_scores["metadata_richness"].append(score.metadata_richness_score)
        self.dimension_scores["complexity"].append(score.complexity_score)

    def add_failure(self, pattern_id: str, error: str):
        """Record a failed pattern."""
        self.total_failed += 1
        self.failed_patterns.append({"pattern_id": pattern_id, "error": error})

    def get_score_distribution(self) -> Dict[str, int]:
        """Calculate score distribution across quality tiers."""
        distribution = {
            "excellent": 0,  # >= 0.9
            "good": 0,  # >= 0.7
            "fair": 0,  # >= 0.5
            "poor": 0,  # < 0.5
        }

        for score in self.scores:
            if score >= PatternQualityScorer.EXCELLENT_THRESHOLD:
                distribution["excellent"] += 1
            elif score >= PatternQualityScorer.GOOD_THRESHOLD:
                distribution["good"] += 1
            elif score >= PatternQualityScorer.FAIR_THRESHOLD:
                distribution["fair"] += 1
            else:
                distribution["poor"] += 1

        return distribution

    @property
    def excellent_count(self) -> int:
        """Count of patterns with excellent scores (>= 0.9)."""
        return sum(
            1
            for score in self.scores
            if score >= PatternQualityScorer.EXCELLENT_THRESHOLD
        )

    @property
    def good_count(self) -> int:
        """Count of patterns with good scores (>= 0.7, < 0.9)."""
        return sum(
            1
            for score in self.scores
            if PatternQualityScorer.GOOD_THRESHOLD
            <= score
            < PatternQualityScorer.EXCELLENT_THRESHOLD
        )

    @property
    def fair_count(self) -> int:
        """Count of patterns with fair scores (>= 0.5, < 0.7)."""
        return sum(
            1
            for score in self.scores
            if PatternQualityScorer.FAIR_THRESHOLD
            <= score
            < PatternQualityScorer.GOOD_THRESHOLD
        )

    @property
    def poor_count(self) -> int:
        """Count of patterns with poor scores (< 0.5)."""
        return sum(
            1 for score in self.scores if score < PatternQualityScorer.FAIR_THRESHOLD
        )

    def get_average_score(self) -> float:
        """Calculate average composite score."""
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    def get_dimension_averages(self) -> Dict[str, float]:
        """Calculate average scores for each dimension."""
        return {
            dim: sum(scores) / len(scores) if scores else 0.0
            for dim, scores in self.dimension_scores.items()
        }

    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    def get_processing_rate(self) -> float:
        """Get patterns processed per second."""
        elapsed = self.get_elapsed_time()
        return self.total_processed / elapsed if elapsed > 0 else 0.0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill pattern quality metrics from Qdrant to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be done
  python3 scripts/backfill_pattern_quality.py --dry-run

  # Process only code patterns
  python3 scripts/backfill_pattern_quality.py --collection code_patterns

  # Process first 100 patterns
  python3 scripts/backfill_pattern_quality.py --limit 100

  # Process high-confidence patterns only
  python3 scripts/backfill_pattern_quality.py --min-confidence 0.8

  # Process in smaller batches
  python3 scripts/backfill_pattern_quality.py --batch-size 50
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing to database",
    )

    parser.add_argument(
        "--collection",
        type=str,
        choices=[
            "archon_vectors",
            "quality_vectors",
            "code_patterns",
            "execution_patterns",
            "all",
        ],
        default="archon_vectors",
        help="Qdrant collection to process (default: archon_vectors)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum patterns to process (default: no limit)",
    )

    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Minimum confidence threshold (default: 0.0)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Process patterns in batches (default: 100)",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between batches to prevent overwhelming system (default: 0.5)",
    )

    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant server URL (default: env QDRANT_URL or http://localhost:6333)",
    )

    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("HOST_DATABASE_URL")
        or os.getenv("DATABASE_URL", "postgresql://localhost/omniclaude"),
        help="PostgreSQL connection string (default: env HOST_DATABASE_URL, DATABASE_URL, or postgresql://localhost/omniclaude)",
    )

    return parser.parse_args(argv)


def connect_to_qdrant(url: str, api_key: Optional[str] = None) -> QdrantClient:
    """Connect to Qdrant vector database."""
    try:
        client = QdrantClient(url=url, api_key=api_key)
        # Test connection by getting collections
        collections = client.get_collections()
        print(f"✓ Connected to Qdrant at {url}")
        print(f"  Available collections: {[c.name for c in collections.collections]}")
        return client
    except Exception as e:
        print(f"✗ Failed to connect to Qdrant at {url}")
        print(f"  Error: {e}")
        sys.exit(1)


def extract_pattern_from_record(record: Record) -> Dict[str, Any]:
    """
    Extract pattern data from Qdrant record.

    Handles multiple collection types:
    - archon_vectors: has content_preview, pattern_confidence, integer IDs
    - quality_vectors: similar to archon_vectors
    - code_patterns: has code, metadata, UUID IDs
    - execution_patterns: has code, metadata, UUID IDs

    Note: For integer IDs from Qdrant, generates deterministic UUIDs using UUID v5
    """
    payload = record.payload or {}

    # Convert record ID to UUID format
    # If ID is already a UUID string, use it; otherwise generate UUID v5 from integer
    record_id_str = str(record.id)
    try:
        # Try to parse as UUID
        pattern_id = str(uuid.UUID(record_id_str))
    except ValueError:
        # Not a valid UUID, generate one using UUID v5 (name-based)
        # Use a namespace UUID for Qdrant patterns
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
        pattern_id = str(uuid.uuid5(namespace, f"qdrant-pattern-{record_id_str}"))

    # Common fields
    pattern = {
        "pattern_id": pattern_id,
        "pattern_name": payload.get("pattern_name", "unnamed_pattern"),
        # Handle different code field names
        "code": payload.get("code") or payload.get("content_preview", ""),
        # Handle different text field names
        "text": payload.get("text") or payload.get("description", ""),
        "metadata": payload.get("metadata", {}),
        # Handle different node type field names
        "node_type": payload.get("node_type")
        or (
            payload.get("node_types", [None])[0] if payload.get("node_types") else None
        ),
        "use_cases": payload.get("use_cases", []),
        "examples": payload.get("examples", []),
        # Handle different confidence field names
        "confidence": payload.get("confidence")
        or payload.get("pattern_confidence", 0.0),
    }

    return pattern


async def query_patterns(
    client: QdrantClient,
    collection_name: str,
    min_confidence: float,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Query patterns from Qdrant collection."""
    patterns = []

    try:
        # Check if collection exists
        collections = client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if collection_name not in collection_names:
            print(f"  ⚠ Collection '{collection_name}' not found")
            return patterns

        # Scroll through all patterns in collection
        offset = None
        processed_count = 0

        while True:
            # Query batch
            result: ScrollResult = client.scroll(
                collection_name=collection_name,
                limit=100,  # Scroll batch size
                offset=offset,
                with_payload=True,
                with_vectors=False,  # We don't need vectors
            )

            if not result[0]:  # No more records
                break

            # Extract patterns from records
            for record in result[0]:
                pattern = extract_pattern_from_record(record)

                # Filter by confidence
                if pattern["confidence"] >= min_confidence:
                    patterns.append(pattern)
                    processed_count += 1

                    # Check limit
                    if limit and processed_count >= limit:
                        return patterns

            # Update offset for next batch
            offset = result[1]
            if offset is None:  # No more pages
                break

        print(f"  Found {len(patterns)} patterns in '{collection_name}'")

    except Exception as e:
        print(f"  ✗ Error querying collection '{collection_name}': {e}")

    return patterns


async def score_patterns(
    patterns: List[Dict[str, Any]], stats: QualityStats, show_progress: bool = True
) -> List[PatternQualityScore]:
    """Score patterns using PatternQualityScorer."""
    scorer = PatternQualityScorer()
    scores = []

    # Create progress bar if available
    iterator = (
        tqdm(patterns, desc="Scoring patterns")
        if HAS_TQDM and show_progress
        else patterns
    )

    for pattern in iterator:
        try:
            score = scorer.score_pattern(pattern)
            scores.append(score)
            stats.add_score(score)
        except Exception as e:
            pattern_id = pattern.get("pattern_id", "unknown")
            stats.add_failure(pattern_id, str(e))

    return scores


async def store_scores_to_database(
    scores: List[PatternQualityScore],
    database_url: str,
    batch_size: int = 100,
    delay: float = 0.5,
    dry_run: bool = False,
) -> None:
    """Store quality scores in PostgreSQL with rate limiting."""
    if dry_run:
        print(f"\n[DRY RUN] Would store {len(scores)} scores to database")
        return

    scorer = PatternQualityScorer()

    # Process in batches
    for i in range(0, len(scores), batch_size):
        batch = scores[i : i + batch_size]

        for score in batch:
            try:
                await scorer.store_quality_metrics(score, database_url)
            except Exception:
                # Continue on individual failures
                pass

        # Rate limiting: delay between batches to prevent overwhelming the system
        if i + batch_size < len(scores):  # Don't delay after last batch
            await asyncio.sleep(delay)


def print_summary(stats: QualityStats, dry_run: bool = False):
    """Print comprehensive summary report."""
    print("\n" + "=" * 80)
    print("BACKFILL SUMMARY")
    print("=" * 80)

    # Overview
    print(f"\nTotal Patterns Processed: {stats.total_processed}")
    print(f"Failed Patterns: {stats.total_failed}")
    print(
        f"Success Rate: {(stats.total_processed / (stats.total_processed + stats.total_failed) * 100):.1f}%"
    )

    # Performance
    elapsed = stats.get_elapsed_time()
    rate = stats.get_processing_rate()
    print(f"\nTime Elapsed: {elapsed:.2f} seconds")
    print(f"Processing Rate: {rate:.2f} patterns/second")

    # Quality Score Distribution
    if stats.scores:
        distribution = stats.get_score_distribution()
        avg_score = stats.get_average_score()

        print(f"\nAverage Quality Score: {avg_score:.3f}")
        print("\nScore Distribution:")
        print(
            f"  Excellent (≥0.9): {distribution['excellent']:4d} ({distribution['excellent']/len(stats.scores)*100:5.1f}%)"
        )
        print(
            f"  Good      (≥0.7): {distribution['good']:4d} ({distribution['good']/len(stats.scores)*100:5.1f}%)"
        )
        print(
            f"  Fair      (≥0.5): {distribution['fair']:4d} ({distribution['fair']/len(stats.scores)*100:5.1f}%)"
        )
        print(
            f"  Poor      (<0.5): {distribution['poor']:4d} ({distribution['poor']/len(stats.scores)*100:5.1f}%)"
        )

        # Dimension averages
        dimension_avgs = stats.get_dimension_averages()
        print("\nAverage Scores by Dimension:")
        print(f"  Completeness:      {dimension_avgs.get('completeness', 0):.3f}")
        print(f"  Documentation:     {dimension_avgs.get('documentation', 0):.3f}")
        print(f"  ONEX Compliance:   {dimension_avgs.get('onex_compliance', 0):.3f}")
        print(f"  Metadata Richness: {dimension_avgs.get('metadata_richness', 0):.3f}")
        print(f"  Complexity:        {dimension_avgs.get('complexity', 0):.3f}")

    # Failed patterns
    if stats.failed_patterns:
        print(f"\nFailed Patterns ({len(stats.failed_patterns)}):")
        for failure in stats.failed_patterns[:10]:  # Show first 10
            print(f"  - {failure['pattern_id']}: {failure['error']}")
        if len(stats.failed_patterns) > 10:
            print(f"  ... and {len(stats.failed_patterns) - 10} more")

    if dry_run:
        print("\n[DRY RUN] No data was written to the database")

    print("\n" + "=" * 80)


async def backfill_pattern_quality(args: argparse.Namespace) -> int:
    """Main backfill logic."""
    print("=" * 80)
    print("PATTERN QUALITY BACKFILL")
    print("=" * 80)

    if args.dry_run:
        print("\n[DRY RUN MODE] No data will be written to database\n")

    # Initialize statistics
    stats = QualityStats()

    # Connect to Qdrant
    print("\n1. Connecting to Qdrant...")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    client = connect_to_qdrant(args.qdrant_url, qdrant_api_key)

    # Determine collections to process
    collections = []
    if args.collection == "all":
        collections = [
            "archon_vectors",
            "quality_vectors",
            "code_patterns",
            "execution_patterns",
        ]
    else:
        collections = [args.collection]

    # Query patterns from all collections
    print(f"\n2. Querying patterns (min_confidence={args.min_confidence})...")
    all_patterns = []

    for collection in collections:
        print(f"\n   Processing collection: {collection}")
        patterns = await query_patterns(
            client, collection, args.min_confidence, args.limit
        )
        all_patterns.extend(patterns)

        # Check if we've hit the limit
        if args.limit and len(all_patterns) >= args.limit:
            all_patterns = all_patterns[: args.limit]
            break

    if not all_patterns:
        print("\n✗ No patterns found matching criteria")
        return 1

    print(f"\nTotal patterns to process: {len(all_patterns)}")

    # Score patterns
    print("\n3. Scoring patterns...")
    scores = await score_patterns(all_patterns, stats, show_progress=not args.dry_run)

    print(f"\n✓ Scored {len(scores)} patterns")
    print(f"  Success: {stats.total_processed}")
    print(f"  Failed: {stats.total_failed}")

    # Store scores in database
    if scores:
        print("\n4. Storing quality metrics...")
        print(f"  Rate limiting: {args.delay}s delay between batches")
        await store_scores_to_database(
            scores,
            args.database_url,
            batch_size=args.batch_size,
            delay=args.delay,
            dry_run=args.dry_run,
        )

    # Print summary
    print_summary(stats, dry_run=args.dry_run)

    return 0


def main():
    """Entry point."""
    args = parse_args()

    try:
        exit_code = asyncio.run(backfill_pattern_quality(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
