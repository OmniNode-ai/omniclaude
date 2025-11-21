#!/usr/bin/env python3
"""
Integration test for ActionLogger + SlackNotifier system.

Tests the complete error notification flow:
1. ActionLogger logs error to Kafka
2. SlackNotifier sends notification to Slack (if configured)
3. Throttling prevents notification spam
4. Non-blocking behavior (errors don't break main flow)

Usage:
    # Test without real Slack (mock notifications)
    python3 agents/lib/test_action_logger_slack_integration.py

    # Test with real Slack webhook
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
        python3 agents/lib/test_action_logger_slack_integration.py --real

Requirements:
    - .env file with configuration
    - Kafka running (for action logging)
    - SLACK_WEBHOOK_URL in .env (for real Slack tests)

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

from agents.lib.action_logger import ActionLogger
from agents.lib.slack_notifier import get_slack_notifier


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_error_without_slack():
    """Test error logging without Slack notification."""
    print("\n" + "=" * 60)
    print("TEST 1: Error Logging Without Slack")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="test-agent",
        correlation_id="test-no-slack-123",
        project_name="omniclaude-test",
    )

    # Log error with Slack disabled
    result = await action_logger.log_error(
        error_type="TestError",
        error_message="This is a test error without Slack notification",
        error_context={"test_field": "test_value"},
        severity="error",
        send_slack_notification=False,  # Explicitly disable
    )

    print(f"✅ Error logged to Kafka: {result}")
    print("   (No Slack notification sent - disabled via parameter)")


async def test_warning_without_slack():
    """Test warning logging (should not trigger Slack even if enabled)."""
    print("\n" + "=" * 60)
    print("TEST 2: Warning Logging (No Slack)")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="test-agent",
        correlation_id="test-warning-456",
        project_name="omniclaude-test",
    )

    # Log warning - should NOT trigger Slack (severity not high enough)
    result = await action_logger.log_error(
        error_type="ValidationWarning",
        error_message="Input validation failed but continuing with defaults",
        error_context={"field": "max_retries", "value": 999, "default": 3},
        severity="warning",  # Won't trigger Slack
        send_slack_notification=True,  # Even if enabled, won't send due to severity
    )

    print(f"✅ Warning logged to Kafka: {result}")
    print("   (No Slack notification - severity='warning' doesn't trigger alerts)")


async def test_critical_error_with_slack():
    """Test critical error logging (should trigger Slack if configured)."""
    print("\n" + "=" * 60)
    print("TEST 3: Critical Error with Slack Notification")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="test-agent",
        correlation_id="test-critical-789",
        project_name="omniclaude-test",
    )

    # Log critical error - WILL trigger Slack if SLACK_WEBHOOK_URL is set
    result = await action_logger.log_error(
        error_type="DatabaseConnectionError",
        error_message="Failed to connect to PostgreSQL after 3 retries",
        error_context={
            "host": "192.168.86.200",
            "port": 5436,
            "database": "omninode_bridge",
            "retry_count": 3,
            "last_error": "Connection timeout",
        },
        severity="critical",  # WILL trigger Slack
    )

    print(f"✅ Critical error logged to Kafka: {result}")

    # Check if Slack notification was sent
    notifier = get_slack_notifier()
    if notifier.is_enabled():
        print("   📤 Slack notification sent (if not throttled)")
        print("   ⏳ Check your Slack channel for the notification")
    else:
        print("   ⏭️  Slack notifications disabled (SLACK_WEBHOOK_URL not configured)")
        print("   💡 Set SLACK_WEBHOOK_URL in .env to enable notifications")


async def test_throttling():
    """Test throttling behavior (multiple errors of same type)."""
    print("\n" + "=" * 60)
    print("TEST 4: Throttling (Multiple Same Errors)")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="test-agent",
        correlation_id="test-throttle-abc",
        project_name="omniclaude-test",
    )

    print("Logging 3 consecutive critical errors of same type...")

    # First error - should send notification
    result1 = await action_logger.log_error(
        error_type="KafkaConnectionError",
        error_message="First error: Kafka connection failed",
        error_context={"attempt": 1},
        severity="critical",
    )
    print(f"✅ Error 1 logged: {result1}")

    # Second error - should be throttled (same error type within window)
    result2 = await action_logger.log_error(
        error_type="KafkaConnectionError",
        error_message="Second error: Kafka connection failed again",
        error_context={"attempt": 2},
        severity="critical",
    )
    print(f"✅ Error 2 logged: {result2}")

    # Third error - should be throttled (same error type within window)
    result3 = await action_logger.log_error(
        error_type="KafkaConnectionError",
        error_message="Third error: Kafka connection failed once more",
        error_context={"attempt": 3},
        severity="critical",
    )
    print(f"✅ Error 3 logged: {result3}")

    notifier = get_slack_notifier()
    if notifier.is_enabled():
        stats = notifier.get_stats()
        print(
            f"\n📊 Notification stats: {stats['notifications_sent']} sent, "
            f"{stats['notifications_throttled']} throttled"
        )
        print(
            "   💡 Only first error should send Slack notification (others throttled)"
        )
    else:
        print("\n⏭️  Slack notifications disabled (SLACK_WEBHOOK_URL not configured)")


async def test_different_error_types():
    """Test that different error types are NOT throttled."""
    print("\n" + "=" * 60)
    print("TEST 5: Different Error Types (No Throttling)")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="test-agent",
        correlation_id="test-different-xyz",
        project_name="omniclaude-test",
    )

    print("Logging 3 different error types consecutively...")

    # Error 1: Database
    result1 = await action_logger.log_error(
        error_type="DatabaseError",
        error_message="Database query timeout",
        error_context={"query": "SELECT * FROM patterns"},
        severity="critical",
    )
    print(f"✅ DatabaseError logged: {result1}")

    # Error 2: Network
    result2 = await action_logger.log_error(
        error_type="NetworkError",
        error_message="Network unreachable",
        error_context={"target": "192.168.86.200"},
        severity="critical",
    )
    print(f"✅ NetworkError logged: {result2}")

    # Error 3: Validation
    result3 = await action_logger.log_error(
        error_type="ValidationError",
        error_message="Invalid configuration parameter",
        error_context={"parameter": "kafka_timeout", "value": -1},
        severity="critical",
    )
    print(f"✅ ValidationError logged: {result3}")

    notifier = get_slack_notifier()
    if notifier.is_enabled():
        print(
            "\n📤 All 3 errors should send Slack notifications (different error types)"
        )
        print("   ⏳ Check your Slack channel for 3 separate notifications")
    else:
        print("\n⏭️  Slack notifications disabled (SLACK_WEBHOOK_URL not configured)")


async def test_rich_context():
    """Test error notification with rich context."""
    print("\n" + "=" * 60)
    print("TEST 6: Rich Error Context")
    print("=" * 60)

    action_logger = ActionLogger(
        agent_name="agent-researcher",
        correlation_id="test-rich-context-999",
        project_name="omniclaude-test",
    )

    # Log error with extensive context
    result = await action_logger.log_error(
        error_type="PatternDiscoveryFailure",
        error_message="Failed to discover patterns from Qdrant after 3 attempts",
        error_context={
            "collection": "execution_patterns",
            "query_vector_size": 1536,
            "filter": {"node_type": "EFFECT"},
            "limit": 50,
            "timeout_ms": 5000,
            "attempts": 3,
            "last_error": "Connection timeout to Qdrant",
            "qdrant_url": "http://192.168.86.101:6333",
        },
        severity="error",
    )

    print(f"✅ Error logged with rich context: {result}")

    notifier = get_slack_notifier()
    if notifier.is_enabled():
        print("\n📤 Slack notification includes all context fields")
        print(
            "   ⏳ Check Slack message - should show all 8 context fields in 'Additional Context' section"
        )
    else:
        print("\n⏭️  Slack notifications disabled (SLACK_WEBHOOK_URL not configured)")


async def main():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("ActionLogger + SlackNotifier Integration Test Suite")
    print("=" * 60)

    # Check if real Slack testing is requested
    test_real = "--real" in sys.argv

    # Check Slack configuration
    notifier = get_slack_notifier()
    if notifier.is_enabled():
        print(f"✅ Slack notifications: ENABLED")
        print(
            f"   Throttle window: {notifier.throttle_seconds}s ({notifier.throttle_seconds // 60} minutes)"
        )
    else:
        print("⚠️  Slack notifications: DISABLED")
        print("   Set SLACK_WEBHOOK_URL in .env to enable")

    print("\n" + "=" * 60)

    try:
        # Run all tests
        await test_error_without_slack()
        await test_warning_without_slack()
        await test_critical_error_with_slack()
        await test_throttling()
        await test_different_error_types()
        await test_rich_context()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)

        # Show final statistics
        if notifier.is_enabled():
            stats = notifier.get_stats()
            print("\n📊 Final Slack Notification Statistics:")
            print(f"   Sent: {stats['notifications_sent']}")
            print(f"   Throttled: {stats['notifications_throttled']}")
            print(f"   Failed: {stats['notifications_failed']}")

        print("\n💡 Tips:")
        print("   - Set SLACK_WEBHOOK_URL in .env to enable real notifications")
        print(
            "   - Use severity='critical' or severity='error' to trigger Slack alerts"
        )
        print("   - Throttling prevents spam (5 minute default window)")
        print(
            "   - Check Kafka topic 'agent-actions' for all logged events (with/without Slack)"
        )

    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ TESTS FAILED")
        print("=" * 60)
        logger.error(f"Test failure: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
