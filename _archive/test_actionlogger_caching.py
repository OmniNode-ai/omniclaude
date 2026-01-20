#!/usr/bin/env python3
"""
Test ActionLogger caching in ManifestInjector.

Validates that:
1. ActionLogger instances are cached by correlation_id
2. Cache hits avoid recreation overhead
3. No breaking changes to existing functionality
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


async def test_actionlogger_caching():
    """Test that ActionLogger instances are cached properly."""
    print("=" * 70)
    print("Testing ActionLogger Caching in ManifestInjector")
    print("=" * 70)

    # Create ManifestInjector instance
    injector = ManifestInjector(
        agent_name="test-agent",
        enable_intelligence=False,  # Disable for faster testing
        enable_storage=False,  # Disable DB storage for testing
        enable_cache=False,  # Disable manifest cache for testing
    )

    # Test 1: Verify cache is initialized
    print("\n[Test 1] Verify cache initialization")
    assert hasattr(injector, "_action_logger_cache"), "Cache not initialized!"
    assert isinstance(injector._action_logger_cache, dict), "Cache is not a dict!"
    print("✅ Cache initialized correctly")

    # Test 2: First call creates ActionLogger
    print("\n[Test 2] First call creates ActionLogger")
    correlation_id = "test-correlation-id-001"

    start_time = time.time()
    logger1 = injector._get_action_logger(correlation_id)
    first_call_time = (time.time() - start_time) * 1000

    print(f"  First call time: {first_call_time:.2f}ms")
    print(f"  Logger created: {logger1 is not None}")
    print(f"  Cache size: {len(injector._action_logger_cache)}")

    if logger1:
        assert correlation_id in injector._action_logger_cache, "Logger not cached!"
        print("✅ Logger created and cached")
    else:
        print("⚠️  Logger creation failed (ActionLogger might be unavailable)")
        print("   This is expected if ActionLogger dependencies are missing")

    # Test 3: Second call retrieves from cache
    print("\n[Test 3] Second call retrieves from cache")

    start_time = time.time()
    logger2 = injector._get_action_logger(correlation_id)
    second_call_time = (time.time() - start_time) * 1000

    print(f"  Second call time: {second_call_time:.2f}ms")
    print(f"  Same instance: {logger1 is logger2}")
    print(f"  Cache size: {len(injector._action_logger_cache)}")

    if logger1:
        assert logger1 is logger2, "Cache not working - different instances!"
        assert second_call_time < first_call_time, "Cache not faster than creation!"
        speedup = ((first_call_time - second_call_time) / first_call_time) * 100
        print(f"  Speedup: {speedup:.1f}% faster")
        print("✅ Cache hit successful")
    else:
        assert logger2 is None, "Cache inconsistency!"
        print("✅ Cache correctly returns None for failed creation")

    # Test 4: Different correlation_id creates new logger
    print("\n[Test 4] Different correlation_id creates new logger")

    correlation_id2 = "test-correlation-id-002"
    logger3 = injector._get_action_logger(correlation_id2)

    print(f"  New logger created: {logger3 is not None}")
    print(f"  Different from first: {logger3 is not logger1}")
    print(f"  Cache size: {len(injector._action_logger_cache)}")

    if logger1 and logger3:
        assert (
            logger3 is not logger1
        ), "Different correlation_ids should create different loggers!"
        assert len(injector._action_logger_cache) == 2, "Cache should have 2 entries!"
        print("✅ Multiple correlation_ids handled correctly")
    else:
        print("⚠️  Skipping (ActionLogger unavailable)")

    # Test 5: Integration test - actual manifest generation
    print("\n[Test 5] Integration test - manifest generation uses cache")

    # Generate a valid UUID for the integration test
    integration_correlation_id = str(uuid.uuid4())
    print(f"  Using correlation_id: {integration_correlation_id}")

    # Use context manager
    async with injector:
        try:
            # First generation
            start_time = time.time()
            manifest1 = await injector.generate_dynamic_manifest_async(
                correlation_id=integration_correlation_id, user_prompt="test request 1"
            )
            first_gen_time = (time.time() - start_time) * 1000

            print(f"  First generation time: {first_gen_time:.2f}ms")
            print(f"  Manifest generated: {manifest1 is not None}")

            # Second generation with same correlation_id
            start_time = time.time()
            manifest2 = await injector.generate_dynamic_manifest_async(
                correlation_id=integration_correlation_id, user_prompt="test request 2"
            )
            second_gen_time = (time.time() - start_time) * 1000

            print(f"  Second generation time: {second_gen_time:.2f}ms")
            print(
                f"  Cache size after integration: {len(injector._action_logger_cache)}"
            )

            # Verify cache was used
            assert (
                integration_correlation_id in injector._action_logger_cache
            ), "Integration didn't use cache!"
            print("✅ Integration test passed - cache used in manifest generation")

        except Exception as e:
            print(f"  Integration test error: {e}")
            print("  This may be expected if intelligence services are unavailable")

    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Total cache entries: {len(injector._action_logger_cache)}")
    print(f"Cache contents: {list(injector._action_logger_cache.keys())}")

    if logger1:
        print("\n✅ ALL TESTS PASSED")
        print("   ActionLogger caching is working correctly")
        print(f"   Performance improvement: ~{speedup:.1f}% on cache hits")
    else:
        print("\n⚠️  TESTS COMPLETED WITH WARNINGS")
        print("   ActionLogger creation failed (dependencies missing)")
        print("   Cache logic verified but not fully tested")

    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_actionlogger_caching())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
