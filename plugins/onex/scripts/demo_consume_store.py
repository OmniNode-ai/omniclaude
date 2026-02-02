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

Environment Variables:
    KAFKA_BOOTSTRAP_SERVERS: Kafka brokers (default: 192.168.86.200:29092)
    KAFKA_ENVIRONMENT: Topic prefix (default: dev)
    POSTGRES_HOST: Database host (default: 192.168.86.200)
    POSTGRES_PORT: Database port (default: 5436)
    POSTGRES_DATABASE: Database name (default: omninode_bridge)
    POSTGRES_USER: Database user (default: postgres)
    POSTGRES_PASSWORD: Database password (required)
"""

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from threading import Event

import psycopg2
from kafka import KafkaConsumer

# Add src to path for imports
SRC_DIR = Path(__file__).parent.parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from omniclaude.hooks.topics import TopicBase, build_topic

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
    kafka_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")
    kafka_env = os.environ.get("KAFKA_ENVIRONMENT", "dev")
    topic = build_topic(kafka_env, TopicBase.CLAUDE_HOOK_EVENT)

    return {
        "bootstrap_servers": kafka_servers.split(","),
        "topic": topic,
        "group_id": "demo-vertical-001-consumer",
    }


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

    # Generate pattern_id from prompt hash
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    pattern_id = f"demo-{prompt_hash}"

    # Derive domain from prompt keywords (simple heuristic)
    prompt_lower = prompt.lower()
    if any(kw in prompt_lower for kw in ["test", "pytest", "unittest"]):
        domain = "testing"
    elif any(kw in prompt_lower for kw in ["review", "pr", "code review"]):
        domain = "code_review"
    elif any(kw in prompt_lower for kw in ["debug", "error", "fix"]):
        domain = "debugging"
    else:
        domain = "general"

    # Extract title from first line or first 50 chars
    title = prompt.split("\n")[0][:100] if "\n" in prompt else prompt[:100]

    return {
        "pattern_id": pattern_id,
        "domain": domain,
        "title": title,
        "description": prompt[:500],  # Truncate for storage
        "confidence": 0.7,  # Default confidence for demo patterns
        "usage_count": 1,
        "success_rate": 1.0,
        "example_reference": f"session:{event.get('session_id', 'unknown')}",
    }


def upsert_pattern(conn, pattern: dict) -> str:
    """Upsert pattern into learned_patterns table.

    Args:
        conn: PostgreSQL connection.
        pattern: Pattern dict to upsert.

    Returns:
        "insert" or "update" indicating operation type.
    """
    sql = """
        INSERT INTO learned_patterns (
            pattern_id, domain, title, description, confidence,
            usage_count, success_rate, example_reference
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (pattern_id) DO UPDATE SET
            domain = EXCLUDED.domain,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            confidence = EXCLUDED.confidence,
            usage_count = learned_patterns.usage_count + 1,
            success_rate = EXCLUDED.success_rate,
            example_reference = EXCLUDED.example_reference
        RETURNING (xmax = 0) as inserted
    """

    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            (
                pattern["pattern_id"],
                pattern["domain"],
                pattern["title"],
                pattern["description"],
                pattern["confidence"],
                pattern["usage_count"],
                pattern["success_rate"],
                pattern["example_reference"],
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

                        print(
                            f"[{operation.upper()}] Pattern: {pattern['pattern_id']}"
                            f" (domain={pattern['domain']})"
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

        # Cleanup
        consumer.close()
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
        print("  2. Check topic has messages: kcat -L -b 192.168.86.200:29092")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
