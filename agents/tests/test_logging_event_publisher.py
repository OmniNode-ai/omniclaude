#!/usr/bin/env python3
"""
Unit Tests for Logging Event Publisher

Tests the Kafka publisher for structured logging events (application, audit, security),
ensuring proper event structure, partition key policy, and error handling.

Test Coverage:
- Event envelope structure validation for all three event types
- Partition key policy compliance (service_name for application, tenant_id for audit/security)
- Kafka producer lifecycle management
- Error handling and graceful degradation
- Context manager functionality
- Convenience function behavior

Created: 2025-11-13
Reference: agents/lib/logging_event_publisher.py
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Import the module under test
from agents.lib.logging_event_publisher import (
    LoggingEventPublisher,
    LoggingEventPublisherContext,
    publish_application_log,
    publish_audit_log,
    publish_security_log,
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
def sample_application_log_data():
    """Sample application log data for tests."""
    return {
        "service_name": "omniclaude",
        "instance_id": "omniclaude-1",
        "level": "INFO",
        "logger_name": "router.pipeline",
        "message": "Agent execution completed successfully",
        "code": "AGENT_EXECUTION_COMPLETED",
        "context": {
            "agent_name": "agent-api-architect",
            "duration_ms": 1234,
            "quality_score": 0.95,
        },
        "correlation_id": str(uuid4()),
    }


@pytest.fixture
def sample_audit_log_data():
    """Sample audit log data for tests."""
    return {
        "tenant_id": "tenant-123",
        "action": "agent.execution",
        "actor": "user-456",
        "resource": "agent-api-architect",
        "outcome": "success",
        "correlation_id": str(uuid4()),
        "context": {
            "duration_ms": 1234,
            "quality_score": 0.95,
        },
    }


@pytest.fixture
def sample_security_log_data():
    """Sample security log data for tests."""
    return {
        "tenant_id": "tenant-123",
        "event_type": "api_key_used",
        "user_id": "user-456",
        "resource": "gemini-api",
        "decision": "allow",
        "correlation_id": str(uuid4()),
        "context": {
            "api_key_hash": "sha256:abc123",
            "ip_address": "192.168.1.1",
        },
    }


class TestLoggingEventPublisher:
    """Test suite for LoggingEventPublisher class."""

    @pytest.mark.asyncio
    async def test_initialization_with_defaults(self):
        """Test publisher initializes with default configuration."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            publisher = LoggingEventPublisher()

            assert publisher.bootstrap_servers == "localhost:9092"
            assert publisher.enable_events is True
            assert publisher._started is False
            assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_initialization_with_custom_config(self, publisher_config):
        """Test publisher initializes with custom configuration."""
        publisher = LoggingEventPublisher(**publisher_config)

        assert publisher.bootstrap_servers == "localhost:9092"
        assert publisher.enable_events is True

    @pytest.mark.asyncio
    async def test_initialization_without_bootstrap_servers(self):
        """Test publisher raises error if bootstrap_servers not provided."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = None
            mock_settings.kafka_bootstrap_servers = "not set"

            with pytest.raises(ValueError, match="bootstrap_servers must be provided"):
                LoggingEventPublisher()

    @pytest.mark.asyncio
    async def test_start_creates_producer(self, publisher_config, mock_kafka_producer):
        """Test start() creates and initializes Kafka producer."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            assert publisher._started is True
            mock_kafka_producer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_skips_if_already_started(
        self, publisher_config, mock_kafka_producer
    ):
        """Test start() is idempotent (no-op if already started)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()
            mock_kafka_producer.start.reset_mock()

            # Start again
            await publisher.start()

            # Should not call producer.start() again
            mock_kafka_producer.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_skips_if_events_disabled(self):
        """Test start() skips initialization if events disabled."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            publisher = LoggingEventPublisher(enable_events=False)
            await publisher.start()

            assert publisher._started is False
            assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_stop_closes_producer(self, publisher_config, mock_kafka_producer):
        """Test stop() closes Kafka producer gracefully."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()
            await publisher.stop()

            assert publisher._started is False
            assert publisher._producer is None
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, publisher_config, mock_kafka_producer):
        """Test stop() is idempotent (no-op if already stopped)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()
            await publisher.stop()
            mock_kafka_producer.stop.reset_mock()

            # Stop again
            await publisher.stop()

            # Should not call producer.stop() again
            mock_kafka_producer.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_application_log_success(
        self, publisher_config, mock_kafka_producer, sample_application_log_data
    ):
        """Test publish_application_log() publishes event successfully."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_application_log(
                **sample_application_log_data
            )

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify topic
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert (
                call_args[0][0] == "omninode.logging.application.v1"
            )  # First positional arg is topic

            # Verify partition key (service_name)
            assert call_args.kwargs["key"] == b"omniclaude"

    @pytest.mark.asyncio
    async def test_publish_application_log_envelope_structure(
        self, publisher_config, mock_kafka_producer, sample_application_log_data
    ):
        """Test publish_application_log() creates correct event envelope."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_application_log(**sample_application_log_data)

            # Extract envelope from call
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify envelope structure
            assert envelope["event_type"] == "omninode.logging.application.v1"
            assert "event_id" in envelope
            assert "timestamp" in envelope
            assert envelope["namespace"] == "omninode"
            assert envelope["source"] == "omniclaude"
            assert (
                envelope["correlation_id"]
                == sample_application_log_data["correlation_id"]
            )
            assert "schema_ref" in envelope

            # Verify payload
            payload = envelope["payload"]
            assert payload["service_name"] == "omniclaude"
            assert payload["instance_id"] == "omniclaude-1"
            assert payload["level"] == "INFO"
            assert payload["logger"] == "router.pipeline"
            assert payload["message"] == "Agent execution completed successfully"
            assert payload["code"] == "AGENT_EXECUTION_COMPLETED"
            assert payload["context"]["agent_name"] == "agent-api-architect"

    @pytest.mark.asyncio
    async def test_publish_audit_log_success(
        self, publisher_config, mock_kafka_producer, sample_audit_log_data
    ):
        """Test publish_audit_log() publishes event successfully."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_audit_log(**sample_audit_log_data)

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify topic
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert call_args[0][0] == "omninode.logging.audit.v1"

            # Verify partition key (tenant_id)
            assert call_args.kwargs["key"] == b"tenant-123"

    @pytest.mark.asyncio
    async def test_publish_audit_log_envelope_structure(
        self, publisher_config, mock_kafka_producer, sample_audit_log_data
    ):
        """Test publish_audit_log() creates correct event envelope."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_audit_log(**sample_audit_log_data)

            # Extract envelope from call
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify envelope structure
            assert envelope["event_type"] == "omninode.logging.audit.v1"
            assert envelope["tenant_id"] == "tenant-123"

            # Verify payload
            payload = envelope["payload"]
            assert payload["tenant_id"] == "tenant-123"
            assert payload["action"] == "agent.execution"
            assert payload["actor"] == "user-456"
            assert payload["resource"] == "agent-api-architect"
            assert payload["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_publish_security_log_success(
        self, publisher_config, mock_kafka_producer, sample_security_log_data
    ):
        """Test publish_security_log() publishes event successfully."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_security_log(**sample_security_log_data)

            assert success is True
            mock_kafka_producer.send_and_wait.assert_called_once()

            # Verify topic
            call_args = mock_kafka_producer.send_and_wait.call_args
            assert call_args[0][0] == "omninode.logging.security.v1"

            # Verify partition key (tenant_id)
            assert call_args.kwargs["key"] == b"tenant-123"

    @pytest.mark.asyncio
    async def test_publish_security_log_envelope_structure(
        self, publisher_config, mock_kafka_producer, sample_security_log_data
    ):
        """Test publish_security_log() creates correct event envelope."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_security_log(**sample_security_log_data)

            # Extract envelope from call
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify envelope structure
            assert envelope["event_type"] == "omninode.logging.security.v1"
            assert envelope["tenant_id"] == "tenant-123"

            # Verify payload
            payload = envelope["payload"]
            assert payload["tenant_id"] == "tenant-123"
            assert payload["event_type"] == "api_key_used"
            assert payload["user_id"] == "user-456"
            assert payload["resource"] == "gemini-api"
            assert payload["decision"] == "allow"

    @pytest.mark.asyncio
    async def test_publish_skips_if_not_started(
        self, publisher_config, sample_application_log_data
    ):
        """Test publish methods skip if publisher not started."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Should return False without publishing
        success = await publisher.publish_application_log(**sample_application_log_data)
        assert success is False

    @pytest.mark.asyncio
    async def test_publish_skips_if_events_disabled(
        self, mock_kafka_producer, sample_application_log_data
    ):
        """Test publish methods skip if events disabled."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
                mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                    "localhost:9092"
                )
                publisher = LoggingEventPublisher(enable_events=False)
                await publisher.start()

                success = await publisher.publish_application_log(
                    **sample_application_log_data
                )

                assert success is False
                mock_kafka_producer.send_and_wait.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_handles_kafka_error(
        self, publisher_config, mock_kafka_producer, sample_application_log_data
    ):
        """Test publish methods handle Kafka errors gracefully."""
        mock_kafka_producer.send_and_wait.side_effect = Exception(
            "Kafka connection lost"
        )

        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_application_log(
                **sample_application_log_data
            )

            assert success is False

    @pytest.mark.asyncio
    async def test_context_manager_lifecycle(
        self, publisher_config, mock_kafka_producer, sample_application_log_data
    ):
        """Test context manager handles publisher lifecycle automatically."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            async with LoggingEventPublisherContext(**publisher_config) as publisher:
                # Publisher should be started
                assert isinstance(publisher, LoggingEventPublisher)
                mock_kafka_producer.start.assert_called_once()

                await publisher.publish_application_log(**sample_application_log_data)

            # Publisher should be stopped after context exit
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_stops_on_exception(
        self, publisher_config, mock_kafka_producer
    ):
        """Test context manager stops publisher even if exception raised."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            with pytest.raises(RuntimeError):
                async with LoggingEventPublisherContext(
                    **publisher_config
                ) as publisher:
                    raise RuntimeError("Test exception")

            # Publisher should still be stopped
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_convenience_function_publish_application_log(
        self, mock_kafka_producer, sample_application_log_data
    ):
        """Test convenience function publish_application_log()."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_application_log(**sample_application_log_data)

            assert success is True
            mock_kafka_producer.start.assert_called_once()
            mock_kafka_producer.send_and_wait.assert_called_once()
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_convenience_function_publish_audit_log(
        self, mock_kafka_producer, sample_audit_log_data
    ):
        """Test convenience function publish_audit_log()."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_audit_log(**sample_audit_log_data)

            assert success is True
            mock_kafka_producer.start.assert_called_once()
            mock_kafka_producer.send_and_wait.assert_called_once()
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_convenience_function_publish_security_log(
        self, mock_kafka_producer, sample_security_log_data
    ):
        """Test convenience function publish_security_log()."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            success = await publish_security_log(**sample_security_log_data)

            assert success is True
            mock_kafka_producer.start.assert_called_once()
            mock_kafka_producer.send_and_wait.assert_called_once()
            mock_kafka_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_application_log_without_correlation_id(
        self, publisher_config, mock_kafka_producer
    ):
        """Test application log generates correlation_id if not provided."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test message",
                code="TEST_CODE",
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Should have generated correlation_id
            assert "correlation_id" in envelope
            assert envelope["correlation_id"] is not None

    @pytest.mark.asyncio
    async def test_kafka_headers_with_correlation_id(
        self, publisher_config, mock_kafka_producer, sample_application_log_data
    ):
        """Test Kafka headers include correlation ID when provided."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_application_log(**sample_application_log_data)

            # Extract headers
            call_args = mock_kafka_producer.send_and_wait.call_args
            headers = call_args.kwargs["headers"]

            # Verify correlation ID in headers
            header_dict = {
                k.decode() if isinstance(k, bytes) else k: v for k, v in headers
            }
            assert "x-correlation-id" in header_dict
            assert header_dict["x-correlation-id"] == sample_application_log_data[
                "correlation_id"
            ].encode("utf-8")


class TestLoggingEventPublisherIntegration:
    """Integration tests for LoggingEventPublisher (require actual Kafka)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_publish_to_real_kafka(self, sample_application_log_data):
        """
        Integration test: Publish to real Kafka instance.

        NOTE: This test requires a running Kafka instance.
        Skip in CI/CD if Kafka not available.
        """
        pytest.skip("Requires running Kafka instance (integration test)")

        # This would test with actual Kafka
        publisher = LoggingEventPublisher(
            bootstrap_servers="localhost:9092",
            enable_events=True,
        )

        try:
            await publisher.start()
            success = await publisher.publish_application_log(
                **sample_application_log_data
            )
            assert success is True
        finally:
            await publisher.stop()
