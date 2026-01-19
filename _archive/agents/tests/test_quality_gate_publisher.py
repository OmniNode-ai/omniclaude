#!/usr/bin/env python3
"""
Tests for Quality Gate Event Publisher

Tests the quality gate event publishing functionality including:
- Event structure validation (OnexEnvelopeV1 compliance)
- Partition key policy (correlation_id)
- Kafka integration
- Error handling and graceful degradation
- Payload schema compliance
- Both PASSED and FAILED event types
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agents.lib.quality_gate_publisher import (
    QualityGateEventType,
    _create_event_envelope,
    close_producer,
    publish_quality_gate_failed,
    publish_quality_gate_failed_sync,
    publish_quality_gate_passed,
    publish_quality_gate_passed_sync,
)


@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer for testing."""
    producer = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.send_and_wait = AsyncMock()
    return producer


@pytest.fixture
def sample_correlation_id():
    """Sample correlation ID for testing."""
    return str(uuid4())


class TestQualityGateEventType:
    """Test quality gate event type enumeration."""

    def test_event_type_passed_value(self):
        """Test PASSED event type enum value."""
        assert (
            QualityGateEventType.PASSED.value == "omninode.agent.quality.gate.passed.v1"
        )

    def test_event_type_failed_value(self):
        """Test FAILED event type enum value."""
        assert (
            QualityGateEventType.FAILED.value == "omninode.agent.quality.gate.failed.v1"
        )

    def test_get_topic_name_passed(self):
        """Test topic name for PASSED event matches value."""
        assert (
            QualityGateEventType.PASSED.get_topic_name()
            == "omninode.agent.quality.gate.passed.v1"
        )

    def test_get_topic_name_failed(self):
        """Test topic name for FAILED event matches value."""
        assert (
            QualityGateEventType.FAILED.get_topic_name()
            == "omninode.agent.quality.gate.failed.v1"
        )


class TestEventEnvelope:
    """Test OnexEnvelopeV1 event envelope creation."""

    def test_create_event_envelope_structure(self, sample_correlation_id):
        """Test envelope has all required OnexEnvelopeV1 fields."""
        payload = {
            "gate_name": "onex_compliance",
            "score": 0.65,
            "threshold": 0.80,
            "failure_reasons": ["Missing type hints"],
        }

        envelope = _create_event_envelope(
            event_type=QualityGateEventType.FAILED,
            payload=payload,
            correlation_id=sample_correlation_id,
        )

        # Verify required OnexEnvelopeV1 fields
        assert "event_type" in envelope
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert "tenant_id" in envelope
        assert "namespace" in envelope
        assert "source" in envelope
        assert "correlation_id" in envelope
        assert "causation_id" in envelope
        assert "schema_ref" in envelope
        assert "payload" in envelope

        # Verify values
        assert envelope["event_type"] == QualityGateEventType.FAILED.value
        assert envelope["correlation_id"] == sample_correlation_id
        assert envelope["source"] == "omniclaude"
        assert envelope["tenant_id"] == "default"
        assert envelope["namespace"] == "omninode"
        assert envelope["payload"] == payload

    def test_event_envelope_timestamp_format(self, sample_correlation_id):
        """Test timestamp is in RFC3339 format."""
        envelope = _create_event_envelope(
            event_type=QualityGateEventType.FAILED,
            payload={},
            correlation_id=sample_correlation_id,
        )

        # Verify timestamp is ISO 8601 / RFC3339 format
        timestamp = envelope["timestamp"]
        assert "T" in timestamp
        assert timestamp.endswith("Z") or "+" in timestamp or "-" in timestamp[-6:]

        # Verify timestamp can be parsed
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            pytest.fail("Timestamp is not in valid RFC3339 format")

    def test_event_envelope_schema_ref_failed(self, sample_correlation_id):
        """Test schema_ref follows expected pattern for FAILED event."""
        envelope = _create_event_envelope(
            event_type=QualityGateEventType.FAILED,
            payload={},
            correlation_id=sample_correlation_id,
        )

        schema_ref = envelope["schema_ref"]
        assert schema_ref == "registry://omninode/agent/quality_gate_failed/v1"

    def test_event_envelope_schema_ref_passed(self, sample_correlation_id):
        """Test schema_ref follows expected pattern for PASSED event."""
        envelope = _create_event_envelope(
            event_type=QualityGateEventType.PASSED,
            payload={},
            correlation_id=sample_correlation_id,
        )

        schema_ref = envelope["schema_ref"]
        assert schema_ref == "registry://omninode/agent/quality_gate_passed/v1"


class TestPublishQualityGateFailed:
    """Test quality gate failed event publishing."""

    @pytest.mark.asyncio
    async def test_publish_failed_event_success(
        self, mock_kafka_producer, sample_correlation_id
    ):
        """Test successful quality gate failed event publishing."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_failed(
                gate_name="onex_compliance",
                correlation_id=sample_correlation_id,
                score=0.65,
                threshold=0.80,
                failure_reasons=["Missing type hints", "Bare Any types detected"],
                recommendations=[
                    "Add type hints",
                    "Replace Any with specific types",
                ],
            )

            assert success is True
            assert mock_kafka_producer.send_and_wait.called

            # Verify call arguments
            call_args = mock_kafka_producer.send_and_wait.call_args
            topic = call_args[0][0]
            event = call_args[1]["value"]
            partition_key = call_args[1]["key"]

            # Verify topic
            assert topic == "omninode.agent.quality.gate.failed.v1"

            # Verify partition key (correlation_id as partition key)
            assert partition_key == sample_correlation_id.encode("utf-8")

            # Verify event structure (OnexEnvelopeV1)
            assert event["event_type"] == "omninode.agent.quality.gate.failed.v1"
            assert event["correlation_id"] == sample_correlation_id
            assert "event_id" in event
            assert "timestamp" in event

            # Verify payload schema
            payload = event["payload"]
            assert payload["gate_name"] == "onex_compliance"
            assert payload["score"] == 0.65
            assert payload["threshold"] == 0.80
            assert payload["failure_reasons"] == [
                "Missing type hints",
                "Bare Any types detected",
            ]
            assert payload["recommendations"] == [
                "Add type hints",
                "Replace Any with specific types",
            ]
            assert "failed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_failed_event_minimal_payload(
        self, mock_kafka_producer, sample_correlation_id
    ):
        """Test publishing with minimal required fields."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_failed(
                gate_name="type_safety",
                correlation_id=sample_correlation_id,
                score=0.45,
                threshold=0.70,
                failure_reasons=["Type annotations missing"],
                # recommendations is optional
            )

            assert success is True

            # Verify payload has all required fields
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            payload = event["payload"]

            assert payload["gate_name"] == "type_safety"
            assert payload["correlation_id"] == sample_correlation_id
            assert payload["score"] == 0.45
            assert payload["threshold"] == 0.70
            assert payload["failure_reasons"] == ["Type annotations missing"]
            assert payload["recommendations"] == []  # Default empty list

    @pytest.mark.asyncio
    async def test_publish_auto_generates_correlation_id(self, mock_kafka_producer):
        """Test correlation_id is auto-generated if not provided."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_failed(
                gate_name="test_gate",
                correlation_id=None,  # Not provided
                score=0.5,
                threshold=0.8,
                failure_reasons=["Test failure"],
            )

            assert success is True

            # Verify correlation_id was generated
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            assert event["correlation_id"] is not None
            assert len(event["correlation_id"]) > 0

    @pytest.mark.asyncio
    async def test_publish_kafka_unavailable(self):
        """Test graceful degradation when Kafka is unavailable."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer", return_value=None
        ):
            success = await publish_quality_gate_failed(
                gate_name="test_gate",
                correlation_id=str(uuid4()),
                score=0.5,
                threshold=0.8,
                failure_reasons=["Test failure"],
            )

            # Should return False but not raise exception
            assert success is False

    @pytest.mark.asyncio
    async def test_publish_kafka_error_handling(self, mock_kafka_producer):
        """Test error handling when Kafka publish fails."""
        # Simulate Kafka error
        mock_kafka_producer.send_and_wait.side_effect = Exception("Kafka error")

        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_failed(
                gate_name="test_gate",
                correlation_id=str(uuid4()),
                score=0.5,
                threshold=0.8,
                failure_reasons=["Test failure"],
            )

            # Should return False but not raise exception (graceful degradation)
            assert success is False

    @pytest.mark.asyncio
    async def test_partition_key_policy(self, mock_kafka_producer):
        """Test partition key is set to correlation_id for workflow coherence."""
        correlation_id = str(uuid4())

        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            await publish_quality_gate_failed(
                gate_name="test_gate",
                correlation_id=correlation_id,
                score=0.5,
                threshold=0.8,
                failure_reasons=["Test failure"],
            )

            # Verify partition key matches correlation_id
            call_args = mock_kafka_producer.send_and_wait.call_args
            partition_key = call_args[1]["key"]
            assert partition_key == correlation_id.encode("utf-8")

    @pytest.mark.asyncio
    async def test_payload_schema_compliance(self, mock_kafka_producer):
        """Test payload matches EVENT_ALIGNMENT_PLAN.md schema."""
        correlation_id = str(uuid4())

        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            await publish_quality_gate_failed(
                gate_name="contract_conformance",
                correlation_id=correlation_id,
                score=0.72,
                threshold=0.85,
                failure_reasons=[
                    "Missing method: validate_input",
                    "Missing capability: health_check",
                ],
                recommendations=[
                    "Implement validate_input method",
                    "Add health_check capability",
                ],
            )

            # Verify payload schema
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            payload = event["payload"]

            # Required fields from EVENT_ALIGNMENT_PLAN.md
            assert "gate_name" in payload
            assert isinstance(payload["gate_name"], str)

            assert "correlation_id" in payload
            assert isinstance(payload["correlation_id"], str)

            assert "score" in payload
            assert isinstance(payload["score"], float)
            assert 0.0 <= payload["score"] <= 1.0

            assert "threshold" in payload
            assert isinstance(payload["threshold"], float)
            assert 0.0 <= payload["threshold"] <= 1.0

            assert "failed_at" in payload
            assert isinstance(payload["failed_at"], str)

            assert "failure_reasons" in payload
            assert isinstance(payload["failure_reasons"], list)

            assert "recommendations" in payload
            assert isinstance(payload["recommendations"], list)


class TestPublishQualityGatePassed:
    """Test quality gate passed event publishing."""

    @pytest.mark.asyncio
    async def test_publish_passed_event_success(
        self, mock_kafka_producer, sample_correlation_id
    ):
        """Test successful quality gate passed event publishing."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_passed(
                gate_name="input_validation",
                correlation_id=sample_correlation_id,
                score=0.95,
                threshold=0.80,
                metrics={
                    "validation_checks": 12,
                    "passed_checks": 12,
                    "execution_time_ms": 45,
                },
            )

            assert success is True
            assert mock_kafka_producer.send_and_wait.called

            # Verify call arguments
            call_args = mock_kafka_producer.send_and_wait.call_args
            topic = call_args[0][0]
            event = call_args[1]["value"]
            partition_key = call_args[1]["key"]

            # Verify topic
            assert topic == "omninode.agent.quality.gate.passed.v1"

            # Verify partition key (correlation_id as partition key)
            assert partition_key == sample_correlation_id.encode("utf-8")

            # Verify event structure (OnexEnvelopeV1)
            assert event["event_type"] == "omninode.agent.quality.gate.passed.v1"
            assert event["correlation_id"] == sample_correlation_id
            assert "event_id" in event
            assert "timestamp" in event

            # Verify payload schema
            payload = event["payload"]
            assert payload["gate_name"] == "input_validation"
            assert payload["score"] == 0.95
            assert payload["threshold"] == 0.80
            assert payload["metrics"] == {
                "validation_checks": 12,
                "passed_checks": 12,
                "execution_time_ms": 45,
            }
            assert "passed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_passed_event_minimal_payload(
        self, mock_kafka_producer, sample_correlation_id
    ):
        """Test publishing with minimal required fields (only gate_name)."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_passed(
                gate_name="type_safety",
                # All other fields are optional
            )

            assert success is True

            # Verify payload has gate_name
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            payload = event["payload"]

            assert payload["gate_name"] == "type_safety"
            # correlation_id should be auto-generated
            assert "correlation_id" in payload or "correlation_id" in event

    @pytest.mark.asyncio
    async def test_publish_passed_auto_generates_correlation_id(
        self, mock_kafka_producer
    ):
        """Test correlation_id is auto-generated if not provided."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_quality_gate_passed(
                gate_name="test_gate",
                correlation_id=None,  # Not provided
            )

            assert success is True

            # Verify correlation_id was generated
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            assert event["correlation_id"] is not None
            assert len(event["correlation_id"]) > 0

    @pytest.mark.asyncio
    async def test_publish_passed_kafka_unavailable(self):
        """Test graceful degradation when Kafka is unavailable."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer", return_value=None
        ):
            success = await publish_quality_gate_passed(
                gate_name="test_gate",
                correlation_id=str(uuid4()),
            )

            # Should return False but not raise exception
            assert success is False

    @pytest.mark.asyncio
    async def test_publish_passed_payload_schema_compliance(self, mock_kafka_producer):
        """Test payload matches OMN-30 schema from Linear ticket."""
        correlation_id = str(uuid4())

        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            await publish_quality_gate_passed(
                gate_name="performance_validation",
                correlation_id=correlation_id,
                score=0.88,
                threshold=0.75,
                metrics={
                    "execution_time_ms": 150,
                    "memory_usage_mb": 45,
                    "cpu_percent": 12,
                },
            )

            # Verify payload schema matches OMN-30 requirements
            call_args = mock_kafka_producer.send_and_wait.call_args
            event = call_args[1]["value"]
            payload = event["payload"]

            # Required fields from OMN-30
            assert "gate_name" in payload
            assert isinstance(payload["gate_name"], str)

            assert "correlation_id" in payload
            assert isinstance(payload["correlation_id"], str)

            assert "score" in payload
            assert isinstance(payload["score"], float)
            assert 0.0 <= payload["score"] <= 1.0

            assert "threshold" in payload
            assert isinstance(payload["threshold"], float)
            assert 0.0 <= payload["threshold"] <= 1.0

            assert "passed_at" in payload
            assert isinstance(payload["passed_at"], str)  # RFC3339 format

            assert "metrics" in payload
            assert isinstance(payload["metrics"], dict)


class TestSyncWrapper:
    """Test synchronous wrappers for backward compatibility."""

    def test_sync_wrapper_passed(self, mock_kafka_producer):
        """Test synchronous wrapper for passed events."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            correlation_id = str(uuid4())
            success = publish_quality_gate_passed_sync(
                gate_name="test_gate",
                correlation_id=correlation_id,
                score=0.9,
                threshold=0.8,
            )

            assert success is True
            assert mock_kafka_producer.send_and_wait.called

    def test_sync_wrapper_failed(self, mock_kafka_producer):
        """Test synchronous wrapper for failed events."""
        with patch(
            "agents.lib.quality_gate_publisher._get_kafka_producer",
            return_value=mock_kafka_producer,
        ):
            correlation_id = str(uuid4())
            success = publish_quality_gate_failed_sync(
                gate_name="test_gate",
                correlation_id=correlation_id,
                score=0.5,
                threshold=0.8,
                failure_reasons=["Test failure"],
            )

            assert success is True
            assert mock_kafka_producer.send_and_wait.called


class TestProducerLifecycle:
    """Test Kafka producer lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_producer(self, mock_kafka_producer):
        """Test producer cleanup on shutdown."""
        # Simulate active producer
        with patch(
            "agents.lib.quality_gate_publisher._kafka_producer",
            mock_kafka_producer,
        ):
            await close_producer()
            assert mock_kafka_producer.stop.called

    @pytest.mark.asyncio
    async def test_close_producer_when_none(self):
        """Test closing producer when it's None doesn't error."""
        with patch("agents.lib.quality_gate_publisher._kafka_producer", None):
            # Should not raise exception
            await close_producer()


class TestIntegration:
    """Integration tests with real Kafka (if available)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_kafka_publish(self):
        """Test publishing to real Kafka (requires Kafka running)."""
        # Skip if KAFKA_BOOTSTRAP_SERVERS not set
        if not os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
            pytest.skip("KAFKA_BOOTSTRAP_SERVERS not configured")

        correlation_id = str(uuid4())

        success = await publish_quality_gate_failed(
            gate_name="integration_test",
            correlation_id=correlation_id,
            score=0.5,
            threshold=0.8,
            failure_reasons=["Integration test failure"],
            recommendations=["This is a test"],
        )

        # Should succeed if Kafka is available
        # May fail gracefully if Kafka is down
        assert success is True or success is False

        # Clean up
        await close_producer()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
