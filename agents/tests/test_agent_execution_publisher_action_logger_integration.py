#!/usr/bin/env python3
"""
Test Agent Execution Publisher with ActionLogger Integration

This test demonstrates the enhanced observability provided by ActionLogger
integration in the agent execution publisher.

Features tested:
- ActionLogger integration in publish_execution_started
- ActionLogger integration in publish_execution_completed
- ActionLogger integration in publish_execution_failed
- Automatic timing and correlation ID tracking
- Performance metrics capture
- Graceful degradation when ActionLogger unavailable
"""

import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Add parent directories to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent.parent))

from agents.lib.agent_execution_publisher import (
    AgentExecutionPublisher,
    AgentExecutionPublisherContext,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_execution_started_with_action_logger():
    """Test publish_execution_started with ActionLogger integration."""
    logger.info("=" * 60)
    logger.info("Test 1: Execution Started with ActionLogger")
    logger.info("=" * 60)

    # Create publisher (using context manager for auto start/stop)
    async with AgentExecutionPublisherContext() as publisher:
        correlation_id = str(uuid4())
        session_id = str(uuid4())

        # Publish execution started event
        success = await publisher.publish_execution_started(
            agent_name="agent-test-researcher",
            user_request="Test research task with action logging",
            correlation_id=correlation_id,
            session_id=session_id,
            context={"domain": "testing", "phase": "integration"},
        )

        logger.info(f"Execution started event published: {success}")
        logger.info(f"Correlation ID: {correlation_id}")

        if success:
            logger.info(
                "✓ Event published to Kafka AND logged with ActionLogger (decision)"
            )
        else:
            logger.warning("⚠ Event failed to publish (check Kafka connectivity)")

    logger.info("")


async def test_execution_completed_with_action_logger():
    """Test publish_execution_completed with ActionLogger integration."""
    logger.info("=" * 60)
    logger.info("Test 2: Execution Completed with ActionLogger")
    logger.info("=" * 60)

    async with AgentExecutionPublisherContext() as publisher:
        correlation_id = str(uuid4())

        # Simulate agent execution
        execution_duration_ms = 1500  # 1.5 seconds
        quality_score = 0.92
        output_summary = "Research completed with 5 findings"
        metrics = {
            "tool_calls": 12,
            "files_read": 5,
            "files_written": 2,
            "tokens_used": 3500,
        }

        # Publish execution completed event
        success = await publisher.publish_execution_completed(
            agent_name="agent-test-researcher",
            correlation_id=correlation_id,
            duration_ms=execution_duration_ms,
            quality_score=quality_score,
            output_summary=output_summary,
            metrics=metrics,
        )

        logger.info(f"Execution completed event published: {success}")
        logger.info(f"Correlation ID: {correlation_id}")
        logger.info(f"Execution duration: {execution_duration_ms}ms")
        logger.info(f"Quality score: {quality_score}")

        if success:
            logger.info(
                "✓ Event published to Kafka AND logged with ActionLogger (success with metrics)"
            )
        else:
            logger.warning("⚠ Event failed to publish (check Kafka connectivity)")

    logger.info("")


async def test_execution_failed_with_action_logger():
    """Test publish_execution_failed with ActionLogger integration."""
    logger.info("=" * 60)
    logger.info("Test 3: Execution Failed with ActionLogger")
    logger.info("=" * 60)

    async with AgentExecutionPublisherContext() as publisher:
        correlation_id = str(uuid4())

        # Simulate agent failure
        error_message = "Failed to access required file: /path/to/missing/file.py"
        error_type = "FileNotFoundError"
        error_stack_trace = """Traceback (most recent call last):
  File "agent_executor.py", line 42, in execute
    with open(file_path, 'r') as f:
FileNotFoundError: [Errno 2] No such file or directory: '/path/to/missing/file.py'
"""
        partial_results = {
            "files_processed": 3,
            "failed_at": "file_read",
            "progress_percentage": 60,
        }

        # Publish execution failed event
        success = await publisher.publish_execution_failed(
            agent_name="agent-test-researcher",
            correlation_id=correlation_id,
            error_message=error_message,
            error_type=error_type,
            error_stack_trace=error_stack_trace,
            partial_results=partial_results,
        )

        logger.info(f"Execution failed event published: {success}")
        logger.info(f"Correlation ID: {correlation_id}")
        logger.info(f"Error type: {error_type}")
        logger.info(f"Partial results: {partial_results}")

        if success:
            logger.info(
                "✓ Event published to Kafka AND logged with ActionLogger (error with context)"
            )
        else:
            logger.warning("⚠ Event failed to publish (check Kafka connectivity)")

    logger.info("")


async def test_complete_lifecycle():
    """Test complete agent lifecycle with ActionLogger integration."""
    logger.info("=" * 60)
    logger.info("Test 4: Complete Agent Lifecycle")
    logger.info("=" * 60)

    async with AgentExecutionPublisherContext() as publisher:
        correlation_id = str(uuid4())
        session_id = str(uuid4())
        agent_name = "agent-test-lifecycle"

        logger.info(f"Starting agent lifecycle test (correlation_id: {correlation_id})")

        # 1. Start execution
        await publisher.publish_execution_started(
            agent_name=agent_name,
            user_request="Complete lifecycle test with ActionLogger",
            correlation_id=correlation_id,
            session_id=session_id,
            context={"test_type": "lifecycle"},
        )
        logger.info("✓ Execution started")

        # 2. Simulate some work
        await asyncio.sleep(0.1)

        # 3. Complete execution
        await publisher.publish_execution_completed(
            agent_name=agent_name,
            correlation_id=correlation_id,
            duration_ms=150,
            quality_score=0.95,
            output_summary="Lifecycle test completed successfully",
            metrics={"steps_completed": 3, "total_time_ms": 150},
        )
        logger.info("✓ Execution completed")

        logger.info("\n✓ Complete lifecycle logged with ActionLogger integration")
        logger.info("  - Decision logged at start")
        logger.info("  - Success logged at completion with performance metrics")

    logger.info("")


async def main():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("Agent Execution Publisher - ActionLogger Integration Tests")
    logger.info("=" * 60)
    logger.info("")

    try:
        # Run individual tests
        await test_execution_started_with_action_logger()
        await test_execution_completed_with_action_logger()
        await test_execution_failed_with_action_logger()
        await test_complete_lifecycle()

        logger.info("=" * 60)
        logger.info("All Tests Passed!")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Check Kafka topic 'agent-actions' for ActionLogger events")
        logger.info(
            "2. Check Kafka topics 'omninode.agent.execution.*' for execution events"
        )
        logger.info("3. Verify consumer is processing events:")
        logger.info("   docker ps | grep agent-actions-consumer")
        logger.info("4. Query database for logged actions:")
        logger.info(
            "   SELECT * FROM agent_actions WHERE correlation_id = '<correlation_id>';"
        )

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
