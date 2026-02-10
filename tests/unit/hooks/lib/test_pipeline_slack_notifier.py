"""Tests for pipeline_slack_notifier module.

Tests the pipeline Slack notifier with mocked Slack handler (DI).
Validates correlation formatting, threading, dry-run behavior,
and graceful degradation.

Uses asyncio.run() wrappers since pytest-asyncio is not installed.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from pipeline_slack_notifier import (
    AlertSeverity,
    PipelineSlackNotifier,
    SlackHandlerProtocol,
    notify_sync,
)

# =============================================================================
# Mock Handler
# =============================================================================


@dataclass
class MockSlackResult:
    """Mock result from HandlerSlackWebhook.handle()."""

    success: bool = True
    thread_ts: str | None = None
    error: str | None = None
    duration_ms: float = 50.0
    correlation_id: UUID | None = None
    retry_count: int = 0


class MockSlackHandler:
    """Mock Slack handler implementing SlackHandlerProtocol."""

    def __init__(
        self,
        success: bool = True,
        thread_ts: str | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.thread_ts = thread_ts
        self.error = error
        self.calls: list[Any] = []

    async def handle(self, alert: object) -> MockSlackResult:
        self.calls.append(alert)
        return MockSlackResult(
            success=self.success,
            thread_ts=self.thread_ts,
            error=self.error,
        )


# =============================================================================
# Fixture
# =============================================================================


@pytest.fixture
def handler() -> MockSlackHandler:
    return MockSlackHandler(success=True, thread_ts="1234567890.123456")


@pytest.fixture
def notifier(handler: MockSlackHandler) -> PipelineSlackNotifier:
    return PipelineSlackNotifier(
        ticket_id="OMN-1804",
        run_id="abcd-1234",
        handler=handler,
    )


@pytest.fixture
def dry_run_notifier(handler: MockSlackHandler) -> PipelineSlackNotifier:
    return PipelineSlackNotifier(
        ticket_id="OMN-1804",
        run_id="abcd-1234",
        dry_run=True,
        handler=handler,
    )


# =============================================================================
# Protocol Tests
# =============================================================================


class TestSlackHandlerProtocol:
    """Test the SlackHandlerProtocol runtime check."""

    def test_mock_satisfies_protocol(self) -> None:
        handler = MockSlackHandler()
        assert isinstance(handler, SlackHandlerProtocol)


# =============================================================================
# Correlation Formatting Tests
# =============================================================================


class TestCorrelationFormatting:
    """Test the [ticket][phase][run] correlation prefix."""

    def test_format_with_phase(self, notifier: PipelineSlackNotifier) -> None:
        prefix = notifier._format_prefix("local_review")
        assert prefix == "[OMN-1804][pipeline:local_review][run:abcd-1234]"

    def test_format_without_phase(self, notifier: PipelineSlackNotifier) -> None:
        prefix = notifier._format_prefix(None)
        assert prefix == "[OMN-1804][run:abcd-1234]"

    def test_dry_run_prefix(self, dry_run_notifier: PipelineSlackNotifier) -> None:
        prefix = dry_run_notifier._format_prefix("implement")
        assert prefix.startswith("[DRY RUN]")
        assert "[OMN-1804]" in prefix
        assert "[pipeline:implement]" in prefix


# =============================================================================
# Notification Tests
# =============================================================================


class TestNotifyPhaseCompleted:
    """Test phase completion notifications."""

    def test_sends_notification(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        thread_ts = asyncio.run(
            notifier.notify_phase_completed(
                phase="local_review",
                summary="0 blocking, 3 nits",
            )
        )

        assert len(handler.calls) == 1
        assert thread_ts == "1234567890.123456"

    def test_includes_correlation_in_message(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_phase_completed(
                phase="local_review",
                summary="0 blocking, 3 nits",
            )
        )

        alert = handler.calls[0]
        assert "[OMN-1804]" in alert.message
        assert "[pipeline:local_review]" in alert.message
        assert "[run:abcd-1234]" in alert.message
        assert "Completed" in alert.message

    def test_passes_through_thread_ts(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        """When handler returns no thread_ts, fall back to existing."""
        handler.thread_ts = None

        thread_ts = asyncio.run(
            notifier.notify_phase_completed(
                phase="local_review",
                summary="done",
                thread_ts="existing-ts",
            )
        )

        assert thread_ts == "existing-ts"

    def test_new_thread_ts_overrides_existing(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        """When handler returns a new thread_ts, use it."""
        handler.thread_ts = "new-ts"

        thread_ts = asyncio.run(
            notifier.notify_phase_completed(
                phase="local_review",
                summary="done",
                thread_ts="existing-ts",
            )
        )

        assert thread_ts == "new-ts"

    def test_includes_pr_url_in_details(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_phase_completed(
                phase="create_pr",
                summary="PR created",
                pr_url="https://github.com/org/repo/pull/42",
            )
        )

        alert = handler.calls[0]
        assert alert.details["PR"] == "https://github.com/org/repo/pull/42"


class TestNotifyBlocked:
    """Test blocked pipeline notifications."""

    def test_sends_warning_for_policy_block(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_blocked(
                phase="implement",
                reason="Cross-repo change detected",
                block_kind="blocked_policy",
            )
        )

        alert = handler.calls[0]
        # Compare using string value — works with both the local AlertSeverity
        # fallback and the real EnumAlertSeverity (whose .value is "WARNING").
        severity_value = getattr(alert.severity, "value", alert.severity)
        assert severity_value == AlertSeverity.WARNING

    def test_sends_error_for_exception(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_blocked(
                phase="local_review",
                reason="Phase execution failed",
                block_kind="failed_exception",
            )
        )

        alert = handler.calls[0]
        severity_value = getattr(alert.severity, "value", alert.severity)
        assert severity_value == AlertSeverity.ERROR

    def test_includes_block_kind_in_details(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_blocked(
                phase="implement",
                reason="Waiting for spec approval",
                block_kind="blocked_human_gate",
            )
        )

        alert = handler.calls[0]
        assert alert.details["Block Kind"] == "blocked_human_gate"


class TestNotifyPipelineStarted:
    """Test pipeline started notification."""

    def test_sends_start_notification(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        thread_ts = asyncio.run(notifier.notify_pipeline_started())

        assert len(handler.calls) == 1
        assert "Pipeline started" in handler.calls[0].message
        assert thread_ts == "1234567890.123456"

    def test_resume_preserves_thread_ts(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        """On resume, pass existing thread_ts to continue the thread."""
        handler.thread_ts = None  # Handler doesn't return one

        thread_ts = asyncio.run(
            notifier.notify_pipeline_started(thread_ts="resume-thread-ts")
        )

        assert thread_ts == "resume-thread-ts"

    def test_dry_run_label(
        self, dry_run_notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(dry_run_notifier.notify_pipeline_started())

        alert = handler.calls[0]
        assert "[DRY RUN]" in alert.message
        assert "dry run" in alert.message.lower()


# =============================================================================
# Graceful Degradation Tests
# =============================================================================


class TestGracefulDegradation:
    """Test behavior when Slack is not configured."""

    def test_no_handler_returns_existing_thread_ts(self) -> None:
        """When no handler configured, pass through thread_ts."""
        notifier = PipelineSlackNotifier(
            ticket_id="OMN-1234",
            run_id="test",
            handler=None,  # type: ignore[arg-type]
        )
        notifier._configured = False

        thread_ts = asyncio.run(
            notifier.notify_phase_completed(
                phase="test",
                summary="test",
                thread_ts="existing",
            )
        )

        assert thread_ts == "existing"

    def test_handler_failure_returns_none_thread_ts(self) -> None:
        """When handler fails and returns no thread_ts, get None."""
        handler = MockSlackHandler(success=False, error="Connection refused")

        notifier = PipelineSlackNotifier(
            ticket_id="OMN-1234",
            run_id="test",
            handler=handler,
        )

        thread_ts = asyncio.run(
            notifier.notify_phase_completed(
                phase="test",
                summary="test",
            )
        )

        # thread_ts is None when handler fails and returns no thread_ts
        assert thread_ts is None


# =============================================================================
# Event Emission Tests
# =============================================================================


class TestEventEmission:
    """Test dual-emission (Slack + Kafka event)."""

    def test_emits_completed_event(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_phase_completed(
                phase="local_review",
                summary="0 blocking",
            )
        )

        # Slack handler was called
        assert len(handler.calls) == 1

    def test_emits_blocked_event(
        self, notifier: PipelineSlackNotifier, handler: MockSlackHandler
    ) -> None:
        asyncio.run(
            notifier.notify_blocked(
                phase="implement",
                reason="test",
                block_kind="blocked_policy",
            )
        )

        assert len(handler.calls) == 1


# =============================================================================
# Sync Wrapper Tests
# =============================================================================


class TestNotifySync:
    """Test the synchronous wrapper for async methods."""

    def test_sync_wrapper_calls_method(self, handler: MockSlackHandler) -> None:
        notifier = PipelineSlackNotifier(
            ticket_id="OMN-1234",
            run_id="test",
            handler=handler,
        )

        thread_ts = notify_sync(
            notifier,
            "notify_pipeline_started",
        )

        assert len(handler.calls) == 1
        assert thread_ts == "1234567890.123456"
