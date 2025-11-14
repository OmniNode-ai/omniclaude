#!/usr/bin/env python3
"""
Unit Tests for Agent Execution Publisher

Tests the Kafka publisher for agent execution lifecycle events,
ensuring proper event structure, partition key policy, and error handling.

Test Coverage:
- Event envelope structure validation
- Partition key policy compliance
- Kafka producer lifecycle management
- Error handling and graceful degradation
- Context manager functionality
- Convenience function behavior

Created: 2025-11-13
Reference: agents/lib/agent_execution_publisher.py
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Import the module under test
from agents.lib.agent_execution_publisher import (
    AgentExecutionPublisher,
    AgentExecutionPublisherContext,
    publish_execution_completed,
    publish_execution_failed,
    publish_execution_started,
)


@pytest.fixture
def mock_kafka_producer():
    """Mock aiokafka producer for testing."""
    producer = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.send_and_wait = AsyncMock()
    return producer


@pytest.fixture
def publisher_config():
    """Publisher configuration for tests."""
    return {
        "bootstrap_servers": "localhost:9092",
        "enable_events": True,
    }


@pytest.fixture
def sample_execution_data():
    """Sample execution data for tests."""
    return {
        "agent_name": "agent-api-architect",
        "user_request": "Design a REST API for user management",
        "correlation_id": str(uuid4()),
        "session_id": str(uuid4()),
        "context": {
            "domain": "api_design",
            "previous_agent": "agent-router",
        },
    }


@pytest.fixture
def sample_completed_data():
    """Sample completed execution data for tests."""
    return {
        "agent_name": "agent-api-architect",
        "correlation_id": str(uuid4()),
        "duration_ms": 5432,
        "quality_score": 0.92,
        "output_summary": "Successfully designed REST API with 15 endpoints",
        "metrics": {
            "endpoints_created": 15,
            "models_generated": 8,
            "total_tokens": 12000,
        },
    }


class TestAgentExecutionPublisher:
    """Test suite for AgentExecutionPublisher class."""

    @pytest.mark.asyncio
    async def test_initialization_with_defaults(self):
        """Test publisher initializes with default configuration."""
        with patch("agents.lib.agent_execution_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            publisher = AgentExecutionPublisher()
            assert publisher.bootstrap_servers == "localhost:9092"
            assert publisher.enable_events is True
            assert publisher._started is False
            assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_initialization_with_custom_config(self, publisher_config):
        """Test publisher initializes with custom configuration."""
        publisher = AgentExecutionPublisher(**publisher_config)
        assert publisher.bootstrap_servers == "localhost:9092"
        assert publisher.enable_events is True

    @pytest.mark.asyncio
    async def test_start_creates_producer(self, publisher_config, mock_kafka_producer):
        """Test start() creates and starts Kafka producer."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            assert publisher._started is True
            assert publisher._producer is not None
            mock_kafka_producer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_skips_if_already_started(
        self, publisher_config, mock_kafka_producer
    ):
        """Test start() skips if already started."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()
            await publisher.start()  # Second call should be no-op

            # Producer.start() should only be called once
            assert mock_kafka_producer.start.call_count == 1

    @pytest.mark.asyncio
    async def test_start_skips_if_events_disabled(self):
        """Test start() skips if events are disabled."""
        publisher = AgentExecutionPublisher(
            bootstrap_servers="localhost:9092",
            enable_events=False,
        )
        await publisher.start()

        assert publisher._started is False
        assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_stop_closes_producer(self, publisher_config, mock_kafka_producer):
        """Test stop() closes Kafka producer gracefully."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()
            await publisher.stop()

            assert publisher._started is False
            assert publisher._producer is None
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_execution_started_success(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test successful execution started event publishing."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_started(**sample_execution_data)

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify send_and_wait call arguments
            call_args = mock_kafka_producer.send_and_wait.call_args
            # AIOKafkaProducer.send_and_wait uses positional args: (topic, value=..., key=..., headers=...)
            assert call_args.args[0] == "omninode.agent.execution.started.v1"  # topic
            assert call_args.kwargs["key"] == sample_execution_data[
                "correlation_id"
            ].encode("utf-8")

            # Verify envelope structure
            envelope = call_args.kwargs["value"]
            assert envelope["event_type"] == "omninode.agent.execution.started.v1"
            assert envelope["correlation_id"] == sample_execution_data["correlation_id"]
            assert envelope["namespace"] == "omninode"
            assert envelope["source"] == "omniclaude"

            # Verify payload structure
            payload = envelope["payload"]
            assert payload["agent_name"] == sample_execution_data["agent_name"]
            assert payload["user_request"] == sample_execution_data["user_request"]
            assert payload["correlation_id"] == sample_execution_data["correlation_id"]
            assert payload["session_id"] == sample_execution_data["session_id"]
            assert payload["context"] == sample_execution_data["context"]
            assert "started_at" in payload

            # Verify required envelope fields
            required_fields = [
                "event_type",
                "event_id",
                "timestamp",
                "tenant_id",
                "namespace",
                "source",
                "correlation_id",
                "causation_id",
                "schema_ref",
                "payload",
            ]
            for field in required_fields:
                assert field in envelope, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_publish_execution_started_with_partition_key(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test execution started event uses correlation_id as partition key."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_execution_started(**sample_execution_data)

            call_args = mock_kafka_producer.send_and_wait.call_args
            partition_key = call_args.kwargs["key"]

            # Verify partition key is correlation_id (encoded)
            assert partition_key == sample_execution_data["correlation_id"].encode(
                "utf-8"
            )

    @pytest.mark.asyncio
    async def test_publish_execution_started_with_kafka_headers(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test execution started event includes required Kafka headers."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_execution_started(**sample_execution_data)

            call_args = mock_kafka_producer.send_and_wait.call_args
            headers = call_args.kwargs["headers"]

            # Verify required headers are present
            header_names = [name for name, _ in headers]
            required_headers = [
                "x-traceparent",
                "x-correlation-id",
                "x-causation-id",
                "x-tenant",
                "x-schema-hash",
            ]
            for required_header in required_headers:
                assert (
                    required_header in header_names
                ), f"Missing required header: {required_header}"

    @pytest.mark.asyncio
    async def test_publish_execution_started_skips_if_not_started(
        self, publisher_config, sample_execution_data
    ):
        """Test publish_execution_started() skips if publisher not started."""
        publisher = AgentExecutionPublisher(**publisher_config)
        # Don't call start()

        success = await publisher.publish_execution_started(**sample_execution_data)

        assert success is False

    @pytest.mark.asyncio
    async def test_publish_execution_started_skips_if_events_disabled(
        self, sample_execution_data
    ):
        """Test publish_execution_started() skips if events disabled."""
        publisher = AgentExecutionPublisher(
            bootstrap_servers="localhost:9092",
            enable_events=False,
        )

        success = await publisher.publish_execution_started(**sample_execution_data)

        assert success is False

    @pytest.mark.asyncio
    async def test_publish_execution_started_graceful_degradation_on_kafka_error(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test publish_execution_started() returns False on Kafka error (graceful degradation)."""
        # Simulate Kafka send failure
        mock_kafka_producer.send_and_wait.side_effect = Exception(
            "Kafka connection failed"
        )

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_started(**sample_execution_data)

            # Should return False but NOT raise exception (graceful degradation)
            assert success is False

    @pytest.mark.asyncio
    async def test_create_execution_started_envelope_structure(
        self, publisher_config, sample_execution_data
    ):
        """Test _create_execution_started_envelope() produces correct structure."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_started_envelope(**sample_execution_data)

        # Verify envelope structure
        assert envelope["event_type"] == "omninode.agent.execution.started.v1"
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert envelope["tenant_id"] == "default"
        assert envelope["namespace"] == "omninode"
        assert envelope["source"] == "omniclaude"
        assert envelope["correlation_id"] == sample_execution_data["correlation_id"]
        assert envelope["causation_id"] == sample_execution_data["correlation_id"]
        assert (
            envelope["schema_ref"] == "registry://omninode/agent/execution_started/v1"
        )

        # Verify payload
        payload = envelope["payload"]
        assert payload["agent_name"] == sample_execution_data["agent_name"]
        assert payload["user_request"] == sample_execution_data["user_request"]
        assert payload["correlation_id"] == sample_execution_data["correlation_id"]
        assert payload["session_id"] == sample_execution_data["session_id"]
        assert payload["context"] == sample_execution_data["context"]

        # Verify timestamp formats (RFC3339)
        assert "T" in envelope["timestamp"]
        assert "started_at" in payload
        assert "T" in payload["started_at"]


class TestAgentExecutionPublisherContext:
    """Test suite for AgentExecutionPublisherContext context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_lifecycle(
        self, mock_kafka_producer, sample_execution_data
    ):
        """Test context manager automatically starts and stops publisher."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            async with AgentExecutionPublisherContext(
                bootstrap_servers="localhost:9092",
                enable_events=True,
            ) as publisher:
                assert publisher._started is True
                assert publisher._producer is not None

                # Should be able to publish events
                await publisher.publish_execution_started(**sample_execution_data)

            # After context exit, publisher should be stopped
            assert publisher._started is False
            assert publisher._producer is None
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_cleanup_on_exception(self, mock_kafka_producer):
        """Test context manager cleans up even if exception occurs."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            try:
                async with AgentExecutionPublisherContext(
                    bootstrap_servers="localhost:9092",
                    enable_events=True,
                ) as publisher:
                    assert publisher._started is True
                    raise ValueError("Test exception")
            except ValueError:
                pass

            # Publisher should still be stopped despite exception
            mock_kafka_producer.stop.assert_called_once()


class TestPublishExecutionStartedConvenienceFunction:
    """Test suite for publish_execution_started() convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function_success(
        self, mock_kafka_producer, sample_execution_data
    ):
        """Test convenience function publishes event successfully."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_started(**sample_execution_data)

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_convenience_function_graceful_degradation(
        self, mock_kafka_producer, sample_execution_data
    ):
        """Test convenience function returns False on error (graceful degradation)."""
        # Simulate Kafka failure
        mock_kafka_producer.start.side_effect = Exception("Kafka connection failed")

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_started(**sample_execution_data)

            # Should return False but NOT raise exception
            assert success is False


class TestEventValidation:
    """Test suite for event validation compliance."""

    @pytest.mark.asyncio
    async def test_event_envelope_has_all_required_fields(
        self, publisher_config, sample_execution_data
    ):
        """Test event envelope includes all required fields per EVENT_BUS_INTEGRATION_GUIDE."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_started_envelope(**sample_execution_data)

        required_fields = [
            "event_type",
            "event_id",
            "timestamp",
            "tenant_id",
            "namespace",
            "source",
            "correlation_id",
            "causation_id",
            "schema_ref",
            "payload",
        ]

        for field in required_fields:
            assert field in envelope, f"Missing required envelope field: {field}"

    @pytest.mark.asyncio
    async def test_event_payload_has_all_required_fields(
        self, publisher_config, sample_execution_data
    ):
        """Test event payload includes all required fields per EVENT_ALIGNMENT_PLAN."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_started_envelope(**sample_execution_data)
        payload = envelope["payload"]

        required_fields = [
            "agent_name",
            "user_request",
            "correlation_id",
            "session_id",
            "started_at",
            "context",
        ]

        for field in required_fields:
            assert field in payload, f"Missing required payload field: {field}"

    @pytest.mark.asyncio
    async def test_event_type_follows_naming_convention(
        self, publisher_config, sample_execution_data
    ):
        """Test event type follows omninode.{domain}.{entity}.{action}.v{major} convention."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_started_envelope(**sample_execution_data)

        event_type = envelope["event_type"]
        assert event_type == "omninode.agent.execution.started.v1"

        # Verify naming convention structure
        parts = event_type.split(".")
        assert len(parts) == 5  # omninode, agent, execution, started, v1
        assert parts[0] == "omninode"  # namespace
        assert parts[1] == "agent"  # domain
        assert parts[2] == "execution"  # entity
        assert parts[3] == "started"  # action
        assert parts[4] == "v1"  # version

    @pytest.mark.asyncio
    async def test_partition_key_is_correlation_id(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test partition key policy: correlation_id for execution events."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_execution_started(**sample_execution_data)

            call_args = mock_kafka_producer.send_and_wait.call_args
            partition_key = call_args.kwargs["key"]

            # Verify partition key is correlation_id
            assert partition_key == sample_execution_data["correlation_id"].encode(
                "utf-8"
            )


class TestPublishExecutionCompleted:
    """Test suite for publish_execution_completed functionality."""

    @pytest.mark.asyncio
    async def test_publish_execution_completed_success(
        self, publisher_config, mock_kafka_producer, sample_completed_data
    ):
        """Test successful execution completed event publishing."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_completed(
                **sample_completed_data
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify send_and_wait call arguments
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert call_args.args[0] == "omninode.agent.execution.completed.v1"  # topic
            assert call_args.kwargs["key"] == sample_completed_data[
                "correlation_id"
            ].encode("utf-8")

            # Verify envelope structure
            envelope = call_args.kwargs["value"]
            assert envelope["event_type"] == "omninode.agent.execution.completed.v1"
            assert envelope["correlation_id"] == sample_completed_data["correlation_id"]
            assert envelope["namespace"] == "omninode"
            assert envelope["source"] == "omniclaude"

            # Verify payload structure
            payload = envelope["payload"]
            assert payload["agent_name"] == sample_completed_data["agent_name"]
            assert payload["correlation_id"] == sample_completed_data["correlation_id"]
            assert payload["duration_ms"] == sample_completed_data["duration_ms"]
            assert payload["quality_score"] == sample_completed_data["quality_score"]
            assert payload["output_summary"] == sample_completed_data["output_summary"]
            assert payload["metrics"] == sample_completed_data["metrics"]
            assert "completed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_execution_completed_with_optional_fields(
        self, publisher_config, mock_kafka_producer
    ):
        """Test execution completed event with minimal required fields."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            # Publish with only required fields
            success = await publisher.publish_execution_completed(
                agent_name="agent-test",
                correlation_id=str(uuid4()),
                duration_ms=1000,
            )

            assert success is True

            # Verify envelope structure
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            payload = envelope["payload"]

            # Required fields should be present
            assert payload["agent_name"] == "agent-test"
            assert payload["duration_ms"] == 1000
            assert "completed_at" in payload

            # Optional fields should not be in payload (None values removed)
            assert "quality_score" not in payload
            assert "output_summary" not in payload

    @pytest.mark.asyncio
    async def test_create_execution_completed_envelope_structure(
        self, publisher_config, sample_completed_data
    ):
        """Test _create_execution_completed_envelope() produces correct structure."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_completed_envelope(
            **sample_completed_data
        )

        # Verify envelope structure
        assert envelope["event_type"] == "omninode.agent.execution.completed.v1"
        assert "event_id" in envelope
        assert "timestamp" in envelope
        assert envelope["tenant_id"] == "default"
        assert envelope["namespace"] == "omninode"
        assert envelope["source"] == "omniclaude"
        assert envelope["correlation_id"] == sample_completed_data["correlation_id"]
        assert envelope["causation_id"] == sample_completed_data["correlation_id"]
        assert (
            envelope["schema_ref"] == "registry://omninode/agent/execution_completed/v1"
        )

        # Verify payload
        payload = envelope["payload"]
        assert payload["agent_name"] == sample_completed_data["agent_name"]
        assert payload["correlation_id"] == sample_completed_data["correlation_id"]
        assert payload["duration_ms"] == sample_completed_data["duration_ms"]
        assert payload["quality_score"] == sample_completed_data["quality_score"]
        assert payload["output_summary"] == sample_completed_data["output_summary"]
        assert payload["metrics"] == sample_completed_data["metrics"]

        # Verify timestamp format (RFC3339)
        assert "T" in envelope["timestamp"]
        assert "completed_at" in payload
        assert "T" in payload["completed_at"]

    @pytest.mark.asyncio
    async def test_publish_execution_completed_skips_if_not_started(
        self, publisher_config, sample_completed_data
    ):
        """Test publish_execution_completed() skips if publisher not started."""
        publisher = AgentExecutionPublisher(**publisher_config)
        # Don't call start()

        success = await publisher.publish_execution_completed(**sample_completed_data)

        assert success is False

    @pytest.mark.asyncio
    async def test_publish_execution_completed_graceful_degradation_on_kafka_error(
        self, publisher_config, mock_kafka_producer, sample_completed_data
    ):
        """Test publish_execution_completed() returns False on Kafka error (graceful degradation)."""
        # Simulate Kafka send failure
        mock_kafka_producer.send_and_wait.side_effect = Exception(
            "Kafka connection failed"
        )

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_completed(
                **sample_completed_data
            )

            # Should return False but NOT raise exception (graceful degradation)
            assert success is False

    @pytest.mark.asyncio
    async def test_execution_completed_event_has_all_required_fields(
        self, publisher_config, sample_completed_data
    ):
        """Test completed event payload includes all required fields per EVENT_ALIGNMENT_PLAN."""
        publisher = AgentExecutionPublisher(**publisher_config)

        envelope = publisher._create_execution_completed_envelope(
            **sample_completed_data
        )
        payload = envelope["payload"]

        required_fields = [
            "agent_name",
            "correlation_id",
            "duration_ms",
            "completed_at",
        ]

        for field in required_fields:
            assert field in payload, f"Missing required payload field: {field}"

    @pytest.mark.asyncio
    async def test_execution_completed_partition_key_is_correlation_id(
        self, publisher_config, mock_kafka_producer, sample_completed_data
    ):
        """Test partition key policy: correlation_id for completed events."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_execution_completed(**sample_completed_data)

            call_args = mock_kafka_producer.send_and_wait.call_args
            partition_key = call_args.kwargs["key"]

            # Verify partition key is correlation_id
            assert partition_key == sample_completed_data["correlation_id"].encode(
                "utf-8"
            )


class TestPublishExecutionCompletedConvenienceFunction:
    """Test suite for publish_execution_completed() convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function_success(
        self, mock_kafka_producer, sample_completed_data
    ):
        """Test convenience function publishes completed event successfully."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_completed(**sample_completed_data)

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_convenience_function_graceful_degradation(
        self, mock_kafka_producer, sample_completed_data
    ):
        """Test convenience function returns False on error (graceful degradation)."""
        # Simulate Kafka failure
        mock_kafka_producer.start.side_effect = Exception("Kafka connection failed")

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_completed(**sample_completed_data)

            # Should return False but NOT raise exception
            assert success is False


class TestExecutionCompletedEvent:
    """Test suite for execution completed event."""

    @pytest.mark.asyncio
    async def test_publish_execution_completed_success(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test successful execution completed event publishing."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_completed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                duration_ms=1500,
                quality_score=0.92,
                output_summary="Analysis complete with 3 findings",
                metrics={"tool_calls": 5, "tokens_used": 1200},
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify topic
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert call_args.args[0] == "omninode.agent.execution.completed.v1"

            # Verify partition key
            assert call_args.kwargs["key"] == sample_execution_data[
                "correlation_id"
            ].encode("utf-8")

            # Verify envelope
            envelope = call_args.kwargs["value"]
            assert envelope["event_type"] == "omninode.agent.execution.completed.v1"
            assert envelope["correlation_id"] == sample_execution_data["correlation_id"]

            # Verify payload
            payload = envelope["payload"]
            assert payload["agent_name"] == sample_execution_data["agent_name"]
            assert payload["duration_ms"] == 1500
            assert payload["quality_score"] == 0.92
            assert payload["output_summary"] == "Analysis complete with 3 findings"
            assert payload["metrics"] == {"tool_calls": 5, "tokens_used": 1200}
            assert "completed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_execution_completed_minimal_fields(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test execution completed event with minimal fields."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_completed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                duration_ms=1500,
            )

            assert success is True

            # Verify payload has required fields
            call_args = mock_kafka_producer.send_and_wait.call_args
            payload = call_args.kwargs["value"]["payload"]
            assert payload["agent_name"] == sample_execution_data["agent_name"]
            assert payload["duration_ms"] == 1500
            assert "completed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_execution_completed_convenience_function(
        self, mock_kafka_producer, sample_execution_data
    ):
        """Test convenience function for execution completed."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_completed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                duration_ms=1500,
                quality_score=0.92,
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()


class TestExecutionFailedEvent:
    """Test suite for execution failed event."""

    @pytest.mark.asyncio
    async def test_publish_execution_failed_success(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test successful execution failed event publishing."""
        import traceback

        # Simulate error
        try:
            raise FileNotFoundError("config.py not found")
        except Exception as e:
            error_message = str(e)
            error_type = type(e).__name__
            error_stack_trace = traceback.format_exc()

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_failed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                error_message=error_message,
                error_type=error_type,
                error_stack_trace=error_stack_trace,
                partial_results={"files_processed": 3, "files_failed": 1},
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify topic
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert call_args.args[0] == "omninode.agent.execution.failed.v1"

            # Verify partition key
            assert call_args.kwargs["key"] == sample_execution_data[
                "correlation_id"
            ].encode("utf-8")

            # Verify envelope
            envelope = call_args.kwargs["value"]
            assert envelope["event_type"] == "omninode.agent.execution.failed.v1"
            assert envelope["correlation_id"] == sample_execution_data["correlation_id"]

            # Verify payload
            payload = envelope["payload"]
            assert payload["agent_name"] == sample_execution_data["agent_name"]
            assert payload["error_message"] == "config.py not found"
            assert payload["error_type"] == "FileNotFoundError"
            assert "Traceback" in payload["error_stack_trace"]
            assert payload["partial_results"] == {
                "files_processed": 3,
                "files_failed": 1,
            }
            assert "failed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_execution_failed_minimal_fields(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test execution failed event with minimal fields."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_execution_failed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                error_message="Something went wrong",
            )

            assert success is True

            # Verify payload has required fields
            call_args = mock_kafka_producer.send_and_wait.call_args
            payload = call_args.kwargs["value"]["payload"]
            assert payload["agent_name"] == sample_execution_data["agent_name"]
            assert payload["error_message"] == "Something went wrong"
            assert "failed_at" in payload

    @pytest.mark.asyncio
    async def test_publish_execution_failed_convenience_function(
        self, mock_kafka_producer, sample_execution_data
    ):
        """Test convenience function for execution failed."""
        import traceback

        try:
            raise ValueError("Test error")
        except Exception as e:
            error_message = str(e)
            error_type = type(e).__name__
            error_stack_trace = traceback.format_exc()

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_execution_failed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                error_message=error_message,
                error_type=error_type,
                error_stack_trace=error_stack_trace,
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_execution_failed_partition_key_policy(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test execution failed event uses correlation_id as partition key."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_execution_failed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                error_message="Test error",
            )

            call_args = mock_kafka_producer.send_and_wait.call_args
            partition_key = call_args.kwargs["key"]

            # Verify partition key is correlation_id (encoded)
            assert partition_key == sample_execution_data["correlation_id"].encode(
                "utf-8"
            )


class TestAllExecutionEventsIntegration:
    """Integration tests for complete execution lifecycle."""

    @pytest.mark.asyncio
    async def test_complete_execution_lifecycle(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test publishing complete execution lifecycle: started -> completed."""
        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            # 1. Publish started event
            success1 = await publisher.publish_execution_started(
                **sample_execution_data
            )
            assert success1 is True

            # 2. Publish completed event
            success2 = await publisher.publish_execution_completed(
                agent_name=sample_execution_data["agent_name"],
                correlation_id=sample_execution_data["correlation_id"],
                duration_ms=1500,
                quality_score=0.92,
            )
            assert success2 is True

            # Verify both events were published
            assert mock_kafka_producer.send_and_wait.call_count == 2

            # Verify both events use same correlation_id as partition key
            for call in mock_kafka_producer.send_and_wait.call_args_list:
                assert call.kwargs["key"] == sample_execution_data[
                    "correlation_id"
                ].encode("utf-8")

    @pytest.mark.asyncio
    async def test_failed_execution_lifecycle(
        self, publisher_config, mock_kafka_producer, sample_execution_data
    ):
        """Test publishing failed execution lifecycle: started -> failed."""
        import traceback

        with patch(
            "agents.lib.agent_execution_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = AgentExecutionPublisher(**publisher_config)
            await publisher.start()

            # 1. Publish started event
            success1 = await publisher.publish_execution_started(
                **sample_execution_data
            )
            assert success1 is True

            # 2. Simulate error and publish failed event
            try:
                raise RuntimeError("Agent execution failed")
            except Exception as e:
                success2 = await publisher.publish_execution_failed(
                    agent_name=sample_execution_data["agent_name"],
                    correlation_id=sample_execution_data["correlation_id"],
                    error_message=str(e),
                    error_type=type(e).__name__,
                    error_stack_trace=traceback.format_exc(),
                )
                assert success2 is True

            # Verify both events were published
            assert mock_kafka_producer.send_and_wait.call_count == 2

            # Verify correlation_id consistency
            for call in mock_kafka_producer.send_and_wait.call_args_list:
                assert (
                    call.kwargs["value"]["correlation_id"]
                    == sample_execution_data["correlation_id"]
                )


# Run tests with: pytest agents/tests/test_agent_execution_publisher.py -v
