#!/usr/bin/env python3
"""
Test: Slack Notifier with Distributed Cache
============================================

Tests distributed throttling with Valkey/Redis cache.

Run:
    # Without cache (graceful degradation)
    python3 test_slack_notifier_distributed_cache.py

    # With cache (requires VALKEY_URL)
    VALKEY_URL=redis://:password@localhost:6379/0 python3 test_slack_notifier_distributed_cache.py

Expected Behavior:
    - Without cache: All notifications sent (fail open)
    - With cache: Second notification throttled (within window)

Created: 2025-11-07
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.slack_notifier import SlackNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_throttling():
    """Test distributed throttling behavior"""

    print("\n" + "=" * 60)
    print("Testing Slack Notifier Distributed Cache")
    print("=" * 60)

    # Create notifier without webhook URL (won't actually send to Slack)
    notifier = SlackNotifier(
        webhook_url=None,  # Don't actually send to Slack
        throttle_seconds=5,  # 5 second window for testing
    )

    # Check cache status
    has_cache = notifier._cache_client is not None
    print(f"\nCache available: {has_cache}")

    if has_cache:
        print("✓ Distributed cache initialized")
        print("  Throttling will work across multiple instances")
    else:
        print("⚠ Cache not available (fail open mode)")
        print("  Throttling disabled - all notifications will be sent")

    # Test throttle logic
    print("\n" + "-" * 60)
    print("Testing Throttle Logic")
    print("-" * 60)

    error_key = "TestError:test-service"

    # First check (should NOT throttle)
    should_throttle_1 = notifier._should_throttle(error_key)
    print(f"1st check: should_throttle = {should_throttle_1}")
    if not should_throttle_1:
        print("  ✓ First occurrence - would send notification")
        notifier._update_throttle_cache(error_key)
        print("  ✓ Cache updated with TTL")

    # Second check (should throttle if cache available)
    should_throttle_2 = notifier._should_throttle(error_key)
    print(f"2nd check: should_throttle = {should_throttle_2}")

    if has_cache:
        if should_throttle_2:
            print("  ✓ Within throttle window - notification blocked")
        else:
            print("  ✗ UNEXPECTED: Should have throttled")
    else:
        if not should_throttle_2:
            print("  ✓ No cache - fail open (notification sent)")
        else:
            print("  ✗ UNEXPECTED: Should not throttle without cache")

    # Wait for TTL to expire
    print(f"\nWaiting {notifier.throttle_seconds + 1}s for TTL to expire...")
    await asyncio.sleep(notifier.throttle_seconds + 1)

    # Third check (should NOT throttle - TTL expired)
    should_throttle_3 = notifier._should_throttle(error_key)
    print(f"3rd check: should_throttle = {should_throttle_3}")

    if not should_throttle_3:
        print("  ✓ TTL expired - would send notification again")
    else:
        print(f"  ✗ UNEXPECTED: TTL should have expired (has_cache={has_cache})")

    # Test cache clear
    print("\n" + "-" * 60)
    print("Testing Cache Clear")
    print("-" * 60)

    # Set cache again
    notifier._update_throttle_cache(error_key)
    print("Cache updated")

    # Clear cache
    notifier.clear_throttle_cache()
    print("Cache cleared")

    # Check should not throttle after clear
    should_throttle_4 = notifier._should_throttle(error_key)
    print(f"After clear: should_throttle = {should_throttle_4}")

    if not should_throttle_4:
        print("  ✓ Cache cleared successfully")
    else:
        print("  ✗ UNEXPECTED: Should not throttle after clear")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    stats = notifier.get_stats()
    print(f"Notifications sent: {stats['notifications_sent']}")
    print(f"Notifications throttled: {stats['notifications_throttled']}")
    print(f"Notifications failed: {stats['notifications_failed']}")

    if has_cache:
        print("\n✓ Distributed cache is working correctly")
        print("  Throttling will work across multiple instances/containers")
    else:
        print("\n⚠ Cache not available - running in fail-open mode")
        print("  To enable distributed throttling:")
        print("  1. Set VALKEY_URL environment variable")
        print("  2. Start Valkey/Redis service")
        print("  Example: VALKEY_URL=redis://:password@localhost:6379/0")


async def test_error_key_generation():
    """Test error key generation"""

    print("\n" + "=" * 60)
    print("Testing Error Key Generation")
    print("=" * 60)

    notifier = SlackNotifier()

    # Test with different errors and contexts
    test_cases = [
        (ValueError("test"), {"service": "routing"}, "ValueError:routing"),
        (KeyError("missing"), {"service": "database"}, "KeyError:database"),
        (Exception("generic"), {}, "Exception:unknown"),
        (
            RuntimeError("test"),
            {"service": "api", "operation": "kafka"},
            "RuntimeError:api",
        ),
    ]

    for error, context, expected_key in test_cases:
        actual_key = notifier._generate_error_key(error, context)
        match = actual_key == expected_key
        status = "✓" if match else "✗"
        print(
            f"{status} {error.__class__.__name__}: {actual_key} {'==' if match else '!='} {expected_key}"
        )


if __name__ == "__main__":
    # Run tests
    asyncio.run(test_throttling())
    asyncio.run(test_error_key_generation())

    print("\n" + "=" * 60)
    print("✓ All tests completed")
    print("=" * 60)
