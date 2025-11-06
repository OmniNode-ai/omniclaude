#!/usr/bin/env python3
"""
Simple Test for Agent Action Publishing

Tests that action events can be published to Kafka successfully.
Does NOT require database access - just tests the publishing side.

Usage:
    python tests/test_action_publishing.py
    python tests/test_action_publishing.py --verbose
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Add agents/lib to path
SCRIPT_DIR = Path(__file__).parent
AGENTS_LIB = SCRIPT_DIR.parent / "agents" / "lib"
sys.path.insert(0, str(AGENTS_LIB))

from action_logger import ActionLogger

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_action_publishing(verbose: bool = False):
    """
    Test that action events can be published to Kafka.

    Args:
        verbose: Enable verbose logging

    Returns:
        bool: True if all publishing succeeded
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Agent Action Publishing Test")
    logger.info("=" * 60)

    correlation_id = str(uuid4())
    logger.info(f"Test correlation_id: {correlation_id}")

    # Initialize action logger
    action_logger = ActionLogger(
        agent_name="test-agent-publisher",
        correlation_id=correlation_id,
        project_name="omniclaude-test",
        project_path="/tmp/test",
        debug_mode=True,
    )

    results = []

    # Test 1: Tool call with context manager
    logger.info("\n[Test 1] Tool call with context manager")
    try:
        async with action_logger.tool_call(
            "Read",
            tool_parameters={"file_path": "/tmp/test.py", "offset": 0, "limit": 100},
        ) as action:
            await asyncio.sleep(0.02)
            action.set_result({"line_count": 100, "success": True})

        logger.info("✓ Read action published successfully")
        results.append(True)
    except Exception as e:
        logger.error(f"❌ Read action failed: {e}", exc_info=verbose)
        results.append(False)

    # Test 2: Manual tool call
    logger.info("\n[Test 2] Manual tool call")
    try:
        success = await action_logger.log_tool_call(
            tool_name="Write",
            tool_parameters={"file_path": "/tmp/output.py", "content_length": 2048},
            tool_result={"success": True, "bytes_written": 2048},
            duration_ms=30,
            success=True,
        )

        if success:
            logger.info("✓ Write action published successfully")
            results.append(True)
        else:
            logger.warning(
                "⚠️  Write action publish returned False (Kafka may be unavailable)"
            )
            results.append(False)

    except Exception as e:
        logger.error(f"❌ Write action failed: {e}", exc_info=verbose)
        results.append(False)

    # Test 3: Decision
    logger.info("\n[Test 3] Decision action")
    try:
        success = await action_logger.log_decision(
            decision_name="select_agent",
            decision_context={"candidates": ["agent-a", "agent-b"]},
            decision_result={"selected": "agent-a", "confidence": 0.92},
            duration_ms=15,
        )

        if success:
            logger.info("✓ Decision action published successfully")
            results.append(True)
        else:
            logger.warning("⚠️  Decision action publish returned False")
            results.append(False)

    except Exception as e:
        logger.error(f"❌ Decision action failed: {e}", exc_info=verbose)
        results.append(False)

    # Test 4: Error
    logger.info("\n[Test 4] Error action")
    try:
        success = await action_logger.log_error(
            error_type="ImportError",
            error_message="Module 'test_module' not found",
            error_context={"file": "/tmp/test.py", "line": 42},
        )

        if success:
            logger.info("✓ Error action published successfully")
            results.append(True)
        else:
            logger.warning("⚠️  Error action publish returned False")
            results.append(False)

    except Exception as e:
        logger.error(f"❌ Error action failed: {e}", exc_info=verbose)
        results.append(False)

    # Test 5: Success
    logger.info("\n[Test 5] Success action")
    try:
        success = await action_logger.log_success(
            success_name="task_completed",
            success_details={"files_processed": 5, "quality_score": 0.95},
            duration_ms=250,
        )

        if success:
            logger.info("✓ Success action published successfully")
            results.append(True)
        else:
            logger.warning("⚠️  Success action publish returned False")
            results.append(False)

    except Exception as e:
        logger.error(f"❌ Success action failed: {e}", exc_info=verbose)
        results.append(False)

    # Test 6: Bash command
    logger.info("\n[Test 6] Bash command action")
    try:
        async with action_logger.tool_call(
            "Bash", tool_parameters={"command": "ls -la", "working_directory": "/tmp"}
        ) as action:
            await asyncio.sleep(0.01)
            action.set_result({"exit_code": 0, "success": True})

        logger.info("✓ Bash action published successfully")
        results.append(True)
    except Exception as e:
        logger.error(f"❌ Bash action failed: {e}", exc_info=verbose)
        results.append(False)

    # Report results
    logger.info("\n" + "=" * 60)
    logger.info(f"Results: {sum(results)}/{len(results)} tests passed")

    if all(results):
        logger.info("✅ All publishing tests PASSED")
        logger.info("\nNext steps:")
        logger.info("1. Check Kafka topic: kcat -C -b localhost:29092 -t agent-actions")
        logger.info(
            "2. Verify consumer is running: docker ps | grep agent-actions-consumer"
        )
        logger.info("3. Query database (if consumer running):")
        logger.info(
            f"   SELECT * FROM agent_actions WHERE correlation_id = '{correlation_id}';"
        )
    elif any(results):
        logger.warning("⚠️  Some tests PASSED, some FAILED")
        logger.warning("Check if Kafka is running and accessible")
    else:
        logger.error("❌ All publishing tests FAILED")
        logger.error("Kafka may not be running or accessible")
        logger.error("Check KAFKA_BOOTSTRAP_SERVERS environment variable")

    logger.info("=" * 60)

    return all(results)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Simple test for agent action publishing"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Run test
    success = await test_action_publishing(verbose=args.verbose)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
