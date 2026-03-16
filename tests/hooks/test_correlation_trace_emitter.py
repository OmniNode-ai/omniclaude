# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for correlation_trace_emitter module.

This module tests the adapter layer for trace span emission to the
emit daemon. It validates:
- Valid span emission (happy path with mocked emit_event)
- Invalid span_kind rejection
- Invalid status rejection
- Environment variable fallback for session_id
- Fail-open exception handling (emit_event raises, function does NOT raise)
- Convenience wrappers (emit_trace_span_from_hook, emit_trace_span_from_tool)
- Auto-computed duration when ended_at is provided but duration_ms is not

Related Tickets:
    - OMN-5047: Correlation trace span emitter for omnidash /trace page
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Patch target: the actual emit_event in emit_client_wrapper, which is
# resolved by the lazy import inside correlation_trace_emitter.
_EMIT_PATCH = "plugins.onex.hooks.lib.emit_client_wrapper.emit_event"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def _mock_emit_event():
    """Mock emit_event to avoid daemon dependency."""
    with patch(
        _EMIT_PATCH,
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def _mock_emit_event_failure():
    """Mock emit_event that returns False (daemon unavailable)."""
    with patch(
        _EMIT_PATCH,
        return_value=False,
    ) as mock:
        yield mock


# =============================================================================
# emit_trace_span Tests
# =============================================================================


class TestEmitTraceSpan:
    """Tests for the emit_trace_span function."""

    def test_happy_path(self, _mock_emit_event) -> None:
        """Valid span is accepted and emitted."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        now = datetime.now(UTC)
        trace_id = uuid4()
        span_id = uuid4()
        session_id = "test-session-123"

        result = emit_trace_span(
            span_kind="hook",
            operation_name="UserPromptSubmit",
            status="ok",
            started_at=now,
            trace_id=trace_id,
            span_id=span_id,
            session_id=session_id,
            ended_at=now + timedelta(milliseconds=250),
            duration_ms=250,
        )

        assert result is True
        _mock_emit_event.assert_called_once()
        call_args = _mock_emit_event.call_args
        assert call_args[0][0] == "correlation.trace.span"
        payload = call_args[0][1]
        assert payload["span_kind"] == "hook"
        assert payload["operation_name"] == "UserPromptSubmit"
        assert payload["status"] == "ok"
        assert payload["session_id"] == session_id
        assert payload["trace_id"] == str(trace_id)
        assert payload["span_id"] == str(span_id)

    def test_defaults_generated(self, _mock_emit_event) -> None:
        """span_id, trace_id, correlation_id default to generated UUIDs."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        now = datetime.now(UTC)

        result = emit_trace_span(
            span_kind="session",
            operation_name="SessionStart",
            status="ok",
            started_at=now,
            session_id="s-1",
        )

        assert result is True
        payload = _mock_emit_event.call_args[0][1]
        # All IDs should be valid UUID strings
        UUID(payload["span_id"])
        UUID(payload["trace_id"])
        UUID(payload["correlation_id"])
        # correlation_id defaults to trace_id
        assert payload["correlation_id"] == payload["trace_id"]

    def test_session_id_from_env(self, _mock_emit_event) -> None:
        """session_id falls back to SESSION_ID env var."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        now = datetime.now(UTC)

        with patch.dict(os.environ, {"SESSION_ID": "env-session-42"}):
            emit_trace_span(
                span_kind="hook",
                operation_name="PostToolUse",
                status="ok",
                started_at=now,
            )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["session_id"] == "env-session-42"

    def test_session_id_defaults_to_unknown(self, _mock_emit_event) -> None:
        """session_id defaults to 'unknown' when not provided and env var unset."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        now = datetime.now(UTC)

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SESSION_ID", None)
            emit_trace_span(
                span_kind="hook",
                operation_name="PostToolUse",
                status="ok",
                started_at=now,
            )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["session_id"] == "unknown"

    def test_invalid_span_kind_returns_false(self) -> None:
        """Invalid span_kind returns False without raising."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        result = emit_trace_span(
            span_kind="invalid_kind",
            operation_name="test",
            status="ok",
            started_at=datetime.now(UTC),
            session_id="s-1",
        )
        assert result is False

    def test_invalid_status_returns_false(self) -> None:
        """Invalid status returns False without raising."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        result = emit_trace_span(
            span_kind="hook",
            operation_name="test",
            status="invalid_status",
            started_at=datetime.now(UTC),
            session_id="s-1",
        )
        assert result is False

    def test_fail_open_on_emit_error(self) -> None:
        """emit_event raising does not propagate -- returns False."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        with patch(
            _EMIT_PATCH,
            side_effect=RuntimeError("daemon crash"),
        ):
            result = emit_trace_span(
                span_kind="hook",
                operation_name="test",
                status="ok",
                started_at=datetime.now(UTC),
                session_id="s-1",
            )
        assert result is False

    def test_metadata_passthrough(self, _mock_emit_event) -> None:
        """Metadata dict is included in the emitted payload."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        meta = {"tool_name": "Bash", "exit_code": "0"}
        emit_trace_span(
            span_kind="tool_use",
            operation_name="Bash",
            status="ok",
            started_at=datetime.now(UTC),
            session_id="s-1",
            metadata=meta,
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["metadata"] == meta

    def test_error_message_passthrough(self, _mock_emit_event) -> None:
        """Error message is included when status is error."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        emit_trace_span(
            span_kind="hook",
            operation_name="PostToolUse",
            status="error",
            started_at=datetime.now(UTC),
            session_id="s-1",
            error_message="timeout waiting for response",
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["error_message"] == "timeout waiting for response"
        assert payload["status"] == "error"

    def test_parent_span_id_included(self, _mock_emit_event) -> None:
        """parent_span_id is passed through to the payload."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        parent = uuid4()
        emit_trace_span(
            span_kind="tool_use",
            operation_name="Read",
            status="ok",
            started_at=datetime.now(UTC),
            session_id="s-1",
            parent_span_id=parent,
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["parent_span_id"] == str(parent)

    def test_all_span_kinds_accepted(self, _mock_emit_event) -> None:
        """Every valid EnumTraceSpanKind value is accepted."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        valid_kinds = [
            "session",
            "hook",
            "tool_use",
            "routing",
            "context_injection",
            "emit",
            "skill",
            "custom",
        ]
        for kind in valid_kinds:
            result = emit_trace_span(
                span_kind=kind,
                operation_name=f"test_{kind}",
                status="ok",
                started_at=datetime.now(UTC),
                session_id="s-1",
            )
            assert result is True, f"span_kind={kind!r} should be accepted"


# =============================================================================
# emit_trace_span_from_hook Tests
# =============================================================================


class TestEmitTraceSpanFromHook:
    """Tests for the convenience hook wrapper."""

    def test_happy_path(self, _mock_emit_event) -> None:
        """Hook span is emitted with correct kind and operation."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_hook,
        )

        started = datetime.now(UTC)
        ended = started + timedelta(milliseconds=100)

        result = emit_trace_span_from_hook(
            hook_name="UserPromptSubmit",
            started_at=started,
            ended_at=ended,
            session_id="s-hook",
        )

        assert result is True
        payload = _mock_emit_event.call_args[0][1]
        assert payload["span_kind"] == "hook"
        assert payload["operation_name"] == "UserPromptSubmit"
        assert payload["status"] == "ok"

    def test_auto_duration(self, _mock_emit_event) -> None:
        """Duration is auto-computed from started_at and ended_at."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_hook,
        )

        started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        ended = datetime(2025, 6, 1, 12, 0, 0, 350000, tzinfo=UTC)

        emit_trace_span_from_hook(
            hook_name="PostToolUse",
            started_at=started,
            ended_at=ended,
            session_id="s-1",
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["duration_ms"] == 350

    def test_error_status(self, _mock_emit_event) -> None:
        """Error status and message are passed through."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_hook,
        )

        emit_trace_span_from_hook(
            hook_name="SessionStart",
            started_at=datetime.now(UTC),
            session_id="s-1",
            status="error",
            error_message="hook failed",
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["status"] == "error"
        assert payload["error_message"] == "hook failed"


# =============================================================================
# emit_trace_span_from_tool Tests
# =============================================================================


class TestEmitTraceSpanFromTool:
    """Tests for the convenience tool wrapper."""

    def test_success_tool(self, _mock_emit_event) -> None:
        """Successful tool execution emits with status ok."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_tool,
        )

        started = datetime.now(UTC)
        ended = started + timedelta(milliseconds=50)

        result = emit_trace_span_from_tool(
            tool_name="Read",
            started_at=started,
            success=True,
            ended_at=ended,
            session_id="s-tool",
        )

        assert result is True
        payload = _mock_emit_event.call_args[0][1]
        assert payload["span_kind"] == "tool_use"
        assert payload["operation_name"] == "Read"
        assert payload["status"] == "ok"

    def test_failed_tool(self, _mock_emit_event) -> None:
        """Failed tool execution emits with status error."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_tool,
        )

        emit_trace_span_from_tool(
            tool_name="Bash",
            started_at=datetime.now(UTC),
            success=False,
            session_id="s-tool",
            error_message="exit code 1",
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["status"] == "error"
        assert payload["error_message"] == "exit code 1"

    def test_auto_duration_from_timestamps(self, _mock_emit_event) -> None:
        """Duration is auto-computed when only timestamps provided."""
        from plugins.onex.hooks.lib.correlation_trace_emitter import (
            emit_trace_span_from_tool,
        )

        started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        ended = datetime(2025, 6, 1, 12, 0, 1, tzinfo=UTC)  # 1 second later

        emit_trace_span_from_tool(
            tool_name="Write",
            started_at=started,
            ended_at=ended,
            session_id="s-1",
        )

        payload = _mock_emit_event.call_args[0][1]
        assert payload["duration_ms"] == 1000


# =============================================================================
# Schema Model Tests
# =============================================================================


class TestModelCorrelationTraceSpanPayload:
    """Tests for the Pydantic schema model."""

    def test_frozen(self) -> None:
        """Payload model is immutable."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        span = ModelCorrelationTraceSpanPayload(
            span_id=uuid4(),
            trace_id=uuid4(),
            correlation_id=uuid4(),
            session_id="s-1",
            span_kind="hook",
            operation_name="test",
            status="ok",
            started_at=datetime.now(UTC),
        )

        with pytest.raises(Exception):  # ValidationError for frozen model
            span.operation_name = "modified"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        with pytest.raises(Exception):  # ValidationError
            ModelCorrelationTraceSpanPayload(
                span_id=uuid4(),
                trace_id=uuid4(),
                correlation_id=uuid4(),
                session_id="s-1",
                span_kind="hook",
                operation_name="test",
                status="ok",
                started_at=datetime.now(UTC),
                unexpected_field="value",  # type: ignore[call-arg]
            )

    def test_operation_name_max_length(self) -> None:
        """operation_name exceeding 500 chars is rejected."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        with pytest.raises(Exception):  # ValidationError
            ModelCorrelationTraceSpanPayload(
                span_id=uuid4(),
                trace_id=uuid4(),
                correlation_id=uuid4(),
                session_id="s-1",
                span_kind="hook",
                operation_name="x" * 501,
                status="ok",
                started_at=datetime.now(UTC),
            )

    def test_duration_ms_non_negative(self) -> None:
        """Negative duration_ms is rejected."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        with pytest.raises(Exception):  # ValidationError
            ModelCorrelationTraceSpanPayload(
                span_id=uuid4(),
                trace_id=uuid4(),
                correlation_id=uuid4(),
                session_id="s-1",
                span_kind="hook",
                operation_name="test",
                status="ok",
                started_at=datetime.now(UTC),
                duration_ms=-1,
            )

    def test_schema_version_default(self) -> None:
        """Schema version defaults to 1."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        span = ModelCorrelationTraceSpanPayload(
            span_id=uuid4(),
            trace_id=uuid4(),
            correlation_id=uuid4(),
            session_id="s-1",
            span_kind="hook",
            operation_name="test",
            status="ok",
            started_at=datetime.now(UTC),
        )
        assert span.schema_version == 1

    def test_serialization_roundtrip(self) -> None:
        """Model serializes to JSON and deserializes back."""
        from omniclaude.hooks.schemas import ModelCorrelationTraceSpanPayload

        span_id = uuid4()
        trace_id = uuid4()
        now = datetime.now(UTC)

        span = ModelCorrelationTraceSpanPayload(
            span_id=span_id,
            trace_id=trace_id,
            correlation_id=trace_id,
            session_id="s-1",
            span_kind="tool_use",
            operation_name="Bash",
            status="ok",
            started_at=now,
            ended_at=now + timedelta(milliseconds=42),
            duration_ms=42,
            metadata={"exit_code": "0"},
        )

        json_str = span.model_dump_json()
        restored = ModelCorrelationTraceSpanPayload.model_validate_json(json_str)
        assert restored.span_id == span_id
        assert restored.trace_id == trace_id
        assert restored.duration_ms == 42
        assert restored.metadata == {"exit_code": "0"}


# =============================================================================
# Event Registry Tests
# =============================================================================


class TestEventRegistryIntegration:
    """Tests verifying the event is properly registered in the event registry."""

    def test_event_type_registered(self) -> None:
        """correlation.trace.span is registered in EVENT_REGISTRY."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "correlation.trace.span" in EVENT_REGISTRY

    def test_fan_out_to_correct_topic(self) -> None:
        """Fan-out targets the CORRELATION_TRACE topic."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["correlation.trace.span"]
        assert len(reg.fan_out) == 1
        assert reg.fan_out[0].topic_base == TopicBase.CORRELATION_TRACE

    def test_partition_key_is_trace_id(self) -> None:
        """Partition key field is trace_id for ordering within a trace."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["correlation.trace.span"]
        assert reg.partition_key_field == "trace_id"

    def test_required_fields(self) -> None:
        """Required fields match the minimum viable span payload."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["correlation.trace.span"]
        expected = {"span_id", "trace_id", "session_id", "span_kind", "operation_name"}
        assert set(reg.required_fields) == expected

    def test_validate_payload_passes(self) -> None:
        """validate_payload succeeds with all required fields present."""
        from omniclaude.hooks.event_registry import validate_payload

        missing = validate_payload(
            "correlation.trace.span",
            {
                "span_id": str(uuid4()),
                "trace_id": str(uuid4()),
                "session_id": "s-1",
                "span_kind": "hook",
                "operation_name": "test",
            },
        )
        assert missing == []

    def test_validate_payload_missing_fields(self) -> None:
        """validate_payload reports missing required fields."""
        from omniclaude.hooks.event_registry import validate_payload

        missing = validate_payload(
            "correlation.trace.span",
            {"span_id": str(uuid4())},
        )
        assert "trace_id" in missing
        assert "session_id" in missing


# =============================================================================
# Topic Tests
# =============================================================================


class TestTopicRegistration:
    """Tests verifying the topic is defined in TopicBase."""

    def test_correlation_trace_topic_exists(self) -> None:
        """CORRELATION_TRACE is a valid TopicBase member."""
        from omniclaude.hooks.topics import TopicBase

        assert hasattr(TopicBase, "CORRELATION_TRACE")
        assert TopicBase.CORRELATION_TRACE == "onex.evt.omniclaude.correlation-trace.v1"

    def test_topic_in_supported_event_types(self) -> None:
        """correlation.trace.span is in SUPPORTED_EVENT_TYPES."""
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        assert "correlation.trace.span" in SUPPORTED_EVENT_TYPES
