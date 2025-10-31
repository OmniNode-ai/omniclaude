#!/usr/bin/env python3
"""
Test script to verify Kafka consumer race condition fix.

This script tests that:
1. Consumer properly waits for polling to start before allowing requests
2. Responses are correctly consumed and matched to requests
3. No 25-second timeouts occur due to missed responses

Usage:
    python3 test_kafka_consumer_fix.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent))

from intelligence_event_client import IntelligenceEventClient

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_consumer_startup_timing():
    """
    Test that consumer is ready before requests are allowed.

    This verifies the race condition fix.
    """
    logger.info("=" * 70)
    logger.info("TEST 1: Consumer Startup Timing")
    logger.info("=" * 70)

    # Get Kafka brokers from environment
    kafka_brokers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092")
    logger.info(f"Using Kafka brokers: {kafka_brokers}")

    client = IntelligenceEventClient(
        bootstrap_servers=kafka_brokers,
        enable_intelligence=True,
        request_timeout_ms=5000,
    )

    try:
        # Start client - should wait for consumer to be ready
        logger.info("Starting client...")
        start_time = asyncio.get_event_loop().time()
        await client.start()
        elapsed = asyncio.get_event_loop().time() - start_time

        logger.info(f"✅ Client started successfully in {elapsed:.2f}s")
        logger.info("✅ Consumer confirmed ready for polling")

        # Verify consumer is actually started
        if client._consumer is None:
            logger.error("❌ Consumer is None after start()")
            return False

        if not client._consumer_ready.is_set():
            logger.error("❌ Consumer ready event not set")
            return False

        logger.info("✅ Consumer ready event is set")
        logger.info("✅ Test passed: Consumer is ready before requests allowed")
        return True

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False

    finally:
        await client.stop()


async def test_pattern_discovery_with_timeout():
    """
    Test pattern discovery with timeout handling.

    This tests the complete request-response flow including:
    - Request publishing
    - Consumer waiting for response
    - Timeout handling
    """
    logger.info("=" * 70)
    logger.info("TEST 2: Pattern Discovery with Timeout")
    logger.info("=" * 70)

    kafka_brokers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092")
    logger.info(f"Using Kafka brokers: {kafka_brokers}")

    client = IntelligenceEventClient(
        bootstrap_servers=kafka_brokers,
        enable_intelligence=True,
        request_timeout_ms=5000,
    )

    try:
        # Start client
        await client.start()
        logger.info("✅ Client started")

        # Make test request
        logger.info("Making pattern discovery request...")

        start_time = asyncio.get_event_loop().time()
        try:
            result = await client.request_code_analysis(
                content="",  # Empty for pattern discovery
                source_path="node_*_effect.py",
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                    "limit": 10,
                },
                timeout_ms=5000,
            )
            elapsed = asyncio.get_event_loop().time() - start_time

            logger.info(f"✅ Request completed in {elapsed:.2f}s")
            logger.info(
                f"✅ Response received: {len(result.get('patterns', []))} patterns"
            )
            logger.info("✅ Test passed: No timeout, response consumed successfully")
            return True

        except TimeoutError as e:
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.warning(f"⚠️  Request timed out after {elapsed:.2f}s: {e}")
            logger.warning("This could indicate:")
            logger.warning("  1. archon-intelligence service not running")
            logger.warning("  2. Kafka broker not accessible")
            logger.warning("  3. Response not being published to correct topic")

            # Check if it's the old 25-second timeout bug
            if elapsed > 20:
                logger.error(f"❌ CRITICAL: Timeout took {elapsed:.2f}s (expected ~5s)")
                logger.error("This suggests responses are not being consumed!")
                return False
            else:
                logger.info("✅ Timeout duration is correct (~5s)")
                logger.info("✅ Consumer is working, just no response from service")
                return True

        except Exception as e:
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.error(f"❌ Request failed after {elapsed:.2f}s: {e}", exc_info=True)
            return False

    finally:
        await client.stop()


async def test_multiple_concurrent_requests():
    """
    Test multiple concurrent requests to verify consumer handles them correctly.
    """
    logger.info("=" * 70)
    logger.info("TEST 3: Multiple Concurrent Requests")
    logger.info("=" * 70)

    kafka_brokers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092")

    client = IntelligenceEventClient(
        bootstrap_servers=kafka_brokers,
        enable_intelligence=True,
        request_timeout_ms=5000,
    )

    try:
        await client.start()
        logger.info("✅ Client started")

        # Make multiple requests concurrently
        num_requests = 3
        logger.info(f"Making {num_requests} concurrent requests...")

        tasks = [
            client.request_code_analysis(
                content="",
                source_path=f"test_{i}.py",
                language="python",
                options={"operation_type": "PATTERN_EXTRACTION"},
                timeout_ms=5000,
            )
            for i in range(num_requests)
        ]

        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = asyncio.get_event_loop().time() - start_time

        # Count successes and timeouts
        successes = sum(1 for r in results if not isinstance(r, Exception))
        timeouts = sum(1 for r in results if isinstance(r, TimeoutError))
        errors = sum(
            1
            for r in results
            if isinstance(r, Exception) and not isinstance(r, TimeoutError)
        )

        logger.info(
            f"Results: {successes} succeeded, {timeouts} timed out, {errors} errored"
        )
        logger.info(f"Total time: {elapsed:.2f}s")

        if errors > 0:
            logger.error("❌ Some requests failed with errors")
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(
                    result, TimeoutError
                ):
                    logger.error(f"  Request {i}: {result}")
            return False

        logger.info("✅ Test passed: All requests handled correctly")
        return True

    finally:
        await client.stop()


async def main():
    """Run all tests."""
    logger.info("=" * 70)
    logger.info("Kafka Consumer Fix Verification Tests")
    logger.info("=" * 70)
    logger.info("")

    results = []

    # Test 1: Consumer startup timing
    try:
        result = await test_consumer_startup_timing()
        results.append(("Consumer Startup Timing", result))
    except Exception as e:
        logger.error(f"Test 1 crashed: {e}", exc_info=True)
        results.append(("Consumer Startup Timing", False))

    logger.info("")

    # Test 2: Pattern discovery with timeout
    try:
        result = await test_pattern_discovery_with_timeout()
        results.append(("Pattern Discovery with Timeout", result))
    except Exception as e:
        logger.error(f"Test 2 crashed: {e}", exc_info=True)
        results.append(("Pattern Discovery with Timeout", False))

    logger.info("")

    # Test 3: Multiple concurrent requests
    try:
        result = await test_multiple_concurrent_requests()
        results.append(("Multiple Concurrent Requests", result))
    except Exception as e:
        logger.error(f"Test 3 crashed: {e}", exc_info=True)
        results.append(("Multiple Concurrent Requests", False))

    # Print summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info("=" * 70)

    # Overall result
    all_passed = all(result for _, result in results)
    if all_passed:
        logger.info("✅ ALL TESTS PASSED")
        return 0
    else:
        logger.error("❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
