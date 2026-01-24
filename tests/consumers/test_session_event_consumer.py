# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for SessionEventConsumer.

These tests verify the Kafka consumer implementation for Claude Code
session events. Tests focus on:
    - Consumer initialization and configuration
    - Circuit breaker state transitions
    - Message processing flow
    - At-least-once delivery semantics (via offset commit behavior)
    - Graceful shutdown

Note:
    These are unit tests that mock Kafka connections. Integration tests
    with real Kafka are in test_integration_kafka.py.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from omniclaude.aggregators.protocol_session_aggregator import (
    ProtocolSessionAggregator,
)
from omniclaude.consumers import (
    ConfigSessionConsumer,
    ConsumerMetrics,
    EnumCircuitState,
    SessionEventConsumer,
)
from omniclaude.hooks.schemas import (
    HookEventType,
    HookSource,
    ModelHookEventEnvelope,
    ModelHookSessionStartedPayload,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockAggregator:
    """Mock aggregator for testing.

    Implements the ProtocolSessionAggregator interface for unit tests.
    """

    def __init__(self) -> None:
        self._id = f"mock-aggregator-{uuid4().hex[:8]}"
        self._events: list[object] = []
        self._should_fail = False
        self._should_reject = False

    @property
    def aggregator_id(self) -> str:
        return self._id

    async def process_event(self, event: object, correlation_id: UUID) -> bool:
        if self._should_fail:
            raise RuntimeError("Simulated aggregator failure")
        if self._should_reject:
            return False
        self._events.append(event)
        return True

    async def get_snapshot(
        self, session_id: str, correlation_id: UUID
    ) -> object | None:
        return None

    async def finalize_session(
        self, session_id: str, correlation_id: UUID, reason: str | None = None
    ) -> object | None:
        return None

    async def get_active_sessions(self, correlation_id: UUID) -> list[str]:
        return []

    async def get_session_last_activity(
        self, session_id: str, correlation_id: UUID
    ) -> datetime | None:
        return None


@pytest.fixture
def config() -> ConfigSessionConsumer:
    """Create a test configuration."""
    return ConfigSessionConsumer(
        bootstrap_servers="localhost:9092",
        group_id="test-consumer-group",
        topics=["dev.omniclaude.session.started.v1"],
        circuit_breaker_threshold=3,
        circuit_breaker_timeout_seconds=5,
    )


@pytest.fixture
def aggregator() -> MockAggregator:
    """Create a mock aggregator."""
    return MockAggregator()


@pytest.fixture
def consumer(
    config: ConfigSessionConsumer, aggregator: MockAggregator
) -> SessionEventConsumer:
    """Create a consumer instance for testing."""
    return SessionEventConsumer(config=config, aggregator=aggregator)


def create_test_envelope() -> ModelHookEventEnvelope:
    """Create a test event envelope."""
    session_id = uuid4()
    payload = ModelHookSessionStartedPayload(
        entity_id=session_id,
        session_id=str(session_id),
        correlation_id=session_id,
        causation_id=uuid4(),
        emitted_at=datetime.now(UTC),
        working_directory="/workspace/test",
        git_branch="main",
        hook_source=HookSource.STARTUP,
    )
    return ModelHookEventEnvelope(
        event_type=HookEventType.SESSION_STARTED,
        payload=payload,
    )


# =============================================================================
# Consumer Initialization Tests
# =============================================================================


class TestConsumerInitialization:
    """Tests for consumer initialization."""

    def test_consumer_initializes_with_config(
        self, config: ConfigSessionConsumer, aggregator: MockAggregator
    ) -> None:
        """Consumer should initialize with provided config."""
        consumer = SessionEventConsumer(config=config, aggregator=aggregator)

        assert consumer.is_running is False
        assert consumer.circuit_state == EnumCircuitState.CLOSED
        assert consumer.consumer_id.startswith("session-consumer-")

    def test_consumer_uses_default_config(
        self, aggregator: MockAggregator
    ) -> None:
        """Consumer should work with default config."""
        config = ConfigSessionConsumer()
        consumer = SessionEventConsumer(config=config, aggregator=aggregator)

        assert consumer._config.group_id == "omniclaude-session-consumer"

    def test_consumer_has_metrics(self, consumer: SessionEventConsumer) -> None:
        """Consumer should have metrics instance."""
        assert consumer.metrics is not None
        assert isinstance(consumer.metrics, ConsumerMetrics)


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    async def test_circuit_starts_closed(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Circuit should start in closed state."""
        assert consumer.circuit_state == EnumCircuitState.CLOSED
        assert await consumer._is_circuit_open() is False

    async def test_circuit_opens_after_threshold_failures(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Circuit should open after consecutive failures exceed threshold."""
        # Record failures up to threshold
        for _ in range(consumer._config.circuit_breaker_threshold):
            await consumer._record_failure()

        assert consumer.circuit_state == EnumCircuitState.OPEN
        assert await consumer._is_circuit_open() is True

    async def test_circuit_stays_closed_below_threshold(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Circuit should stay closed when failures below threshold."""
        # Record one less than threshold
        for _ in range(consumer._config.circuit_breaker_threshold - 1):
            await consumer._record_failure()

        assert consumer.circuit_state == EnumCircuitState.CLOSED

    async def test_success_resets_failure_count(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Success should reset the consecutive failure count."""
        # Record some failures
        for _ in range(2):
            await consumer._record_failure()

        # Record success
        await consumer._record_success()

        # Record failures again - should need full threshold
        for _ in range(consumer._config.circuit_breaker_threshold - 1):
            await consumer._record_failure()

        assert consumer.circuit_state == EnumCircuitState.CLOSED

    async def test_success_closes_half_open_circuit(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Success in half-open state should close circuit."""
        # Open the circuit
        for _ in range(consumer._config.circuit_breaker_threshold):
            await consumer._record_failure()

        # Manually set to half-open
        async with consumer._circuit_lock:
            consumer._circuit_state = EnumCircuitState.HALF_OPEN

        # Record success
        await consumer._record_success()

        assert consumer.circuit_state == EnumCircuitState.CLOSED

    async def test_circuit_metrics_recorded(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Circuit open events should be recorded in metrics."""
        # Open the circuit
        for _ in range(consumer._config.circuit_breaker_threshold):
            await consumer._record_failure()

        metrics = await consumer.metrics.snapshot()
        assert metrics["circuit_opens"] == 1


# =============================================================================
# Metrics Tests
# =============================================================================


class TestConsumerMetrics:
    """Tests for ConsumerMetrics."""

    async def test_metrics_start_at_zero(self) -> None:
        """Metrics should start at zero."""
        metrics = ConsumerMetrics()
        snapshot = await metrics.snapshot()

        assert snapshot["messages_received"] == 0
        assert snapshot["messages_processed"] == 0
        assert snapshot["messages_failed"] == 0
        assert snapshot["messages_skipped"] == 0
        assert snapshot["circuit_opens"] == 0
        assert snapshot["last_message_at"] is None

    async def test_record_received_increments(self) -> None:
        """record_received should increment counter."""
        metrics = ConsumerMetrics()

        await metrics.record_received()
        await metrics.record_received()

        snapshot = await metrics.snapshot()
        assert snapshot["messages_received"] == 2
        assert snapshot["last_message_at"] is not None

    async def test_record_processed_increments(self) -> None:
        """record_processed should increment counter."""
        metrics = ConsumerMetrics()

        await metrics.record_processed()

        snapshot = await metrics.snapshot()
        assert snapshot["messages_processed"] == 1

    async def test_record_failed_increments(self) -> None:
        """record_failed should increment counter."""
        metrics = ConsumerMetrics()

        await metrics.record_failed()
        await metrics.record_failed()
        await metrics.record_failed()

        snapshot = await metrics.snapshot()
        assert snapshot["messages_failed"] == 3

    async def test_record_skipped_increments(self) -> None:
        """record_skipped should increment counter."""
        metrics = ConsumerMetrics()

        await metrics.record_skipped()

        snapshot = await metrics.snapshot()
        assert snapshot["messages_skipped"] == 1


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for health check functionality."""

    async def test_health_check_not_running(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Health check should show unhealthy when not running."""
        health = await consumer.health_check()

        assert health["healthy"] is False
        assert health["running"] is False
        assert health["circuit_state"] == "closed"

    async def test_health_check_reports_circuit_state(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Health check should report circuit breaker state."""
        # Open the circuit
        for _ in range(consumer._config.circuit_breaker_threshold):
            await consumer._record_failure()

        health = await consumer.health_check()

        assert health["circuit_state"] == "open"

    async def test_health_check_includes_metrics(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Health check should include metrics."""
        health = await consumer.health_check()

        assert "metrics" in health
        assert isinstance(health["metrics"], dict)


# =============================================================================
# Message Processing Tests
# =============================================================================


class TestMessageProcessing:
    """Tests for message processing."""

    async def test_process_message_calls_aggregator(
        self, consumer: SessionEventConsumer, aggregator: MockAggregator
    ) -> None:
        """Processing should call aggregator.process_event."""
        envelope = create_test_envelope()
        message = MagicMock()
        message.value = envelope.model_dump_json().encode("utf-8")
        message.topic = "test-topic"

        result = await consumer._process_message(message, uuid4())

        assert result is True
        assert len(aggregator._events) == 1

    async def test_process_message_returns_false_on_reject(
        self, consumer: SessionEventConsumer, aggregator: MockAggregator
    ) -> None:
        """Processing should return False when aggregator rejects."""
        aggregator._should_reject = True

        envelope = create_test_envelope()
        message = MagicMock()
        message.value = envelope.model_dump_json().encode("utf-8")
        message.topic = "test-topic"

        result = await consumer._process_message(message, uuid4())

        assert result is False

    async def test_process_message_raises_on_aggregator_error(
        self, consumer: SessionEventConsumer, aggregator: MockAggregator
    ) -> None:
        """Processing should raise when aggregator fails."""
        aggregator._should_fail = True

        envelope = create_test_envelope()
        message = MagicMock()
        message.value = envelope.model_dump_json().encode("utf-8")
        message.topic = "test-topic"

        with pytest.raises(RuntimeError, match="Simulated aggregator failure"):
            await consumer._process_message(message, uuid4())

    async def test_process_message_handles_bytes(
        self, consumer: SessionEventConsumer, aggregator: MockAggregator
    ) -> None:
        """Processing should handle bytes message value."""
        envelope = create_test_envelope()
        message = MagicMock()
        message.value = envelope.model_dump_json().encode("utf-8")
        message.topic = "test-topic"

        result = await consumer._process_message(message, uuid4())

        assert result is True

    async def test_process_message_handles_string(
        self, consumer: SessionEventConsumer, aggregator: MockAggregator
    ) -> None:
        """Processing should handle string message value."""
        envelope = create_test_envelope()
        message = MagicMock()
        message.value = envelope.model_dump_json()  # String, not bytes
        message.topic = "test-topic"

        result = await consumer._process_message(message, uuid4())

        assert result is True

    async def test_process_message_handles_none_value(
        self, consumer: SessionEventConsumer
    ) -> None:
        """Processing should return False for None value."""
        message = MagicMock()
        message.value = None
        message.topic = "test-topic"

        result = await consumer._process_message(message, uuid4())

        assert result is False


# =============================================================================
# Enum Tests
# =============================================================================


class TestEnumCircuitState:
    """Tests for EnumCircuitState."""

    def test_circuit_states_are_strings(self) -> None:
        """Circuit states should be string enums."""
        assert EnumCircuitState.CLOSED.value == "closed"
        assert EnumCircuitState.OPEN.value == "open"
        assert EnumCircuitState.HALF_OPEN.value == "half_open"

    def test_circuit_state_comparison(self) -> None:
        """Circuit states should support string comparison."""
        assert EnumCircuitState.CLOSED == "closed"
        assert EnumCircuitState("open") == EnumCircuitState.OPEN


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestContextManager:
    """Tests for async context manager support."""

    async def test_context_manager_calls_start_and_stop(
        self, config: ConfigSessionConsumer, aggregator: MockAggregator
    ) -> None:
        """Context manager should call start on enter and stop on exit."""
        consumer = SessionEventConsumer(config=config, aggregator=aggregator)

        with patch.object(consumer, "start", new_callable=AsyncMock) as mock_start:
            with patch.object(consumer, "stop", new_callable=AsyncMock) as mock_stop:
                async with consumer:
                    mock_start.assert_called_once()
                    mock_stop.assert_not_called()

                mock_stop.assert_called_once()


# =============================================================================
# Import Tests
# =============================================================================


class TestImports:
    """Tests for module imports."""

    def test_session_event_consumer_importable(self) -> None:
        """SessionEventConsumer should be importable from package."""
        from omniclaude.consumers import SessionEventConsumer

        assert SessionEventConsumer is not None

    def test_config_importable(self) -> None:
        """ConfigSessionConsumer should be importable from package."""
        from omniclaude.consumers import ConfigSessionConsumer

        assert ConfigSessionConsumer is not None

    def test_metrics_importable(self) -> None:
        """ConsumerMetrics should be importable from package."""
        from omniclaude.consumers import ConsumerMetrics

        assert ConsumerMetrics is not None

    def test_enum_importable(self) -> None:
        """EnumCircuitState should be importable from package."""
        from omniclaude.consumers import EnumCircuitState

        assert EnumCircuitState is not None
