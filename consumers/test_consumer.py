#!/usr/bin/env python3
"""
Test script for Agent Actions Kafka Consumer

This script:
1. Publishes test events to the agent-actions topic
2. Verifies the consumer processes them correctly
3. Checks database for inserted records
4. Tests health check endpoint

Usage:
    python test_consumer.py
"""

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import requests
from kafka import KafkaProducer

# Add config for type-safe settings
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings

# Add _shared to path
SCRIPT_DIR = Path(__file__).parent
SHARED_DIR = SCRIPT_DIR.parent / "skills" / "_shared"
sys.path.insert(0, str(SHARED_DIR))

# Database configuration
DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", settings.postgres_host or "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", settings.postgres_port or 5436)),
    "database": os.environ.get(
        "POSTGRES_DATABASE", settings.postgres_database or "omniclaude"
    ),
    "user": os.environ.get("POSTGRES_USER", settings.postgres_user or "postgres"),
    "password": settings.get_effective_postgres_password(),
}


def create_test_event(agent_name: str, action_type: str = "tool_call") -> dict:
    """Create a test agent action event."""
    return {
        "correlation_id": str(uuid.uuid4()),
        "agent_name": agent_name,
        "action_type": action_type,
        "action_name": f"Test{action_type.title()}",
        "action_details": {
            "test": True,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "debug_mode": True,
        "duration_ms": 42,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def publish_test_events(count: int = 10) -> list[str]:
    """
    Publish test events to Kafka.

    Returns:
        List of correlation IDs for verification
    """
    print(f"📤 Publishing {count} test events to Kafka...")

    producer = KafkaProducer(
        bootstrap_servers=os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        ).split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    correlation_ids = []

    for i in range(count):
        event = create_test_event(
            agent_name=f"test-agent-{i % 3}",
            action_type=["tool_call", "decision", "success"][i % 3],
        )

        correlation_ids.append(event["correlation_id"])

        producer.send("agent-actions", value=event)
        print(f"  ✓ Event {i + 1}/{count}: {event['correlation_id']}")

    producer.flush()
    producer.close()

    print(f"✅ Published {count} events successfully\n")
    return correlation_ids


def verify_database_records(correlation_ids: list[str], timeout: int = 30):
    """
    Verify events were inserted into PostgreSQL.

    Args:
        correlation_ids: List of correlation IDs to check
        timeout: Max seconds to wait for records
    """
    print(f"🔍 Verifying {len(correlation_ids)} records in database...")

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    start_time = time.time()
    found_count = 0

    while time.time() - start_time < timeout:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM agent_actions
            WHERE correlation_id = ANY(%s)
            """,
            (correlation_ids,),
        )

        found_count = cursor.fetchone()[0]

        if found_count == len(correlation_ids):
            print(f"✅ All {found_count} records found in database!\n")
            cursor.close()
            conn.close()
            return True

        print(f"  ⏳ Found {found_count}/{len(correlation_ids)}, waiting...")
        time.sleep(2)

    cursor.close()
    conn.close()

    print(
        f"❌ Only found {found_count}/{len(correlation_ids)} records after {timeout}s\n"
    )
    return False


def check_health_endpoint():
    """Check consumer health endpoint."""
    print("🏥 Checking health endpoint...")

    try:
        response = requests.get("http://localhost:8080/health", timeout=5)

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health check passed: {data}\n")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}\n")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Health check error: {e}\n")
        return False


def check_metrics_endpoint():
    """Check consumer metrics endpoint."""
    print("📊 Checking metrics endpoint...")

    try:
        response = requests.get("http://localhost:8080/metrics", timeout=5)

        if response.status_code == 200:
            metrics = response.json()
            print("✅ Metrics retrieved:")
            print(f"  - Uptime: {metrics.get('uptime_seconds', 0):.1f}s")
            print(f"  - Messages consumed: {metrics.get('messages_consumed', 0)}")
            print(f"  - Messages inserted: {metrics.get('messages_inserted', 0)}")
            print(f"  - Messages failed: {metrics.get('messages_failed', 0)}")
            print(f"  - Batches processed: {metrics.get('batches_processed', 0)}")
            print(
                f"  - Avg batch time: {metrics.get('avg_batch_processing_ms', 0):.2f}ms"
            )
            print(f"  - Messages/sec: {metrics.get('messages_per_second', 0):.2f}\n")
            return True
        else:
            print(f"❌ Metrics check failed: {response.status_code}\n")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Metrics check error: {e}\n")
        return False


def query_recent_traces():
    """Query recent debug traces view."""
    print("📋 Querying recent debug traces...")

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            correlation_id,
            agent_name,
            action_count,
            error_count,
            success_count,
            total_duration_ms
        FROM recent_debug_traces
        LIMIT 5
        """
    )

    rows = cursor.fetchall()

    if rows:
        print("✅ Recent traces:")
        for row in rows:
            _corr_id, agent, actions, errors, successes, duration = row
            print(
                f"  - {agent}: {actions} actions, {errors} errors, {successes} successes ({duration:.1f}ms)"
            )
        print()
    else:
        print("  No traces found\n")

    cursor.close()
    conn.close()


def run_tests():
    """Run all tests."""
    print("=" * 70)
    print("Agent Actions Kafka Consumer - Test Suite")
    print("=" * 70)
    print()

    # Step 1: Check health endpoint (consumer should be running)
    print("Step 1: Pre-flight checks")
    print("-" * 70)
    health_ok = check_health_endpoint()

    if not health_ok:
        print("⚠️  Consumer may not be running. Start it with:")
        print("    python agent_actions_consumer.py")
        print()
        print("Continuing with tests...\n")

    # Step 2: Publish test events
    print("Step 2: Publish test events")
    print("-" * 70)
    correlation_ids = publish_test_events(count=15)

    # Step 3: Verify database records
    print("Step 3: Verify database persistence")
    print("-" * 70)
    db_ok = verify_database_records(correlation_ids, timeout=30)

    # Step 4: Check metrics
    print("Step 4: Check consumer metrics")
    print("-" * 70)
    metrics_ok = check_metrics_endpoint()

    # Step 5: Query recent traces
    print("Step 5: Query recent traces")
    print("-" * 70)
    query_recent_traces()

    # Summary
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Health Check:     {'✅ PASS' if health_ok else '⚠️  WARN'}")
    print("Event Publishing: ✅ PASS")
    print(f"Database Insert:  {'✅ PASS' if db_ok else '❌ FAIL'}")
    print(f"Metrics:          {'✅ PASS' if metrics_ok else '⚠️  WARN'}")
    print()

    if db_ok and (health_ok or metrics_ok):
        print("🎉 All critical tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. Check consumer logs.")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
