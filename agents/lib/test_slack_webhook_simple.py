#!/usr/bin/env python3
"""
Simple Slack webhook test.

This script sends a single test message to verify the webhook URL works.

Usage:
    python3 agents/lib/test_slack_webhook_simple.py

Requirements:
    - aiohttp (pip install aiohttp)
    - certifi (pip install certifi) - for SSL certificate verification
"""

import asyncio
import json
import ssl

try:
    import aiohttp
    import certifi
except ImportError:
    print("❌ Missing dependencies. Install with:")
    print("   pip install aiohttp certifi")
    exit(1)

WEBHOOK_URL = (
    "https://hooks.slack.com/services/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"
)


async def send_test_notification():
    """Send a simple test notification to Slack."""
    message = {
        "text": "🧪 Test notification from OmniClaude",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🧪 Test Notification",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Status:* Slack notification system is working!\n*Timestamp:* 2025-11-06 15:15:00 UTC\n*Source:* test_slack_webhook_simple.py",
                },
            },
        ],
    }

    print("📤 Sending test notification to Slack...")
    print(f"   Webhook: {WEBHOOK_URL[:50]}...")

    try:
        # Create SSL context using certifi's certificate bundle
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        # Create connector with proper SSL context
        connector = aiohttp.TCPConnector(ssl=ssl_context)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                WEBHOOK_URL,
                json=message,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    print("✅ SUCCESS! Notification sent to Slack")
                    print("   Check your Slack channel to verify")
                    return True
                else:
                    print(f"❌ FAILED: Slack returned status {response.status}")
                    response_text = await response.text()
                    print(f"   Response: {response_text}")
                    return False

    except Exception as e:
        print(f"❌ FAILED: {e}")
        print("\n💡 Troubleshooting:")
        print("   1. Verify webhook URL is correct")
        print("   2. Check network connectivity")
        print("   3. Install SSL certificates: pip install certifi")
        return False


if __name__ == "__main__":
    asyncio.run(send_test_notification())
