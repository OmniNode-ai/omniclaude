#!/usr/bin/env python3
"""
Test script for transformation event logging to Kafka and PostgreSQL.

This script tests the complete flow:
1. Publish transformation event to Kafka
2. Consumer picks it up
3. Event persisted to agent_transformation_events table

Usage:
    python tests/test_transformation_event_logging.py

Prerequisites:
    - Kafka running (KAFKA_BOOTSTRAP_SERVERS set in .env)
    - PostgreSQL running (POSTGRES_* set in .env)
    - Consumer running (consumers/agent_actions_consumer.py)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.lib.transformation_event_publisher import (
    close_producer,
    publish_transformation_complete,
    publish_transformation_failed,
    publish_transformation_start,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_transformation_complete_event():
    """Test publishing a successful transformation event."""
    logger.info("Test 1: Publishing transformation_complete event...")

    correlation_id = str(uuid4())

    success = await publish_transformation_complete(
        source_agent="polymorphic-agent",
        target_agent="agent-api-architect",
        transformation_reason="API design task detected via routing",
        correlation_id=correlation_id,
        user_request="Design a REST API for user management with CRUD operations",
        routing_confidence=0.92,
        routing_strategy="fuzzy_match",
        transformation_duration_ms=45,
        initialization_duration_ms=120,
    )

    if success:
        logger.info(f"✓ Transformation complete event published (correlation_id={correlation_id})")
        return True, correlation_id
    else:
        logger.error("✗ Failed to publish transformation complete event")
        return False, correlation_id


async def test_transformation_failed_event():
    """Test publishing a failed transformation event."""
    logger.info("Test 2: Publishing transformation_failed event...")

    correlation_id = str(uuid4())

    success = await publish_transformation_failed(
        source_agent="polymorphic-agent",
        target_agent="agent-nonexistent",
        transformation_reason="Attempted transformation to unknown agent",
        correlation_id=correlation_id,
        error_message="Agent definition not found: agent-nonexistent.yaml",
        error_type="FileNotFoundError",
        user_request="Use nonexistent agent",
        routing_confidence=0.75,
    )

    if success:
        logger.info(f"✓ Transformation failed event published (correlation_id={correlation_id})")
        return True, correlation_id
    else:
        logger.error("✗ Failed to publish transformation failed event")
        return False, correlation_id


async def test_transformation_start_event():
    """Test publishing a transformation start event."""
    logger.info("Test 3: Publishing transformation_start event...")

    correlation_id = str(uuid4())

    success = await publish_transformation_start(
        source_agent="polymorphic-agent",
        target_agent="agent-debug-intelligence",
        transformation_reason="Debug investigation task detected",
        correlation_id=correlation_id,
        user_request="Debug why my database queries are slow",
        routing_confidence=0.88,
        routing_strategy="capability_match",
    )

    if success:
        logger.info(f"✓ Transformation start event published (correlation_id={correlation_id})")
        return True, correlation_id
    else:
        logger.error("✗ Failed to publish transformation start event")
        return False, correlation_id


async def test_self_transformation_detection():
    """Test detecting self-transformation (polymorphic → polymorphic)."""
    logger.info("Test 4: Publishing self-transformation event...")

    correlation_id = str(uuid4())

    success = await publish_transformation_complete(
        source_agent="polymorphic-agent",
        target_agent="polymorphic-agent",
        transformation_reason="Self-transformation detected - routing bypass attempt",
        correlation_id=correlation_id,
        user_request="Direct execution without routing",
        routing_confidence=0.0,  # No routing occurred
        routing_strategy="direct_execution",
        transformation_duration_ms=5,
    )

    if success:
        logger.warning(
            f"⚠ Self-transformation event published (correlation_id={correlation_id}) "
            "- this should be flagged by metrics"
        )
        return True, correlation_id
    else:
        logger.error("✗ Failed to publish self-transformation event")
        return False, correlation_id


async def verify_database_persistence(correlation_ids: list[str], wait_seconds: int = 5):
    """
    Verify events were persisted to PostgreSQL.

    Args:
        correlation_ids: List of correlation IDs to verify
        wait_seconds: Seconds to wait for consumer to process events
    """
    logger.info(f"Waiting {wait_seconds} seconds for consumer to process events...")
    await asyncio.sleep(wait_seconds)

    logger.info("Verifying database persistence...")

    try:
        import psycopg2

        # Load database credentials from environment
        db_config = {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5436")),
            "database": os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", ""),
        }

        conn = psycopg2.connect(
            host=str(db_config["host"]),
            port=db_config["port"],
            dbname=str(db_config["database"]),
            user=str(db_config["user"]),
            password=str(db_config["password"]),
        )
        cursor = conn.cursor()

        # Query for our test events
        query = """
            SELECT
                correlation_id, source_agent, target_agent,
                event_type, success, transformation_duration_ms,
                created_at
            FROM agent_transformation_events
            WHERE correlation_id = ANY(%s)
            ORDER BY created_at DESC
        """

        cursor.execute(query, (correlation_ids,))
        rows = cursor.fetchall()

        logger.info(f"Found {len(rows)} events in database:")
        for row in rows:
            logger.info(
                f"  • {row[3]}: {row[1]} → {row[2]} "
                f"(success={row[4]}, duration={row[5]}ms, correlation_id={row[0]})"
            )

        cursor.close()
        conn.close()

        if len(rows) == len(correlation_ids):
            logger.info("✓ All test events successfully persisted to database")
            return True
        else:
            logger.warning(
                f"⚠ Only {len(rows)}/{len(correlation_ids)} events found in database. "
                f"Consumer may still be processing or not running."
            )
            return False

    except ImportError:
        logger.error("✗ psycopg2 not installed. Install with: pip install psycopg2-binary")
        return False
    except Exception as e:
        logger.error(f"✗ Database verification failed: {e}")
        return False


async def run_tests():
    """Run all transformation event logging tests."""
    logger.info("=" * 80)
    logger.info("TRANSFORMATION EVENT LOGGING TEST SUITE")
    logger.info("=" * 80)

    # Check prerequisites
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    postgres_password = os.getenv("POSTGRES_PASSWORD")

    if not kafka_servers:
        logger.error("✗ KAFKA_BOOTSTRAP_SERVERS not set in environment")
        return False

    if not postgres_password:
        logger.error("✗ POSTGRES_PASSWORD not set in environment")
        logger.info("  Load .env file with: source .env")
        return False

    logger.info(f"Kafka: {kafka_servers}")
    logger.info(f"PostgreSQL: {os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}")
    logger.info("")

    # Run tests
    correlation_ids = []
    test_results = []

    # Test 1: Transformation complete
    success, corr_id = await test_transformation_complete_event()
    test_results.append(("Transformation Complete", success))
    if success:
        correlation_ids.append(corr_id)

    await asyncio.sleep(0.5)

    # Test 2: Transformation failed
    success, corr_id = await test_transformation_failed_event()
    test_results.append(("Transformation Failed", success))
    if success:
        correlation_ids.append(corr_id)

    await asyncio.sleep(0.5)

    # Test 3: Transformation start
    success, corr_id = await test_transformation_start_event()
    test_results.append(("Transformation Start", success))
    if success:
        correlation_ids.append(corr_id)

    await asyncio.sleep(0.5)

    # Test 4: Self-transformation detection
    success, corr_id = await test_self_transformation_detection()
    test_results.append(("Self-Transformation Detection", success))
    if success:
        correlation_ids.append(corr_id)

    # Close producer
    await close_producer()

    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)

    for test_name, success in test_results:
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info("")

    # Verify database persistence
    if correlation_ids:
        db_success = await verify_database_persistence(correlation_ids)
    else:
        logger.error("✗ No events published to verify in database")
        db_success = False

    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)

    kafka_tests_passed = sum(1 for _, success in test_results if success)
    logger.info(f"Kafka Publishing: {kafka_tests_passed}/{len(test_results)} tests passed")
    logger.info(f"Database Persistence: {'✓ PASS' if db_success else '⚠ PARTIAL or ✗ FAIL'}")

    if kafka_tests_passed == len(test_results) and db_success:
        logger.info("")
        logger.info("✓ ALL TESTS PASSED - Transformation event logging working end-to-end!")
        return True
    else:
        logger.info("")
        logger.info("⚠ SOME TESTS FAILED - Check logs above for details")
        logger.info("")
        logger.info("Troubleshooting:")
        logger.info("  1. Ensure Kafka is running: docker ps | grep redpanda")
        logger.info("  2. Ensure consumer is running: ps aux | grep agent_actions_consumer")
        logger.info("  3. Check consumer logs: docker logs -f <consumer-container>")
        logger.info("  4. Verify .env file loaded: echo $KAFKA_BOOTSTRAP_SERVERS")
        return False


if __name__ == "__main__":
    # Load .env file
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        logger.info(f"Loading environment from {env_path}")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key not in os.environ:
                        os.environ[key] = value.strip('"').strip("'")

    # Run tests
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
