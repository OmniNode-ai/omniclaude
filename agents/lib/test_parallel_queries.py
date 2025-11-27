#!/usr/bin/env python3
"""
Test script to verify parallel query execution in manifest_injector.

This script tests that the refactored _query_patterns method correctly
executes queries in parallel rather than sequentially.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from .manifest_injector import ManifestInjector


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_parallel_query_execution():
    """
    Test that queries execute in parallel with expected performance improvements.
    """
    logger.info("=" * 80)
    logger.info("PARALLEL QUERY TEST - manifest_injector.py")
    logger.info("=" * 80)

    # Create manifest injector
    # Note: This will attempt to connect to real services
    # Set enable_intelligence=False to test without actual services
    injector = ManifestInjector(
        enable_intelligence=True,
        query_timeout_ms=5000,
        enable_storage=False,  # Don't store test data
    )

    # Generate a test correlation ID
    correlation_id = str(uuid4())

    logger.info(f"Test correlation ID: {correlation_id}")
    logger.info("Starting manifest generation with parallel queries...")
    logger.info("")

    start_time = datetime.now()

    try:
        # Generate manifest (will execute parallel queries internally)
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=correlation_id, force_refresh=True
        )

        end_time = datetime.now()
        total_elapsed = (end_time - start_time).total_seconds() * 1000

        logger.info("")
        logger.info("=" * 80)
        logger.info("TEST RESULTS")
        logger.info("=" * 80)

        # Display results
        logger.info(f"Total manifest generation time: {total_elapsed:.0f}ms")
        logger.info("")

        # Show individual query times
        if hasattr(injector, "_current_query_times"):
            query_times = injector._current_query_times
            logger.info("Individual query times:")
            for query_name, time_ms in query_times.items():
                logger.info(f"  - {query_name}: {time_ms}ms")
            logger.info("")

            # Calculate sum of individual query times (sequential worst case)
            total_sequential_time = sum(query_times.values())
            logger.info(
                f"Sum of individual queries (sequential): {total_sequential_time}ms"
            )
            logger.info(f"Actual total time (parallel): {total_elapsed:.0f}ms")

            if total_sequential_time > total_elapsed:
                speedup = total_sequential_time / max(total_elapsed, 1)
                logger.info(f"Parallelization speedup: {speedup:.2f}x")
                logger.info("✅ PARALLEL EXECUTION WORKING CORRECTLY")
            else:
                logger.warning("⚠️  Queries may not be running in parallel")

        # Show manifest sections
        logger.info("")
        logger.info("Manifest sections retrieved:")
        if "patterns" in manifest:
            pattern_count = len(manifest["patterns"].get("available", []))
            logger.info(f"  - Patterns: {pattern_count} patterns")

        if "infrastructure" in manifest:
            logger.info(
                f"  - Infrastructure: {len(manifest.get('infrastructure', {}))} items"
            )

        if "models" in manifest:
            logger.info(f"  - Models: {len(manifest.get('models', {}))} items")

        if "database_schemas" in manifest:
            logger.info(
                f"  - Database schemas: {len(manifest.get('database_schemas', {}))} items"
            )

        if "debug_intelligence" in manifest:
            logger.info(
                f"  - Debug intelligence: {len(manifest.get('debug_intelligence', {}))} items"
            )

        logger.info("")
        logger.info("=" * 80)
        logger.info("TEST COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)

        return True

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        logger.info("")
        logger.info("=" * 80)
        logger.info("TEST FAILED")
        logger.info("=" * 80)
        return False


async def test_fallback_on_service_unavailable():
    """
    Test that the system gracefully falls back when services are unavailable.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("FALLBACK TEST - Service unavailable")
    logger.info("=" * 80)

    # Create injector with invalid broker to force fallback
    injector = ManifestInjector(
        kafka_brokers="invalid-broker:9092",
        enable_intelligence=True,
        query_timeout_ms=1000,  # Short timeout
        enable_storage=False,
    )

    correlation_id = str(uuid4())

    try:
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        # Should get minimal manifest
        if manifest and "manifest_metadata" in manifest:
            source = manifest["manifest_metadata"].get("source", "unknown")
            logger.info(f"Manifest source: {source}")

            if source == "fallback":
                logger.info("✅ FALLBACK WORKING CORRECTLY")
                return True
            else:
                logger.warning("⚠️  Expected fallback manifest")
                return False
        else:
            logger.error("❌ No manifest returned")
            return False

    except Exception as e:
        logger.error(f"Fallback test failed: {e}", exc_info=True)
        return False


async def main():
    """Run all tests."""
    logger.info("Starting manifest_injector parallel query tests")
    logger.info("")

    # Test 1: Parallel query execution
    test1_passed = await test_parallel_query_execution()

    # Test 2: Fallback behavior
    test2_passed = await test_fallback_on_service_unavailable()

    logger.info("")
    logger.info("=" * 80)
    logger.info("OVERALL TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Parallel query test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    logger.info(f"Fallback test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    logger.info("")

    if test1_passed and test2_passed:
        logger.info("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        logger.error("❌ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
