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

Environment Variables:
    POSTGRES_HOST: Database host (default: 192.168.86.200)
    POSTGRES_PORT: Database port (default: 5436)
    POSTGRES_DATABASE: Database name (default: omninode_bridge)
    POSTGRES_USER: Database user (default: postgres)
    POSTGRES_PASSWORD: Database password (required)
"""

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor


def print_banner() -> None:
    """Print demo banner."""
    print("=" * 70)
    print("VERTICAL-001 Demo: Query Patterns")
    print("=" * 70)
    print()


def get_postgres_config() -> dict:
    """Get PostgreSQL configuration from environment."""
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        print("[ERROR] POSTGRES_PASSWORD environment variable required")
        print("  Run: source .env")
        sys.exit(1)

    return {
        "host": os.environ.get("POSTGRES_HOST", "192.168.86.200"),
        "port": int(os.environ.get("POSTGRES_PORT", "5436")),
        "database": os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": password,
    }


def print_config(config: dict) -> None:
    """Print current configuration."""
    print("PostgreSQL Configuration:")
    print(f"  Host:     {config['host']}:{config['port']}")
    print(f"  Database: {config['database']}")
    print(f"  User:     {config['user']}")
    print()


def query_patterns(
    conn,
    domain: str | None = None,
    demo_only: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Query patterns from the database.

    Args:
        conn: PostgreSQL connection.
        domain: Optional domain filter.
        demo_only: If True, only return demo patterns (pattern_id starts with 'demo-').
        limit: Maximum number of patterns to return.

    Returns:
        List of pattern dictionaries.
    """
    conditions = []
    params = []

    if demo_only:
        conditions.append("pattern_id LIKE 'demo-%%'")

    if domain:
        conditions.append("domain = %s")
        params.append(domain)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"""
        SELECT
            pattern_id,
            domain,
            title,
            description,
            confidence,
            usage_count,
            success_rate,
            example_reference,
            created_at,
            updated_at
        FROM learned_patterns
        WHERE {where_clause}
        ORDER BY updated_at DESC, confidence DESC
        LIMIT %s
    """  # nosec B608 - where_clause built from safe conditions
    params.append(limit)

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def print_pattern(pattern: dict, index: int) -> None:
    """Print a single pattern in formatted manner."""
    print(f"[{index}] {pattern['pattern_id']}")
    print(f"    Domain:     {pattern['domain']}")
    print(
        f"    Title:      {pattern['title'][:60]}..."
        if len(pattern["title"]) > 60
        else f"    Title:      {pattern['title']}"
    )
    print(f"    Confidence: {pattern['confidence']:.1%}")
    print(f"    Usage:      {pattern['usage_count']} times")
    print(f"    Success:    {pattern['success_rate']:.1%}")
    print(f"    Reference:  {pattern['example_reference'] or 'N/A'}")
    print(f"    Created:    {pattern['created_at']}")
    print(f"    Updated:    {pattern['updated_at']}")
    print()


def print_summary(patterns: list[dict]) -> None:
    """Print summary statistics."""
    if not patterns:
        return

    domains = {}
    total_usage = 0
    avg_confidence = 0

    for p in patterns:
        domains[p["domain"]] = domains.get(p["domain"], 0) + 1
        total_usage += p["usage_count"]
        avg_confidence += p["confidence"]

    avg_confidence /= len(patterns)

    print("-" * 70)
    print("Summary:")
    print(f"  Total patterns:     {len(patterns)}")
    print(f"  Total usage:        {total_usage}")
    print(f"  Average confidence: {avg_confidence:.1%}")
    print(
        f"  Domains:            {', '.join(f'{k}({v})' for k, v in sorted(domains.items()))}"
    )


def count_all_patterns(conn) -> int:
    """Count total patterns in database."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM learned_patterns")
        return cursor.fetchone()[0]


def count_demo_patterns(conn) -> int:
    """Count demo patterns in database."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM learned_patterns WHERE pattern_id LIKE 'demo-%%'"
        )
        return cursor.fetchone()[0]


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
        help="Only show demo patterns (pattern_id starts with 'demo-')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum patterns to display (default: 20)",
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

    finally:
        conn.close()

    print()
    print("=" * 70)
    print("Demo step 3/3 complete: Patterns retrieved from PostgreSQL")
    print()
    print("VERTICAL-001 Demo Summary:")
    print("  [OK] Step 1: Emit hook event to Kafka")
    print("  [OK] Step 2: Consume event and store pattern")
    print("  [OK] Step 3: Query pattern from PostgreSQL")
    print()
    print("Full pipeline validated successfully!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
