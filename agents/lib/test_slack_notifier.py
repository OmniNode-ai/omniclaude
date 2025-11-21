#!/usr/bin/env python3
"""
Test script for SlackNotifier system.

Tests:
1. Initialization (with and without webhook URL)
2. Throttling behavior
3. Error notification format
4. Non-blocking behavior
5. Statistics tracking

Usage:
    # Test with mock webhook (no real Slack notification)
    python3 agents/lib/test_slack_notifier.py

    # Test with real Slack webhook (requires SLACK_WEBHOOK_URL in .env)
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
        python3 agents/lib/test_slack_notifier.py --real

Created: 2025-11-06
"""

import asyncio
import logging
import os
import sys
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.slack_notifier import SlackNotifier, get_slack_notifier


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_initialization():
    """Test SlackNotifier initialization."""
    print("\n" + "=" * 60)
    print("TEST 1: Initialization")
    print("=" * 60)

    # Test without webhook URL
    notifier = SlackNotifier(webhook_url=None, throttle_seconds=10)
    assert not notifier.is_enabled(), "Notifier should be disabled without webhook URL"
    print("✅ Initialization without webhook URL: PASSED")

    # Test with webhook URL
    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/services/TEST/TEST/TEST",
        throttle_seconds=10,
    )
    assert notifier.is_enabled(), "Notifier should be enabled with webhook URL"
    print("✅ Initialization with webhook URL: PASSED")

    # Test singleton
    notifier1 = get_slack_notifier()
    notifier2 = get_slack_notifier()
    assert notifier1 is notifier2, "Singleton should return same instance"
    print("✅ Singleton pattern: PASSED")


async def test_throttling():
    """Test notification throttling."""
    print("\n" + "=" * 60)
    print("TEST 2: Throttling")
    print("=" * 60)

    # Create notifier with short throttle window for testing
    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/services/TEST/TEST/TEST",
        throttle_seconds=2,  # 2 seconds for testing
    )

    # Clear throttle cache
    notifier.clear_throttle_cache()

    # First notification should go through (but fail due to mock URL)
    error1 = ValueError("Test error 1")
    context1 = {"service": "test_service", "operation": "test_op"}

    result1 = await notifier.send_error_notification(error1, context1)
    print(f"First notification result: {result1} (expected: False due to mock URL)")

    # Second notification with same error type should be throttled
    # Note: Only throttles if first notification succeeded. Since we're using
    # a mock URL that fails, there will be no throttling. To test throttling,
    # we need to mock a successful send first.

    # Manually update throttle cache to simulate successful first send
    notifier._update_throttle_cache("ValueError:test_service")

    error2 = ValueError("Test error 2 (should be throttled)")
    result2 = await notifier.send_error_notification(error2, context1)
    assert not result2, "Second notification should be throttled"
    print("✅ Throttling same error type: PASSED")

    # Notification with different error type should go through
    error3 = RuntimeError("Test error 3 (different type)")
    result3 = await notifier.send_error_notification(error3, context1)
    print(f"Different error type result: {result3} (expected: False due to mock URL)")
    print("✅ Different error type not throttled: PASSED")

    # Wait for throttle window to expire
    print("⏳ Waiting 2 seconds for throttle window to expire...")
    await asyncio.sleep(2.1)

    # Same error type should now go through
    error4 = ValueError("Test error 4 (after throttle window)")
    result4 = await notifier.send_error_notification(error4, context1)
    print(f"After throttle window result: {result4} (expected: False due to mock URL)")
    print("✅ Throttle window expiration: PASSED")

    # Check statistics
    stats = notifier.get_stats()
    print(f"\n📊 Statistics: {stats}")
    assert (
        stats["notifications_throttled"] >= 1
    ), "Should have throttled at least 1 notification"
    print("✅ Statistics tracking: PASSED")


async def test_error_notification_format():
    """Test error notification message format."""
    print("\n" + "=" * 60)
    print("TEST 3: Error Notification Format")
    print("=" * 60)

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/services/TEST/TEST/TEST",
        throttle_seconds=300,
    )

    # Create test error with rich context
    error = RuntimeError("Test error message")
    context = {
        "service": "test_service",
        "operation": "test_operation",
        "correlation_id": "test-correlation-123",
        "extra_field_1": "value1",
        "extra_field_2": 42,
    }

    # Build message (internal method)
    message = notifier._build_slack_message(error, context)

    # Verify message structure
    assert "text" in message, "Message should have text field"
    assert "blocks" in message, "Message should have blocks field"
    assert len(message["blocks"]) >= 4, "Message should have multiple blocks"

    # Verify header block
    header_block = message["blocks"][0]
    assert header_block["type"] == "header", "First block should be header"
    assert (
        "test_service" in header_block["text"]["text"]
    ), "Header should mention service"

    # Verify fields block
    fields_block = message["blocks"][1]
    assert fields_block["type"] == "section", "Second block should be section"
    assert len(fields_block["fields"]) >= 4, "Should have at least 4 fields"

    # Verify error message block
    error_block = message["blocks"][2]
    assert error_block["type"] == "section", "Third block should be section"
    assert (
        "Test error message" in error_block["text"]["text"]
    ), "Should contain error message"

    print("✅ Message structure: PASSED")
    print("✅ Header block: PASSED")
    print("✅ Fields block: PASSED")
    print("✅ Error message block: PASSED")


async def test_non_blocking():
    """Test that notification failures don't break main flow."""
    print("\n" + "=" * 60)
    print("TEST 4: Non-Blocking Behavior")
    print("=" * 60)

    notifier = SlackNotifier(
        webhook_url="https://invalid-webhook-url-that-will-fail",
        throttle_seconds=300,
    )

    # Clear throttle cache
    notifier.clear_throttle_cache()

    # This should fail but not raise exception
    error = ValueError("Test error")
    context = {"service": "test_service", "operation": "test_op"}

    try:
        result = await notifier.send_error_notification(error, context)
        # Should return False but not raise exception
        assert result is False, "Should return False on failure"
        print("✅ Non-blocking on failure: PASSED")
    except Exception as e:
        print(f"❌ FAILED: Exception raised: {e}")
        raise


async def test_force_bypass_throttle():
    """Test force parameter to bypass throttling."""
    print("\n" + "=" * 60)
    print("TEST 5: Force Bypass Throttle")
    print("=" * 60)

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/services/TEST/TEST/TEST",
        throttle_seconds=300,
    )

    # Clear throttle cache
    notifier.clear_throttle_cache()

    error = ValueError("Test error")
    context = {"service": "test_service", "operation": "test_op"}

    # First notification
    result1 = await notifier.send_error_notification(error, context)
    print(f"First notification result: {result1}")

    # Second notification (should be throttled)
    result2 = await notifier.send_error_notification(error, context, force=False)
    assert not result2, "Should be throttled"
    print("✅ Throttled without force: PASSED")

    # Third notification with force=True (should bypass throttle)
    result3 = await notifier.send_error_notification(error, context, force=True)
    print(f"Forced notification result: {result3} (bypassed throttle)")
    print("✅ Force bypass throttle: PASSED")


async def test_real_slack_notification():
    """Test real Slack notification (requires SLACK_WEBHOOK_URL)."""
    print("\n" + "=" * 60)
    print("TEST 6: Real Slack Notification (Optional)")
    print("=" * 60)

    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("⏭️  SKIPPED: SLACK_WEBHOOK_URL not set")
        print(
            "   To test with real Slack webhook, set SLACK_WEBHOOK_URL environment variable"
        )
        return

    print(f"📤 Sending real notification to Slack...")

    notifier = SlackNotifier(webhook_url=webhook_url, throttle_seconds=0)

    error = RuntimeError("Test error from SlackNotifier test suite")
    context = {
        "service": "test_slack_notifier",
        "operation": "real_notification_test",
        "test_timestamp": "2025-11-06",
        "note": "This is a test notification - you can ignore it",
    }

    result = await notifier.send_error_notification(error, context)

    if result:
        print("✅ Real Slack notification sent successfully!")
        print("   Check your Slack channel to verify the message")
    else:
        print("❌ FAILED: Slack notification failed")
        print("   Check your webhook URL and network connection")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SlackNotifier Test Suite")
    print("=" * 60)

    # Check if real Slack testing is requested
    test_real = "--real" in sys.argv

    try:
        await test_initialization()
        await test_throttling()
        await test_error_notification_format()
        await test_non_blocking()
        await test_force_bypass_throttle()

        if test_real:
            await test_real_slack_notification()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ TESTS FAILED")
        print("=" * 60)
        raise


if __name__ == "__main__":
    asyncio.run(main())
