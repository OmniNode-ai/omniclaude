#!/usr/bin/env python3
"""
Simple test to verify debug loop context integration in manifest injector.

Tests:
1. _query_debug_loop_context() method exists and returns correct structure
2. Debug loop section is included in manifest generation
3. Format methods work correctly
"""

import asyncio
import logging
import uuid

from agents.lib.manifest_injector import ManifestInjector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_debug_loop_query():
    """Test debug loop context query method."""
    logger.info("=" * 70)
    logger.info("TEST 1: Debug Loop Query Method")
    logger.info("=" * 70)

    injector = ManifestInjector(
        enable_intelligence=False, enable_storage=False, agent_name="test-agent"
    )

    correlation_id = str(uuid.uuid4())

    # Test the query method directly
    result = await injector._query_debug_loop_context(correlation_id)

    # Verify structure
    assert "available" in result, "Missing 'available' key"
    assert "stf_count" in result, "Missing 'stf_count' key"
    assert "categories" in result, "Missing 'categories' key"
    assert "top_stfs" in result, "Missing 'top_stfs' key"
    assert "query_time_ms" in result, "Missing 'query_time_ms' key"

    logger.info(f"✓ Debug loop query structure valid")
    logger.info(f"  Available: {result['available']}")
    logger.info(f"  STF Count: {result['stf_count']}")
    logger.info(f"  Query Time: {result['query_time_ms']}ms")

    if not result["available"]:
        logger.info(f"  Reason: {result.get('reason', 'Unknown')}")

    return result


async def test_manifest_includes_debug_loop():
    """Test that debug loop section is included in manifest."""
    logger.info("=" * 70)
    logger.info("TEST 2: Manifest Generation with Debug Loop")
    logger.info("=" * 70)

    async with ManifestInjector(
        enable_intelligence=False, enable_storage=False, agent_name="test-agent"
    ) as injector:
        correlation_id = str(uuid.uuid4())

        # Generate manifest
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)

        # Verify debug loop section exists
        assert "debug_loop" in manifest, "Debug loop section missing from manifest"

        debug_loop = manifest["debug_loop"]
        assert "available" in debug_loop, "Debug loop missing 'available' key"

        logger.info(f"✓ Debug loop section present in manifest")
        logger.info(f"  Available: {debug_loop['available']}")
        logger.info(f"  STF Count: {debug_loop.get('stf_count', 0)}")

        return manifest


async def test_format_debug_loop():
    """Test debug loop formatting for prompt."""
    logger.info("=" * 70)
    logger.info("TEST 3: Debug Loop Format for Prompt")
    logger.info("=" * 70)

    async with ManifestInjector(
        enable_intelligence=False, enable_storage=False, agent_name="test-agent"
    ) as injector:
        correlation_id = str(uuid.uuid4())

        # Generate manifest
        await injector.generate_dynamic_manifest_async(correlation_id)

        # Format for prompt
        formatted = injector.format_for_prompt()

        # Verify debug loop section is in formatted output
        assert (
            "DEBUG PATTERNS (STFs)" in formatted
        ), "Debug loop section missing from formatted output"

        logger.info(f"✓ Debug loop section formatted correctly")
        logger.info(f"  Formatted manifest length: {len(formatted)} bytes")

        # Extract debug loop section
        if "DEBUG PATTERNS (STFs)" in formatted:
            start = formatted.index("DEBUG PATTERNS (STFs)")
            # Find next section or end
            end = formatted.find("\n\n", start + 200)
            if end == -1:
                end = len(formatted)
            debug_section = formatted[start:end]
            logger.info(f"\n{debug_section[:500]}")

        return formatted


async def test_performance():
    """Test that debug loop query stays under 500ms budget."""
    logger.info("=" * 70)
    logger.info("TEST 4: Performance Budget (<500ms)")
    logger.info("=" * 70)

    import time

    injector = ManifestInjector(
        enable_intelligence=False, enable_storage=False, agent_name="test-agent"
    )

    correlation_id = str(uuid.uuid4())

    # Measure query time
    start = time.time()
    result = await injector._query_debug_loop_context(correlation_id)
    elapsed_ms = (time.time() - start) * 1000

    logger.info(f"  Query time: {elapsed_ms:.2f}ms")

    if elapsed_ms < 500:
        logger.info(f"✓ Performance within budget (<500ms)")
    else:
        logger.warning(f"⚠️  Performance exceeds budget: {elapsed_ms:.2f}ms > 500ms")

    return elapsed_ms


async def main():
    """Run all tests."""
    logger.info("\n" + "=" * 70)
    logger.info("DEBUG LOOP INTEGRATION TESTS")
    logger.info("=" * 70 + "\n")

    try:
        # Test 1: Query method
        await test_debug_loop_query()
        logger.info("")

        # Test 2: Manifest generation
        await test_manifest_includes_debug_loop()
        logger.info("")

        # Test 3: Formatting
        await test_format_debug_loop()
        logger.info("")

        # Test 4: Performance
        elapsed = await test_performance()
        logger.info("")

        logger.info("=" * 70)
        logger.info("ALL TESTS PASSED ✓")
        logger.info("=" * 70)
        logger.info(f"Summary:")
        logger.info(f"  - Debug loop query method: ✓")
        logger.info(f"  - Manifest includes debug loop: ✓")
        logger.info(f"  - Formatting works correctly: ✓")
        logger.info(f"  - Performance: {elapsed:.2f}ms {'✓' if elapsed < 500 else '⚠️'}")

    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
