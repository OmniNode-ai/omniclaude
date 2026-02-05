# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for transformation event publisher.

Tests verify:
- TransformationEventType enum values match TopicBase topics
- Event envelope creation with OnexEnvelopeV1 structure
- User request sanitization (truncation and secret redaction)
- Producer lock lazy creation with double-checked locking
- Convenience methods (publish_transformation_start, complete, failed)
- Non-blocking behavior on failures

Migrated from inline tests in src/omniclaude/lib/transformation_event_publisher.py
per PR #92 review (nitpick: move inline tests to proper test file).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Add src to path to enable direct imports without triggering problematic __init__.py
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from omniclaude.hooks.topics import TopicBase

# Import directly from module file to avoid __init__.py chain that pulls in
# omnibase_infra dependencies not needed for these tests
# Use namespaced module name to avoid polluting sys.modules with generic names
_MODULE_NAME = "omniclaude.tests.transformation_event_publisher"
spec = importlib.util.spec_from_file_location(
    _MODULE_NAME,
    src_path / "omniclaude" / "lib" / "transformation_event_publisher.py",
)
assert spec is not None and spec.loader is not None
tep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tep)

# Register the module in sys.modules for patch() to work
sys.modules[_MODULE_NAME] = tep

MAX_USER_REQUEST_LENGTH = tep.MAX_USER_REQUEST_LENGTH
TransformationEventType = tep.TransformationEventType
_create_event_envelope = tep._create_event_envelope
_sanitize_user_request = tep._sanitize_user_request
close_producer = tep.close_producer
get_producer_lock = tep.get_producer_lock
publish_transformation_complete = tep.publish_transformation_complete
publish_transformation_event = tep.publish_transformation_event
publish_transformation_failed = tep.publish_transformation_failed
publish_transformation_start = tep.publish_transformation_start

pytestmark = pytest.mark.unit


class TestTransformationEventType:
    """Test TransformationEventType enum."""

    def test_started_value_matches_topic_base(self) -> None:
        """Test STARTED enum value matches TopicBase.TRANSFORMATION_STARTED."""
        assert (
            TransformationEventType.STARTED.value
            == TopicBase.TRANSFORMATION_STARTED.value
        )

    def test_completed_value_matches_topic_base(self) -> None:
        """Test COMPLETED enum value matches TopicBase.TRANSFORMATION_COMPLETED."""
        assert (
            TransformationEventType.COMPLETED.value
            == TopicBase.TRANSFORMATION_COMPLETED.value
        )

    def test_failed_value_matches_topic_base(self) -> None:
        """Test FAILED enum value matches TopicBase.TRANSFORMATION_FAILED."""
        assert (
            TransformationEventType.FAILED.value
            == TopicBase.TRANSFORMATION_FAILED.value
        )

    def test_get_topic_name_returns_value(self) -> None:
        """Test get_topic_name returns the enum value (topic name)."""
        for event_type in TransformationEventType:
            assert event_type.get_topic_name() == event_type.value

    def test_topic_names_follow_onex_convention(self) -> None:
        """Test all topic names follow ONEX naming convention."""
        # ONEX convention: onex.{kind}.{producer}.{event-name}.v{n}
        for event_type in TransformationEventType:
            topic = event_type.get_topic_name()
            parts = topic.split(".")
            assert len(parts) == 5, f"Topic {topic} should have 5 parts"
            assert parts[0] == "onex", f"Topic {topic} should start with 'onex'"
            assert parts[1] in ("evt", "cmd"), (
                f"Topic {topic} kind should be evt or cmd"
            )
            assert parts[2] == "omniclaude", (
                f"Topic {topic} producer should be omniclaude"
            )
            assert parts[4].startswith("v"), f"Topic {topic} should end with version"


class TestEventEnvelope:
    """Test event envelope creation."""

    def test_create_event_envelope_structure(self) -> None:
        """Test envelope contains all required OnexEnvelopeV1 fields."""
        envelope = _create_event_envelope(
            event_type=TransformationEventType.COMPLETED,
            payload={"key": "value"},
            correlation_id="corr-123",
        )

        # Required fields
        assert "event_type" in envelope
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert "tenant_id" in envelope
        assert "namespace" in envelope
        assert "source" in envelope
        assert "correlation_id" in envelope
        assert "schema_ref" in envelope
        assert "payload" in envelope

    def test_create_event_envelope_values(self) -> None:
        """Test envelope field values are set correctly."""
        correlation_id = "test-correlation-id"
        payload = {"source_agent": "agent-a", "target_agent": "agent-b"}

        envelope = _create_event_envelope(
            event_type=TransformationEventType.STARTED,
            payload=payload,
            correlation_id=correlation_id,
            tenant_id="custom-tenant",
            namespace="custom-namespace",
            causation_id="cause-123",
        )

        assert envelope["event_type"] == TransformationEventType.STARTED.value
        assert envelope["correlation_id"] == correlation_id
        assert envelope["tenant_id"] == "custom-tenant"
        assert envelope["namespace"] == "custom-namespace"
        assert envelope["source"] == "omniclaude"
        assert envelope["causation_id"] == "cause-123"
        assert envelope["payload"] == payload

    def test_create_event_envelope_schema_ref_format(self) -> None:
        """Test schema_ref follows expected format."""
        envelope = _create_event_envelope(
            event_type=TransformationEventType.FAILED,
            payload={},
            correlation_id="test",
            namespace="onex",
        )

        # Schema ref format: registry://{namespace}/transformation/{event_type}/v1
        expected_schema = "registry://onex/transformation/failed/v1"
        assert envelope["schema_ref"] == expected_schema


class TestUserRequestSanitization:
    """Test user request sanitization for privacy."""

    def test_sanitize_none_returns_none(self) -> None:
        """Test None input returns None."""
        assert _sanitize_user_request(None) is None

    def test_sanitize_empty_string_returns_empty(self) -> None:
        """Test empty string is returned as-is."""
        assert _sanitize_user_request("") == ""

    def test_sanitize_truncates_long_requests(self) -> None:
        """Test long requests are truncated to MAX_USER_REQUEST_LENGTH."""
        long_request = "a" * (MAX_USER_REQUEST_LENGTH + 100)
        result = _sanitize_user_request(long_request)

        assert result is not None
        assert len(result) <= MAX_USER_REQUEST_LENGTH + len("...[TRUNCATED]")
        assert result.endswith("...[TRUNCATED]")

    def test_sanitize_preserves_short_requests(self) -> None:
        """Test short requests are preserved without truncation."""
        short_request = "This is a short request"
        result = _sanitize_user_request(short_request)
        assert result == short_request

    def test_sanitize_redacts_openai_keys(self) -> None:
        """Test OpenAI API keys are redacted."""
        request = "Use this key: sk-1234567890abcdefghijklmnop"
        result = _sanitize_user_request(request)
        assert result is not None
        assert "sk-" not in result
        assert "[OPENAI_KEY_REDACTED]" in result

    def test_sanitize_redacts_aws_keys(self) -> None:
        """Test AWS access keys are redacted."""
        request = "AWS key: AKIA1234567890ABCDEF"
        result = _sanitize_user_request(request)
        assert result is not None
        assert "AKIA" not in result
        assert "[AWS_KEY_REDACTED]" in result

    def test_sanitize_redacts_github_tokens(self) -> None:
        """Test GitHub tokens are redacted."""
        request = "Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = _sanitize_user_request(request)
        assert result is not None
        assert "ghp_" not in result
        assert "[GITHUB_TOKEN_REDACTED]" in result

    def test_sanitize_redacts_bearer_tokens(self) -> None:
        """Test Bearer tokens are redacted."""
        request = "Auth: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = _sanitize_user_request(request)
        assert result is not None
        assert "Bearer eyJ" not in result
        assert "[BEARER_TOKEN_REDACTED]" in result

    def test_sanitize_redacts_passwords_in_urls(self) -> None:
        """Test passwords in URLs are redacted."""
        request = "Connect to postgres://user:mysecretpassword@localhost:5432/db"
        result = _sanitize_user_request(request)
        assert result is not None
        assert "mysecretpassword" not in result
        assert "[PASSWORD_REDACTED]" in result


class TestProducerLock:
    """Test producer lock lazy creation and thread-safety."""

    @pytest.fixture(autouse=True)
    def reset_producer_lock(self) -> None:
        """Reset the global producer lock before each test."""
        tep._producer_lock = None
        yield
        tep._producer_lock = None

    @pytest.mark.asyncio
    async def test_get_producer_lock_returns_asyncio_lock(self) -> None:
        """Test get_producer_lock returns an asyncio.Lock instance."""
        lock = await get_producer_lock()
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_get_producer_lock_returns_singleton(self) -> None:
        """Test get_producer_lock returns the same instance on multiple calls."""
        lock1 = await get_producer_lock()
        lock2 = await get_producer_lock()
        lock3 = await get_producer_lock()
        assert lock1 is lock2 is lock3

    @pytest.mark.asyncio
    async def test_lock_can_be_acquired_and_released(self) -> None:
        """Test the lock can be used for synchronization."""
        lock = await get_producer_lock()

        async with lock:
            # Lock is held
            assert lock.locked()

        # Lock is released
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_concurrent_lock_creation_returns_same_instance(self) -> None:
        """Test concurrent calls to get_producer_lock return the same lock.

        This tests the double-checked locking pattern for thread-safety.
        """
        results: list[asyncio.Lock] = []

        async def get_lock() -> None:
            lock = await get_producer_lock()
            results.append(lock)

        # Create multiple concurrent tasks
        tasks = [get_lock() for _ in range(10)]
        await asyncio.gather(*tasks)

        # All tasks should have received the same lock instance
        assert len(results) == 10
        assert all(lock is results[0] for lock in results)


class TestPublishTransformationEvent:
    """Test the main publish_transformation_event function."""

    @pytest.mark.asyncio
    async def test_returns_false_when_producer_unavailable(self) -> None:
        """Test returns False when Kafka producer cannot be created."""
        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await publish_transformation_event(
                source_agent="agent-a",
                target_agent="agent-b",
                transformation_reason="test",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_generates_correlation_id_when_not_provided(self) -> None:
        """Test correlation_id is generated if not provided."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=mock_producer,
        ):
            await publish_transformation_event(
                source_agent="agent-a",
                target_agent="agent-b",
                transformation_reason="test",
            )

            # Verify send_and_wait was called with a generated correlation_id
            call_args = mock_producer.send_and_wait.call_args
            envelope = call_args[1]["value"]
            assert envelope["correlation_id"] is not None
            assert len(envelope["correlation_id"]) > 0

    @pytest.mark.asyncio
    async def test_uses_provided_correlation_id(self) -> None:
        """Test provided correlation_id is used."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        expected_corr_id = "my-custom-correlation-id"

        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=mock_producer,
        ):
            await publish_transformation_event(
                source_agent="agent-a",
                target_agent="agent-b",
                transformation_reason="test",
                correlation_id=expected_corr_id,
            )

            call_args = mock_producer.send_and_wait.call_args
            envelope = call_args[1]["value"]
            assert envelope["correlation_id"] == expected_corr_id

    @pytest.mark.asyncio
    async def test_routes_to_correct_topic_by_event_type(self) -> None:
        """Test events are routed to correct topic based on event_type."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()

        test_cases = [
            (
                TransformationEventType.STARTED,
                TopicBase.TRANSFORMATION_STARTED.value,
            ),
            (
                TransformationEventType.COMPLETED,
                TopicBase.TRANSFORMATION_COMPLETED.value,
            ),
            (
                TransformationEventType.FAILED,
                TopicBase.TRANSFORMATION_FAILED.value,
            ),
        ]

        for event_type, expected_topic in test_cases:
            mock_producer.send_and_wait.reset_mock()

            with patch.object(
                tep,
                "_get_kafka_producer",
                new_callable=AsyncMock,
                return_value=mock_producer,
            ):
                await publish_transformation_event(
                    source_agent="agent-a",
                    target_agent="agent-b",
                    transformation_reason="test",
                    event_type=event_type,
                )

                call_args = mock_producer.send_and_wait.call_args
                actual_topic = call_args[0][0]
                assert actual_topic == expected_topic, (
                    f"Event type {event_type} should route to {expected_topic}, "
                    f"got {actual_topic}"
                )

    @pytest.mark.asyncio
    async def test_non_blocking_on_exception(self) -> None:
        """Test function returns False on exception, doesn't raise."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(side_effect=Exception("Kafka error"))

        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=mock_producer,
        ):
            # Should not raise, should return False
            result = await publish_transformation_event(
                source_agent="agent-a",
                target_agent="agent-b",
                transformation_reason="test",
            )
            assert result is False


class TestConvenienceMethods:
    """Test convenience methods for common transformation events."""

    @pytest.mark.asyncio
    async def test_publish_transformation_start_uses_started_type(self) -> None:
        """Test publish_transformation_start uses STARTED event type."""
        with patch.object(
            tep,
            "publish_transformation_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_publish:
            await publish_transformation_start(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
            )

            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["event_type"] == TransformationEventType.STARTED

    @pytest.mark.asyncio
    async def test_publish_transformation_complete_uses_completed_type(self) -> None:
        """Test publish_transformation_complete uses COMPLETED event type."""
        with patch.object(
            tep,
            "publish_transformation_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_publish:
            await publish_transformation_complete(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                transformation_duration_ms=45,
            )

            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["event_type"] == TransformationEventType.COMPLETED
            assert call_kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_publish_transformation_failed_uses_failed_type(self) -> None:
        """Test publish_transformation_failed uses FAILED event type."""
        with patch.object(
            tep,
            "publish_transformation_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_publish:
            await publish_transformation_failed(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                error_message="Agent initialization failed",
                error_type="InitializationError",
            )

            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["event_type"] == TransformationEventType.FAILED
            assert call_kwargs["success"] is False
            assert call_kwargs["error_message"] == "Agent initialization failed"
            assert call_kwargs["error_type"] == "InitializationError"


class TestCloseProducer:
    """Test producer cleanup."""

    @pytest.fixture(autouse=True)
    def reset_producer(self) -> None:
        """Reset the global producer before each test."""
        tep._kafka_producer = None
        yield
        tep._kafka_producer = None

    @pytest.mark.asyncio
    async def test_close_producer_when_none(self) -> None:
        """Test close_producer handles None producer gracefully."""
        # Should not raise
        await close_producer()

    @pytest.mark.asyncio
    async def test_close_producer_stops_producer(self) -> None:
        """Test close_producer calls stop on the producer."""
        mock_producer = AsyncMock()
        mock_producer.stop = AsyncMock()
        tep._kafka_producer = mock_producer

        await close_producer()

        mock_producer.stop.assert_called_once()
        assert tep._kafka_producer is None


class TestIntegrationScenarios:
    """Integration-style tests for common transformation scenarios.

    These tests verify the full flow that was previously tested in the
    inline __main__ block.
    """

    @pytest.mark.asyncio
    async def test_full_transformation_lifecycle(self) -> None:
        """Test complete transformation lifecycle: start -> complete."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        correlation_id = str(uuid4())

        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=mock_producer,
        ):
            # Start transformation
            success_start = await publish_transformation_start(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                correlation_id=correlation_id,
                routing_confidence=0.92,
            )
            assert success_start is True

            # Complete transformation
            success_complete = await publish_transformation_complete(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                correlation_id=correlation_id,
                transformation_duration_ms=45,
            )
            assert success_complete is True

        # Verify two events were sent
        assert mock_producer.send_and_wait.call_count == 2

        # Verify first event is STARTED
        first_call = mock_producer.send_and_wait.call_args_list[0]
        assert first_call[0][0] == TopicBase.TRANSFORMATION_STARTED.value

        # Verify second event is COMPLETED
        second_call = mock_producer.send_and_wait.call_args_list[1]
        assert second_call[0][0] == TopicBase.TRANSFORMATION_COMPLETED.value

    @pytest.mark.asyncio
    async def test_transformation_failure_scenario(self) -> None:
        """Test transformation failure event publishing."""
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        correlation_id = str(uuid4())

        with patch.object(
            tep,
            "_get_kafka_producer",
            new_callable=AsyncMock,
            return_value=mock_producer,
        ):
            # Start transformation
            success_start = await publish_transformation_start(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                correlation_id=correlation_id,
            )
            assert success_start is True

            # Transformation fails
            success_failed = await publish_transformation_failed(
                source_agent="polymorphic-agent",
                target_agent="agent-api-architect",
                transformation_reason="API design task detected",
                error_message="Agent initialization failed",
                error_type="InitializationError",
                correlation_id=correlation_id,
            )
            assert success_failed is True

        # Verify events were sent to correct topics
        assert mock_producer.send_and_wait.call_count == 2

        # Second event should be FAILED
        second_call = mock_producer.send_and_wait.call_args_list[1]
        assert second_call[0][0] == TopicBase.TRANSFORMATION_FAILED.value

        # Verify error details in payload
        envelope = second_call[1]["value"]
        assert envelope["payload"]["error_message"] == "Agent initialization failed"
        assert envelope["payload"]["error_type"] == "InitializationError"
        assert envelope["payload"]["success"] is False
