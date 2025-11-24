#!/usr/bin/env python3
"""
Test agent execution logging with Kafka integration.

Tests the complete flow:
1. AgentExecutionLogger publishes events to Kafka
2. Kafka consumer receives events
3. Events are persisted to PostgreSQL agent_execution_logs table

Usage:
    python3 test_agent_execution_logging.py
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest


# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "lib"))

from agent_execution_logger import AgentExecutionLogger


# Load environment variables (no fallback values)
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")


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
async def test_agent_execution_logging():
    """Test complete agent execution logging flow."""
    print("=" * 70)
    print("Testing Agent Execution Logging with Kafka Integration")
    print("=" * 70)
    print()

    # Create logger instance
    agent_name = "test-kafka-logging-agent"
    user_prompt = "Test Kafka-based agent execution logging"

    print(f"📝 Agent: {agent_name}")
    print(f"📝 Task: {user_prompt}")
    print()

    logger = AgentExecutionLogger(
        agent_name=agent_name,
        user_prompt=user_prompt,
        project_path=str(Path(__file__).parent.parent.resolve()),
        project_name="omniclaude",
    )

    # Start execution
    print("▶️  Starting execution...")
    execution_id = await logger.start()
    print(f"   ✅ Execution started: {execution_id}")
    print()

    # Log progress stages
    print("📊 Logging progress...")
    await logger.progress(stage="initializing", percent=10)
    print("   ✅ Progress: initializing (10%)")
    await asyncio.sleep(0.5)

    await logger.progress(stage="gathering_intelligence", percent=30)
    print("   ✅ Progress: gathering_intelligence (30%)")
    await asyncio.sleep(0.5)

    await logger.progress(stage="analyzing_patterns", percent=60)
    print("   ✅ Progress: analyzing_patterns (60%)")
    await asyncio.sleep(0.5)

    await logger.progress(stage="generating_report", percent=90)
    print("   ✅ Progress: generating_report (90%)")
    await asyncio.sleep(0.5)

    # Complete execution
    print()
    print("✅ Completing execution...")

    # Note: AgentExecutionLogger expects EnumOperationStatus, but we'll pass string
    # The logger will convert it to the enum value
    class MockStatus:
        SUCCESS = type("obj", (object,), {"value": "success"})()

    await logger.complete(status=MockStatus.SUCCESS, quality_score=0.95)
    print("   ✅ Execution completed with quality_score=0.95")
    print()

    # Wait for Kafka consumer to process events
    print("⏳ Waiting for Kafka consumer to process events (5 seconds)...")
    await asyncio.sleep(5)
    print()

    # Verify in database
    print("🔍 Verifying execution logged to database...")
    print()

    try:
        import psycopg2

        # Connect to database using environment variables
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=int(POSTGRES_PORT),
            database=POSTGRES_DATABASE,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )

        cursor = conn.cursor()

        # Query execution log
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

            # Calculate duration
            if row[6] and row[7]:
                duration = (row[7] - row[6]).total_seconds()
                print(f"   📊 Total Duration: {duration:.2f} seconds")
                print()

            cursor.close()
            conn.close()

            print("=" * 70)
            print("✅ TEST PASSED: Kafka-based logging working correctly!")
            print("=" * 70)
            return 0

        else:
            print("❌ FAILURE: Execution NOT found in database!")
            print()
            print(f"   Execution ID: {execution_id}")
            print(f"   Agent Name: {agent_name}")
            print()
            print("Possible issues:")
            print("  1. Kafka consumer not processing events")
            print("  2. Database connection issues")
            print("  3. Event schema mismatch")
            print()

            cursor.close()
            conn.close()

            print("=" * 70)
            print("❌ TEST FAILED")
            print("=" * 70)
            return 1

    except Exception as e:
        print(f"❌ Database verification failed: {e}")
        print()
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_agent_execution_logging())
    sys.exit(exit_code)
