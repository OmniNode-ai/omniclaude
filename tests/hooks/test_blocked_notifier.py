# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for blocked_notifier module.

This module tests the Slack notification adapter for blocked agent states.
It validates:
- Guard checks (non-blocked state, missing state, no webhook URL)
- Rate limiting (file-based, 5-minute window, key computation, pruning)
- Slack delivery (handler path, urllib fallback, message formatting)
- Fail-open semantics (never raises regardless of input)
- Integration with agent_status_emitter (blocked triggers notify, non-blocked skips)

Transitive dependency note:
    omniclaude.hooks.schemas transitively imports tiktoken (via injection_limits
    or omnibase_core/omnibase_infra). When tiktoken is not installed the lazy
    ``from omniclaude.hooks.schemas import ...`` inside emit_agent_status()
    raises ModuleNotFoundError, which the fail-open handler catches and returns
    False -- causing all happy-path tests to fail.

    To decouple these tests from tiktoken availability we attempt to import the
    real schemas first.  If that fails we install lightweight stand-ins into
    ``sys.modules`` so the lazy import succeeds.  The stand-ins faithfully
    replicate EnumAgentState (StrEnum) and ModelAgentStatusPayload (frozen
    Pydantic BaseModel with identical field constraints) so every test exercises
    the same validation logic as production.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from enum import StrEnum
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Tiktoken-safe schema mocking (identical to test_agent_status_emitter.py)
# =============================================================================

_SCHEMAS_MOCK_INSTALLED = False

try:
    from omniclaude.hooks.schemas import (  # noqa: F401
        EnumAgentState,
        ModelAgentStatusPayload,
    )
except Exception:

    class EnumAgentState(StrEnum):  # type: ignore[no-redef]
        IDLE = "idle"
        WORKING = "working"
        BLOCKED = "blocked"
        AWAITING_INPUT = "awaiting_input"
        FINISHED = "finished"
        ERROR = "error"

    class ModelAgentStatusPayload(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(frozen=True, extra="forbid")

        correlation_id: UUID = Field(...)
        agent_name: str = Field(..., min_length=1)
        session_id: str = Field(..., min_length=1)
        agent_instance_id: str | None = Field(default=None)
        state: EnumAgentState = Field(...)
        schema_version: Literal[1] = Field(default=1)
        message: str = Field(..., min_length=1, max_length=500)
        progress: float | None = Field(default=None, ge=0.0, le=1.0)
        current_phase: str | None = Field(default=None)
        current_task: str | None = Field(default=None)
        blocking_reason: str | None = Field(default=None)
        emitted_at: datetime = Field(...)
        metadata: dict[str, str] = Field(default_factory=dict)

    import types as _types

    _schemas_mod = sys.modules.get("omniclaude.hooks.schemas")
    if _schemas_mod is None:
        _schemas_mod = _types.ModuleType("omniclaude.hooks.schemas")
        for _parent in ("omniclaude", "omniclaude.hooks"):
            if _parent not in sys.modules:
                sys.modules[_parent] = _types.ModuleType(_parent)
        sys.modules["omniclaude.hooks.schemas"] = _schemas_mod

    _schemas_mod.EnumAgentState = EnumAgentState  # type: ignore[attr-defined]
    _schemas_mod.ModelAgentStatusPayload = ModelAgentStatusPayload  # type: ignore[attr-defined]
    _SCHEMAS_MOCK_INSTALLED = True


# =============================================================================
# Helpers
# =============================================================================


def _make_blocked_payload(**overrides: object) -> dict[str, object]:
    """Create a minimal blocked agent status payload dict."""
    base: dict[str, object] = {
        "state": "blocked",
        "agent_name": "test-agent",
        "session_id": "session-123",
        "correlation_id": str(uuid4()),
        "message": "Agent is blocked",
        "schema_version": 1,
        "emitted_at": "2026-02-12T00:00:00Z",
        "agent_instance_id": None,
        "current_phase": None,
        "current_task": None,
        "blocking_reason": None,
        "progress": None,
        "metadata": {},
    }
    base.update(overrides)
    return base


# =============================================================================
# Module Import Tests
# =============================================================================


class TestModuleImport:
    """Tests for module imports and constants."""

    def test_module_imports_successfully(self) -> None:
        """Verify module can be imported without errors."""
        from plugins.onex.hooks.lib import blocked_notifier

        assert blocked_notifier is not None

    def test_maybe_notify_blocked_is_callable(self) -> None:
        """Verify maybe_notify_blocked function exists and is callable."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        assert callable(maybe_notify_blocked)

    def test_public_api_exports(self) -> None:
        """Verify __all__ exports expected public API."""
        from plugins.onex.hooks.lib.blocked_notifier import __all__

        expected_exports = {"maybe_notify_blocked"}
        assert set(__all__) == expected_exports


# =============================================================================
# Guard Check Tests
# =============================================================================


class TestGuardChecks:
    """Tests for guard conditions that short-circuit notification."""

    def test_non_blocked_state_returns_false(self) -> None:
        """Payload with state='working' returns False without sending."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        payload = _make_blocked_payload(state="working")
        result = maybe_notify_blocked(payload)
        assert result is False

    def test_missing_state_returns_false(self) -> None:
        """Payload with no 'state' key returns False."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        payload = _make_blocked_payload()
        del payload["state"]
        result = maybe_notify_blocked(payload)
        assert result is False

    def test_no_webhook_url_returns_false_with_debug_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No SLACK_WEBHOOK_URL returns False and logs at DEBUG."""
        from plugins.onex.hooks.lib import blocked_notifier
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        with patch.object(blocked_notifier.logger, "debug") as mock_debug:
            result = maybe_notify_blocked(_make_blocked_payload())

        assert result is False
        # Verify DEBUG log mentions Slack not configured
        debug_calls = [str(c) for c in mock_debug.call_args_list]
        assert any("Slack not configured" in c for c in debug_calls)


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for file-based rate limiting."""

    def test_first_notification_is_not_rate_limited(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First notification for a key is always allowed."""
        from plugins.onex.hooks.lib.blocked_notifier import (
            _check_and_update_rate_limit,
        )

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)

        result = _check_and_update_rate_limit("agent-1:sess-1")
        assert result is True

    def test_second_notification_within_5_min_is_rate_limited(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second notification within 5 minutes is rate-limited."""
        from plugins.onex.hooks.lib.blocked_notifier import (
            _check_and_update_rate_limit,
        )

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)

        # First call — allowed
        assert _check_and_update_rate_limit("agent-1:sess-1") is True
        # Second call — rate-limited
        assert _check_and_update_rate_limit("agent-1:sess-1") is False

    def test_notification_after_5_min_is_allowed(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Notification after 5 minutes have elapsed is allowed."""
        from plugins.onex.hooks.lib.blocked_notifier import (
            _check_and_update_rate_limit,
        )

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)

        # First call at t=0
        with patch("plugins.onex.hooks.lib.blocked_notifier.time") as mock_time:
            mock_time.time.return_value = 1000.0
            assert _check_and_update_rate_limit("agent-1:sess-1") is True

        # Second call at t=301 (just past 5min window)
        with patch("plugins.onex.hooks.lib.blocked_notifier.time") as mock_time:
            mock_time.time.return_value = 1301.0
            assert _check_and_update_rate_limit("agent-1:sess-1") is True

    def test_stale_entries_are_pruned(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entries older than 1 hour are pruned on write."""
        from plugins.onex.hooks.lib.blocked_notifier import (
            _check_and_update_rate_limit,
        )

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)

        now = 10000.0
        stale_time = now - 3700  # >1 hour ago

        # Pre-seed with a stale entry
        with open(rate_file, "w") as f:
            json.dump({"stale-agent:old-sess": stale_time}, f)

        with patch("plugins.onex.hooks.lib.blocked_notifier.time") as mock_time:
            mock_time.time.return_value = now
            _check_and_update_rate_limit("new-agent:new-sess")

        # Read back and verify stale entry was pruned
        with open(rate_file) as f:
            data = json.load(f)

        assert "stale-agent:old-sess" not in data
        assert "new-agent:new-sess" in data

    def test_key_uses_agent_instance_id_when_present(self) -> None:
        """Rate limit key is agent_instance_id when present and truthy."""
        from plugins.onex.hooks.lib.blocked_notifier import _compute_rate_key

        payload = _make_blocked_payload(agent_instance_id="instance-42")
        assert _compute_rate_key(payload) == "instance-42"

    def test_key_uses_agent_name_session_id_when_no_instance_id(self) -> None:
        """Rate limit key is agent_name:session_id when no instance ID."""
        from plugins.onex.hooks.lib.blocked_notifier import _compute_rate_key

        payload = _make_blocked_payload(
            agent_instance_id=None,
            agent_name="my-agent",
            session_id="sess-99",
        )
        assert _compute_rate_key(payload) == "my-agent:sess-99"


# =============================================================================
# Slack Delivery Tests
# =============================================================================


class TestSlackDelivery:
    """Tests for Slack notification delivery paths."""

    def test_sends_notification_via_handler_when_available(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When HandlerSlackWebhook is importable, uses handler path."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/test")

        with patch(
            "plugins.onex.hooks.lib.blocked_notifier._send_via_handler",
            return_value=True,
        ) as mock_handler:
            result = maybe_notify_blocked(_make_blocked_payload())

        assert result is True
        mock_handler.assert_called_once()

    def test_falls_back_to_urllib_when_handler_unavailable(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to urllib when HandlerSlackWebhook import fails."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/test")

        with (
            patch(
                "plugins.onex.hooks.lib.blocked_notifier._send_via_handler",
                side_effect=ImportError("no omnibase_infra"),
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier._send_via_urllib",
                return_value=True,
            ) as mock_urllib,
        ):
            result = maybe_notify_blocked(_make_blocked_payload())

        assert result is True
        mock_urllib.assert_called_once()

    def test_message_format_includes_all_fields(self) -> None:
        """Formatted message includes all non-None fields."""
        from plugins.onex.hooks.lib.blocked_notifier import _format_slack_message

        payload = _make_blocked_payload(
            agent_name="blocked-agent",
            session_id="sess-xyz",
            current_phase="planning",
            current_task="Analyzing requirements",
            blocking_reason="Missing API credentials",
            correlation_id="corr-id-abc",
        )

        message = _format_slack_message(payload)

        assert ":warning: Agent Blocked" in message
        assert "Agent: blocked-agent" in message
        assert "Session: sess-xyz" in message
        assert "Phase: planning" in message
        assert "Task: Analyzing requirements" in message
        assert "Reason: Missing API credentials" in message
        assert "Correlation ID: corr-id-abc" in message

    def test_message_format_omits_none_fields(self) -> None:
        """Formatted message omits lines where value is None."""
        from plugins.onex.hooks.lib.blocked_notifier import _format_slack_message

        payload = _make_blocked_payload(
            current_phase=None,
            current_task=None,
            blocking_reason=None,
        )

        message = _format_slack_message(payload)

        assert "Phase:" not in message
        assert "Task:" not in message
        assert "Reason:" not in message
        # These should still be present
        assert "Agent:" in message
        assert "Session:" in message
        assert "Correlation ID:" in message


# =============================================================================
# Fail-Open Tests
# =============================================================================


class TestFailOpen:
    """Tests that the notifier never raises, always returns False on error."""

    def test_sender_exception_returns_false(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both send paths raise, returns False without raising."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/test")

        with (
            patch(
                "plugins.onex.hooks.lib.blocked_notifier._send_via_handler",
                side_effect=RuntimeError("Handler exploded"),
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier._send_via_urllib",
                side_effect=ConnectionError("Network down"),
            ),
        ):
            result = maybe_notify_blocked(_make_blocked_payload())

        assert result is False

    def test_rate_limit_file_corruption_returns_false(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupted rate limit file does not crash; returns False or recovers."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        rate_file = str(tmp_path) + "/rate_limits.json"  # type: ignore[operator]
        monkeypatch.setenv("BLOCKED_RATE_LIMIT_PATH", rate_file)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/test")

        # Write garbage to the rate limit file
        with open(rate_file, "w") as f:
            f.write("THIS IS NOT JSON {{{{")

        # Should either recover (parse failure → empty dict → allow) or fail open
        with (
            patch(
                "plugins.onex.hooks.lib.blocked_notifier._send_via_handler",
                return_value=True,
            ),
        ):
            result = maybe_notify_blocked(_make_blocked_payload())

        # Should succeed because corrupt file is treated as empty
        assert result is True

    def test_never_raises_regardless_of_input(self) -> None:
        """maybe_notify_blocked must never raise, even with bizarre input."""
        from plugins.onex.hooks.lib.blocked_notifier import maybe_notify_blocked

        bizarre_inputs: list[dict[str, object]] = [
            {},
            {"state": None},
            {"state": 42},
            {"state": "blocked"},  # No webhook configured
            None,  # type: ignore[list-item]
        ]

        for payload in bizarre_inputs:
            try:
                result = maybe_notify_blocked(payload)  # type: ignore[arg-type]
                assert isinstance(result, bool)
            except Exception:
                pytest.fail(
                    f"maybe_notify_blocked raised an exception with input: {payload}"
                )


# =============================================================================
# Emitter Integration Tests
# =============================================================================


class TestEmitterIntegration:
    """Tests for integration between agent_status_emitter and blocked_notifier."""

    def test_blocked_state_triggers_notification(self) -> None:
        """emit_agent_status with state='blocked' calls maybe_notify_blocked."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with (
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                return_value=True,
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier.maybe_notify_blocked",
                return_value=True,
            ) as mock_notify,
        ):
            result = emit_agent_status(
                "blocked",
                "Waiting for human approval",
                agent_name="test-agent",
                session_id="session-123",
                blocking_reason="Need credentials",
            )

        assert result is True
        mock_notify.assert_called_once()
        # Verify the payload passed is a dict with state=blocked
        call_payload = mock_notify.call_args[0][0]
        assert call_payload["state"] == "blocked"

    def test_non_blocked_state_does_not_trigger_notification(self) -> None:
        """emit_agent_status with state='working' does NOT call maybe_notify_blocked."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with (
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                return_value=True,
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier.maybe_notify_blocked",
            ) as mock_notify,
        ):
            result = emit_agent_status(
                "working",
                "Processing request",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is True
        mock_notify.assert_not_called()

    def test_notification_failure_does_not_affect_emission(self) -> None:
        """maybe_notify_blocked raising does NOT affect emit_agent_status return."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with (
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                return_value=True,
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier.maybe_notify_blocked",
                side_effect=RuntimeError("Notification exploded"),
            ),
        ):
            result = emit_agent_status(
                "blocked",
                "Blocked but notification fails",
                agent_name="test-agent",
                session_id="session-123",
            )

        # emit_agent_status should still return True despite notification failure
        assert result is True

    def test_emit_failure_does_not_trigger_notification(self) -> None:
        """When emit_event returns False, maybe_notify_blocked is NOT called."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with (
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                return_value=False,
            ),
            patch(
                "plugins.onex.hooks.lib.blocked_notifier.maybe_notify_blocked",
            ) as mock_notify,
        ):
            result = emit_agent_status(
                "blocked",
                "Blocked but emit fails",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False
        mock_notify.assert_not_called()
