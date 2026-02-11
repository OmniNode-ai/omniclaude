#!/usr/bin/env python3
"""Pipeline Slack Notifier - Threaded Slack notifications for ticket-pipeline.

Provides correlation-formatted, per-ticket threaded Slack notifications for
the ticket-pipeline. Uses the omnibase_infra HandlerSlackWebhook for formatting
and delivery, with thread_ts management for grouping pipeline messages.

Architecture:
    ```
    Pipeline Phase
        │
        ├── emit_event() → Kafka (observability, fire-and-forget)
        │
        └── PipelineSlackNotifier.notify()
                │
                ├── [Web API mode] → chat.postMessage (threading)
                │     └── returns thread_ts for state storage
                │
                └── [Webhook mode] → HandlerSlackWebhook (no threading)
                      └── returns None for thread_ts
    ```

    Web API mode (OMN-2157) is activated when SLACK_BOT_TOKEN is configured.
    Falls back to webhook mode (existing infrastructure) otherwise.

Message Format:
    ```
    [OMN-1804][pipeline:local_review][run:abcd-1234]
    Completed — 0 blocking, 3 nits
    ```

Threading:
    - First notification creates a new message (no thread_ts)
    - Response includes ts → stored in pipeline state as slack_thread_ts
    - All subsequent notifications include thread_ts → appear in same thread
    - >3 parallel pipelines stay organized via per-ticket threads

Dependencies:
    - omnibase_infra.handlers.HandlerSlackWebhook (existing, for webhook mode)
    - omnibase_infra.handlers.models.ModelSlackAlert (existing, for payload)
    - OMN-2157 (future, for Web API threading support)

Usage:
    from pipeline_slack_notifier import PipelineSlackNotifier

    notifier = PipelineSlackNotifier(
        ticket_id="OMN-1804",
        run_id="abcd-1234",
    )

    # Send notification (returns thread_ts for state storage)
    thread_ts = await notifier.notify_phase_completed(
        phase="local_review",
        summary="0 blocking, 3 nits",
        thread_ts=state.get("slack_thread_ts"),
    )

    # Store thread_ts in pipeline state
    state["slack_thread_ts"] = thread_ts

Related Tickets:
    - OMN-1970: Slack notification threading for ticket-pipeline
    - OMN-2157: Extend HandlerSlackWebhook with Web API threading
    - OMN-1831: Event-driven Slack notifications via runtime

.. versionadded:: 0.2.2
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# Local Fallback Alert Model (used when omnibase_infra is not available)
# =============================================================================


class AlertSeverity:
    """Severity level constants for pipeline alerts.

    Mirrors EnumAlertSeverity from omnibase_infra but without the dependency.
    Values are lowercase to match EnumAlertSeverity.value (e.g. "warning", "error").
    When omnibase_infra IS available, _create_alert() uses the real enum values.
    When it is NOT available, these string constants are used instead.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PipelineAlert:
    """Local fallback alert model for when omnibase_infra is unavailable.

    Provides the same attribute interface as ModelSlackAlert so that
    handlers (real or mock) can access .severity, .message, .title,
    .details, and .correlation_id uniformly.
    """

    severity: str
    message: str
    title: str
    details: dict[str, str]
    correlation_id: UUID
    thread_ts: str | None = None


# =============================================================================
# Protocol for Slack Handler (DI boundary for OMN-2157)
# =============================================================================


@runtime_checkable
class SlackHandlerProtocol(Protocol):
    """Protocol for Slack message delivery.

    The real implementation comes from omnibase_infra.handlers.HandlerSlackWebhook.
    When OMN-2157 lands, it will add thread_ts support to the same handler.
    For testing, mock this protocol.
    """

    async def handle(self, alert: object) -> object:
        """Send a Slack alert and return the result."""
        ...


# =============================================================================
# Result Types
# =============================================================================


@dataclass(frozen=True)
class NotifyResult:
    """Result of a pipeline Slack notification.

    Attributes:
        success: True if the notification was delivered (or skipped in dry-run).
        thread_ts: Slack thread timestamp for threading subsequent messages.
            None if threading not available (webhook mode) or delivery failed.
        error: Error message if delivery failed.
        dry_run: True if this was a dry-run notification.
    """

    success: bool
    thread_ts: str | None = None
    error: str | None = None
    dry_run: bool = False


# =============================================================================
# Pipeline Slack Notifier
# =============================================================================


class PipelineSlackNotifier:
    """Threaded Slack notifier for ticket-pipeline phases.

    Formats messages with correlation context and manages thread_ts for
    per-ticket message threading.

    Supports two modes:
    1. Webhook mode (current): Uses HandlerSlackWebhook, no threading
    2. Web API mode (OMN-2157): Uses extended handler with thread_ts support

    Graceful degradation:
    - No SLACK_WEBHOOK_URL and no SLACK_BOT_TOKEN: notifications silently skipped
    - Webhook only: notifications sent without threading
    - Bot token: full threading support

    Attributes:
        ticket_id: Linear ticket identifier (e.g., "OMN-1804")
        run_id: Pipeline run identifier (e.g., "abcd-1234")
        dry_run: Whether this is a dry-run pipeline execution
    """

    def __init__(
        self,
        ticket_id: str,
        run_id: str,
        *,
        dry_run: bool = False,
        handler: SlackHandlerProtocol | None = None,
    ) -> None:
        """Initialize the pipeline notifier.

        Args:
            ticket_id: Linear ticket identifier (e.g., "OMN-1804").
            run_id: Pipeline run correlation ID.
            dry_run: If True, prefix messages with [DRY RUN].
            handler: Optional injected Slack handler (for testing/DI).
                If None, creates a real handler from omnibase_infra.
        """
        self.ticket_id = ticket_id
        self.run_id = run_id
        self.dry_run = dry_run
        self._handler = handler or self._create_default_handler()
        self._configured = self._handler is not None

    @staticmethod
    def _create_default_handler() -> SlackHandlerProtocol | None:
        """Create the default Slack handler from omnibase_infra.

        Returns None if omnibase_infra is not available or Slack is not configured.
        """
        webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        bot_token = os.getenv("SLACK_BOT_TOKEN", "")

        if not webhook_url and not bot_token:
            logger.debug(
                "Slack not configured (no SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN)"
            )
            return None

        try:
            from omnibase_infra.handlers.handler_slack_webhook import (
                HandlerSlackWebhook,
            )

            # When OMN-2157 lands, HandlerSlackWebhook will accept bot_token
            # and default_channel params for Web API mode. For now, webhook only.
            return HandlerSlackWebhook(webhook_url=webhook_url or None)
        except ImportError:
            logger.warning(
                "omnibase_infra not available — Slack notifications disabled"
            )
            return None

    def _format_prefix(self, phase: str | None = None) -> str:
        """Format the correlation prefix for a Slack message.

        Format: [OMN-1804][pipeline:local_review][run:abcd-1234]

        Args:
            phase: Pipeline phase name (e.g., "local_review").

        Returns:
            Formatted prefix string.
        """
        parts = [f"[{self.ticket_id}]"]
        if phase:
            parts.append(f"[pipeline:{phase}]")
        parts.append(f"[run:{self.run_id}]")

        prefix = "".join(parts)
        if self.dry_run:
            prefix = f"[DRY RUN] {prefix}"
        return prefix

    def _create_alert(
        self,
        *,
        phase: str | None,
        message: str,
        severity: str = "INFO",
        thread_ts: str | None = None,
        details: dict[str, str] | None = None,
        correlation_id: UUID | None = None,
    ) -> object | None:
        """Create an alert object for Slack delivery.

        Tries to use ModelSlackAlert from omnibase_infra first (production).
        Falls back to the local PipelineAlert dataclass if omnibase_infra
        is not installed (unit test / standalone environment).

        Args:
            severity: One of "INFO", "WARNING", "ERROR", "CRITICAL" (case-insensitive).
                Normalized to uppercase for the EnumAlertSeverity lookup, and to
                lowercase for the local PipelineAlert fallback.

        Returns None only if neither model can be constructed (should not happen).
        """
        prefix = self._format_prefix(phase)
        formatted_message = f"{prefix}\n{message}"

        alert_details: dict[str, str] = {
            "Ticket": self.ticket_id,
            "Run": self.run_id,
        }
        if phase:
            alert_details["Phase"] = phase
        if details:
            alert_details.update(details)

        cid = correlation_id or uuid4()

        # Normalize severity to uppercase for severity_map lookup
        severity_key = severity.upper()

        # --- Try omnibase_infra first (production path) ---
        try:
            from omnibase_infra.handlers.models.model_slack_alert import (
                EnumAlertSeverity,
                ModelSlackAlert,
            )

            severity_map = {
                "INFO": EnumAlertSeverity.INFO,
                "WARNING": EnumAlertSeverity.WARNING,
                "ERROR": EnumAlertSeverity.ERROR,
                "CRITICAL": EnumAlertSeverity.CRITICAL,
            }

            alert_kwargs: dict[str, object] = {
                "severity": severity_map.get(severity_key, EnumAlertSeverity.INFO),
                "message": formatted_message,
                "title": f"{prefix} Pipeline Notification",
                "details": alert_details,
                "correlation_id": cid,
            }

            # Forward-compatible: pass thread_ts if the model accepts it
            # (OMN-2157 will add this field to ModelSlackAlert)
            if thread_ts:
                model_fields = set(ModelSlackAlert.model_fields.keys())
                if "thread_ts" in model_fields:
                    alert_kwargs["thread_ts"] = thread_ts

            return ModelSlackAlert(**alert_kwargs)  # type: ignore[arg-type]

        except ImportError:
            pass

        # --- Fallback: local PipelineAlert dataclass ---
        logger.debug(
            "omnibase_infra models not available — using local PipelineAlert fallback"
        )
        return PipelineAlert(
            severity=severity_key.lower(),
            message=formatted_message,
            title=f"{prefix} Pipeline Notification",
            details=alert_details,
            correlation_id=cid,
            thread_ts=thread_ts,
        )

    async def _send_alert(
        self,
        alert: object,
    ) -> NotifyResult:
        """Send a Slack alert via the handler.

        Args:
            alert: ModelSlackAlert instance.

        Returns:
            NotifyResult with delivery status and thread_ts.
        """
        if self._handler is None:
            return NotifyResult(success=False, error="No Slack handler configured")

        try:
            result = await self._handler.handle(alert)

            # Extract success and thread_ts from result
            # ModelSlackAlertResult has .success and (after OMN-2157) .thread_ts
            success = getattr(result, "success", False)
            thread_ts = getattr(result, "thread_ts", None)
            error = getattr(result, "error", None) if not success else None

            return NotifyResult(
                success=success,
                thread_ts=thread_ts,
                error=error,
            )

        except Exception as e:
            logger.warning(f"Slack notification failed: {e}")
            return NotifyResult(success=False, error=str(e))

    async def notify_phase_completed(
        self,
        phase: str,
        summary: str,
        *,
        thread_ts: str | None = None,
        pr_url: str | None = None,
        nit_count: int = 0,
        blocking_count: int = 0,
        correlation_id: UUID | None = None,
    ) -> str | None:
        """Send a phase completion notification.

        Args:
            phase: Pipeline phase name (e.g., "local_review").
            summary: Human-readable summary of what happened.
            thread_ts: Existing thread timestamp for threading.
            pr_url: PR URL to include in details (if applicable).
            nit_count: Number of nits remaining.
            blocking_count: Number of blocking issues remaining.
            correlation_id: Optional correlation UUID.

        Returns:
            thread_ts for state storage (None if threading not available).
        """
        if not self._configured:
            return thread_ts  # Pass through existing thread_ts

        details: dict[str, str] = {}
        if pr_url:
            details["PR"] = pr_url
        if nit_count:
            details["Nits"] = str(nit_count)
        if blocking_count:
            details["Blocking"] = str(blocking_count)

        message = f"Completed — {summary}"

        alert = self._create_alert(
            phase=phase,
            message=message,
            severity="INFO",
            thread_ts=thread_ts,
            details=details,
            correlation_id=correlation_id,
        )

        if alert is None:
            return thread_ts

        result = await self._send_alert(alert)

        # Also emit event for observability (dual-emission)
        self._emit_event(
            "notification.completed", phase=phase, summary=summary, pr_url=pr_url
        )

        # Return thread_ts: prefer new one from response, fall back to existing
        return result.thread_ts or thread_ts

    async def notify_blocked(
        self,
        phase: str,
        reason: str,
        block_kind: str,
        *,
        thread_ts: str | None = None,
        correlation_id: UUID | None = None,
    ) -> str | None:
        """Send a pipeline blocked notification.

        Args:
            phase: Pipeline phase name where the block occurred.
            reason: Human-readable reason for the block.
            block_kind: Classification (blocked_human_gate, blocked_policy, etc.).
            thread_ts: Existing thread timestamp for threading.
            correlation_id: Optional correlation UUID.

        Returns:
            thread_ts for state storage (None if threading not available).
        """
        if not self._configured:
            return thread_ts

        severity = "ERROR" if block_kind == "failed_exception" else "WARNING"

        details: dict[str, str] = {
            "Block Kind": block_kind,
        }

        message = f"Blocked — {reason}"

        alert = self._create_alert(
            phase=phase,
            message=message,
            severity=severity,
            thread_ts=thread_ts,
            details=details,
            correlation_id=correlation_id,
        )

        if alert is None:
            return thread_ts

        result = await self._send_alert(alert)

        # Also emit event for observability
        self._emit_event(
            "notification.blocked",
            phase=phase,
            reason=reason,
            block_kind=block_kind,
        )

        return result.thread_ts or thread_ts

    async def notify_pipeline_started(
        self,
        *,
        thread_ts: str | None = None,
        correlation_id: UUID | None = None,
    ) -> str | None:
        """Send a pipeline started notification.

        This is the first message — its response thread_ts seeds the thread.

        Args:
            thread_ts: Existing thread timestamp (for resume).
            correlation_id: Optional correlation UUID.

        Returns:
            thread_ts for state storage.
        """
        if not self._configured:
            return thread_ts

        dry_label = " (dry run)" if self.dry_run else ""
        message = f"Pipeline started{dry_label}"

        alert = self._create_alert(
            phase=None,
            message=message,
            severity="INFO",
            thread_ts=thread_ts,
            correlation_id=correlation_id,
        )

        if alert is None:
            return thread_ts

        result = await self._send_alert(alert)
        return result.thread_ts or thread_ts

    def _emit_event(
        self,
        event_type: str,
        *,
        phase: str | None = None,
        summary: str | None = None,
        reason: str | None = None,
        block_kind: str | None = None,
        pr_url: str | None = None,
    ) -> None:
        """Emit a notification event via the emit daemon (best-effort).

        This provides observability through the Kafka event bus, independent
        of the direct Slack delivery.
        """
        try:
            from emit_client_wrapper import emit_event

            payload: dict[str, object] = {
                "ticket_id": self.ticket_id,
                "repo": os.path.basename(os.getcwd()),
                "session_id": os.environ.get("CLAUDE_SESSION_ID", "unknown"),
                "run_id": self.run_id,
            }

            if phase:
                payload["phase"] = phase

            prefix = self._format_prefix(phase)

            if event_type == "notification.completed":
                payload["summary"] = f"{prefix} {summary or 'Completed'}"
                payload["ticket_identifier"] = self.ticket_id
                if pr_url:
                    payload["pr_url"] = pr_url
            elif event_type == "notification.blocked":
                payload["reason"] = f"{prefix} {reason or 'Unknown'}"
                payload["ticket_identifier"] = self.ticket_id
                payload["details"] = [f"block_kind: {block_kind or 'unknown'}"]

            emit_event(event_type=event_type, payload=payload)

        except Exception:
            logger.debug(
                "_emit_event failed (best-effort, non-blocking)", exc_info=True
            )


# =============================================================================
# Sync wrapper for use in pipeline prompt.md (which runs in sync context)
# =============================================================================


def notify_sync(
    notifier: PipelineSlackNotifier,
    method_name: str,
    **kwargs: object,
) -> str | None:
    """Synchronous wrapper for async notifier methods.

    Handles event loop detection: if already in an async context,
    runs in a thread; otherwise creates a new event loop.

    Args:
        notifier: PipelineSlackNotifier instance.
        method_name: Method to call (e.g., "notify_phase_completed").
        **kwargs: Arguments to pass to the method.

    Returns:
        thread_ts from the notification result.
    """
    method = getattr(notifier, method_name)
    coro = method(**kwargs)

    try:
        loop = asyncio.get_running_loop()
        # Already in async context — run in thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=15)
    except RuntimeError:
        # No running loop — safe to create one
        return asyncio.run(coro)


__all__ = [
    "AlertSeverity",
    "NotifyResult",
    "PipelineAlert",
    "PipelineSlackNotifier",
    "SlackHandlerProtocol",
    "notify_sync",
]
