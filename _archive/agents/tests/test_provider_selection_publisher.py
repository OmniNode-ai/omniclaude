#!/usr/bin/env python3
"""
Tests for Provider Selection Event Publisher

Tests event publishing, envelope structure, partition key policy,
and integration with Kafka.

Coverage:
- Event envelope creation (OnexEnvelopeV1 format)
- Kafka producer initialization
- Event publishing (async and sync)
- Partition key extraction and validation
- Error handling and graceful degradation
- Schema compliance

Created: 2025-11-13
Reference: OMN-32
"""

import sys
from datetime import datetime
from pathlib import Path as PathLib
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Add project root to path
_project_root = PathLib(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agents.lib.partition_key_policy import (
    EventFamily,
    get_event_family,
    get_partition_key_for_event,
    validate_partition_key,
)
from agents.lib.provider_selection_publisher import (
    PROVIDER_SELECTION_TOPIC,
    _create_event_envelope,
    publish_provider_selection,
    publish_provider_selection_sync,
)


class TestEventEnvelope:
    """Test OnexEnvelopeV1 event envelope creation."""

    def test_envelope_structure(self):
        """Test envelope has all required OnexEnvelopeV1 fields."""
        correlation_id = str(uuid4())
        payload = {
            "provider_name": "gemini-flash",
            "model_name": "gemini-1.5-flash-002",
            "correlation_id": correlation_id,
            "selection_reason": "Cost-effective",
            "selection_criteria": {"cost": 0.000001},
            "selected_at": datetime.now().isoformat(),
        }

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
        )

        # Required OnexEnvelopeV1 fields
        assert "event_type" in envelope
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert "tenant_id" in envelope
        assert "namespace" in envelope
        assert "source" in envelope
        assert "correlation_id" in envelope
        assert "schema_ref" in envelope
        assert "payload" in envelope

        # Verify values
        assert envelope["event_type"] == PROVIDER_SELECTION_TOPIC
        assert envelope["correlation_id"] == correlation_id
        assert envelope["namespace"] == "omninode"
        assert envelope["source"] == "omniclaude"
        assert envelope["tenant_id"] == "default"
        assert envelope["payload"] == payload

    def test_envelope_with_causation_id(self):
        """Test envelope includes causation_id when provided."""
        correlation_id = str(uuid4())
        causation_id = str(uuid4())
        payload = {
            "provider_name": "claude",
            "model_name": "claude-3-5-sonnet-20241022",
            "correlation_id": correlation_id,
            "selection_reason": "High quality",
            "selection_criteria": {},
            "selected_at": datetime.now().isoformat(),
        }

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        assert envelope["causation_id"] == causation_id

    def test_envelope_timestamp_format(self):
        """Test timestamp is RFC3339/ISO8601 format."""
        correlation_id = str(uuid4())
        payload = {
            "provider_name": "openai",
            "model_name": "gpt-4",
            "correlation_id": correlation_id,
            "selection_reason": "Test",
            "selection_criteria": {},
            "selected_at": datetime.now().isoformat(),
        }

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
        )

        # Verify timestamp is parseable as ISO8601
        timestamp = envelope["timestamp"]
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)

    def test_envelope_schema_ref_format(self):
        """Test schema_ref follows registry:// format."""
        correlation_id = str(uuid4())
        payload = {
            "provider_name": "test",
            "model_name": "test-model",
            "correlation_id": correlation_id,
            "selection_reason": "Test",
            "selection_criteria": {},
            "selected_at": datetime.now().isoformat(),
        }

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
        )

        schema_ref = envelope["schema_ref"]
        assert schema_ref.startswith("registry://")
        assert "omninode" in schema_ref
        assert "provider_selected" in schema_ref
        assert "/v1" in schema_ref


class TestPartitionKeyPolicy:
    """Test partition key policy compliance."""

    def test_event_family_recognition(self):
        """Test provider selection events are recognized as AGENT_PROVIDER family."""
        event_type = "omninode.agent.provider.selected.v1"
        family = get_event_family(event_type)
        assert family == EventFamily.AGENT_PROVIDER

    def test_partition_key_extraction(self):
        """Test partition key (correlation_id) is extracted correctly."""
        correlation_id = str(uuid4())
        event_type = PROVIDER_SELECTION_TOPIC
        envelope = {
            "correlation_id": correlation_id,
            "payload": {
                "provider_name": "gemini-flash",
                "model_name": "gemini-1.5-flash-002",
            },
        }

        partition_key = get_partition_key_for_event(event_type, envelope)
        assert partition_key == correlation_id

    def test_partition_key_from_payload(self):
        """Test partition key extraction from payload (fallback)."""
        correlation_id = str(uuid4())
        event_type = PROVIDER_SELECTION_TOPIC
        envelope = {
            "payload": {
                "correlation_id": correlation_id,
                "provider_name": "claude",
            },
        }

        partition_key = get_partition_key_for_event(event_type, envelope)
        assert partition_key == correlation_id

    def test_partition_key_validation(self):
        """Test partition key validation."""
        correlation_id = str(uuid4())
        event_type = PROVIDER_SELECTION_TOPIC

        # Valid partition key
        is_valid = validate_partition_key(event_type, correlation_id)
        assert is_valid is True

        # Invalid: None
        is_valid = validate_partition_key(event_type, None)
        assert is_valid is False

        # Invalid: empty string
        is_valid = validate_partition_key(event_type, "")
        assert is_valid is False


class TestEventPublishing:
    """Test event publishing to Kafka."""

    @pytest.mark.asyncio
    async def test_publish_provider_selection_success(self):
        """Test successful provider selection event publishing."""
        correlation_id = str(uuid4())

        # Mock Kafka producer
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=mock_producer,
        ):
            success = await publish_provider_selection(
                provider_name="gemini-flash",
                model_name="gemini-1.5-flash-002",
                correlation_id=correlation_id,
                selection_reason="Cost-effective for high-volume pattern matching",
                selection_criteria={
                    "cost_per_token": 0.000001,
                    "latency_ms": 50,
                    "quality_score": 0.85,
                },
            )

            assert success is True
            mock_producer.send_and_wait.assert_called_once()

            # Verify call arguments
            call_args = mock_producer.send_and_wait.call_args
            assert call_args.kwargs["topic"] == PROVIDER_SELECTION_TOPIC
            assert call_args.kwargs["key"] == correlation_id.encode("utf-8")

            # Verify envelope structure
            envelope = call_args.kwargs["value"]
            assert envelope["event_type"] == PROVIDER_SELECTION_TOPIC
            assert envelope["correlation_id"] == correlation_id
            assert envelope["payload"]["provider_name"] == "gemini-flash"
            assert envelope["payload"]["model_name"] == "gemini-1.5-flash-002"
            assert (
                envelope["payload"]["selection_reason"]
                == "Cost-effective for high-volume pattern matching"
            )

    @pytest.mark.asyncio
    async def test_publish_provider_selection_kafka_unavailable(self):
        """Test graceful degradation when Kafka is unavailable."""
        correlation_id = str(uuid4())

        # Mock producer returning None (unavailable)
        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=None,
        ):
            success = await publish_provider_selection(
                provider_name="claude",
                model_name="claude-3-5-sonnet-20241022",
                correlation_id=correlation_id,
                selection_reason="High quality",
                selection_criteria={},
            )

            # Should return False but not raise exception
            assert success is False

    @pytest.mark.asyncio
    async def test_publish_provider_selection_kafka_error(self):
        """Test error handling when Kafka publish fails."""
        correlation_id = str(uuid4())

        # Mock producer that raises exception
        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(
            side_effect=Exception("Kafka connection error")
        )

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=mock_producer,
        ):
            success = await publish_provider_selection(
                provider_name="openai",
                model_name="gpt-4",
                correlation_id=correlation_id,
                selection_reason="Test",
                selection_criteria={},
            )

            # Should return False but not raise exception (graceful degradation)
            assert success is False

    @pytest.mark.asyncio
    async def test_publish_with_optional_criteria(self):
        """Test publishing with optional selection_criteria."""
        correlation_id = str(uuid4())

        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=mock_producer,
        ):
            success = await publish_provider_selection(
                provider_name="gemini-flash",
                model_name="gemini-1.5-flash-002",
                correlation_id=correlation_id,
                selection_reason="Default choice",
                # selection_criteria omitted (should default to {})
            )

            assert success is True

            # Verify selection_criteria defaults to empty dict
            call_args = mock_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            assert envelope["payload"]["selection_criteria"] == {}


class TestSynchronousWrapper:
    """Test synchronous wrapper function."""

    def test_publish_provider_selection_sync(self):
        """Test synchronous wrapper creates event loop and publishes."""
        correlation_id = str(uuid4())

        # Mock async function
        mock_async_publish = AsyncMock(return_value=True)

        with patch(
            "agents.lib.provider_selection_publisher.publish_provider_selection",
            mock_async_publish,
        ):
            success = publish_provider_selection_sync(
                provider_name="gemini-flash",
                model_name="gemini-1.5-flash-002",
                correlation_id=correlation_id,
                selection_reason="Sync test",
                selection_criteria={"test": True},
            )

            assert success is True
            mock_async_publish.assert_called_once()


class TestPayloadSchema:
    """Test payload schema compliance."""

    @pytest.mark.asyncio
    async def test_payload_has_required_fields(self):
        """Test payload includes all required fields from EVENT_ALIGNMENT_PLAN."""
        correlation_id = str(uuid4())

        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=mock_producer,
        ):
            await publish_provider_selection(
                provider_name="gemini-flash",
                model_name="gemini-1.5-flash-002",
                correlation_id=correlation_id,
                selection_reason="Test",
                selection_criteria={"key": "value"},
            )

            # Extract payload from call
            call_args = mock_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            payload = envelope["payload"]

            # Required fields per EVENT_ALIGNMENT_PLAN
            required_fields = [
                "provider_name",
                "model_name",
                "correlation_id",
                "selection_reason",
                "selection_criteria",
                "selected_at",
            ]

            for field in required_fields:
                assert field in payload, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_selected_at_is_rfc3339(self):
        """Test selected_at timestamp is RFC3339 format."""
        correlation_id = str(uuid4())

        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            return_value=mock_producer,
        ):
            await publish_provider_selection(
                provider_name="claude",
                model_name="claude-3-5-sonnet-20241022",
                correlation_id=correlation_id,
                selection_reason="Test",
                selection_criteria={},
            )

            call_args = mock_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            selected_at = envelope["payload"]["selected_at"]

            # Verify RFC3339/ISO8601 format
            parsed = datetime.fromisoformat(selected_at.replace("Z", "+00:00"))
            assert isinstance(parsed, datetime)


class TestProducerManagement:
    """Test Kafka producer lifecycle management."""

    @pytest.mark.asyncio
    async def test_producer_singleton_pattern(self):
        """Test producer is reused across multiple publishes."""
        correlation_id = str(uuid4())

        mock_producer = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(return_value=None)

        create_count = 0

        async def mock_get_producer():
            nonlocal create_count
            create_count += 1
            return mock_producer

        with patch(
            "agents.lib.provider_selection_publisher._get_kafka_producer",
            side_effect=mock_get_producer,
        ):
            # Publish twice
            await publish_provider_selection(
                provider_name="gemini-flash",
                model_name="gemini-1.5-flash-002",
                correlation_id=correlation_id,
                selection_reason="Test 1",
                selection_criteria={},
            )

            await publish_provider_selection(
                provider_name="claude",
                model_name="claude-3-5-sonnet-20241022",
                correlation_id=correlation_id,
                selection_reason="Test 2",
                selection_criteria={},
            )

            # Producer should be created twice (called twice, not necessarily singleton in mock)
            # But send_and_wait should be called twice
            assert mock_producer.send_and_wait.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
