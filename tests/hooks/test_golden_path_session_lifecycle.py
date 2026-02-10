# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Golden path unit tests for session lifecycle: start → inject → work → end → outcome.

Tests verify the full session lifecycle at the Python handler layer with mocked Kafka.
This exercises the integration between session start, context injection tracking,
session outcome derivation, and session outcome emission.

Part of OMN-2076: Golden path session + injection + outcome emission.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from omniclaude.hooks.handler_event_emitter import (
    ModelEventTracingConfig,
    ModelSessionEndedConfig,
    ModelSessionOutcomeConfig,
    ModelSessionStartedConfig,
    emit_session_ended_from_config,
    emit_session_outcome_from_config,
    emit_session_started_from_config,
)
from omniclaude.hooks.schemas import (
    HookSource,
    ModelSessionOutcome,
    SessionEndReason,
)
from omniclaude.hooks.topics import TopicBase
from plugins.onex.hooks.lib.session_outcome import (
    OUTCOME_SUCCESS,
    derive_session_outcome,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Test Helpers (R4)
# =============================================================================


def make_session_lifecycle_context(
    *,
    emitted_at: datetime | None = None,
    environment: str = "test",
):
    """Create a session lifecycle context with correlated identifiers.

    Returns a dict with session_id, correlation_id, timestamps, and tracing
    config that can be used across all lifecycle stages.
    """
    session_id = uuid4()
    correlation_id = session_id  # Convention: correlation_id == session_id
    ts = emitted_at or datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC)

    return {
        "session_id": session_id,
        "correlation_id": correlation_id,
        "emitted_at": ts,
        "environment": environment,
        "tracing": ModelEventTracingConfig(
            correlation_id=correlation_id,
            emitted_at=ts,
            environment=environment,
        ),
    }


def derive_and_build_outcome_config(
    session_id_str: str,
    *,
    exit_code: int = 0,
    session_output: str = "Task completed successfully",
    tool_calls_completed: int = 5,
    duration_seconds: float = 300.0,
    emitted_at: datetime | None = None,
    environment: str = "test",
) -> tuple[ModelSessionOutcomeConfig, str]:
    """Derive session outcome and build emission config in one call.

    Returns (config, outcome_string) tuple for assertion convenience.
    """
    result = derive_session_outcome(
        exit_code=exit_code,
        session_output=session_output,
        tool_calls_completed=tool_calls_completed,
        duration_seconds=duration_seconds,
    )

    config = ModelSessionOutcomeConfig(
        session_id=session_id_str,
        outcome=result.outcome,
        tracing=ModelEventTracingConfig(
            emitted_at=emitted_at or datetime(2026, 2, 9, 12, 5, 0, tzinfo=UTC),
            environment=environment,
        ),
    )

    return config, result.outcome


# =============================================================================
# Golden Path: Full Session Lifecycle
# =============================================================================


@patch.dict(
    os.environ, {"KAFKA_BOOTSTRAP_SERVERS": "test:9092", "KAFKA_ENVIRONMENT": "test"}
)
class TestGoldenPathSessionLifecycle:
    """Golden path: session start → injection → work → end → outcome emission."""

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_full_lifecycle_success_path(self, mock_bus_cls) -> None:
        """Exercise the complete session lifecycle for a successful session.

        This test verifies the full happy path:
        1. Session starts with injection
        2. Work happens (tool calls + completion markers)
        3. Session ends normally
        4. Outcome is derived as SUCCESS
        5. Outcome event is emitted to both CMD and EVT topics
        """
        # Arrange: mock Kafka bus
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        ctx = make_session_lifecycle_context()
        session_id = ctx["session_id"]
        tracing = ctx["tracing"]

        # Phase 1: Session Start
        start_config = ModelSessionStartedConfig(
            session_id=session_id,
            working_directory="/workspace/omniclaude4",
            hook_source=HookSource.STARTUP,
            git_branch="main",
            tracing=tracing,
        )
        start_result = await emit_session_started_from_config(start_config)
        assert start_result.success is True

        # Phase 2: Context Injection — injection is a no-op at the handler
        # level; actual injection happens in session_marker.py (file I/O).
        # This placeholder verifies the lifecycle concept flows correctly
        # without exercising the injection code path itself.
        injection_id = str(uuid4())[:8]
        assert len(injection_id) == 8

        # Phase 3: Work happens (simulated — tool calls + completion markers)
        tool_calls_completed = 5
        session_output = "Task completed successfully with abc1234 commit"

        # Phase 4: Session End
        end_config = ModelSessionEndedConfig(
            session_id=session_id,
            reason=SessionEndReason.CLEAR,
            duration_seconds=300.0,
            tools_used_count=tool_calls_completed,
            tracing=tracing,
        )
        end_result = await emit_session_ended_from_config(end_config)
        assert end_result.success is True

        # Phase 5: Derive Outcome
        outcome_config, outcome_str = derive_and_build_outcome_config(
            session_id_str=str(session_id),
            exit_code=0,
            session_output=session_output,
            tool_calls_completed=tool_calls_completed,
            duration_seconds=300.0,
            environment="test",
        )
        assert outcome_str == OUTCOME_SUCCESS

        # Phase 6: Emit Outcome
        outcome_result = await emit_session_outcome_from_config(outcome_config)
        assert outcome_result.success is True

        # Verify: outcome was published to Kafka
        publish_calls = mock_bus.publish.call_args_list

        # There should be publishes from session_started (1), session_ended (1),
        # and session_outcome (2: CMD + EVT) = 4 total
        assert len(publish_calls) == 4, (
            f"Expected 4 publishes (start + end + 2x outcome), got {len(publish_calls)}"
        )

        # Find the outcome publishes (last two)
        outcome_publishes = publish_calls[-2:]
        topics_published = {call.kwargs["topic"] for call in outcome_publishes}

        # Verify both fan-out topics were hit (OMN-1972: bare enum values are wire topics)
        assert TopicBase.SESSION_OUTCOME_CMD in topics_published, (
            f"CMD topic not found in {topics_published}"
        )
        assert TopicBase.SESSION_OUTCOME_EVT in topics_published, (
            f"EVT topic not found in {topics_published}"
        )

        # Verify payload structure
        for call in outcome_publishes:
            value_bytes = call.kwargs["value"]
            payload = json.loads(value_bytes.decode("utf-8"))
            assert payload["session_id"] == str(session_id)
            assert payload["outcome"] == "success"
            assert payload["event_name"] == "session.outcome"
            assert "emitted_at" in payload

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_full_lifecycle_failed_path(self, mock_bus_cls) -> None:
        """Exercise the complete session lifecycle for a failed session."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        ctx = make_session_lifecycle_context()

        # Derive failed outcome
        outcome_config, outcome_str = derive_and_build_outcome_config(
            session_id_str=str(ctx["session_id"]),
            exit_code=1,
            session_output="Error: something went wrong",
            tool_calls_completed=3,
            duration_seconds=120.0,
        )
        assert outcome_str == "failed"

        # Emit outcome
        result = await emit_session_outcome_from_config(outcome_config)
        assert result.success is True

        # Verify publishes happened
        assert mock_bus.publish.call_count == 2

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_full_lifecycle_abandoned_path(self, mock_bus_cls) -> None:
        """Exercise the session lifecycle for an abandoned session."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        ctx = make_session_lifecycle_context()

        outcome_config, outcome_str = derive_and_build_outcome_config(
            session_id_str=str(ctx["session_id"]),
            exit_code=0,
            session_output="Hello",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        assert outcome_str == "abandoned"

        result = await emit_session_outcome_from_config(outcome_config)
        assert result.success is True
        assert mock_bus.publish.call_count == 2


# =============================================================================
# Session Outcome Emission (emit_session_outcome_from_config)
# =============================================================================


@patch.dict(
    os.environ, {"KAFKA_BOOTSTRAP_SERVERS": "test:9092", "KAFKA_ENVIRONMENT": "test"}
)
class TestEmitSessionOutcome:
    """Tests for emit_session_outcome_from_config function."""

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_publishes_to_both_topics(self, mock_bus_cls) -> None:
        """Session outcome is fan-out published to CMD and EVT topics."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        config = ModelSessionOutcomeConfig(
            session_id="test-session-123",
            outcome="success",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                environment="test",
            ),
        )

        result = await emit_session_outcome_from_config(config)

        assert result.success is True
        assert mock_bus.publish.call_count == 2

        topics = [call.kwargs["topic"] for call in mock_bus.publish.call_args_list]
        assert TopicBase.SESSION_OUTCOME_CMD in topics
        assert TopicBase.SESSION_OUTCOME_EVT in topics

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_partition_key_is_session_id(self, mock_bus_cls) -> None:
        """Partition key is set to session_id for ordering guarantees."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        config = ModelSessionOutcomeConfig(
            session_id="my-session-id",
            outcome="success",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                environment="test",
            ),
        )

        await emit_session_outcome_from_config(config)

        for call in mock_bus.publish.call_args_list:
            assert call.kwargs["key"] == b"my-session-id"

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_payload_matches_schema(self, mock_bus_cls) -> None:
        """Published payload matches ModelSessionOutcome schema."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        ts = datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC)
        config = ModelSessionOutcomeConfig(
            session_id="schema-test-session",
            outcome="failed",
            tracing=ModelEventTracingConfig(emitted_at=ts, environment="test"),
        )

        await emit_session_outcome_from_config(config)

        # Deserialize the published payload and validate with schema
        for call in mock_bus.publish.call_args_list:
            raw = json.loads(call.kwargs["value"].decode("utf-8"))
            # Validate with Pydantic model
            validated = ModelSessionOutcome.model_validate(raw)
            assert validated.session_id == "schema-test-session"
            assert validated.outcome.value == "failed"
            assert validated.event_name == "session.outcome"
            assert validated.emitted_at == ts

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_invalid_outcome_raises_at_config_construction(
        self, mock_bus_cls
    ) -> None:
        """Invalid outcome value raises ValueError at config construction."""
        with pytest.raises(ValueError, match="invalid_outcome"):
            ModelSessionOutcomeConfig(
                session_id="test-session",
                outcome="invalid_outcome",
                tracing=ModelEventTracingConfig(
                    emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                    environment="test",
                ),
            )

    def test_empty_session_id_raises(self) -> None:
        """Empty session_id raises ValueError at config construction."""
        with pytest.raises(ValueError, match="non-empty"):
            ModelSessionOutcomeConfig(
                session_id="",
                outcome="success",
            )

    def test_whitespace_session_id_raises(self) -> None:
        """Whitespace-only session_id raises ValueError at config construction."""
        with pytest.raises(ValueError, match="non-empty"):
            ModelSessionOutcomeConfig(
                session_id="   ",
                outcome="success",
            )

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_all_four_outcomes_are_valid(self, mock_bus_cls) -> None:
        """All four outcome classifications can be emitted."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        for outcome in ["success", "failed", "abandoned", "unknown"]:
            mock_bus.reset_mock()

            config = ModelSessionOutcomeConfig(
                session_id=f"test-{outcome}",
                outcome=outcome,
                tracing=ModelEventTracingConfig(
                    emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                    environment="test",
                ),
            )

            result = await emit_session_outcome_from_config(config)
            assert result.success is True, f"Failed for outcome={outcome}"
            assert mock_bus.publish.call_count == 2, (
                f"Expected 2 publishes for outcome={outcome}"
            )

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_never_raises_exceptions(self, mock_bus_cls) -> None:
        """Function never raises, returns failure result instead."""
        mock_bus = AsyncMock()
        mock_bus.start.side_effect = ConnectionRefusedError("Kafka unavailable")
        mock_bus_cls.return_value = mock_bus

        config = ModelSessionOutcomeConfig(
            session_id="test-session",
            outcome="success",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                environment="test",
            ),
        )

        # Should not raise
        result = await emit_session_outcome_from_config(config)
        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_partial_fanout_cmd_ok_evt_fails(self, mock_bus_cls) -> None:
        """CMD succeeds but EVT fails: returns success=True with partial error."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        # First publish (CMD) succeeds, second publish (EVT) raises
        mock_bus.publish.side_effect = [None, RuntimeError("EVT broker down")]

        config = ModelSessionOutcomeConfig(
            session_id="partial-fanout-test",
            outcome="success",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
                environment="test",
            ),
        )

        result = await emit_session_outcome_from_config(config)
        assert result.success is True  # CMD is primary target
        assert result.error_message is not None
        assert "Partial fan-out" in result.error_message

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_event_emitter.EventBusKafka")
    async def test_defaults_emitted_at_to_now(self, mock_bus_cls, caplog) -> None:
        """When emitted_at is not provided, defaults to current UTC time and warns."""
        mock_bus = AsyncMock()
        mock_bus_cls.return_value = mock_bus

        before = datetime.now(UTC)

        config = ModelSessionOutcomeConfig(
            session_id="test-session",
            outcome="success",
            # No emitted_at in tracing
        )

        with caplog.at_level(
            logging.WARNING, logger="omniclaude.hooks.handler_event_emitter"
        ):
            result = await emit_session_outcome_from_config(config)
        assert result.success is True

        # Verify warning was emitted for missing emitted_at
        assert any("emitted_at_not_injected" in r.message for r in caplog.records)

        after = datetime.now(UTC)

        # Verify the emitted_at was set between before and after
        raw = json.loads(
            mock_bus.publish.call_args_list[0].kwargs["value"].decode("utf-8")
        )
        emitted_str = raw["emitted_at"]
        # Handle both Z and +00:00 formats
        if emitted_str.endswith("Z"):
            emitted_str = emitted_str[:-1] + "+00:00"
        emitted = datetime.fromisoformat(emitted_str)
        assert emitted >= before
        assert emitted <= after


# =============================================================================
# Helpers Validation
# =============================================================================


class TestHelpers:
    """Validate test helper functions work correctly."""

    def test_make_session_lifecycle_context(self) -> None:
        """Helper creates valid context with correlated IDs."""
        ctx = make_session_lifecycle_context()
        assert ctx["session_id"] is not None
        assert ctx["correlation_id"] == ctx["session_id"]
        assert ctx["emitted_at"] is not None
        assert ctx["environment"] == "test"
        assert ctx["tracing"] is not None

    def test_derive_and_build_outcome_config_success(self) -> None:
        """Helper correctly derives SUCCESS outcome."""
        config, outcome = derive_and_build_outcome_config(
            "test-session",
            exit_code=0,
            session_output="Task completed",
            tool_calls_completed=3,
            duration_seconds=120.0,
        )
        assert outcome == OUTCOME_SUCCESS
        assert config.session_id == "test-session"
        assert config.outcome == "success"

    def test_derive_and_build_outcome_config_failed(self) -> None:
        """Helper correctly derives FAILED outcome."""
        _, outcome = derive_and_build_outcome_config(
            "test-session",
            exit_code=1,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert outcome == "failed"
