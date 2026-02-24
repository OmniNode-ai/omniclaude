# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Blocked agent Slack notifier — sends a Slack message when an agent reports blocked state.

Called by emit_agent_status() after successful event emission when state=blocked.
Implements rate limiting, graceful degradation, and fail-open semantics.

INVARIANT: This function MUST fail open and NEVER raise exceptions.
All failures are logged at DEBUG level and return False.

Architecture:
    ```
    emit_agent_status(state="blocked")
        │
        ├── emit_event() → Kafka (observability)
        │
        └── maybe_notify_blocked(payload)
                │
                ├── Guard: state != "blocked" → return False
                ├── Guard: no SLACK_WEBHOOK_URL → return False
                ├── Rate limit check (file-based, 5min window)
                │
                ├── [omnibase_infra available] → HandlerSlackWebhook
                └── [fallback] → urllib.request POST to webhook
    ```

Related Tickets:
    - OMN-1851: Integrate blocked agent status with Slack notifications
    - OMN-1848: Agent Status Kafka Emitter (prerequisite)

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Rate limit file path (overridable via env for testing)
_DEFAULT_RATE_LIMIT_PATH = "/tmp/omniclaude-blocked-rate-limits.json"  # noqa: S108

# Rate limit window: 5 minutes
_RATE_LIMIT_WINDOW_SECONDS = 300

# Prune entries older than 1 hour
_PRUNE_THRESHOLD_SECONDS = 3600


def _get_rate_limit_path() -> str:
    """Return the rate limit file path, from env var or default."""
    return os.environ.get("BLOCKED_RATE_LIMIT_PATH", _DEFAULT_RATE_LIMIT_PATH)


def _compute_rate_key(payload: dict[str, object]) -> str:
    """Compute the rate limiting key for a payload.

    Uses agent_instance_id if truthy, otherwise agent_name:session_id.
    """
    agent_instance_id = payload.get("agent_instance_id")
    if agent_instance_id:
        return str(agent_instance_id)
    agent_name = payload.get("agent_name", "unknown")
    session_id = payload.get("session_id", "unknown")
    return f"{agent_name}:{session_id}"


def _check_and_update_rate_limit(key: str) -> bool:
    """Check if the key is rate-limited, and update the rate limit file.

    Uses file-based advisory locking for atomic read-modify-write.

    Args:
        key: Rate limit key.

    Returns:
        True if the notification should be sent (not rate-limited).
        False if rate-limited.
    """
    rate_limit_path = _get_rate_limit_path()
    now = time.time()

    # Ensure parent directory exists
    Path(rate_limit_path).parent.mkdir(parents=True, exist_ok=True)

    # Open or create the file for read/write
    fd = os.open(rate_limit_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        # Advisory lock (non-blocking to avoid indefinite hang)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.debug("Rate limit file locked by another process, skipping")
            return False

        # Read existing data
        with os.fdopen(os.dup(fd), "r") as f:
            content = f.read()

        if content.strip():
            try:
                data: dict[str, float] = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                data = {}
        else:
            data = {}

        # Check if rate-limited
        last_sent = data.get(key)
        if last_sent is not None and (now - last_sent) < _RATE_LIMIT_WINDOW_SECONDS:
            logger.debug("Rate limited: %s", key)
            return False

        # Update the timestamp for this key
        data[key] = now

        # Prune stale entries (older than 1 hour)
        cutoff = now - _PRUNE_THRESHOLD_SECONDS
        data = {k: v for k, v in data.items() if v > cutoff}

        # Atomic write: write to temp file, then rename over original
        dir_path = str(Path(rate_limit_path).parent)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as tmp_f:
                json.dump(data, tmp_f)
            Path(tmp_path).rename(rate_limit_path)
        except Exception:
            # Clean up temp file on error
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise

        return True

    finally:
        # Release lock and close fd
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _format_slack_message(payload: dict[str, object]) -> str:
    """Format the Slack notification message for a blocked agent.

    Omits lines where the value is None.
    """
    lines = [":warning: Agent Blocked", ""]

    lines.append(f"Agent: {payload.get('agent_name', 'unknown')}")
    lines.append(f"Session: {payload.get('session_id', 'unknown')}")

    current_phase = payload.get("current_phase")
    if current_phase is not None:
        lines.append(f"Phase: {current_phase}")

    current_task = payload.get("current_task")
    if current_task is not None:
        lines.append(f"Task: {current_task}")

    blocking_reason = payload.get("blocking_reason")
    if blocking_reason is not None:
        lines.append("")
        lines.append(f"Reason: {blocking_reason}")

    lines.append("")
    lines.append(f"Correlation ID: {payload.get('correlation_id', 'unknown')}")

    return "\n".join(lines)


def _send_via_handler(webhook_url: str, message: str) -> bool:
    """Send notification via omnibase_infra HandlerSlackWebhook.

    Returns True if sent successfully, False otherwise.
    """
    import asyncio

    from omnibase_infra.handlers.handler_slack_webhook import HandlerSlackWebhook

    handler = HandlerSlackWebhook(webhook_url=webhook_url)

    # Try to use ModelSlackAlert from omnibase_infra
    try:
        from omnibase_infra.handlers.models.model_slack_alert import (
            EnumAlertSeverity,
            ModelSlackAlert,
        )

        alert = ModelSlackAlert(
            severity=EnumAlertSeverity.WARNING,
            message=message,
            title="Agent Blocked",
            details={},
        )
    except ImportError:
        # Fall back to a simple object with the required interface
        from dataclasses import dataclass, field
        from uuid import uuid4

        @dataclass(frozen=True)
        class _FallbackAlert:
            severity: str = "warning"
            message: str = ""
            title: str = "Agent Blocked"
            details: dict[str, str] = field(default_factory=dict)
            correlation_id: object = field(default_factory=uuid4)

        alert = _FallbackAlert(message=message)  # type: ignore[assignment]

    try:
        asyncio.run(asyncio.wait_for(handler.handle(alert), timeout=10.0))
    except TimeoutError:
        logger.debug("HandlerSlackWebhook timed out after 10s")
        return False
    return True


def _send_via_urllib(webhook_url: str, message: str) -> bool:
    """Send notification via stdlib urllib as fallback.

    Returns True if sent successfully, False otherwise.
    """
    payload_json = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        webhook_url,
        data=payload_json,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)  # noqa: S310
    return True


def maybe_notify_blocked(payload: dict[str, object]) -> bool:
    """Send a Slack notification when an agent reports state=blocked.

    Accepts the serialized ModelAgentStatusPayload dict (already serialized
    via .model_dump(mode="json")).

    Guards:
        - Only proceeds if payload state is "blocked"
        - Only proceeds if SLACK_WEBHOOK_URL is configured
        - Rate-limited per agent (5 minute window)

    Args:
        payload: Serialized ModelAgentStatusPayload dict.

    Returns:
        True if notification sent, False otherwise.
        Never raises exceptions.
    """
    try:
        # R2: Guard — only proceed for blocked state
        if payload.get("state") != "blocked":
            return False

        # R3/R6: Check SLACK_WEBHOOK_URL
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            logger.debug("Slack not configured (no SLACK_WEBHOOK_URL)")
            return False

        # R4: Rate limiting
        key = _compute_rate_key(payload)
        if not _check_and_update_rate_limit(key):
            return False

        # R5: Format message
        message = _format_slack_message(payload)

        # R6: Send notification — try handler first, fall back to urllib
        try:
            return _send_via_handler(webhook_url, message)
        except ImportError:
            logger.debug(
                "omnibase_infra not available, falling back to urllib for Slack"
            )
        except Exception:
            logger.debug(
                "HandlerSlackWebhook failed, falling back to urllib", exc_info=True
            )

        try:
            return _send_via_urllib(webhook_url, message)
        except Exception:
            logger.debug("urllib Slack delivery failed", exc_info=True)
            return False

    except Exception:
        # R7: Fail open — never raise
        logger.debug("maybe_notify_blocked failed (fail-open)", exc_info=True)
        return False


__all__ = ["maybe_notify_blocked"]
