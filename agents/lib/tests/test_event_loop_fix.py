#!/usr/bin/env python3
"""
Test script to verify the event loop lock fix in quality_gate_publisher.py

This script tests that the publisher correctly handles switching between
async and sync publishing contexts without raising RuntimeError.
"""

import asyncio
import sys
from pathlib import Path

# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from quality_gate_publisher import (
    close_producer,
    publish_quality_gate_passed,
    publish_quality_gate_passed_sync,
)


async def test_async_publish():
    """
    Test Case 1a: Async publish

    First part of async-then-sync test.
    """
    print("=" * 60)
    print("Test Case 1: Async → Sync Publishing")
    print("=" * 60)

    print("\n1. Publishing via async (in asyncio.run() event loop)...")
    result = await publish_quality_gate_passed(
        gate_name="test_async_gate",
        correlation_id="test-async-001",
        score=0.95,
        threshold=0.80,
    )
    print(
        f"   Result: {'✅ Success' if result else '❌ Failed (Kafka unavailable - expected)'}"
    )

    # Close the async producer
    await close_producer()
    return True


def test_async_then_sync():
    """
    Test Case 1: Async publish, then sync publish

    This was the failing case - sync publish would create a new event loop
    but try to use a lock bound to the old event loop.
    """
    # First, do an async publish in its own event loop
    asyncio.run(test_async_publish())

    # Now do a sync publish (will create NEW event loop)
    print("\n2. Publishing via sync wrapper (new event loop)...")
    try:
        result = publish_quality_gate_passed_sync(
            gate_name="test_sync_gate",
            correlation_id="test-sync-001",
            score=0.92,
            threshold=0.80,
        )
        print(
            f"   Result: {'✅ Success' if result else '❌ Failed (Kafka unavailable - expected)'}"
        )
        print("\n✅ TEST PASSED: No RuntimeError when switching contexts")
    except RuntimeError as e:
        if "different event loop" in str(e):
            print(f"\n❌ TEST FAILED: RuntimeError raised: {e}")
            return False
        raise

    return True


def test_sync_multiple_times():
    """
    Test Case 2: Multiple sync publishes

    Each sync publish creates a new event loop, so each should get its own lock.
    """
    print("\n" + "=" * 60)
    print("Test Case 2: Multiple Sync Publishing")
    print("=" * 60)

    for i in range(3):
        print(f"\n{i+1}. Publishing via sync wrapper (iteration {i+1})...")
        try:
            result = publish_quality_gate_passed_sync(
                gate_name=f"test_sync_gate_{i}",
                correlation_id=f"test-sync-{i:03d}",
                score=0.90,
                threshold=0.80,
            )
            print(f"   Result: {'✅ Success' if result else '❌ Failed'}")
        except RuntimeError as e:
            if "different event loop" in str(e):
                print(f"\n❌ TEST FAILED: RuntimeError on iteration {i+1}: {e}")
                return False
            raise

    print("\n✅ TEST PASSED: Multiple sync publishes work correctly")
    return True


async def test_concurrent_async():
    """
    Test Case 3: Concurrent async publishes in same event loop

    Should share the same lock and work correctly.
    """
    print("\n" + "=" * 60)
    print("Test Case 3: Concurrent Async Publishing")
    print("=" * 60)

    print("\nPublishing 5 events concurrently...")
    tasks = [
        publish_quality_gate_passed(
            gate_name=f"test_concurrent_gate_{i}",
            correlation_id=f"test-concurrent-{i:03d}",
            score=0.88,
            threshold=0.80,
        )
        for i in range(5)
    ]

    try:
        results = await asyncio.gather(*tasks)
        success_count = sum(1 for r in results if r)
        print(f"   Results: {success_count}/5 succeeded")
        print("\n✅ TEST PASSED: Concurrent async publishes work correctly")
        await close_producer()
        return True
    except RuntimeError as e:
        if "different event loop" in str(e):
            print(f"\n❌ TEST FAILED: RuntimeError in concurrent async: {e}")
            return False
        raise


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Event Loop Lock Fix Verification")
    print("=" * 60)
    print("\nTesting quality_gate_publisher.py event loop handling...\n")

    all_passed = True

    # Test 1: Async then sync (the critical fix)
    test1_passed = test_async_then_sync()
    all_passed = all_passed and test1_passed

    # Test 2: Multiple sync publishes
    test2_passed = test_sync_multiple_times()
    all_passed = all_passed and test2_passed

    # Test 3: Concurrent async
    test3_passed = asyncio.run(test_concurrent_async())
    all_passed = all_passed and test3_passed

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(
        f"Test 1 (Async → Sync):       {'✅ PASSED' if test1_passed else '❌ FAILED'}"
    )
    print(
        f"Test 2 (Multiple Sync):      {'✅ PASSED' if test2_passed else '❌ FAILED'}"
    )
    print(
        f"Test 3 (Concurrent Async):   {'✅ PASSED' if test3_passed else '❌ FAILED'}"
    )
    print("=" * 60)

    if all_passed:
        print("\n✅ ALL TESTS PASSED - Event loop lock fix is working correctly!")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED - Review output above for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
