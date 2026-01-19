#!/usr/bin/env python3
"""
Test Kafka-based agent execution logging by publishing events directly.

Publishes test events to Kafka and verifies they appear in the database.
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

# Load environment variables (no fallback values)
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")


def publish_to_kafka(topic, payload):
    """Publish message to Kafka using rpk."""
    data = json.dumps(payload)

    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "omninode-bridge-redpanda",
                "rpk",
                "topic",
                "produce",
                topic,
            ],
            input=data.encode("utf-8"),
            capture_output=True,
            check=True,
            timeout=10,
        )

        if result.returncode == 0:
            return True
        else:
            print(f"❌ rpk failed with code {result.returncode}")
            return False

    except Exception as e:
        print(f"❌ Kafka publish failed: {e}")
        return False


def verify_in_database(execution_id):
    """Check if execution exists in database."""
    try:
        if not all(
            [
                POSTGRES_HOST,
                POSTGRES_PORT,
                POSTGRES_DATABASE,
                POSTGRES_USER,
                POSTGRES_PASSWORD,
            ]
        ):
            print(
                "⚠️  PostgreSQL environment variables not set, skipping database verification"
            )
            return None

        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=int(POSTGRES_PORT or "5436"),
            database=POSTGRES_DATABASE,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                execution_id,
                agent_name,
                user_prompt,
                status,
                duration_ms,
                quality_score,
                started_at,
                completed_at
            FROM agent_execution_logs
            WHERE execution_id = %s
        """,
            (execution_id,),
        )

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        return row

    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return None


@pytest.mark.integration
@pytest.mark.skipif(
    not all(
        [
            POSTGRES_HOST,
            POSTGRES_PORT,
            POSTGRES_DATABASE,
            POSTGRES_USER,
            POSTGRES_PASSWORD,
        ]
    ),
    reason="Requires PostgreSQL environment variables (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD)",
)
def test_kafka_execution_logging():
    """Test Kafka-based agent execution logging by publishing events directly."""
    return main()


def main():
    print("=" * 70)
    print("Testing Kafka-Based Agent Execution Logging")
    print("=" * 70)
    print()

    # Generate test data
    execution_id = str(uuid4())
    correlation_id = str(uuid4())
    session_id = str(uuid4())
    agent_name = "test-kafka-direct-logging"
    user_prompt = "Test direct Kafka event publishing"
    started_at = datetime.now(UTC)

    print(f"📝 Execution ID: {execution_id}")
    print(f"📝 Agent: {agent_name}")
    print(f"📝 Task: {user_prompt}")
    print()

    # Publish start event
    print("▶️  Publishing START event to Kafka...")
    start_event = {
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "session_id": session_id,
        "agent_name": agent_name,
        "user_prompt": user_prompt,
        "status": "in_progress",
        "started_at": started_at.isoformat(),
        "metadata": {},
        "project_path": str(Path(__file__).parent.parent.resolve()),
        "project_name": "omniclaude",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not publish_to_kafka("agent-execution-logs", start_event):
        print("❌ Failed to publish start event")
        return 1

    print("   ✅ START event published")
    print()

    # Wait a moment
    time.sleep(1)

    # Publish complete event
    print("✅ Publishing COMPLETE event to Kafka...")
    completed_at = datetime.now(UTC)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    complete_event = {
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "session_id": session_id,
        "agent_name": agent_name,
        "status": "success",
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
        "quality_score": 0.95,
        "metadata": {"completed": True},
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not publish_to_kafka("agent-execution-logs", complete_event):
        print("❌ Failed to publish complete event")
        return 1

    print("   ✅ COMPLETE event published")
    print()

    # Wait for Kafka consumer to process
    print("⏳ Waiting for Kafka consumer to process events (5 seconds)...")
    time.sleep(5)
    print()

    # Verify in database
    print("🔍 Verifying execution logged to database...")
    row = verify_in_database(execution_id)

    if row:
        print("✅ SUCCESS: Execution logged to database!")
        print()
        print(f"   Execution ID: {row[0]}")
        print(f"   Agent Name: {row[1]}")
        print(f"   User Prompt: {row[2]}")
        print(f"   Status: {row[3]}")
        print(f"   Duration: {row[4]}ms")
        print(f"   Quality Score: {row[5]}")
        print(f"   Started: {row[6]}")
        print(f"   Completed: {row[7]}")
        print()

        print("=" * 70)
        print("✅ TEST PASSED: Kafka-based logging working correctly!")
        print("=" * 70)
        print()
        print("🎉 agent_execution_logs logging pipeline is fully functional!")
        print()
        return 0

    else:
        print("❌ FAILURE: Execution NOT found in database!")
        print()
        print(f"   Execution ID: {execution_id}")
        print()
        print("Possible issues:")
        print("  1. Kafka consumer not processing agent-execution-logs topic")
        print("  2. Consumer handler not inserting to database")
        print("  3. Database connection issues")
        print()

        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
