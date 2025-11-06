#!/usr/bin/env python3
"""
Slack Webhook Error Notification System
========================================

Fail-fast error notification system that sends critical errors to Slack
with intelligent throttling to prevent spam.

Features:
- Async HTTP POST to Slack webhooks
- Rate limiting (max 1 notification per error type per 5 minutes)
- Rich error context (type, message, stack trace, service, timestamp)
- Non-blocking (errors don't break main flow)
- Opt-in (only sends if webhook URL configured)

Integration:
- Routing failures (Kafka connection errors, routing errors)
- Configuration validation failures
- Database connection errors
- Critical service initialization failures

Usage:
    from agents.lib.slack_notifier import SlackNotifier

    notifier = SlackNotifier()

    try:
        # Your code
        pass
    except Exception as e:
        await notifier.send_error_notification(
            error=e,
            context={
                "service": "routing_event_client",
                "operation": "kafka_connection",
                "correlation_id": "abc-123",
            }
        )
        raise  # Re-raise to maintain normal error flow

Created: 2025-11-06
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# HTTP client imports
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.warning("aiohttp not available - Slack notifications disabled")

# Add project root to path for config import
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Import type-safe configuration
try:
    from config import settings

    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False
    logging.warning(
        "config.settings not available - falling back to environment variables"
    )
    import os

logger = logging.getLogger(__name__)


class SlackNotifier:
    """
    Slack webhook error notification system with throttling.

    Provides fail-fast error notifications to Slack with intelligent
    rate limiting to prevent spam. Notifications are sent asynchronously
    and non-blocking - failures do not affect the main application flow.

    Features:
    - Throttling: Max 1 notification per error type per configurable window
    - Rich context: Error type, message, stack trace, service name, timestamp
    - Opt-in: Only sends if SLACK_WEBHOOK_URL is configured
    - Non-blocking: Errors in notification system are logged but don't propagate

    Usage:
        notifier = SlackNotifier()

        try:
            await some_operation()
        except Exception as e:
            await notifier.send_error_notification(
                error=e,
                context={"service": "my-service", "operation": "kafka_connect"}
            )
            raise  # Re-raise to maintain normal error flow
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        throttle_seconds: Optional[int] = None,
    ):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack webhook URL (optional, defaults to config/env)
            throttle_seconds: Throttle window in seconds (optional, defaults to config/env)
        """
        # Load webhook URL from config or environment
        if webhook_url:
            self.webhook_url = webhook_url
        elif SETTINGS_AVAILABLE:
            self.webhook_url = settings.slack_webhook_url
        else:
            # Fallback to environment variable
            import os

            self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")

        # Load throttle seconds from config or environment
        if throttle_seconds is not None:
            self.throttle_seconds = throttle_seconds
        elif SETTINGS_AVAILABLE:
            self.throttle_seconds = settings.slack_notification_throttle_seconds
        else:
            # Fallback to environment variable or default (5 minutes)
            import os

            self.throttle_seconds = int(
                os.getenv("SLACK_NOTIFICATION_THROTTLE_SECONDS", "300")
            )

        # In-memory throttle cache: {error_key: last_sent_timestamp}
        self._throttle_cache: Dict[str, float] = {}

        # Metrics
        self._notifications_sent = 0
        self._notifications_throttled = 0
        self._notifications_failed = 0

        self.logger = logging.getLogger(__name__)

        # Log initialization status
        if self.webhook_url:
            self.logger.info(
                f"SlackNotifier initialized (throttle: {self.throttle_seconds}s)"
            )
        else:
            self.logger.debug(
                "SlackNotifier initialized but webhook URL not configured - notifications disabled"
            )

    def is_enabled(self) -> bool:
        """
        Check if Slack notifications are enabled.

        Returns:
            True if webhook URL is configured, False otherwise
        """
        return bool(self.webhook_url and AIOHTTP_AVAILABLE)

    async def send_error_notification(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        """
        Send error notification to Slack with throttling.

        Args:
            error: Exception that occurred
            context: Additional context (service, operation, correlation_id, etc.)
            force: If True, bypass throttling (use sparingly)

        Returns:
            True if notification sent successfully, False otherwise

        Example:
            await notifier.send_error_notification(
                error=KafkaError("Connection failed"),
                context={
                    "service": "routing_event_client",
                    "operation": "kafka_connection",
                    "kafka_servers": "192.168.86.200:29092",
                    "correlation_id": "abc-123",
                }
            )
        """
        # Check if notifications are enabled
        if not self.is_enabled():
            self.logger.debug("Slack notifications disabled - skipping")
            return False

        context = context or {}

        # Generate error key for throttling
        error_key = self._generate_error_key(error, context)

        # Check throttling
        if not force and self._should_throttle(error_key):
            self._notifications_throttled += 1
            self.logger.debug(
                f"Notification throttled (error_key: {error_key}, window: {self.throttle_seconds}s)"
            )
            return False

        # Build Slack message
        message = self._build_slack_message(error, context)

        # Send notification asynchronously
        success = await self._send_to_slack(message)

        if success:
            self._notifications_sent += 1
            self._update_throttle_cache(error_key)  # Only update on success
            self.logger.info(
                f"Error notification sent to Slack (error_key: {error_key})"
            )
        else:
            self._notifications_failed += 1
            # Don't update throttle cache on failure - allow retries
            self.logger.warning(
                f"Failed to send notification to Slack (error_key: {error_key})"
            )

        return success

    def _generate_error_key(self, error: Exception, context: Dict[str, Any]) -> str:
        """
        Generate unique key for error throttling.

        Args:
            error: Exception instance
            context: Error context

        Returns:
            Error key string (e.g., "KafkaError:routing_event_client")
        """
        error_type = type(error).__name__
        service = context.get("service", "unknown")
        return f"{error_type}:{service}"

    def _should_throttle(self, error_key: str) -> bool:
        """
        Check if notification should be throttled.

        Args:
            error_key: Error key for throttling

        Returns:
            True if should throttle, False if should send
        """
        current_time = time.time()
        last_sent = self._throttle_cache.get(error_key)

        if last_sent is None:
            # Never sent before
            return False

        elapsed = current_time - last_sent
        return elapsed < self.throttle_seconds

    def _update_throttle_cache(self, error_key: str) -> None:
        """
        Update throttle cache with current timestamp.

        Args:
            error_key: Error key for throttling
        """
        self._throttle_cache[error_key] = time.time()

    def _build_slack_message(
        self, error: Exception, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build Slack message payload with rich context.

        Args:
            error: Exception instance
            context: Error context

        Returns:
            Slack message payload (dict)
        """
        # Extract context fields
        service = context.get("service", "unknown")
        operation = context.get("operation", "unknown")
        correlation_id = context.get("correlation_id", "N/A")

        # Get error details
        error_type = type(error).__name__
        error_message = str(error)

        # Get stack trace
        tb_str = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        # Truncate stack trace if too long (Slack has message limits)
        if len(tb_str) > 2000:
            tb_str = tb_str[:2000] + "\n... (truncated)"

        # Build timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build Slack message using Block Kit format
        message = {
            "text": f"🚨 OmniClaude Error Alert: {error_type} in {service}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 Error in {service}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Error Type:*\n{error_type}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Service:*\n{service}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Operation:*\n{operation}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Timestamp:*\n{timestamp}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error Message:*\n```{error_message}```",
                    },
                },
            ],
        }

        # Add correlation ID if available
        if correlation_id != "N/A":
            message["blocks"].append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Correlation ID:*\n`{correlation_id}`",
                    },
                }
            )

        # Add additional context if available
        extra_context = {
            k: v
            for k, v in context.items()
            if k not in ("service", "operation", "correlation_id")
        }
        if extra_context:
            context_str = "\n".join(f"• {k}: {v}" for k, v in extra_context.items())
            message["blocks"].append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Additional Context:*\n{context_str}",
                    },
                }
            )

        # Add stack trace (collapsible)
        message["blocks"].append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Stack Trace:*\n```{tb_str}```",
                },
            }
        )

        return message

    async def _send_to_slack(self, message: Dict[str, Any]) -> bool:
        """
        Send message to Slack webhook (non-blocking).

        Args:
            message: Slack message payload

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.webhook_url:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=message,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        return True
                    else:
                        self.logger.warning(
                            f"Slack webhook returned non-200 status: {response.status}"
                        )
                        return False

        except asyncio.TimeoutError:
            self.logger.warning("Slack webhook request timed out")
            return False

        except Exception as e:
            self.logger.warning(f"Failed to send Slack notification: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """
        Get notification statistics.

        Returns:
            Dictionary with notification counts
        """
        return {
            "notifications_sent": self._notifications_sent,
            "notifications_throttled": self._notifications_throttled,
            "notifications_failed": self._notifications_failed,
        }

    def clear_throttle_cache(self) -> None:
        """
        Clear throttle cache (useful for testing).
        """
        self._throttle_cache.clear()
        self.logger.debug("Throttle cache cleared")


# Singleton instance for convenience
_notifier_instance: Optional[SlackNotifier] = None


def get_slack_notifier() -> SlackNotifier:
    """
    Get or create singleton SlackNotifier instance.

    Returns:
        SlackNotifier instance

    Example:
        from agents.lib.slack_notifier import get_slack_notifier

        notifier = get_slack_notifier()
        await notifier.send_error_notification(error, context)
    """
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = SlackNotifier()
    return _notifier_instance


__all__ = ["SlackNotifier", "get_slack_notifier"]
