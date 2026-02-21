"""Tests for epic_milestone_notifier module.

Covers the four public functions, correlation prefix format, thread_ts
threading behaviour, graceful degradation when Slack fails, and the
critical invariant that a non-None thread_ts is never overwritten with None.

Uses asyncio.run() style mocks (same pattern as test_pipeline_slack_notifier)
because pytest-asyncio is not installed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path bootstrap so the module under test can import pipeline_slack_notifier
# ---------------------------------------------------------------------------
_LIB_DIR = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from epic_milestone_notifier import (
    _make_prefix,
    notify_epic_done,
    notify_ticket_completed,
    notify_ticket_failed,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
EPIC_ID = "OMN-2400"
RUN_ID = "abcd-1234"
TICKET_ID = "OMN-2401"
REPO = "omniclaude"
THREAD_TS = "1700000000.123456"
NEW_THREAD_TS = "1700000001.654321"


# =============================================================================
# Helpers / mock builder
# =============================================================================


@dataclass
class _MockNotifyResult:
    success: bool = True
    thread_ts: str | None = None
    error: str | None = None


def _make_mock_notifier(
    *,
    returns_thread_ts: str | None = NEW_THREAD_TS,
    raises: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics PipelineSlackNotifier's async notify methods."""
    mock = MagicMock()

    async def _phase_completed(**kwargs: Any) -> str | None:
        if raises:
            raise raises
        return returns_thread_ts

    async def _blocked(**kwargs: Any) -> str | None:
        if raises:
            raise raises
        return returns_thread_ts

    mock.notify_phase_completed = _phase_completed
    mock.notify_blocked = _blocked
    return mock


# =============================================================================
# Correlation prefix tests
# =============================================================================


class TestCorrelationPrefix:
    """The prefix format is [epic_id][epic-team][run:run_id]."""

    def test_basic_format(self) -> None:
        prefix = _make_prefix(EPIC_ID, RUN_ID)
        assert prefix == f"[{EPIC_ID}][epic-team][run:{RUN_ID}]"

    def test_contains_all_parts(self) -> None:
        prefix = _make_prefix(EPIC_ID, RUN_ID)
        assert EPIC_ID in prefix
        assert "epic-team" in prefix
        assert RUN_ID in prefix

    def test_different_run_ids(self) -> None:
        p1 = _make_prefix(EPIC_ID, "run-1111")
        p2 = _make_prefix(EPIC_ID, "run-2222")
        assert "run-1111" in p1
        assert "run-2222" in p2
        assert p1 != p2


# =============================================================================
# notify_ticket_completed
# =============================================================================


class TestNotifyTicketCompleted:
    """Tests for notify_ticket_completed()."""

    def test_root_message_when_thread_ts_none(self) -> None:
        """thread_ts=None → returns the new thread_ts from Slack."""
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_completed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=None
            )
        assert result == NEW_THREAD_TS

    def test_threads_reply_when_thread_ts_provided(self) -> None:
        """thread_ts provided → still returns whatever Slack hands back."""
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_completed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=THREAD_TS
            )
        assert result == NEW_THREAD_TS

    def test_includes_pr_url(self) -> None:
        """PR URL should be passed through to the underlying notifier."""
        mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _phase_completed(**kwargs: Any) -> str | None:
            captured.update(kwargs)
            return NEW_THREAD_TS

        mock.notify_phase_completed = _phase_completed

        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            notify_ticket_completed(
                EPIC_ID,
                RUN_ID,
                TICKET_ID,
                REPO,
                pr_url="https://github.com/org/repo/pull/99",
                thread_ts=None,
            )

        assert captured.get("pr_url") == "https://github.com/org/repo/pull/99"

    def test_correlation_prefix_in_message(self) -> None:
        """The epic-team prefix must appear in the call to PipelineSlackNotifier."""
        mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _phase_completed(**kwargs: Any) -> str | None:
            captured.update(kwargs)
            return NEW_THREAD_TS

        mock.notify_phase_completed = _phase_completed

        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            notify_ticket_completed(EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=None)

        # The summary must mention the ticket
        assert TICKET_ID in captured.get("summary", "")
        # The phase must be the epic-team segment
        assert captured.get("phase") == "epic-team"


# =============================================================================
# notify_ticket_failed
# =============================================================================


class TestNotifyTicketFailed:
    """Tests for notify_ticket_failed()."""

    def test_returns_thread_ts_on_success(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_failed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, reason="Build failed"
            )
        assert result == NEW_THREAD_TS

    def test_reason_forwarded(self) -> None:
        """Reason string must reach the underlying notify_blocked call."""
        mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _blocked(**kwargs: Any) -> str | None:
            captured.update(kwargs)
            return NEW_THREAD_TS

        mock.notify_blocked = _blocked

        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            notify_ticket_failed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, reason="Tests timed out"
            )

        assert "Tests timed out" in captured.get("reason", "")

    def test_thread_ts_passed_through(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_failed(
                EPIC_ID,
                RUN_ID,
                TICKET_ID,
                REPO,
                reason="Compilation error",
                thread_ts=THREAD_TS,
            )
        assert result == NEW_THREAD_TS


# =============================================================================
# notify_epic_done
# =============================================================================


class TestNotifyEpicDone:
    """Tests for notify_epic_done()."""

    def test_basic_invocation(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_epic_done(
                EPIC_ID,
                RUN_ID,
                completed=["OMN-2401", "OMN-2402"],
                failed=[],
                prs=["https://github.com/org/repo/pull/10"],
            )
        assert result == NEW_THREAD_TS

    def test_summary_contains_completed_tickets(self) -> None:
        mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _phase_completed(**kwargs: Any) -> str | None:
            captured.update(kwargs)
            return NEW_THREAD_TS

        mock.notify_phase_completed = _phase_completed

        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            notify_epic_done(
                EPIC_ID,
                RUN_ID,
                completed=["OMN-2401", "OMN-2402"],
                failed=["OMN-2403"],
                prs=[],
            )

        summary = captured.get("summary", "")
        assert "OMN-2401" in summary
        assert "OMN-2402" in summary
        assert "OMN-2403" in summary

    def test_empty_lists_do_not_raise(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=None)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            # Must not raise even with all-empty lists
            result = notify_epic_done(
                EPIC_ID, RUN_ID, completed=[], failed=[], prs=[], thread_ts=None
            )
        # thread_ts=None in, None back → still None (nothing to preserve)
        assert result is None

    def test_thread_ts_threaded_reply(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=NEW_THREAD_TS)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_epic_done(
                EPIC_ID,
                RUN_ID,
                completed=["OMN-2401"],
                failed=[],
                prs=[],
                thread_ts=THREAD_TS,
            )
        assert result == NEW_THREAD_TS


# =============================================================================
# Graceful degradation: thread_ts MUST be preserved on Slack failure
# =============================================================================


class TestGracefulDegradation:
    """Critical invariant: non-None thread_ts is never overwritten with None."""

    def test_completed_preserves_thread_ts_on_exception(self) -> None:
        """If the Slack call raises, return the original thread_ts unchanged."""
        mock = _make_mock_notifier(raises=RuntimeError("Slack 503"))
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_completed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=THREAD_TS
            )
        assert result == THREAD_TS

    def test_completed_preserves_thread_ts_when_slack_returns_none(self) -> None:
        """If Slack returns None for thread_ts, the original value is kept."""
        mock = _make_mock_notifier(returns_thread_ts=None)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_completed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=THREAD_TS
            )
        assert result == THREAD_TS

    def test_failed_preserves_thread_ts_on_exception(self) -> None:
        mock = _make_mock_notifier(raises=ConnectionError("Network down"))
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_failed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, reason="oops", thread_ts=THREAD_TS
            )
        assert result == THREAD_TS

    def test_failed_preserves_thread_ts_when_slack_returns_none(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=None)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_failed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, reason="oops", thread_ts=THREAD_TS
            )
        assert result == THREAD_TS

    def test_epic_done_preserves_thread_ts_on_exception(self) -> None:
        mock = _make_mock_notifier(raises=OSError("Socket error"))
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_epic_done(
                EPIC_ID,
                RUN_ID,
                completed=["OMN-2401"],
                failed=[],
                prs=[],
                thread_ts=THREAD_TS,
            )
        assert result == THREAD_TS

    def test_epic_done_preserves_thread_ts_when_slack_returns_none(self) -> None:
        mock = _make_mock_notifier(returns_thread_ts=None)
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_epic_done(
                EPIC_ID,
                RUN_ID,
                completed=[],
                failed=[],
                prs=[],
                thread_ts=THREAD_TS,
            )
        assert result == THREAD_TS

    def test_none_thread_ts_remains_none_on_failure(self) -> None:
        """thread_ts=None in + Slack failure → None out (nothing to preserve)."""
        mock = _make_mock_notifier(raises=RuntimeError("Slack down"))
        with patch("epic_milestone_notifier._make_notifier", return_value=mock):
            result = notify_ticket_completed(
                EPIC_ID, RUN_ID, TICKET_ID, REPO, thread_ts=None
            )
        assert result is None
