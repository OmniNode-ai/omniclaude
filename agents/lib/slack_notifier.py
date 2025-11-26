#!/usr/bin/env python3
"""
Slack Webhook Error Notification System
========================================

Fail-fast error notification system that sends critical errors to Slack
with distributed throttling to prevent spam across multiple instances.

Features:
- Async HTTP POST to Slack webhooks
- Distributed rate limiting via Valkey/Redis (works across containers/instances)
- Automatic throttle key expiration (TTL-based)
- Rich error context (type, message, stack trace, service, timestamp)
- Non-blocking (errors don't break main flow)
- Graceful degradation (fail open if cache unavailable)
- Opt-in (only sends if webhook URL configured)

Throttling Strategy:
- Uses distributed cache (Valkey/Redis) with TTL-based keys
- Max 1 notification per error type per 5 minutes (configurable)
- Works across multiple processes/containers (critical for K8s/multi-worker)
- Falls back to no throttling if cache unavailable (fail open)
- Automatic cleanup via TTL expiration

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

Environment Variables:
    VALKEY_URL: redis://:password@host:port/db (for distributed throttling)
    SLACK_WEBHOOK_URL: Slack webhook URL
    SLACK_NOTIFICATION_THROTTLE_SECONDS: Throttle window (default: 300)

Created: 2025-11-06
Updated: 2025-11-07 (distributed cache support)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# HTTP client imports
try:
    import aiohttp
    import certifi  # For SSL certificate verification

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.warning(
        "aiohttp or certifi not available - Slack notifications disabled. "
        "Install with: pip install aiohttp certifi"
    )

# Distributed cache imports (Valkey/Redis)
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.info(
        "redis library not available - distributed throttling disabled, "
        "throttling will not work across multiple instances. "
        "Install with: pip install redis"
    )

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
    Slack webhook error notification system with distributed throttling.

    Provides fail-fast error notifications to Slack with intelligent
    rate limiting to prevent spam. Notifications are sent asynchronously
    and non-blocking - failures do not affect the main application flow.

    Features:
    - Distributed throttling: Max 1 notification per error type per configurable window
      (works across multiple instances/containers via Valkey/Redis)
    - Rich context: Error type, message, stack trace, service name, timestamp
    - Opt-in: Only sends if SLACK_WEBHOOK_URL is configured
    - Non-blocking: Errors in notification system are logged but don't propagate
    - Graceful degradation: Falls back to no throttling if cache unavailable

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
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack webhook URL (optional, defaults to config/env)
            throttle_seconds: Throttle window in seconds (optional, defaults to config/env)
            logger: Logger instance (optional, defaults to module logger)
        """
        # CRITICAL: Initialize logger FIRST (before any method calls that might use it)
        # This prevents AttributeError if _init_cache() or other methods access self.logger
        self.logger = logger or logging.getLogger(__name__)

        # Initialize simple attributes (no method calls yet)
        # Load webhook URL from config or environment
        self.webhook_url: Optional[str]
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

        # Initialize cache client attribute (will be set by _init_cache)
        self._cache_client: Optional[Any] = None

        # Initialize metrics
        self._notifications_sent = 0
        self._notifications_throttled = 0
        self._notifications_failed = 0

        # NOW call initialization methods (logger is available for use)
        self._init_cache()

        # Log initialization status (after _init_cache so we know cache status)
        if self.webhook_url:
            throttle_mode = "distributed" if self._cache_client else "disabled"
            self.logger.info(
                f"SlackNotifier initialized (throttle: {self.throttle_seconds}s, mode: {throttle_mode})"
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

    def _init_cache(self) -> None:
        """
        Initialize distributed cache client for throttling.

        Attempts to connect to Valkey/Redis for distributed throttling.
        Falls back gracefully if cache unavailable (fail open - no throttling).

        Cache Strategy:
        - Uses TTL-based keys for automatic expiration
        - Key format: slack_throttle:{error_key}
        - TTL: self.throttle_seconds (default 5 minutes)
        - Fail open: No cache = no throttling (notifications sent)
        """
        if not REDIS_AVAILABLE:
            self.logger.debug(
                "Redis library not available - distributed throttling disabled"
            )
            return

        try:
            # Get Valkey URL from config or environment
            valkey_url = None
            if SETTINGS_AVAILABLE:
                valkey_url = settings.valkey_url
            else:
                import os

                valkey_url = os.getenv("VALKEY_URL")

            if not valkey_url:
                self.logger.debug(
                    "VALKEY_URL not configured - distributed throttling disabled"
                )
                return

            # Initialize Redis client (Redis protocol, works with Valkey)
            self._cache_client = redis.StrictRedis.from_url(
                valkey_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

            # Test connection
            self._cache_client.ping()
            self.logger.info(
                f"Connected to distributed cache for throttling: {valkey_url.split('@')[-1]}"
            )

        except Exception as e:
            self.logger.warning(
                f"Could not initialize distributed cache (throttling disabled): {e}"
            )
            self._cache_client = None

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
        Check if notification should be throttled using distributed cache.

        Args:
            error_key: Error key for throttling

        Returns:
            True if should throttle (error sent recently), False if should send

        Cache Strategy:
        - If cache unavailable: return False (fail open - send notification)
        - If key exists in cache: return True (throttle)
        - If key doesn't exist: return False (send notification)
        """
        if not self._cache_client:
            # No cache available - fail open (don't throttle)
            return False

        cache_key = f"slack_throttle:{error_key}"

        try:
            # Check if key exists (within throttle window)
            exists = self._cache_client.exists(cache_key)
            if exists:
                self.logger.debug(
                    f"Throttle cache HIT: {error_key} (within {self.throttle_seconds}s window)"
                )
                return True  # Throttle - error was sent recently

            self.logger.debug(f"Throttle cache MISS: {error_key}")
            return False  # Don't throttle - first occurrence in window

        except Exception as e:
            # Fail open - send notification on cache errors
            self.logger.warning(f"Throttle cache error (fail open): {e}")
            return False

    def _update_throttle_cache(self, error_key: str) -> None:
        """
        Update throttle cache with TTL (distributed cache).

        Sets cache key with automatic expiration after throttle_seconds.
        Only called after successful notification delivery.

        Args:
            error_key: Error key for throttling

        Cache Strategy:
        - Key: slack_throttle:{error_key}
        - Value: "1" (sentinel value, existence is what matters)
        - TTL: self.throttle_seconds (default 5 minutes = 300 seconds)
        - Automatic expiration: Redis/Valkey handles cleanup
        """
        if not self._cache_client:
            # No cache available - nothing to update
            return

        cache_key = f"slack_throttle:{error_key}"

        try:
            # Set key with TTL (throttle_seconds)
            self._cache_client.setex(cache_key, self.throttle_seconds, "1")
            self.logger.debug(
                f"Throttle cache SET: {error_key} (TTL: {self.throttle_seconds}s)"
            )

        except Exception as e:
            # Log but don't fail - notification already sent successfully
            self.logger.warning(f"Failed to update throttle cache (non-fatal): {e}")

    def _build_slack_message(
        self, error: Exception, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build Slack message payload with rich context.

        Sanitizes all PII and sensitive data before building message.

        Args:
            error: Exception instance
            context: Error context

        Returns:
            Slack message payload (dict) with PII sanitized
        """
        # Import PII sanitizer
        try:
            from agents.lib.pii_sanitizer import sanitize_for_slack, sanitize_string

            pii_sanitizer_available = True
        except ImportError:
            self.logger.warning(
                "PII sanitizer not available - sending unsanitized data"
            )
            pii_sanitizer_available = False

        # Sanitize context dictionary (deep sanitization)
        if pii_sanitizer_available:
            sanitized_context = sanitize_for_slack(context, sanitize_all_strings=False)
        else:
            sanitized_context = context

        # Extract context fields (from sanitized context)
        service = sanitized_context.get("service", "unknown")
        operation = sanitized_context.get("operation", "unknown")
        correlation_id = sanitized_context.get("correlation_id", "N/A")

        # Get error details
        error_type = type(error).__name__

        # Sanitize error message (may contain PII)
        error_message = str(error)
        if pii_sanitizer_available:
            error_message = sanitize_string(error_message)
        else:
            error_message = str(error)

        # Get stack trace
        tb_str = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )

        # Sanitize stack trace (may contain file paths with usernames, etc.)
        if pii_sanitizer_available:
            tb_str = sanitize_string(tb_str)

        # Truncate stack trace if too long (Slack has message limits)
        if len(tb_str) > 2000:
            tb_str = tb_str[:2000] + "\n... (truncated)"

        # Build timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build Slack message using Block Kit format
        # Explicitly type the blocks as a mutable list to allow append operations
        blocks: List[Dict[str, Any]] = [
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
        ]

        # Add correlation ID if available
        if correlation_id != "N/A":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Correlation ID:*\n`{correlation_id}`",
                    },
                }
            )

        # Add additional context if available (from sanitized context)
        extra_context = {
            k: v
            for k, v in sanitized_context.items()
            if k not in ("service", "operation", "correlation_id")
        }
        if extra_context:
            # Context is already sanitized, just format it
            context_str = "\n".join(f"• {k}: {v}" for k, v in extra_context.items())
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Additional Context:*\n{context_str}",
                    },
                }
            )

        # Add stack trace (collapsible)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Stack Trace:*\n```{tb_str}```",
                },
            }
        )

        message: Dict[str, Any] = {
            "text": f"🚨 OmniClaude Error Alert: {error_type} in {service}",
            "blocks": blocks,
        }

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
            # Create SSL context with certificate verification
            import ssl

            # Try to use certifi's CA bundle (more reliable)
            # Fall back to system CA bundle if certifi not available
            try:
                import certifi

                ssl_context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ssl_context = ssl.create_default_context()  # Use system CA bundle
                self.logger.warning(
                    "certifi not available, using system CA bundle for SSL verification"
                )

            # Create connector with SSL context
            connector = aiohttp.TCPConnector(ssl=ssl_context)

            async with aiohttp.ClientSession(connector=connector) as session:
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
        Clear all throttle cache entries (useful for testing).

        Removes all slack_throttle:* keys from distributed cache.
        """
        if not self._cache_client:
            self.logger.debug("No cache client - nothing to clear")
            return

        try:
            # Find all throttle keys
            keys = self._cache_client.keys("slack_throttle:*")
            if keys:
                # Delete all found keys
                self._cache_client.delete(*keys)
                self.logger.info(f"Throttle cache cleared: {len(keys)} keys deleted")
            else:
                self.logger.debug("Throttle cache already empty")

        except Exception as e:
            self.logger.warning(f"Failed to clear throttle cache: {e}")


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
