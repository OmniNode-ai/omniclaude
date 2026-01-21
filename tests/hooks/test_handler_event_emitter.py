# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for OmniClaude hook event emitter (OMN-1400).

Tests cover:
    - Schema validation (event type to topic mapping)
    - Topic selection (correct topic for each event type)
    - Failure suppression (no exceptions, always returns result)
    - Convenience function validation

Note:
    These tests do NOT:
    - Spin up Kafka (unit tests only)
    - Assert delivery guarantees
    - Simulate Claude Code internals

    Integration tests with real Kafka belong in a separate test module
    or manual smoke test checklist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from omniclaude.hooks.handler_event_emitter import (
    _create_kafka_config,
    _get_event_type,
    _get_topic_base,
    emit_hook_event,
    emit_prompt_submitted,
    emit_session_ended,
    emit_session_started,
    emit_tool_executed,
)
from omniclaude.hooks.schemas import (
    HookEventType,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)
from omniclaude.hooks.topics import TopicBase

if TYPE_CHECKING:
    pass


# =============================================================================
# Helper Factories
# =============================================================================


def make_timestamp() -> datetime:
    """Create a valid timezone-aware timestamp."""
    return datetime.now(UTC)


def make_session_started_payload() -> ModelHookSessionStartedPayload:
    """Create a valid session started payload."""
    entity_id = uuid4()
    return ModelHookSessionStartedPayload(
        entity_id=entity_id,
        session_id=str(entity_id),
        correlation_id=entity_id,
        causation_id=uuid4(),
        emitted_at=make_timestamp(),
        working_directory="/workspace/test",
        git_branch="main",
        hook_source="startup",
    )


def make_session_ended_payload() -> ModelHookSessionEndedPayload:
    """Create a valid session ended payload."""
    entity_id = uuid4()
    return ModelHookSessionEndedPayload(
        entity_id=entity_id,
        session_id=str(entity_id),
        correlation_id=entity_id,
        causation_id=uuid4(),
        emitted_at=make_timestamp(),
        reason="clear",
        duration_seconds=1800.0,
        tools_used_count=42,
    )


def make_prompt_submitted_payload() -> ModelHookPromptSubmittedPayload:
    """Create a valid prompt submitted payload."""
    entity_id = uuid4()
    return ModelHookPromptSubmittedPayload(
        entity_id=entity_id,
        session_id=str(entity_id),
        correlation_id=entity_id,
        causation_id=uuid4(),
        emitted_at=make_timestamp(),
        prompt_id=uuid4(),
        prompt_preview="Fix the bug in authentication...",
        prompt_length=150,
        detected_intent="fix",
    )


def make_tool_executed_payload() -> ModelHookToolExecutedPayload:
    """Create a valid tool executed payload."""
    entity_id = uuid4()
    return ModelHookToolExecutedPayload(
        entity_id=entity_id,
        session_id=str(entity_id),
        correlation_id=entity_id,
        causation_id=uuid4(),
        emitted_at=make_timestamp(),
        tool_execution_id=uuid4(),
        tool_name="Read",
        success=True,
        duration_ms=45,
        summary="Read 150 lines from /workspace/src/main.py",
    )


# =============================================================================
# Event Type to Topic Mapping Tests
# =============================================================================


class TestEventTypeMapping:
    """Tests for event type to topic mapping."""

    def test_session_started_event_type(self) -> None:
        """Session started payload maps to correct event type."""
        payload = make_session_started_payload()
        event_type = _get_event_type(payload)
        assert event_type == HookEventType.SESSION_STARTED

    def test_session_ended_event_type(self) -> None:
        """Session ended payload maps to correct event type."""
        payload = make_session_ended_payload()
        event_type = _get_event_type(payload)
        assert event_type == HookEventType.SESSION_ENDED

    def test_prompt_submitted_event_type(self) -> None:
        """Prompt submitted payload maps to correct event type."""
        payload = make_prompt_submitted_payload()
        event_type = _get_event_type(payload)
        assert event_type == HookEventType.PROMPT_SUBMITTED

    def test_tool_executed_event_type(self) -> None:
        """Tool executed payload maps to correct event type."""
        payload = make_tool_executed_payload()
        event_type = _get_event_type(payload)
        assert event_type == HookEventType.TOOL_EXECUTED

    def test_unknown_payload_type_raises(self) -> None:
        """Unknown payload type raises ValueError."""
        # Create a mock object that is not a valid payload type
        mock_payload = MagicMock()
        mock_payload.__class__.__name__ = "UnknownPayload"

        with pytest.raises(ValueError, match="Unknown payload type"):
            _get_event_type(mock_payload)  # type: ignore[arg-type]


class TestTopicBaseMapping:
    """Tests for event type to topic base mapping."""

    def test_session_started_topic(self) -> None:
        """Session started maps to correct topic base."""
        topic_base = _get_topic_base(HookEventType.SESSION_STARTED)
        assert topic_base == TopicBase.SESSION_STARTED

    def test_session_ended_topic(self) -> None:
        """Session ended maps to correct topic base."""
        topic_base = _get_topic_base(HookEventType.SESSION_ENDED)
        assert topic_base == TopicBase.SESSION_ENDED

    def test_prompt_submitted_topic(self) -> None:
        """Prompt submitted maps to correct topic base."""
        topic_base = _get_topic_base(HookEventType.PROMPT_SUBMITTED)
        assert topic_base == TopicBase.PROMPT_SUBMITTED

    def test_tool_executed_topic(self) -> None:
        """Tool executed maps to correct topic base."""
        topic_base = _get_topic_base(HookEventType.TOOL_EXECUTED)
        assert topic_base == TopicBase.TOOL_EXECUTED


# =============================================================================
# Kafka Configuration Tests
# =============================================================================


class TestKafkaConfig:
    """Tests for Kafka configuration creation."""

    def test_missing_bootstrap_servers_raises(self) -> None:
        """Missing KAFKA_BOOTSTRAP_SERVERS raises ValueError."""
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="KAFKA_BOOTSTRAP_SERVERS.*required"),
        ):
            _create_kafka_config()

    def test_default_config_values(self) -> None:
        """Default config has expected values for hook latency."""
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "test:9092"}):
            config = _create_kafka_config()

            # Verify hook-optimized settings
            assert config.timeout_seconds == 2  # Short timeout
            assert config.max_retry_attempts == 0  # No retries
            assert config.acks == "1"  # Leader ack only
            assert config.group == "omniclaude-hooks"
            assert config.enable_idempotence is False

    def test_config_respects_env_vars(self) -> None:
        """Config respects KAFKA_ENVIRONMENT env var."""
        with patch.dict(
            "os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "test:9092", "KAFKA_ENVIRONMENT": "prod"}
        ):
            config = _create_kafka_config()
            assert config.environment == "prod"

    def test_config_respects_bootstrap_servers(self) -> None:
        """Config respects KAFKA_BOOTSTRAP_SERVERS env var."""
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "kafka:9092"}):
            config = _create_kafka_config()
            assert config.bootstrap_servers == "kafka:9092"


# =============================================================================
# Failure Suppression Tests
# =============================================================================


class TestFailureSuppression:
    """Tests for graceful failure handling.

    The emitter must NEVER raise exceptions to the caller.
    All errors should be caught and returned as failed results.
    """

    @pytest.mark.asyncio
    async def test_kafka_connection_failure_returns_failed_result(self) -> None:
        """Kafka connection failure returns failed result, not exception."""
        payload = make_session_started_payload()

        # Mock EventBusKafka to raise on start
        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus.start.side_effect = ConnectionError("Kafka unavailable")
            mock_bus_class.return_value = mock_bus

            # Should NOT raise
            result = await emit_hook_event(payload)

            # Should return failed result
            assert result.success is False
            assert result.error_message is not None
            assert "ConnectionError" in result.error_message

    @pytest.mark.asyncio
    async def test_kafka_publish_failure_returns_failed_result(self) -> None:
        """Kafka publish failure returns failed result, not exception."""
        payload = make_session_started_payload()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus.start.return_value = None
            mock_bus.publish.side_effect = RuntimeError("Publish failed")
            mock_bus.close.return_value = None
            mock_bus_class.return_value = mock_bus

            result = await emit_hook_event(payload)

            assert result.success is False
            assert "RuntimeError" in result.error_message  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_bus_close_failure_is_silent(self) -> None:
        """Bus close failure is logged but doesn't affect result."""
        payload = make_session_started_payload()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus.start.return_value = None
            mock_bus.publish.return_value = None
            mock_bus.close.side_effect = RuntimeError("Close failed")
            mock_bus_class.return_value = mock_bus

            # Should NOT raise despite close failure
            result = await emit_hook_event(payload)

            # Result should still indicate success (publish succeeded)
            assert result.success is True


# =============================================================================
# Successful Emission Tests (Mocked)
# =============================================================================


class TestSuccessfulEmission:
    """Tests for successful event emission with mocked Kafka."""

    @pytest.mark.asyncio
    async def test_emit_hook_event_success(self) -> None:
        """Successful emission returns success result."""
        payload = make_session_started_payload()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus.start.return_value = None
            mock_bus.publish.return_value = None
            mock_bus.close.return_value = None
            mock_bus_class.return_value = mock_bus

            result = await emit_hook_event(payload)

            assert result.success is True
            assert "omniclaude.session.started.v1" in result.topic

    @pytest.mark.asyncio
    async def test_emit_uses_entity_id_as_partition_key(self) -> None:
        """Emission uses entity_id bytes as partition key."""
        payload = make_session_started_payload()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            await emit_hook_event(payload)

            # Verify publish was called with entity_id.bytes as key
            mock_bus.publish.assert_called_once()
            call_kwargs = mock_bus.publish.call_args.kwargs
            assert call_kwargs["key"] == payload.entity_id.bytes


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience emission functions."""

    @pytest.mark.asyncio
    async def test_emit_session_started(self) -> None:
        """emit_session_started creates correct payload."""
        session_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            result = await emit_session_started(
                session_id=session_id,
                working_directory="/workspace",
                hook_source="startup",
                git_branch="main",
            )

            assert result.success is True
            assert "session.started" in result.topic

    @pytest.mark.asyncio
    async def test_emit_session_ended(self) -> None:
        """emit_session_ended creates correct payload."""
        session_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            result = await emit_session_ended(
                session_id=session_id,
                reason="clear",
                duration_seconds=1800.0,
                tools_used_count=10,
            )

            assert result.success is True
            assert "session.ended" in result.topic

    @pytest.mark.asyncio
    async def test_emit_prompt_submitted(self) -> None:
        """emit_prompt_submitted creates correct payload."""
        session_id = uuid4()
        prompt_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            result = await emit_prompt_submitted(
                session_id=session_id,
                prompt_id=prompt_id,
                prompt_preview="Test prompt",
                prompt_length=100,
            )

            assert result.success is True
            assert "prompt.submitted" in result.topic

    @pytest.mark.asyncio
    async def test_emit_tool_executed(self) -> None:
        """emit_tool_executed creates correct payload."""
        session_id = uuid4()
        execution_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            result = await emit_tool_executed(
                session_id=session_id,
                tool_execution_id=execution_id,
                tool_name="Read",
                success=True,
                duration_ms=50,
            )

            assert result.success is True
            assert "tool.executed" in result.topic

    @pytest.mark.asyncio
    async def test_convenience_functions_auto_generate_ids(self) -> None:
        """Convenience functions auto-generate causation_id if not provided."""
        session_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            # Should not raise even without causation_id
            result = await emit_session_started(
                session_id=session_id,
                working_directory="/workspace",
                hook_source="startup",
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_convenience_functions_auto_timestamp(self) -> None:
        """Convenience functions auto-generate emitted_at if not provided."""
        session_id = uuid4()

        with patch("omniclaude.hooks.handler_event_emitter.EventBusKafka") as mock_bus_class:
            mock_bus = AsyncMock()
            mock_bus_class.return_value = mock_bus

            # Should not raise even without emitted_at
            result = await emit_session_started(
                session_id=session_id,
                working_directory="/workspace",
                hook_source="startup",
            )

            assert result.success is True
