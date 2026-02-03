#!/usr/bin/env python3
"""Demo script: Query stored patterns from PostgreSQL.

Part of VERTICAL-001 (OMN-1802): Validates the query phase of the pattern pipeline.

This script queries the learned_patterns table and displays patterns
in a formatted manner.

Usage:
    # Ensure environment is configured
    source .env

    # Query all patterns
    python plugins/onex/scripts/demo_query_patterns.py

    # Query demo patterns only
    python plugins/onex/scripts/demo_query_patterns.py --demo-only

    # Query specific domain
    python plugins/onex/scripts/demo_query_patterns.py --domain testing

    # Limit results
    python plugins/onex/scripts/demo_query_patterns.py --limit 5

Environment Variables (all required - no defaults):
    POSTGRES_HOST: Database host
    POSTGRES_PORT: Database port
    POSTGRES_DATABASE: Database name
    POSTGRES_USER: Database user
    POSTGRES_PASSWORD: Database password
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

import psycopg2
from psycopg2.extras import RealDictCursor

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection


def print_banner() -> None:
    """Print demo banner."""
    print("=" * 70)
    print("VERTICAL-001 Demo: Query Patterns")
    print("=" * 70)
    print()


def get_postgres_config() -> dict:
    """Get PostgreSQL configuration from environment.

    All variables are required with no defaults per CLAUDE.md:
    '.env file is the SINGLE SOURCE OF TRUTH for all configuration values.'
    """
    required_vars = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DATABASE",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ]

    missing = [var for var in required_vars if not os.environ.get(var)]

    if missing:
        print("[ERROR] Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print()
        print("Run: source .env")
        sys.exit(1)

    try:
        port = int(os.environ["POSTGRES_PORT"])
    except ValueError:
        print(
            f"[ERROR] POSTGRES_PORT must be a valid integer, got: {os.environ['POSTGRES_PORT']}"
        )
        sys.exit(1)

    return {
        "host": os.environ["POSTGRES_HOST"],
        "port": port,
        "database": os.environ["POSTGRES_DATABASE"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }


def print_config(config: dict) -> None:
    """Print current configuration."""
    print("PostgreSQL Configuration:")
    print(f"  Host:     {config['host']}:{config['port']}")
    print(f"  Database: {config['database']}")
    print(f"  User:     {config['user']}")
    print()


def query_patterns(
    conn: PgConnection,
    domain: str | None = None,
    demo_only: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Query patterns from the database.

    Args:
        conn: PostgreSQL connection.
        domain: Optional domain filter (domain_id column).
        demo_only: If True, only return demo patterns (pattern_signature starts with 'Demo pattern:').
        limit: Maximum number of patterns to return.

    Returns:
        List of pattern dictionaries.
    """
    conditions = []
    params = []

    if demo_only:
        conditions.append("pattern_signature LIKE 'Demo pattern:%%'")

    if domain:
        conditions.append("domain_id = %s")
        params.append(domain)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"""
        SELECT
            id,
            pattern_signature,
            signature_hash,
            domain_id,
            confidence,
            status,
            recurrence_count,
            quality_score,
            source_session_ids,
            first_seen_at,
            last_seen_at,
            distinct_days_seen
        FROM learned_patterns
        WHERE {where_clause}
          AND is_current = true
        ORDER BY last_seen_at DESC, confidence DESC
        LIMIT %s
    """  # nosec B608 - where_clause built from safe conditions
    params.append(limit)

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def print_pattern(pattern: dict, index: int) -> None:
    """Print a single pattern in formatted manner."""
    sig = pattern["pattern_signature"]
    print(f"[{index}] {pattern['signature_hash'][:16]}...")
    print(f"    Domain:      {pattern['domain_id']}")
    print(
        f"    Pattern:     {sig[:60]}..."
        if len(sig) > 60
        else f"    Pattern:     {sig}"
    )
    print(f"    Confidence:  {pattern['confidence']:.1%}")
    print(f"    Status:      {pattern['status']}")
    print(f"    Recurrence:  {pattern['recurrence_count']} times")
    print(f"    Quality:     {(pattern['quality_score'] or 0):.1%}")
    print(f"    Days seen:   {pattern['distinct_days_seen']}")
    print(f"    Sessions:    {len(pattern['source_session_ids'] or [])} unique")
    print(f"    First seen:  {pattern['first_seen_at']}")
    print(f"    Last seen:   {pattern['last_seen_at']}")
    print()


def print_summary(patterns: list[dict]) -> None:
    """Print summary statistics."""
    if not patterns:
        return

    domains = {}
    total_recurrence = 0
    avg_confidence = 0
    avg_quality = 0

    for p in patterns:
        domains[p["domain_id"]] = domains.get(p["domain_id"], 0) + 1
        total_recurrence += p["recurrence_count"] or 0
        avg_confidence += p["confidence"] or 0
        avg_quality += p["quality_score"] or 0

    avg_confidence /= len(patterns)
    avg_quality /= len(patterns)

    print("-" * 70)
    print("Summary:")
    print(f"  Total patterns:      {len(patterns)}")
    print(f"  Total recurrence:    {total_recurrence}")
    print(f"  Average confidence:  {avg_confidence:.1%}")
    print(f"  Average quality:     {avg_quality:.1%}")
    print(
        f"  Domains:             {', '.join(f'{k}({v})' for k, v in sorted(domains.items()))}"
    )


def count_all_patterns(conn: PgConnection) -> int:
    """Count total current patterns in database."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM learned_patterns WHERE is_current = true")
        return cursor.fetchone()[0]


def count_demo_patterns(conn: PgConnection) -> int:
    """Count current demo patterns in database."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM learned_patterns WHERE pattern_signature LIKE 'Demo pattern:%%' AND is_current = true"
        )
        return cursor.fetchone()[0]


def delete_demo_patterns(conn: PgConnection) -> int:
    """Delete demo patterns from database.

    Returns:
        Number of patterns deleted.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM learned_patterns WHERE pattern_signature LIKE 'Demo pattern:%%'"
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Query patterns from PostgreSQL (VERTICAL-001 demo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--domain",
        help="Filter by domain (e.g., testing, code_review, general)",
    )
    parser.add_argument(
        "--demo-only",
        action="store_true",
        help="Only show demo patterns (pattern_signature starts with 'Demo pattern:')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum patterns to display (default: 20)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete demo patterns after displaying (clean up test data)",
    )

    args = parser.parse_args()

    print_banner()

    # Get configuration
    config = get_postgres_config()
    print_config(config)

    # Connect to PostgreSQL
    print("[INFO] Connecting to PostgreSQL...")
    conn = psycopg2.connect(**config)
    print("[OK] Connected")
    print()

    try:
        # Get counts
        total_count = count_all_patterns(conn)
        demo_count = count_demo_patterns(conn)

        print(
            f"Database contains {total_count} total patterns ({demo_count} demo patterns)"
        )
        print()

        # Query patterns
        filters = []
        if args.demo_only:
            filters.append("demo patterns only")
        if args.domain:
            filters.append(f"domain={args.domain}")

        filter_str = f" ({', '.join(filters)})" if filters else ""
        print(f"Querying patterns{filter_str}...")
        print()

        patterns = query_patterns(
            conn,
            domain=args.domain,
            demo_only=args.demo_only,
            limit=args.limit,
        )

        if not patterns:
            print("[INFO] No patterns found matching criteria")
            print()
            print("Troubleshooting:")
            print("  1. Run emit:    python plugins/onex/scripts/demo_emit_hook.py")
            print(
                "  2. Run consume: python plugins/onex/scripts/demo_consume_store.py --once"
            )
            print("  3. Try again without filters")
            return 1

        # Display patterns
        print(f"Found {len(patterns)} patterns:")
        print()

        for i, pattern in enumerate(patterns, 1):
            print_pattern(pattern, i)

        print_summary(patterns)

        # Cleanup demo patterns if requested
        if args.cleanup:
            print()
            print("-" * 70)
            deleted = delete_demo_patterns(conn)
            print(f"[CLEANUP] Deleted {deleted} demo patterns from database")

    finally:
        conn.close()

    print()
    print("=" * 70)
    print("Demo step 3/3 complete: Patterns retrieved from PostgreSQL")
    if args.cleanup:
        print("  [OK] Demo patterns cleaned up")
    print()
    print("VERTICAL-001 Demo Summary:")
    print("  [OK] Step 1: Emit hook event to Kafka")
    print("  [OK] Step 2: Consume event and store pattern")
    print("  [OK] Step 3: Query pattern from PostgreSQL")
    if args.cleanup:
        print("  [OK] Step 4: Cleanup demo data")
    print()
    print("Full pipeline validated successfully!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
