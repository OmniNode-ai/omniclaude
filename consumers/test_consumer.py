#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Test script for Claude Session Events Kafka Consumer

This script:
1. Publishes test events to the Kafka topic (see _TEST_TOPIC)
2. Verifies the consumer processes them correctly
3. Checks database for inserted records
4. Tests health check endpoint

Usage:
    python test_consumer.py
"""

import json
import sys
import uuid
from datetime import UTC, datetime

import psycopg2
import requests
from kafka import KafkaProducer

# Import type-safe settings from omniclaude package
from omniclaude.config.settings import settings

# Use canonical topic enum instead of hardcoded string
from omniclaude.hooks.topics import TopicBase


def _get_db_dsn() -> str:
    """Get DB DSN from settings -- deferred to first use for fail-fast."""
    return settings.get_omniclaude_dsn()


def create_test_event(agent_name: str) -> dict:
    """Create a test event compatible with the claude_session_snapshots schema.

    TODO(OMN-2058): This function was updated to produce session-compatible events
    as part of DB-SPLIT-07.  The old agent_actions schema (correlation_id, agent_name,
    action_type, action_name, action_details) no longer has a backing table.  The
    fields below match claude_session_snapshots columns from migration 001.  Once a
    real Kafka consumer for session events is implemented, align this further with the
    actual event envelope used in production.
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    return {
        "session_id": session_id,
        "correlation_id": str(uuid.uuid4()),
        "status": "active",
        "started_at": now.isoformat(),
        "working_directory": f"/test/{agent_name}",
        "git_branch": "test-branch",
        "hook_source": "test_consumer",
        "prompt_count": 0,
        "tool_count": 0,
        "tools_used_count": 0,
        "event_count": 1,
        "last_event_at": now.isoformat(),
        "schema_version": "1.0.0",
    }


def publish_test_events(count: int = 10) -> list[str]:
    """
    Publish test events to Kafka.

    Returns:
        List of correlation IDs for verification
    """
    print(f"📤 Publishing {count} test events to Kafka...")

    kafka_servers = settings.get_effective_kafka_bootstrap_servers()
    if not kafka_servers:
        print("  ✗ KAFKA_BOOTSTRAP_SERVERS not configured. Set it in .env.")
        sys.exit(1)

    producer = KafkaProducer(
        bootstrap_servers=kafka_servers.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    correlation_ids = []

    for i in range(count):
        event = create_test_event(
            agent_name=f"test-agent-{i % 3}",
        )

        correlation_ids.append(event["correlation_id"])

        producer.send(TopicBase.AGENT_ACTIONS, value=event)
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

    conn = psycopg2.connect(_get_db_dsn())
    cursor = conn.cursor()

    # TODO(OMN-2058): This test consumer was written for the old agent_actions
    # table which no longer exists. The test events produced by create_test_event()
    # are 'agent_actions' type events that are NOT written to claude_session_snapshots.
    # This verification will always find 0 records and time out.
    # Update this function to match the new schema (claude_sessions /
    # claude_session_snapshots) once a consumer for the new schema is implemented.
    print(
        "  [SKIP] verify_database_records queries the wrong table (see TODO OMN-2058). "
        "Skipping 30s polling loop until schema is updated.\n"
    )
    cursor.close()
    conn.close()
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


def query_recent_sessions():
    """Query recent session snapshots with prompt and tool counts."""
    print("📋 Querying recent session snapshots...")

    conn = psycopg2.connect(_get_db_dsn())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            session_id,
            status,
            prompt_count,
            tool_count,
            event_count,
            duration_seconds,
            last_event_at
        FROM claude_session_snapshots
        ORDER BY last_event_at DESC
        LIMIT 5
        """
    )

    rows = cursor.fetchall()

    if rows:
        print("✅ Recent sessions:")
        for row in rows:
            session_id, status, prompts, tools, events, duration, _last_event = row
            duration_str = f"{duration}s" if duration is not None else "ongoing"
            print(
                f"  - {session_id[:12]}... [{status}]: {prompts} prompts, {tools} tools, {events} events ({duration_str})"
            )
        print()
    else:
        print("  No sessions found\n")

    cursor.close()
    conn.close()


def run_tests():
    """Run all tests."""
    print("=" * 70)
    print("Claude Session Events Kafka Consumer - Test Suite")
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

    # Step 5: Query recent sessions
    print("Step 5: Query recent sessions")
    print("-" * 70)
    query_recent_sessions()

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
