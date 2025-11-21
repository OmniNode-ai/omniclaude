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
    import psycopg2
    from psycopg2.extras import RealDictCursor

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("WARNING: psycopg2 not installed. Database verification will be skipped.")

from action_logger import ActionLogger


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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
    not all(
        [
            os.getenv("POSTGRES_HOST"),
            os.getenv("POSTGRES_PORT"),
            os.getenv("POSTGRES_DATABASE"),
            os.getenv("POSTGRES_USER"),
            os.getenv("POSTGRES_PASSWORD"),
        ]
    ),
    reason="Requires PostgreSQL environment variables (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD)",
)
@pytest.mark.asyncio
async def test_action_logging_e2e():
    """Pytest wrapper for action logging e2e test."""
    test = ActionLoggingE2ETest(verbose=False)
    success = await test.run()
    assert success, "Action logging e2e test failed"


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
