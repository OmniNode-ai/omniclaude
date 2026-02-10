#!/usr/bin/env python3
"""Demo script: Consume hook events and store patterns.

Part of VERTICAL-001 (OMN-1802): Validates the consume and store phases.

This script consumes Claude Code hook events from Kafka and writes
patterns directly to the learned_patterns PostgreSQL table.

Consumes from:
    onex.cmd.omniintelligence.claude-hook-event.v1

Stores to:
    learned_patterns table in omninode_bridge database

Usage:
    # Ensure environment is configured
    source .env

    # Run consumer (Ctrl+C to stop)
    python plugins/onex/scripts/demo_consume_store.py

    # Process single batch and exit
    python plugins/onex/scripts/demo_consume_store.py --once

Environment Variables (all required - source .env first):
    KAFKA_BOOTSTRAP_SERVERS: Kafka brokers (required)
    POSTGRES_HOST: Database host (required)
    POSTGRES_PORT: Database port (required)
    POSTGRES_DATABASE: Database name (required)
    POSTGRES_USER: Database user (required)
    POSTGRES_PASSWORD: Database password (required)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

import psycopg2
from kafka import KafkaConsumer

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

# Add src to path for imports
SRC_DIR = Path(__file__).parent.parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from omniclaude.hooks.topics import TopicBase, build_topic

# Maximum number of session IDs to store per pattern
MAX_SESSION_IDS_PER_PATTERN = 100

# Shutdown event for graceful termination
shutdown_event = Event()


def signal_handler(signum, frame) -> None:
    """Handle shutdown signals."""
    print(f"\n[INFO] Received signal {signum}, shutting down...")
    shutdown_event.set()


def print_banner() -> None:
    """Print demo banner."""
    print("=" * 70)
    print("VERTICAL-001 Demo: Consume and Store Patterns")
    print("=" * 70)
    print()


def get_kafka_config() -> dict:
    """Get Kafka configuration from environment."""
    kafka_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not kafka_servers:
        print("[ERROR] KAFKA_BOOTSTRAP_SERVERS environment variable required")
        print("  Run: source .env")
        sys.exit(1)

    # Topics are realm-agnostic (OMN-1972): no environment prefix
    topic = build_topic("", TopicBase.CLAUDE_HOOK_EVENT)

    # Generate unique group ID per run for test isolation
    unique_suffix = uuid.uuid4().hex[:8]

    return {
        "bootstrap_servers": kafka_servers.split(","),
        "topic": topic,
        "group_id": f"demo-vertical-001-consumer-{unique_suffix}",
    }


def get_postgres_config() -> dict:
    """Get PostgreSQL configuration from environment."""
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
        print("  Run: source .env")
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


def print_config(kafka_config: dict, postgres_config: dict) -> None:
    """Print current configuration."""
    print("Kafka Configuration:")
    print(f"  Brokers:  {kafka_config['bootstrap_servers']}")
    print(f"  Topic:    {kafka_config['topic']}")
    print(f"  Group:    {kafka_config['group_id']}")
    print()
    print("PostgreSQL Configuration:")
    print(f"  Host:     {postgres_config['host']}:{postgres_config['port']}")
    print(f"  Database: {postgres_config['database']}")
    print(f"  User:     {postgres_config['user']}")
    print()


def has_keyword(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears as a whole word in text.

    Uses word boundaries to avoid false positives like 'test' matching 'contest'.

    Args:
        text: The text to search in.
        keywords: List of keywords to search for.

    Returns:
        True if any keyword is found as a whole word, False otherwise.
    """
    pattern = r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def extract_pattern_from_event(event: dict) -> dict | None:
    """Extract pattern information from a hook event.

    For the demo, we derive a pattern from the prompt content.
    In production, this would use intelligence processing.

    Args:
        event: Parsed hook event from Kafka.

    Returns:
        Pattern dict ready for database insertion, or None if invalid.
    """
    # Get prompt from payload
    payload = event.get("payload", {})
    prompt = payload.get("prompt")

    if not prompt:
        return None

    # Generate pattern_signature from prompt (first 500 chars)
    pattern_signature = prompt[:500]

    # Generate signature_hash using SHA256
    signature_hash = hashlib.sha256(pattern_signature.encode()).hexdigest()

    # Derive domain_id from prompt keywords (simple heuristic)
    # Valid domain_id values: architecture, code_generation, code_review,
    # data_analysis, debugging, devops, documentation, general, refactoring, testing
    # Uses word boundary matching to avoid false positives (e.g., 'test' in 'contest')
    if has_keyword(prompt, ["test", "pytest", "unittest"]):
        domain_id = "testing"
    elif has_keyword(prompt, ["review", "pr", "code review"]):
        domain_id = "code_review"
    elif has_keyword(prompt, ["debug", "error", "fix", "bug"]):
        domain_id = "debugging"
    elif has_keyword(prompt, ["refactor", "clean", "improve"]):
        domain_id = "refactoring"
    elif has_keyword(prompt, ["doc", "readme", "comment"]):
        domain_id = "documentation"
    elif has_keyword(prompt, ["deploy", "ci", "docker", "kubernetes"]):
        domain_id = "devops"
    elif has_keyword(prompt, ["api", "endpoint", "design", "architect"]):
        domain_id = "architecture"
    elif has_keyword(prompt, ["generate", "create", "implement"]):
        domain_id = "code_generation"
    else:
        domain_id = "general"

    # Parse session_id as UUID for source_session_ids array
    session_id_str = event.get("session_id", "")
    try:
        session_uuid = uuid.UUID(session_id_str)
        source_session_ids = [session_uuid]
    except (ValueError, TypeError):
        # Generate a random UUID if session_id is invalid
        fallback_uuid = uuid.uuid4()
        print(
            f"[WARN] Invalid session_id '{session_id_str}', using fallback UUID: {fallback_uuid}"
        )
        source_session_ids = [fallback_uuid]

    return {
        "pattern_signature": pattern_signature,
        "signature_hash": signature_hash,
        "domain_id": domain_id,
        "domain_version": "1.0",
        "confidence": 0.5,  # Minimum allowed confidence
        "status": "candidate",
        "source_session_ids": source_session_ids,
        "recurrence_count": 1,
        "is_current": True,
        "version": 1,
    }


def upsert_pattern(conn: PgConnection, pattern: dict[str, Any]) -> str:
    """Upsert pattern into learned_patterns table.

    Args:
        conn: PostgreSQL connection.
        pattern: Pattern dict to upsert.

    Returns:
        "insert" or "update" indicating operation type.
    """
    # Convert UUID list to PostgreSQL array format
    session_ids_array = [str(sid) for sid in pattern["source_session_ids"]]

    sql = f"""
        INSERT INTO learned_patterns (
            pattern_signature, signature_hash, domain_id, domain_version,
            confidence, status, source_session_ids, recurrence_count,
            is_current, version
        ) VALUES (%s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s)
        ON CONFLICT (pattern_signature, domain_id) WHERE is_current = true
        DO UPDATE SET
            recurrence_count = learned_patterns.recurrence_count + 1,
            last_seen_at = now(),
            source_session_ids = (
                SELECT ARRAY(SELECT DISTINCT unnest(array_cat(
                    learned_patterns.source_session_ids,
                    EXCLUDED.source_session_ids
                )) LIMIT {MAX_SESSION_IDS_PER_PATTERN})
            )
        RETURNING (xmax = 0) as inserted
    """  # nosec B608

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                pattern["pattern_signature"],
                pattern["signature_hash"],
                pattern["domain_id"],
                pattern["domain_version"],
                pattern["confidence"],
                pattern["status"],
                session_ids_array,
                pattern["recurrence_count"],
                pattern["is_current"],
                pattern["version"],
            ),
        )
        result = cursor.fetchone()
        conn.commit()

    return "insert" if result[0] else "update"


def consume_and_store(
    kafka_config: dict, postgres_config: dict, once: bool = False
) -> int:
    """Main consume and store loop.

    Args:
        kafka_config: Kafka connection configuration.
        postgres_config: PostgreSQL connection configuration.
        once: If True, process one batch and exit.

    Returns:
        Number of patterns stored.
    """
    # Initialize for cleanup safety
    conn = None
    consumer = None

    # Connect to PostgreSQL
    print("[INFO] Connecting to PostgreSQL...")
    conn = psycopg2.connect(**postgres_config)
    print("[OK] PostgreSQL connected")
    print()

    # Create Kafka consumer
    print("[INFO] Connecting to Kafka...")
    consumer = KafkaConsumer(
        kafka_config["topic"],
        bootstrap_servers=kafka_config["bootstrap_servers"],
        group_id=kafka_config["group_id"],
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=5000 if once else 1000,
    )
    print(f"[OK] Kafka consumer connected, subscribed to {kafka_config['topic']}")
    print()

    if once:
        print("[INFO] Running in single-batch mode (--once)")
    else:
        print("[INFO] Running in continuous mode (Ctrl+C to stop)")
    print()

    patterns_stored = 0
    events_processed = 0
    start_time = time.time()

    try:
        while not shutdown_event.is_set():
            # Poll for messages
            messages = consumer.poll(timeout_ms=1000)

            for topic_partition, msgs in messages.items():
                for msg in msgs:
                    events_processed += 1
                    event = msg.value

                    # Extract pattern from event
                    pattern = extract_pattern_from_event(event)
                    if pattern:
                        operation = upsert_pattern(conn, pattern)
                        patterns_stored += 1

                        # Truncate pattern_signature for display
                        sig_preview = pattern["pattern_signature"][:60]
                        if len(pattern["pattern_signature"]) > 60:
                            sig_preview += "..."
                        print(
                            f'[{operation.upper()}] Pattern: "{sig_preview}"'
                            f" (domain={pattern['domain_id']})"
                        )

            # Check if we should exit (single batch mode)
            if once and events_processed > 0:
                break

            # Timeout check for single batch mode
            if once and (time.time() - start_time) > 10:
                print("[INFO] Timeout waiting for messages in single-batch mode")
                break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    finally:
        print()
        print(f"[SUMMARY] Events processed: {events_processed}")
        print(f"[SUMMARY] Patterns stored:  {patterns_stored}")
        print()

        # Cleanup (check if initialized to handle early failures)
        if consumer is not None:
            consumer.close()
        if conn is not None:
            conn.close()
        print("[OK] Connections closed")

    return patterns_stored


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Consume hook events and store patterns (VERTICAL-001 demo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch and exit (default: run continuously)",
    )

    args = parser.parse_args()

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print_banner()

    # Get configuration
    kafka_config = get_kafka_config()
    postgres_config = get_postgres_config()
    print_config(kafka_config, postgres_config)

    # Run consume and store
    patterns_stored = consume_and_store(kafka_config, postgres_config, once=args.once)

    print()
    print("=" * 70)
    if patterns_stored > 0:
        print("Demo step 2/3 complete: Patterns stored in PostgreSQL")
        print()
        print("Next step:")
        print("  Query patterns: python plugins/onex/scripts/demo_query_patterns.py")
    else:
        print("Demo step 2/3: No patterns stored (no events in topic?)")
        print()
        print("Troubleshooting:")
        print("  1. Run emit first: python plugins/onex/scripts/demo_emit_hook.py")
        print("  2. Check topic has messages: kcat -L -b $KAFKA_BOOTSTRAP_SERVERS")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
