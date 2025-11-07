#!/usr/bin/env python3
"""
Simple Slack webhook test.

This script sends a single test message to verify the webhook URL works.

Usage:
    # Set SLACK_WEBHOOK_URL in your .env file (already in .gitignore)
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    python3 agents/lib/test_slack_webhook_simple.py

Requirements:
    - aiohttp (pip install aiohttp)
    - certifi (pip install certifi) - for SSL certificate verification

Security:
    ⚠️ NEVER hardcode webhook URLs in source code!
    - Webhook URLs are secrets that grant access to your Slack workspace
    - Always store in environment variables or .env files (add to .gitignore)
    - If a webhook URL is exposed, revoke it immediately in Slack app settings
"""

import asyncio
import json
import os
import ssl

try:
    import aiohttp
    import certifi
except ImportError:
    print("❌ Missing dependencies. Install with:")
    print("   pip install aiohttp certifi")
    exit(1)

# ⚠️ SECURITY: Load webhook URL from environment variable
# NEVER hardcode webhook URLs in source code!
WEBHOOK_URL = os.environ.get(
    "SLACK_WEBHOOK_URL", ""  # Empty default - user must provide their own webhook URL
)


async def send_test_notification():
    """Send a simple test notification to Slack."""
    # Validate webhook URL is provided
    if not WEBHOOK_URL:
        print("❌ ERROR: SLACK_WEBHOOK_URL environment variable not set!")
        print("\n💡 To fix this:")
        print("   1. Add to your .env file:")
        print(
            '      SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"'
        )
        print("   2. Source the .env file: source .env")
        print('   3. Or export directly: export SLACK_WEBHOOK_URL="..."')
        print("\n⚠️  Get your webhook URL from Slack app settings:")
        print("   https://api.slack.com/apps")
        return False

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
    print(f"   Webhook: {WEBHOOK_URL[:30]}...{WEBHOOK_URL[-10:]}")  # Mask middle part

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
    import sys

    try:
        success = asyncio.run(send_test_notification())
        if success:
            print("\n✅ Test passed!")
            sys.exit(0)  # Success
        else:
            print("\n❌ Test failed: Notification could not be sent", file=sys.stderr)
            sys.exit(1)  # Failure
    except Exception as e:
        print(f"\n❌ Test failed: {e}", file=sys.stderr)
        sys.exit(1)  # Failure
