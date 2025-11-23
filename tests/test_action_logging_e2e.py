#!/usr/bin/env python3
"""
End-to-End Test for Agent Action Logging

Tests the complete flow:
1. Publish action events to Kafka topic 'agent-actions'
2. Consumer processes events and writes to PostgreSQL
3. Query database to verify actions were persisted
4. Validate correlation IDs and action details

Usage:
    python tests/test_action_logging_e2e.py
    python tests/test_action_logging_e2e.py --verbose

Requirements:
    - Kafka running and accessible
    - PostgreSQL running and accessible
    - Consumer running (agent_actions_consumer.py)
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest


# Add agents/lib to path
SCRIPT_DIR = Path(__file__).parent
AGENTS_LIB = SCRIPT_DIR.parent / "agents" / "lib"
sys.path.insert(0, str(AGENTS_LIB))

try:
    import asyncpg

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("WARNING: asyncpg not installed. Database verification will be skipped.")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    pass

from action_logger import ActionLogger
from kafka_agent_action_consumer import KafkaAgentActionConsumer


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Pytest Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def kafka_brokers():
    """Kafka brokers for E2E testing."""
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")


@pytest.fixture(scope="session")
def postgres_dsn():
    """PostgreSQL DSN for E2E testing."""
    host = os.getenv("POSTGRES_HOST", "192.168.86.200")
    port = os.getenv("POSTGRES_PORT", "5436")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

    if not password:
        pytest.skip("POSTGRES_PASSWORD environment variable not set")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
async def db_pool(postgres_dsn):
    """Database connection pool."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture
async def running_consumer(kafka_brokers, postgres_dsn):
    """Start consumer in background for E2E tests."""
    consumer = KafkaAgentActionConsumer(
        kafka_brokers=kafka_brokers,
        topic="agent-actions",
        postgres_dsn=postgres_dsn,
        batch_size=50,
        batch_timeout_seconds=2.0,
    )

    await consumer.start()

    # Start consumer loop in background task
    consumer_task = asyncio.create_task(consumer.consume_loop())

    yield consumer

    # Stop consumer
    await consumer.stop()

    try:
        consumer_task.cancel()
        await consumer_task
    except asyncio.CancelledError:
        pass


# -------------------------------------------------------------------------
# Legacy Test Class (for backwards compatibility with standalone execution)
# -------------------------------------------------------------------------


class ActionLoggingE2ETest:
    """End-to-end test for action logging."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.correlation_id = str(uuid4())
        self.test_actions = []
        self.db_conn = None

        # Configure logging level
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

    def setup_database(self):
        """Setup database connection."""
        if not POSTGRES_AVAILABLE:
            logger.warning("PostgreSQL not available, skipping DB setup")
            return False

        try:
            # Load credentials from environment (no fallback values - must be set)
            postgres_host = os.getenv("POSTGRES_HOST")
            postgres_port = os.getenv("POSTGRES_PORT")
            postgres_database = os.getenv("POSTGRES_DATABASE")
            postgres_user = os.getenv("POSTGRES_USER")
            postgres_password = os.getenv("POSTGRES_PASSWORD")

            if not all(
                [
                    postgres_host,
                    postgres_port,
                    postgres_database,
                    postgres_user,
                    postgres_password,
                ]
            ):
                logger.error("Required PostgreSQL environment variables not set")
                logger.error(
                    "Please set: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD"
                )
                return False

            db_config = {
                "host": postgres_host,
                "port": int(postgres_port),
                "database": postgres_database,
                "user": postgres_user,
                "password": postgres_password,
            }

            self.db_conn = psycopg2.connect(**db_config)
            logger.info(
                f"✓ Database connection established: {db_config['host']}:{db_config['port']}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False

    async def publish_test_actions(self):
        """Publish test action events to Kafka."""
        logger.info(f"Publishing test actions (correlation_id: {self.correlation_id})")

        action_logger = ActionLogger(
            agent_name="test-agent-e2e",
            correlation_id=self.correlation_id,
            project_name="omniclaude-test",
            project_path="/tmp/test",
            debug_mode=True,
        )

        # Test 1: Tool call - Read
        async with action_logger.tool_call(
            "Read",
            tool_parameters={"file_path": "/tmp/test.py", "offset": 0, "limit": 100},
        ) as action:
            await asyncio.sleep(0.02)
            action.set_result({"line_count": 100, "success": True})

        self.test_actions.append(
            {
                "action_type": "tool_call",
                "action_name": "Read",
                "expected_details": ["file_path", "line_count"],
            }
        )
        logger.info("✓ Published Read action")

        # Test 2: Tool call - Write
        await action_logger.log_tool_call(
            tool_name="Write",
            tool_parameters={"file_path": "/tmp/output.py", "content_length": 2048},
            tool_result={"success": True, "bytes_written": 2048},
            duration_ms=30,
            success=True,
        )

        self.test_actions.append(
            {
                "action_type": "tool_call",
                "action_name": "Write",
                "expected_details": ["file_path", "bytes_written"],
            }
        )
        logger.info("✓ Published Write action")

        # Test 3: Decision
        await action_logger.log_decision(
            decision_name="select_agent",
            decision_context={"candidates": ["agent-a", "agent-b"]},
            decision_result={"selected": "agent-a", "confidence": 0.92},
            duration_ms=15,
        )

        self.test_actions.append(
            {
                "action_type": "decision",
                "action_name": "select_agent",
                "expected_details": ["decision_context", "decision_result"],
            }
        )
        logger.info("✓ Published Decision action")

        # Test 4: Error
        await action_logger.log_error(
            error_type="ImportError",
            error_message="Module 'test_module' not found",
            error_context={"file": "/tmp/test.py", "line": 42},
        )

        self.test_actions.append(
            {
                "action_type": "error",
                "action_name": "ImportError",
                "expected_details": ["error_type", "error_message"],
            }
        )
        logger.info("✓ Published Error action")

        # Test 5: Success
        await action_logger.log_success(
            success_name="task_completed",
            success_details={"files_processed": 5, "quality_score": 0.95},
            duration_ms=250,
        )

        self.test_actions.append(
            {
                "action_type": "success",
                "action_name": "task_completed",
                "expected_details": ["files_processed", "quality_score"],
            }
        )
        logger.info("✓ Published Success action")

        # Test 6: Bash command
        async with action_logger.tool_call(
            "Bash", tool_parameters={"command": "ls -la", "working_directory": "/tmp"}
        ) as action:
            await asyncio.sleep(0.01)
            action.set_result({"exit_code": 0, "success": True})

        self.test_actions.append(
            {
                "action_type": "tool_call",
                "action_name": "Bash",
                "expected_details": ["command", "exit_code"],
            }
        )
        logger.info("✓ Published Bash action")

        logger.info(f"Published {len(self.test_actions)} test actions")

    def verify_actions_in_database(self, max_wait_seconds: int = 10) -> bool:
        """
        Verify actions were persisted to database.

        Args:
            max_wait_seconds: Maximum time to wait for consumer to process

        Returns:
            bool: True if all actions verified
        """
        if not self.db_conn:
            logger.warning("No database connection, skipping verification")
            return False

        logger.info(
            f"Waiting up to {max_wait_seconds}s for consumer to process events..."
        )

        # Wait for consumer to process events
        start_time = time.time()
        found_actions = []

        while time.time() - start_time < max_wait_seconds:
            try:
                with self.db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT
                            id, correlation_id, agent_name, action_type, action_name,
                            action_details, duration_ms, created_at
                        FROM agent_actions
                        WHERE correlation_id = %s
                        ORDER BY created_at ASC
                        """,
                        (self.correlation_id,),
                    )

                    found_actions = cursor.fetchall()

                    if len(found_actions) >= len(self.test_actions):
                        break

                # Sleep before retry
                if len(found_actions) < len(self.test_actions):
                    await_seconds = 1
                    logger.info(
                        f"Found {len(found_actions)}/{len(self.test_actions)} actions, "
                        f"waiting {await_seconds}s..."
                    )
                    time.sleep(await_seconds)

            except Exception as e:
                logger.error(f"Database query failed: {e}")
                return False

        # Verify results
        if len(found_actions) == 0:
            logger.error(
                f"❌ No actions found in database for correlation_id: {self.correlation_id}"
            )
            return False

        if len(found_actions) < len(self.test_actions):
            logger.warning(
                f"⚠️  Found {len(found_actions)}/{len(self.test_actions)} actions "
                f"(consumer may be slow)"
            )
        else:
            logger.info(f"✓ Found all {len(found_actions)} actions in database")

        # Validate each action
        all_valid = True
        for i, action in enumerate(found_actions):
            expected = self.test_actions[i] if i < len(self.test_actions) else None

            logger.info(f"\nAction {i+1}:")
            logger.info(f"  Type: {action['action_type']}")
            logger.info(f"  Name: {action['action_name']}")
            logger.info(f"  Agent: {action['agent_name']}")
            logger.info(f"  Correlation ID: {action['correlation_id']}")

            if expected:
                # Validate action type and name
                if action["action_type"] != expected["action_type"]:
                    logger.error(
                        f"  ❌ Type mismatch: expected {expected['action_type']}, "
                        f"got {action['action_type']}"
                    )
                    all_valid = False
                elif action["action_name"] != expected["action_name"]:
                    logger.error(
                        f"  ❌ Name mismatch: expected {expected['action_name']}, "
                        f"got {action['action_name']}"
                    )
                    all_valid = False
                else:
                    logger.info(f"  ✓ Type and name match")

                # Validate action details
                if expected["expected_details"]:
                    action_details = action.get("action_details", {})
                    missing_fields = [
                        field
                        for field in expected["expected_details"]
                        if field not in str(action_details)
                    ]

                    if missing_fields:
                        logger.warning(
                            f"  ⚠️  Missing expected fields in action_details: {missing_fields}"
                        )
                    else:
                        logger.info(f"  ✓ Action details contain expected fields")

            # Validate correlation ID
            if str(action["correlation_id"]) != self.correlation_id:
                logger.error(
                    f"  ❌ Correlation ID mismatch: expected {self.correlation_id}, "
                    f"got {action['correlation_id']}"
                )
                all_valid = False
            else:
                logger.info(f"  ✓ Correlation ID matches")

        return all_valid and len(found_actions) >= len(self.test_actions)

    def cleanup(self):
        """Cleanup resources."""
        if self.db_conn:
            self.db_conn.close()
            logger.info("✓ Database connection closed")

    async def run(self) -> bool:
        """
        Run end-to-end test.

        Returns:
            bool: True if test passed
        """
        logger.info("=" * 60)
        logger.info("Agent Action Logging E2E Test")
        logger.info("=" * 60)

        # Setup database connection
        if not self.setup_database():
            logger.error("❌ Database setup failed")
            return False

        # Publish test actions
        try:
            await self.publish_test_actions()
        except Exception as e:
            logger.error(
                f"❌ Failed to publish test actions: {e}", exc_info=self.verbose
            )
            return False

        # Verify actions in database
        success = self.verify_actions_in_database(max_wait_seconds=15)

        # Cleanup
        self.cleanup()

        # Report results
        logger.info("\n" + "=" * 60)
        if success:
            logger.info("✅ Test PASSED - All actions logged and verified")
        else:
            logger.info("❌ Test FAILED - See errors above")
        logger.info("=" * 60)

        return success


@pytest.mark.integration
@pytest.mark.skipif(
    not POSTGRES_AVAILABLE,
    reason="Requires asyncpg and PostgreSQL connection",
)
@pytest.mark.asyncio
async def test_action_logging_e2e(running_consumer, db_pool):
    """
    End-to-end test for action logging with Kafka consumer.

    Tests the complete flow:
    1. Publish action events to Kafka topic 'agent-actions'
    2. Consumer processes events and writes to PostgreSQL
    3. Query database to verify actions were persisted
    4. Validate correlation IDs and action details
    """
    correlation_id = str(uuid4())

    logger.info("=" * 60)
    logger.info("Agent Action Logging E2E Test")
    logger.info("=" * 60)
    logger.info(f"Correlation ID: {correlation_id}")

    # Step 1: Publish test actions to Kafka
    logger.info("\nStep 1: Publishing test actions to Kafka...")

    action_logger = ActionLogger(
        agent_name="test-agent-e2e",
        correlation_id=correlation_id,
        project_name="omniclaude-test",
        project_path="/tmp/test",
        debug_mode=True,
    )

    # Test actions to publish
    test_actions = []

    # Test 1: Tool call - Read
    async with action_logger.tool_call(
        "Read",
        tool_parameters={"file_path": "/tmp/test.py", "offset": 0, "limit": 100},
    ) as action:
        await asyncio.sleep(0.02)
        action.set_result({"line_count": 100, "success": True})

    test_actions.append(
        {
            "action_type": "tool_call",
            "action_name": "Read",
        }
    )
    logger.info("✓ Published Read action")

    # Test 2: Tool call - Write
    await action_logger.log_tool_call(
        tool_name="Write",
        tool_parameters={"file_path": "/tmp/output.py", "content_length": 2048},
        tool_result={"success": True, "bytes_written": 2048},
        duration_ms=30,
        success=True,
    )

    test_actions.append(
        {
            "action_type": "tool_call",
            "action_name": "Write",
        }
    )
    logger.info("✓ Published Write action")

    # Test 3: Decision
    await action_logger.log_decision(
        decision_name="select_agent",
        decision_context={"candidates": ["agent-a", "agent-b"]},
        decision_result={"selected": "agent-a", "confidence": 0.92},
        duration_ms=15,
    )

    test_actions.append(
        {
            "action_type": "decision",
            "action_name": "select_agent",
        }
    )
    logger.info("✓ Published Decision action")

    # Test 4: Error
    await action_logger.log_error(
        error_type="ImportError",
        error_message="Module 'test_module' not found",
        error_context={"file": "/tmp/test.py", "line": 42},
    )

    test_actions.append(
        {
            "action_type": "error",
            "action_name": "ImportError",
        }
    )
    logger.info("✓ Published Error action")

    # Test 5: Success
    await action_logger.log_success(
        success_name="task_completed",
        success_details={"files_processed": 5, "quality_score": 0.95},
        duration_ms=250,
    )

    test_actions.append(
        {
            "action_type": "success",
            "action_name": "task_completed",
        }
    )
    logger.info("✓ Published Success action")

    # Test 6: Bash command
    async with action_logger.tool_call(
        "Bash", tool_parameters={"command": "ls -la", "working_directory": "/tmp"}
    ) as action:
        await asyncio.sleep(0.01)
        action.set_result({"exit_code": 0, "success": True})

    test_actions.append(
        {
            "action_type": "tool_call",
            "action_name": "Bash",
        }
    )
    logger.info("✓ Published Bash action")

    logger.info(f"\nPublished {len(test_actions)} test actions")

    # Step 2: Wait for consumer to process events
    logger.info("\nStep 2: Waiting for consumer to process events...")

    max_wait_seconds = 15.0
    poll_interval = 0.5
    start_time = asyncio.get_event_loop().time()
    found_count = 0

    while (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
        async with db_pool.acquire() as conn:
            found_count = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
                correlation_id,
            )

            if found_count >= len(test_actions):
                break

        logger.info(f"Found {found_count}/{len(test_actions)} actions, waiting...")
        await asyncio.sleep(poll_interval)

    # Step 3: Verify all actions were persisted
    logger.info("\nStep 3: Verifying actions in database...")

    async with db_pool.acquire() as conn:
        results = await conn.fetch(
            """
            SELECT
                id, correlation_id, agent_name, action_type, action_name,
                action_details, duration_ms, created_at
            FROM agent_actions
            WHERE correlation_id = $1
            ORDER BY created_at ASC
            """,
            correlation_id,
        )

    # Verify count
    assert len(results) >= len(
        test_actions
    ), f"Expected at least {len(test_actions)} actions, found {len(results)}"
    logger.info(f"✓ Found all {len(results)} actions in database")

    # Verify each action
    for i, result in enumerate(results):
        if i < len(test_actions):
            expected = test_actions[i]

            assert result["action_type"] == expected["action_type"], (
                f"Action {i+1}: Type mismatch - expected {expected['action_type']}, "
                f"got {result['action_type']}"
            )

            assert result["action_name"] == expected["action_name"], (
                f"Action {i+1}: Name mismatch - expected {expected['action_name']}, "
                f"got {result['action_name']}"
            )

            assert (
                str(result["correlation_id"]) == correlation_id
            ), f"Action {i+1}: Correlation ID mismatch"

            assert (
                result["agent_name"] == "test-agent-e2e"
            ), f"Action {i+1}: Agent name mismatch"

            logger.info(
                f"✓ Action {i+1}: {result['action_type']} - {result['action_name']}"
            )

    logger.info("\n" + "=" * 60)
    logger.info("✅ Test PASSED - All actions logged and verified")
    logger.info("=" * 60)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="End-to-end test for agent action logging"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Check environment
    postgres_password = os.getenv("POSTGRES_PASSWORD")
    if not postgres_password:
        logger.error("POSTGRES_PASSWORD environment variable not set")
        logger.error("Please run: source .env")
        sys.exit(1)

    # Run test
    test = ActionLoggingE2ETest(verbose=args.verbose)
    success = await test.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
