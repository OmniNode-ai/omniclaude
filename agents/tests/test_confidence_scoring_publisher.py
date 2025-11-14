#!/usr/bin/env python3
"""
Unit Tests for Confidence Scoring Event Publisher

Tests the confidence_scoring_publisher module for publishing agent confidence
scoring events to Kafka following EVENT_BUS_INTEGRATION_PATTERNS standards.

Test Coverage:
- Event envelope structure (OnexEnvelopeV1)
- Partition key policy (correlation_id)
- Payload schema validation
- Graceful degradation (Kafka unavailable)
- Producer singleton pattern
- Async/sync API compatibility

Created: 2025-11-13
Reference: OMN-33 - Event Alignment Plan Task 1.7
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from confidence_scoring_publisher import (
    EVENT_TYPE,
    TOPIC_NAME,
    _create_event_envelope,
    close_producer,
    publish_confidence_scored,
    publish_confidence_scored_sync,
)

# Disable logging during tests
logging.disable(logging.CRITICAL)


class TestEventEnvelopeStructure:
    """Test OnexEnvelopeV1 event envelope structure."""

    def test_create_event_envelope_required_fields(self):
        """Test envelope contains all required OnexEnvelopeV1 fields."""
        correlation_id = str(uuid4())
        payload = {
            "agent_name": "test-agent",
            "confidence_score": 0.92,
            "routing_strategy": "enhanced_fuzzy_matching",
            "correlation_id": correlation_id,
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "factors": {"trigger_score": 0.95},
        }

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
        )

        # Verify required OnexEnvelopeV1 fields
        assert "event_type" in envelope
        assert envelope["event_type"] == EVENT_TYPE

        assert "event_id" in envelope
        assert isinstance(envelope["event_id"], str)

        assert "timestamp" in envelope
        assert isinstance(envelope["timestamp"], str)

        assert "tenant_id" in envelope
        assert envelope["tenant_id"] == "default"

        assert "namespace" in envelope
        assert envelope["namespace"] == "omninode"

        assert "source" in envelope
        assert envelope["source"] == "omniclaude"

        assert "correlation_id" in envelope
        assert envelope["correlation_id"] == correlation_id

        assert "schema_ref" in envelope
        assert (
            "registry://omninode/agent/confidence_scored/v1" in envelope["schema_ref"]
        )

        assert "payload" in envelope
        assert envelope["payload"] == payload

    def test_create_event_envelope_optional_fields(self):
        """Test envelope handles optional causation_id field."""
        correlation_id = str(uuid4())
        causation_id = str(uuid4())
        payload = {"agent_name": "test-agent", "confidence_score": 0.92}

        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        assert envelope["causation_id"] == causation_id

    def test_create_event_envelope_custom_tenant_namespace(self):
        """Test envelope handles custom tenant_id and namespace."""
        envelope = _create_event_envelope(
            payload={"test": "data"},
            correlation_id=str(uuid4()),
            tenant_id="custom-tenant",
            namespace="custom-namespace",
        )

        assert envelope["tenant_id"] == "custom-tenant"
        assert envelope["namespace"] == "custom-namespace"


class TestPayloadSchema:
    """Test confidence scoring event payload schema."""

    @pytest.mark.asyncio
    async def test_payload_contains_required_fields(self):
        """Test payload contains all required fields from EVENT_ALIGNMENT_PLAN.md."""
        correlation_id = str(uuid4())

        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            # Mock producer
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish event
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.92,
                routing_strategy="enhanced_fuzzy_matching",
                correlation_id=correlation_id,
                factors={"trigger_score": 0.95, "context_score": 0.88},
            )

            # Verify send_and_wait was called
            assert mock_instance.send_and_wait.called

            # Extract published envelope
            call_args = mock_instance.send_and_wait.call_args
            published_envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )

            # Verify payload structure
            payload = published_envelope["payload"]
            assert "agent_name" in payload
            assert payload["agent_name"] == "test-agent"

            assert "confidence_score" in payload
            assert payload["confidence_score"] == 0.92

            assert "routing_strategy" in payload
            assert payload["routing_strategy"] == "enhanced_fuzzy_matching"

            assert "correlation_id" in payload
            assert payload["correlation_id"] == correlation_id

            assert "scored_at" in payload
            assert isinstance(payload["scored_at"], str)

            assert "factors" in payload
            assert isinstance(payload["factors"], dict)
            assert payload["factors"]["trigger_score"] == 0.95
            assert payload["factors"]["context_score"] == 0.88

    @pytest.mark.asyncio
    async def test_payload_auto_generates_scored_at(self):
        """Test payload auto-generates scored_at timestamp if not provided."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish without scored_at
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.85,
                routing_strategy="fuzzy_match",
            )

            # Extract payload
            call_args = mock_instance.send_and_wait.call_args
            envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )
            payload = envelope["payload"]

            # Verify scored_at was generated
            assert "scored_at" in payload
            assert isinstance(payload["scored_at"], str)

            # Verify it's a valid ISO8601/RFC3339 timestamp
            try:
                datetime.fromisoformat(payload["scored_at"].replace("Z", "+00:00"))
            except ValueError:
                pytest.fail("scored_at is not a valid ISO8601 timestamp")

    @pytest.mark.asyncio
    async def test_payload_handles_empty_factors(self):
        """Test payload handles missing or empty factors dict."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish without factors
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.75,
                routing_strategy="fallback",
            )

            # Extract payload
            call_args = mock_instance.send_and_wait.call_args
            envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )
            payload = envelope["payload"]

            # Verify factors is an empty dict (not None)
            assert "factors" in payload
            assert payload["factors"] == {}


class TestPartitionKeyPolicy:
    """Test partition key policy compliance."""

    @pytest.mark.asyncio
    async def test_uses_correlation_id_as_partition_key(self):
        """Test event uses correlation_id as partition key (EVENT_BUS_INTEGRATION_GUIDE)."""
        correlation_id = str(uuid4())

        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish event
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.88,
                routing_strategy="enhanced_fuzzy_matching",
                correlation_id=correlation_id,
            )

            # Verify send_and_wait called with correlation_id as partition key
            call_args = mock_instance.send_and_wait.call_args
            partition_key = call_args.kwargs["key"]

            assert partition_key == correlation_id.encode("utf-8")

    @pytest.mark.asyncio
    async def test_publishes_to_correct_topic(self):
        """Test event publishes to correct Kafka topic."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish event
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.90,
                routing_strategy="enhanced_fuzzy_matching",
            )

            # Verify topic name
            call_args = mock_instance.send_and_wait.call_args
            topic = call_args[0][0] if call_args[0] else None

            assert topic == TOPIC_NAME
            assert topic == "omninode.agent.confidence.scored.v1"


class TestGracefulDegradation:
    """Test graceful degradation when Kafka unavailable."""

    @pytest.mark.asyncio
    async def test_returns_false_when_producer_unavailable(self):
        """Test returns False when Kafka producer unavailable."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            # Simulate producer unavailable
            mock_producer.return_value = None

            # Publish event
            result = await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.85,
                routing_strategy="fuzzy_match",
            )

            # Verify returns False (graceful degradation)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_publish_exception(self):
        """Test returns False when publish raises exception."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            # Simulate publish failure
            mock_instance.send_and_wait = AsyncMock(
                side_effect=Exception("Kafka connection timeout")
            )
            mock_producer.return_value = mock_instance

            # Publish event
            result = await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.92,
                routing_strategy="enhanced_fuzzy_matching",
            )

            # Verify returns False (doesn't raise)
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_successful_publish(self):
        """Test returns True when publish succeeds."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish event
            result = await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.95,
                routing_strategy="enhanced_fuzzy_matching",
            )

            # Verify returns True
            assert result is True


class TestProducerManagement:
    """Test Kafka producer singleton and lifecycle management."""

    @pytest.mark.asyncio
    async def test_producer_singleton_reused(self):
        """Test producer singleton is reused across multiple publishes."""
        with patch(
            "confidence_scoring_publisher._get_kafka_producer"
        ) as mock_get_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_get_producer.return_value = mock_instance

            # Publish multiple events
            await publish_confidence_scored(
                agent_name="test-agent-1",
                confidence_score=0.90,
                routing_strategy="fuzzy_match",
            )
            await publish_confidence_scored(
                agent_name="test-agent-2",
                confidence_score=0.85,
                routing_strategy="fuzzy_match",
            )

            # Verify producer getter called multiple times (singleton pattern)
            assert mock_get_producer.call_count == 2

    @pytest.mark.asyncio
    async def test_close_producer_cleans_up(self):
        """Test close_producer() properly cleans up producer."""
        with patch(
            "confidence_scoring_publisher._get_kafka_producer"
        ) as mock_get_producer:
            mock_instance = AsyncMock()
            mock_instance.stop = AsyncMock(return_value=None)
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_get_producer.return_value = mock_instance

            # Publish event (initializes producer)
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.88,
                routing_strategy="fuzzy_match",
            )

            # Close producer
            import confidence_scoring_publisher

            confidence_scoring_publisher._kafka_producer = mock_instance
            await close_producer()

            # Verify stop was called
            mock_instance.stop.assert_called_once()


class TestSyncAPI:
    """Test synchronous API wrapper."""

    def test_sync_wrapper_creates_event_loop(self):
        """Test sync wrapper creates event loop if needed."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Call sync wrapper
            result = publish_confidence_scored_sync(
                agent_name="test-agent",
                confidence_score=0.92,
                routing_strategy="enhanced_fuzzy_matching",
            )

            # Verify returns boolean
            assert isinstance(result, bool)

    def test_sync_wrapper_passes_kwargs(self):
        """Test sync wrapper passes all kwargs to async version."""
        correlation_id = str(uuid4())

        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Call sync wrapper with all kwargs
            publish_confidence_scored_sync(
                agent_name="test-agent",
                confidence_score=0.88,
                routing_strategy="fuzzy_match",
                correlation_id=correlation_id,
                factors={"trigger_score": 0.90},
                tenant_id="custom-tenant",
            )

            # Extract published envelope
            call_args = mock_instance.send_and_wait.call_args
            envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )

            # Verify kwargs were passed through
            assert envelope["correlation_id"] == correlation_id
            assert envelope["tenant_id"] == "custom-tenant"
            assert envelope["payload"]["factors"]["trigger_score"] == 0.90


class TestEventValidation:
    """Test event validation and schema compliance."""

    @pytest.mark.asyncio
    async def test_confidence_score_float_type(self):
        """Test confidence_score is properly typed as float."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish with float confidence score
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.92,
                routing_strategy="enhanced_fuzzy_matching",
            )

            # Extract payload
            call_args = mock_instance.send_and_wait.call_args
            envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )
            payload = envelope["payload"]

            # Verify type
            assert isinstance(payload["confidence_score"], float)
            assert payload["confidence_score"] == 0.92

    @pytest.mark.asyncio
    async def test_auto_generates_correlation_id_when_missing(self):
        """Test auto-generates correlation_id when not provided."""
        with patch("confidence_scoring_publisher._get_kafka_producer") as mock_producer:
            mock_instance = AsyncMock()
            mock_instance.send_and_wait = AsyncMock(return_value=None)
            mock_producer.return_value = mock_instance

            # Publish without correlation_id
            await publish_confidence_scored(
                agent_name="test-agent",
                confidence_score=0.88,
                routing_strategy="fuzzy_match",
            )

            # Extract envelope
            call_args = mock_instance.send_and_wait.call_args
            envelope = (
                call_args.kwargs.get("value") or call_args[0][1]
                if len(call_args[0]) > 1
                else call_args.kwargs["value"]
            )

            # Verify correlation_id was auto-generated
            assert "correlation_id" in envelope
            assert isinstance(envelope["correlation_id"], str)
            assert len(envelope["correlation_id"]) > 0

            # Verify it's in payload too
            assert envelope["payload"]["correlation_id"] == envelope["correlation_id"]


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
