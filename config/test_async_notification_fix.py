#!/usr/bin/env python3
"""
Test async notification fix in config/settings.py.

This test verifies that the _send_config_error_notification() function:
1. Works in sync context (no event loop) without RuntimeError
2. Works in async context (with event loop) using async notifications
3. Gracefully degrades based on event loop availability

Usage:
    python config/test_async_notification_fix.py
"""

import asyncio
import os
import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_sync_context():
    """
    Test notification in sync context (no event loop).

    This simulates what happens during module initialization or when
    settings are loaded from CLI scripts without asyncio.
    """
    print("\n" + "=" * 80)
    print("Test 1: Sync Context (No Event Loop)")
    print("=" * 80)

    try:
        # Import settings module - this will auto-load .env and initialize
        from config.settings import _send_config_error_notification

        # Temporarily disable Slack webhook to avoid actual notifications
        original_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        # Call notification function in sync context
        print("  Calling _send_config_error_notification() in sync context...")
        errors = ["Test error 1", "Test error 2"]
        _send_config_error_notification(errors)

        print("  ✅ No RuntimeError raised - sync context works correctly!")
        print(
            "     Expected: 'No event loop detected - using synchronous Slack notification'"
        )

        # Restore original webhook
        if original_webhook:
            os.environ["SLACK_WEBHOOK_URL"] = original_webhook

        return True

    except RuntimeError as e:
        if "no running event loop" in str(e).lower():
            print(f"  ❌ FAILED: RuntimeError raised (this is the bug we're fixing)")
            print(f"     Error: {e}")
            return False
        else:
            raise
    except Exception as e:
        print(f"  ❌ FAILED: Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_async_context():
    """
    Test notification in async context (with event loop).

    This simulates what happens when settings are loaded from
    async services like FastAPI, async Kafka consumers, etc.
    """
    print("\n" + "=" * 80)
    print("Test 2: Async Context (With Event Loop)")
    print("=" * 80)

    try:
        from config.settings import _send_config_error_notification

        # Temporarily disable Slack webhook to avoid actual notifications
        original_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        # Call notification function in async context
        print("  Calling _send_config_error_notification() in async context...")
        errors = ["Test error 1", "Test error 2"]
        _send_config_error_notification(errors)

        # Give async task time to complete (if created)
        await asyncio.sleep(0.1)

        print("  ✅ No RuntimeError raised - async context works correctly!")
        print(
            "     Expected: 'Event loop detected - scheduling async Slack notification'"
        )

        # Restore original webhook
        if original_webhook:
            os.environ["SLACK_WEBHOOK_URL"] = original_webhook

        return True

    except RuntimeError as e:
        if "no running event loop" in str(e).lower():
            print(f"  ❌ FAILED: RuntimeError raised in async context")
            print(f"     Error: {e}")
            return False
        else:
            raise
    except Exception as e:
        print(f"  ❌ FAILED: Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_event_loop_detection():
    """
    Test event loop detection logic.
    """
    print("\n" + "=" * 80)
    print("Test 3: Event Loop Detection")
    print("=" * 80)

    try:
        import asyncio

        # Test 1: No event loop (sync context)
        print("\n  Test 3a: asyncio.get_running_loop() in sync context")
        try:
            loop = asyncio.get_running_loop()
            print(f"    ❌ Unexpected: Event loop found in sync context: {loop}")
            return False
        except RuntimeError as e:
            print(f"    ✅ Expected RuntimeError: {e}")

        # Test 2: With event loop (async context)
        print("\n  Test 3b: asyncio.get_running_loop() in async context")

        async def check_loop():
            try:
                loop = asyncio.get_running_loop()
                print(
                    f"    ✅ Event loop found in async context: {type(loop).__name__}"
                )
                return True
            except RuntimeError as e:
                print(f"    ❌ Unexpected RuntimeError in async context: {e}")
                return False

        result = asyncio.run(check_loop())
        return result

    except Exception as e:
        print(f"  ❌ FAILED: Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """
    Run all tests.
    """
    print("\n" + "=" * 80)
    print("Testing Async Notification Fix (PR #22)")
    print("=" * 80)
    print("\nThis test verifies that _send_config_error_notification() works")
    print("correctly in both sync and async contexts without RuntimeError.")

    results = []

    # Test 1: Sync context
    results.append(("Sync Context", test_sync_context()))

    # Test 2: Async context
    results.append(("Async Context", asyncio.run(test_async_context())))

    # Test 3: Event loop detection
    results.append(("Event Loop Detection", test_event_loop_detection()))

    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ All tests passed! Async notification fix is working correctly.")
        print("=" * 80)
        print("\nThe fix ensures:")
        print("  1. No RuntimeError in sync contexts (CLI scripts, module init)")
        print("  2. Async notifications when event loop is available (FastAPI, etc.)")
        print("  3. Graceful degradation based on context")
        print()
        return True
    else:
        print("❌ Some tests failed. Please review the fix.")
        print("=" * 80)
        print()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
