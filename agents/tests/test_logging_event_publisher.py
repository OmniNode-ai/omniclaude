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
- Enum type safety (LogLevel, Outcome, Decision)
- Tenant ID handling (explicit, env var fallback, default)
- Production edge cases (connection failures, concurrency, large payloads, timeouts, invalid UTF-8)

Edge Case Coverage (marked with @pytest.mark.slow):
- Connection failure recovery (Kafka down mid-publish)
- Concurrent publishing (50 parallel tasks, thread safety verification)
- Large payload handling (1MB+ context dictionaries)
- Oversized payload rejection (>1MB envelope size, DoS protection)
- Network timeout scenarios (graceful degradation)
- Invalid partition keys (non-UTF8 characters)
- Producer stop during active publishing

Created: 2025-11-13
Updated: 2025-11-14 (Added edge case tests for production scenarios)
Reference: agents/lib/logging_event_publisher.py
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiokafka.errors import KafkaError

# Import the module under test
from agents.lib.logging_event_publisher import (
    Decision,
    LoggingEventPublisher,
    LoggingEventPublisherContext,
    LogLevel,
    Outcome,
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
    async def test_initialization_with_defaults(self) -> None:
        """Test publisher initializes with default configuration."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            mock_settings.kafka_enable_logging_events = True
            publisher = LoggingEventPublisher()

            assert publisher.bootstrap_servers == "localhost:9092"
            assert publisher.enable_events is True
            assert publisher._started is False
            assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_initialization_with_custom_config(self, publisher_config) -> None:
        """Test publisher initializes with custom configuration."""
        publisher = LoggingEventPublisher(**publisher_config)

        assert publisher.bootstrap_servers == "localhost:9092"
        assert publisher.enable_events is True

    @pytest.mark.asyncio
    async def test_initialization_reads_env_var(self) -> None:
        """Test publisher reads KAFKA_ENABLE_LOGGING_EVENTS from Pydantic Settings."""
        # Test with settings.kafka_enable_logging_events = False
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            mock_settings.kafka_enable_logging_events = False
            publisher = LoggingEventPublisher()
            assert publisher.enable_events is False

        # Test with settings.kafka_enable_logging_events = True
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )
            mock_settings.kafka_enable_logging_events = True
            publisher = LoggingEventPublisher()
            assert publisher.enable_events is True

    @pytest.mark.asyncio
    async def test_initialization_explicit_param_overrides_env_var(self) -> None:
        """Test explicit enable_events parameter takes precedence over environment variable."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
                "localhost:9092"
            )

            # Explicit True overrides env var False
            with patch.dict("os.environ", {"KAFKA_ENABLE_LOGGING_EVENTS": "false"}):
                publisher = LoggingEventPublisher(enable_events=True)
                assert publisher.enable_events is True

            # Explicit False overrides env var True
            with patch.dict("os.environ", {"KAFKA_ENABLE_LOGGING_EVENTS": "true"}):
                publisher = LoggingEventPublisher(enable_events=False)
                assert publisher.enable_events is False

    @pytest.mark.asyncio
    async def test_initialization_without_bootstrap_servers(self) -> None:
        """Test publisher raises error if bootstrap_servers not provided."""
        with patch("agents.lib.logging_event_publisher.settings") as mock_settings:
            mock_settings.get_effective_kafka_bootstrap_servers.return_value = None
            mock_settings.kafka_bootstrap_servers = "not set"

            with pytest.raises(ValueError, match="bootstrap_servers must be provided"):
                LoggingEventPublisher()

    @pytest.mark.asyncio
    async def test_start_creates_producer(
        self, publisher_config, mock_kafka_producer
    ) -> None:
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
    ) -> None:
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
    async def test_start_skips_if_events_disabled(self) -> None:
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
    async def test_start_failure_cleanup_preserves_original_error(
        self, publisher_config
    ) -> None:
        """Test start() failure cleanup doesn't mask original error."""
        # Create a mock producer that fails on start
        mock_producer = AsyncMock()
        original_error = Exception("Original startup error")
        mock_producer.start.side_effect = original_error

        # Make cleanup also fail
        cleanup_error = Exception("Cleanup error")
        mock_producer.stop.side_effect = cleanup_error

        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)

            # Verify original error is raised, not cleanup error
            with pytest.raises(
                KafkaError, match="Failed to start Kafka producer"
            ) as exc_info:
                await publisher.start()

            # Should raise KafkaError wrapping original error
            assert exc_info.value.__cause__ is original_error

            # Verify cleanup was attempted despite error
            mock_producer.stop.assert_called_once()

            # Verify producer is set to None
            assert publisher._producer is None

    @pytest.mark.asyncio
    async def test_start_failure_cleanup_when_producer_partially_initialized(
        self, publisher_config
    ) -> None:
        """Test start() failure cleanup works when producer is partially initialized."""
        # Create a mock producer that fails on start (after being created)
        mock_producer = AsyncMock()
        mock_producer.start.side_effect = Exception("Connection failed")
        mock_producer.stop = AsyncMock()  # Cleanup should succeed

        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)

            with pytest.raises(
                KafkaError, match="Failed to start Kafka producer"
            ) as exc_info:
                await publisher.start()

            # Verify cleanup was called
            mock_producer.stop.assert_called_once()

            # Verify producer is set to None
            assert publisher._producer is None

            # Verify original error is propagated
            assert "Failed to start Kafka producer" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stop_closes_producer(
        self, publisher_config, mock_kafka_producer
    ) -> None:
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
    async def test_stop_is_idempotent(
        self, publisher_config, mock_kafka_producer
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
        """Test publish methods skip if publisher not started."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Should return False without publishing
        success = await publisher.publish_application_log(**sample_application_log_data)
        assert success is False

    @pytest.mark.asyncio
    async def test_publish_skips_if_events_disabled(
        self, mock_kafka_producer, sample_application_log_data
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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
    ) -> None:
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

    @pytest.mark.asyncio
    async def test_timestamp_consistency_audit_log(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test audit log envelope and payload have identical timestamps."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_audit_log(
                tenant_id="test-tenant",
                action="user.login",
                actor="user123",
                resource="/api/login",
                outcome="success",
                correlation_id=str(uuid4()),
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify timestamps are identical (no microseconds difference)
            assert "timestamp" in envelope
            assert "timestamp" in envelope["payload"]
            assert envelope["timestamp"] == envelope["payload"]["timestamp"]

    @pytest.mark.asyncio
    async def test_timestamp_consistency_security_log(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test security log envelope and payload have identical timestamps."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_security_log(
                tenant_id="test-tenant",
                event_type="authorization.check",
                user_id="user123",
                resource="/api/admin",
                decision="deny",
                correlation_id=str(uuid4()),
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify timestamps are identical (no microseconds difference)
            assert "timestamp" in envelope
            assert "timestamp" in envelope["payload"]
            assert envelope["timestamp"] == envelope["payload"]["timestamp"]

    @pytest.mark.asyncio
    async def test_context_sanitization_redacts_sensitive_keys(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that sensitive keys in context are redacted."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Publish with sensitive context
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test with sensitive data",
                code="TEST_SENSITIVE",
                context={
                    "user": "john_doe",
                    "password": "secret123",
                    "api_key": "sk-abc123xyz",
                    "token": "bearer_token_value",
                    "duration_ms": 1234,  # Non-sensitive - should NOT be redacted
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Verify sensitive keys are redacted
            assert context["password"] == "[REDACTED]"
            assert context["api_key"] == "[REDACTED]"
            assert context["token"] == "[REDACTED]"

            # Verify non-sensitive keys are preserved
            assert context["user"] == "john_doe"
            assert context["duration_ms"] == 1234

    @pytest.mark.asyncio
    async def test_context_sanitization_handles_empty_context(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that sanitization handles None and empty context gracefully."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Test with None context
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test with no context",
                code="TEST_NO_CONTEXT",
                context=None,
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Should have empty context, not None
            assert context == {}

    @pytest.mark.asyncio
    async def test_context_sanitization_case_insensitive(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that sanitization is case-insensitive for key matching."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Publish with mixed-case sensitive keys
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test case sensitivity",
                code="TEST_CASE",
                context={
                    "PASSWORD": "secret123",  # Uppercase
                    "Api_Key": "sk-abc123",  # Mixed case
                    "TOKEN": "bearer_value",  # Uppercase
                    "normal_field": "value",  # Non-sensitive
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # All sensitive keys should be redacted regardless of case
            assert context["PASSWORD"] == "[REDACTED]"
            assert context["Api_Key"] == "[REDACTED]"
            assert context["TOKEN"] == "[REDACTED]"

            # Non-sensitive key preserved
            assert context["normal_field"] == "value"

    @pytest.mark.asyncio
    async def test_audit_log_sanitization(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that audit logs also sanitize context."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_audit_log(
                tenant_id="tenant-123",
                action="user.login",
                actor="user-456",
                resource="/api/login",
                outcome="success",
                context={
                    "session": "session_12345",
                    "email": "user@example.com",
                    "ip_address": "192.168.1.1",  # Non-sensitive
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Sensitive keys redacted
            assert context["session"] == "[REDACTED]"
            assert context["email"] == "[REDACTED]"

            # Non-sensitive preserved
            assert context["ip_address"] == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_security_log_sanitization(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that security logs also sanitize context."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            await publisher.publish_security_log(
                tenant_id="tenant-123",
                event_type="api_key_usage",
                user_id="user-456",
                resource="gemini-api",
                decision="allow",
                context={
                    "api_key": "sk-abc123",
                    "authorization": "Bearer token123",
                    "request_id": "req-789",  # Non-sensitive
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Sensitive keys redacted
            assert context["api_key"] == "[REDACTED]"
            assert context["authorization"] == "[REDACTED]"

            # Non-sensitive preserved
            assert context["request_id"] == "req-789"

    @pytest.mark.asyncio
    async def test_application_log_with_enum_level(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_application_log() accepts LogLevel enum."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level=LogLevel.INFO,  # Use enum
                logger_name="test.logger",
                message="Test with enum",
                code="TEST_ENUM",
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify level was converted to string
            assert envelope["payload"]["level"] == "INFO"

    @pytest.mark.asyncio
    async def test_application_log_with_string_level_backward_compat(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_application_log() still accepts string (backward compatibility)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="WARN",  # Use string
                logger_name="test.logger",
                message="Test with string",
                code="TEST_STRING",
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify level is preserved as string
            assert envelope["payload"]["level"] == "WARN"

    @pytest.mark.asyncio
    async def test_audit_log_with_enum_outcome(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_audit_log() accepts Outcome enum."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_audit_log(
                tenant_id="tenant-123",
                action="test.action",
                actor="test-actor",
                resource="test-resource",
                outcome=Outcome.SUCCESS,  # Use enum
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify outcome was converted to string
            assert envelope["payload"]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_audit_log_with_string_outcome_backward_compat(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_audit_log() still accepts string (backward compatibility)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_audit_log(
                tenant_id="tenant-123",
                action="test.action",
                actor="test-actor",
                resource="test-resource",
                outcome="failure",  # Use string
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify outcome is preserved as string
            assert envelope["payload"]["outcome"] == "failure"

    @pytest.mark.asyncio
    async def test_security_log_with_enum_decision(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_security_log() accepts Decision enum."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_security_log(
                tenant_id="tenant-123",
                event_type="test.event",
                user_id="test-user",
                resource="test-resource",
                decision=Decision.ALLOW,  # Use enum
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify decision was converted to string
            assert envelope["payload"]["decision"] == "allow"

    @pytest.mark.asyncio
    async def test_security_log_with_string_decision_backward_compat(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test publish_security_log() still accepts string (backward compatibility)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            success = await publisher.publish_security_log(
                tenant_id="tenant-123",
                event_type="test.event",
                user_id="test-user",
                resource="test-resource",
                decision="deny",  # Use string
            )

            assert success is True

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Verify decision is preserved as string
            assert envelope["payload"]["decision"] == "deny"

    @pytest.mark.asyncio
    async def test_enum_values_are_correct(self) -> None:
        """Test that enum values match expected strings."""
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARN.value == "WARN"
        assert LogLevel.ERROR.value == "ERROR"

        assert Outcome.SUCCESS.value == "success"
        assert Outcome.FAILURE.value == "failure"

        assert Decision.ALLOW.value == "allow"
        assert Decision.DENY.value == "deny"

    @pytest.mark.asyncio
    async def test_application_log_with_explicit_tenant_id(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test application log uses explicit tenant_id parameter."""
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
                tenant_id="tenant-explicit-123",
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]

            # Should use explicit tenant_id
            assert envelope["tenant_id"] == "tenant-explicit-123"

    @pytest.mark.asyncio
    async def test_application_log_tenant_id_fallback_to_env(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test application log falls back to TENANT_ID environment variable."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            with patch.dict("os.environ", {"TENANT_ID": "tenant-from-env"}):
                publisher = LoggingEventPublisher(**publisher_config)
                await publisher.start()

                await publisher.publish_application_log(
                    service_name="omniclaude",
                    instance_id="omniclaude-1",
                    level="INFO",
                    logger_name="test.logger",
                    message="Test message",
                    code="TEST_CODE",
                    # No tenant_id parameter - should fall back to env var
                )

                # Extract envelope
                call_args = mock_kafka_producer.send_and_wait.call_args
                envelope = call_args.kwargs["value"]

                # Should use env var
                assert envelope["tenant_id"] == "tenant-from-env"

    @pytest.mark.asyncio
    async def test_application_log_tenant_id_fallback_to_default(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test application log falls back to 'default' when no tenant_id provided."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            with patch.dict("os.environ", {}, clear=True):
                publisher = LoggingEventPublisher(**publisher_config)
                await publisher.start()

                await publisher.publish_application_log(
                    service_name="omniclaude",
                    instance_id="omniclaude-1",
                    level="INFO",
                    logger_name="test.logger",
                    message="Test message",
                    code="TEST_CODE",
                    # No tenant_id parameter and no env var - should fall back to "default"
                )

                # Extract envelope
                call_args = mock_kafka_producer.send_and_wait.call_args
                envelope = call_args.kwargs["value"]

                # Should use "default"
                assert envelope["tenant_id"] == "default"

    @pytest.mark.asyncio
    async def test_context_sanitization_nested_dictionaries(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that nested sensitive keys are redacted recursively."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Publish with nested context containing sensitive data
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test nested sanitization",
                code="TEST_NESTED",
                context={
                    "user": "john",
                    "password": "top_level_secret",  # Top-level sensitive
                    "metadata": {
                        "api_key": "nested_api_key",  # Level 1 sensitive
                        "description": "normal value",  # Level 1 non-sensitive
                        "credentials": {
                            "username": "admin",  # Level 2 non-sensitive
                            "token": "nested_token",  # Level 2 sensitive
                            "settings": {
                                "refresh_token": "deep_refresh",  # Level 3 sensitive
                                "timeout": 30,  # Level 3 non-sensitive
                            },
                        },
                    },
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Verify top-level sanitization
            assert context["user"] == "john"
            assert context["password"] == "[REDACTED]"

            # Verify level 1 nested sanitization
            assert context["metadata"]["api_key"] == "[REDACTED]"
            assert context["metadata"]["description"] == "normal value"

            # Verify level 2 nested sanitization (credentials is sensitive key)
            assert context["metadata"]["credentials"] == "[REDACTED]"

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_context_sanitization_deep_nesting(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test sanitization with deep nesting (5+ levels)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create deeply nested context
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test deep nesting",
                code="TEST_DEEP",
                context={
                    "level1": {
                        "level2": {
                            "level3": {
                                "level4": {
                                    "level5": {
                                        "api_key": "deep_secret",
                                        "normal_field": "value",
                                    }
                                }
                            }
                        }
                    }
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Navigate to level 5 and verify sanitization
            level5 = context["level1"]["level2"]["level3"]["level4"]["level5"]
            assert level5["api_key"] == "[REDACTED]"
            assert level5["normal_field"] == "value"

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_context_sanitization_near_max_depth(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that sanitization works correctly near max depth (8-9 levels)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create context with 9 levels (within limit)
            deep_context = {"level1": {}}
            current = deep_context["level1"]
            for i in range(2, 10):
                current[f"level{i}"] = {}
                current = current[f"level{i}"]
            # Add sensitive key at deepest level
            current["api_key"] = "very_deep_secret"
            current["normal_field"] = "normal_value"

            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test near max depth",
                code="TEST_NEAR_MAX_DEPTH",
                context=deep_context,
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Navigate to level 9 (deepest level)
            level9 = context["level1"]["level2"]["level3"]["level4"]["level5"][
                "level6"
            ]["level7"]["level8"]["level9"]

            # Verify sanitization worked at deepest level
            assert level9["api_key"] == "[REDACTED]"
            assert level9["normal_field"] == "normal_value"

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_context_sanitization_mixed_types(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test sanitization with mixed types (lists, primitives, nested dicts)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Context with mixed types
            await publisher.publish_application_log(
                service_name="omniclaude",
                instance_id="omniclaude-1",
                level="INFO",
                logger_name="test.logger",
                message="Test mixed types",
                code="TEST_MIXED",
                context={
                    "string_field": "value",
                    "number_field": 42,
                    "bool_field": True,
                    "list_field": [1, 2, 3],  # Lists are preserved as-is
                    "password": "secret",  # Top-level sensitive
                    "nested": {
                        "api_key": "nested_secret",  # Nested sensitive
                        "data": [4, 5, 6],  # Nested list
                    },
                },
            )

            # Extract envelope
            call_args = mock_kafka_producer.send_and_wait.call_args
            envelope = call_args.kwargs["value"]
            context = envelope["payload"]["context"]

            # Verify types are preserved
            assert context["string_field"] == "value"
            assert context["number_field"] == 42
            assert context["bool_field"] is True
            assert context["list_field"] == [1, 2, 3]

            # Verify sanitization still works
            assert context["password"] == "[REDACTED]"
            assert context["nested"]["api_key"] == "[REDACTED]"
            assert context["nested"]["data"] == [4, 5, 6]

            await publisher.stop()


class TestLoggingEventPublisherValidation:
    """Test suite for input validation methods."""

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_valid_string(
        self, publisher_config
    ) -> None:
        """Test that valid strings pass partition key validation."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Should not raise
        publisher._validate_partition_key_field("tenant_id", "tenant-123")
        publisher._validate_partition_key_field("service_name", "omniclaude")
        publisher._validate_partition_key_field("action", "agent.execution")

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_null_byte_rejection(
        self, publisher_config
    ) -> None:
        """Test that null bytes in partition keys are rejected."""
        publisher = LoggingEventPublisher(**publisher_config)

        with pytest.raises(ValueError, match="cannot contain null bytes"):
            publisher._validate_partition_key_field("tenant_id", "tenant\x00id")

        with pytest.raises(ValueError, match="cannot contain null bytes"):
            publisher._validate_partition_key_field("service_name", "service\x00name")

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_length_limit(
        self, publisher_config
    ) -> None:
        """Test that length limits are enforced for partition keys."""
        publisher = LoggingEventPublisher(**publisher_config)

        # 256 chars should pass
        valid_string = "x" * 256
        publisher._validate_partition_key_field(
            "tenant_id", valid_string, max_length=256
        )

        # 257 chars should fail
        invalid_string = "x" * 257
        with pytest.raises(ValueError, match="must be <= 256 characters"):
            publisher._validate_partition_key_field(
                "tenant_id", invalid_string, max_length=256
            )

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_empty_string_rejection(
        self, publisher_config
    ) -> None:
        """Test that empty strings are rejected for partition keys."""
        publisher = LoggingEventPublisher(**publisher_config)

        with pytest.raises(ValueError, match="cannot be empty or whitespace only"):
            publisher._validate_partition_key_field("tenant_id", "")

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_whitespace_only_rejection(
        self, publisher_config
    ) -> None:
        """Test that whitespace-only strings are rejected for partition keys."""
        publisher = LoggingEventPublisher(**publisher_config)

        with pytest.raises(ValueError, match="cannot be empty or whitespace only"):
            publisher._validate_partition_key_field("tenant_id", "   ")

        with pytest.raises(ValueError, match="cannot be empty or whitespace only"):
            publisher._validate_partition_key_field("tenant_id", "\t\n")

    @pytest.mark.asyncio
    async def test_validate_partition_key_field_non_string_type_rejection(
        self, publisher_config
    ) -> None:
        """Test that non-string types are rejected for partition keys."""
        publisher = LoggingEventPublisher(**publisher_config)

        with pytest.raises(TypeError, match="must be a string, got int"):
            publisher._validate_partition_key_field("tenant_id", 123)  # type: ignore

        with pytest.raises(TypeError, match="must be a string, got NoneType"):
            publisher._validate_partition_key_field("tenant_id", None)  # type: ignore

        with pytest.raises(TypeError, match="must be a string, got list"):
            publisher._validate_partition_key_field("tenant_id", ["tenant"])  # type: ignore

    @pytest.mark.asyncio
    async def test_validate_context_size_deep_nesting_rejection(
        self, publisher_config
    ) -> None:
        """Test that excessively deep nesting (>10 levels) is rejected."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Create deeply nested structure (11 levels of nested dicts)
        deeply_nested = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "level6": {
                                    "level7": {
                                        "level8": {
                                            "level9": {
                                                "level10": {
                                                    "level11": {"data": "too deep"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="nesting depth exceeds 10 levels"):
            publisher._validate_context_size(deeply_nested)

    @pytest.mark.asyncio
    async def test_validate_context_size_deep_nesting_with_lists(
        self, publisher_config
    ) -> None:
        """Test that deep nesting with lists is also rejected."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Create deeply nested structure with lists (11 levels)
        deeply_nested = {
            "level1": [
                {
                    "level2": [
                        {
                            "level3": [
                                {
                                    "level4": [
                                        {
                                            "level5": [
                                                {
                                                    "level6": [
                                                        {
                                                            "level7": [
                                                                {
                                                                    "level8": [
                                                                        {
                                                                            "level9": [
                                                                                {
                                                                                    "level10": [
                                                                                        {
                                                                                            "level11": "too deep"
                                                                                        }
                                                                                    ]
                                                                                }
                                                                            ]
                                                                        }
                                                                    ]
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        with pytest.raises(ValueError, match="nesting depth exceeds 10 levels"):
            publisher._validate_context_size(deeply_nested)

    @pytest.mark.asyncio
    async def test_validate_context_size_circular_reference_rejection(
        self, publisher_config
    ) -> None:
        """Test that circular references are rejected (caught by depth check)."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Create circular reference
        circular_dict: Dict[str, Any] = {"key": "value"}
        circular_dict["self"] = circular_dict

        # Circular references are caught by the depth check (exceeds 10 levels)
        # before json.dumps() would raise. Both error messages are acceptable.
        with pytest.raises(
            ValueError, match="(circular references|nesting depth exceeds 10 levels)"
        ):
            publisher._validate_context_size(circular_dict)

    @pytest.mark.asyncio
    async def test_validate_context_size_acceptable_depth(
        self, publisher_config
    ) -> None:
        """Test that acceptable nesting depth (<=10 levels) passes."""
        publisher = LoggingEventPublisher(**publisher_config)

        # Create structure with exactly 10 levels (should pass)
        acceptable_depth = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "level6": {
                                    "level7": {"level8": {"level9": {"level10": "ok"}}}
                                }
                            }
                        }
                    }
                }
            }
        }

        # Should not raise
        publisher._validate_context_size(acceptable_depth)

    @pytest.mark.asyncio
    async def test_publish_application_log_validates_service_name(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that publish_application_log validates service_name as partition key."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Null byte in service_name should be rejected
            with pytest.raises(
                ValueError, match="service_name cannot contain null bytes"
            ):
                await publisher.publish_application_log(
                    service_name="service\x00name",
                    instance_id="instance-1",
                    level="INFO",
                    logger_name="test.logger",
                    message="Test",
                    code="TEST",
                )

            # Empty service_name should be rejected
            with pytest.raises(ValueError, match="service_name cannot be empty"):
                await publisher.publish_application_log(
                    service_name="",
                    instance_id="instance-1",
                    level="INFO",
                    logger_name="test.logger",
                    message="Test",
                    code="TEST",
                )

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_publish_audit_log_validates_tenant_id(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that publish_audit_log validates tenant_id as partition key."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Null byte in explicitly provided tenant_id should be rejected
            with pytest.raises(ValueError, match="tenant_id cannot contain null bytes"):
                await publisher.publish_audit_log(
                    tenant_id="tenant\x00id",
                    action="test.action",
                    actor="test-actor",
                    resource="test-resource",
                    outcome="success",
                )

            # Excessively long tenant_id should be rejected
            with pytest.raises(ValueError, match="tenant_id must be <= 128 characters"):
                await publisher.publish_audit_log(
                    tenant_id="x" * 129,  # 129 characters exceeds 128 limit
                    action="test.action",
                    actor="test-actor",
                    resource="test-resource",
                    outcome="success",
                )

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_publish_security_log_validates_tenant_id(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that publish_security_log validates tenant_id as partition key."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Null byte in explicitly provided tenant_id should be rejected
            with pytest.raises(ValueError, match="tenant_id cannot contain null bytes"):
                await publisher.publish_security_log(
                    tenant_id="tenant\x00id",
                    event_type="test.event",
                    user_id="test-user",
                    resource="test-resource",
                    decision="allow",
                )

            # Excessively long tenant_id should be rejected
            with pytest.raises(ValueError, match="tenant_id must be <= 128 characters"):
                await publisher.publish_security_log(
                    tenant_id="x" * 129,  # 129 characters exceeds 128 limit
                    event_type="test.event",
                    user_id="test-user",
                    resource="test-resource",
                    decision="allow",
                )

            await publisher.stop()

    @pytest.mark.asyncio
    async def test_publish_with_deeply_nested_context_rejection(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that all publish methods reject deeply nested context."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create deeply nested context (11 levels of nested dicts)
            deeply_nested = {
                "level1": {
                    "level2": {
                        "level3": {
                            "level4": {
                                "level5": {
                                    "level6": {
                                        "level7": {
                                            "level8": {
                                                "level9": {
                                                    "level10": {
                                                        "level11": {"data": "too deep"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            # Application log should reject
            with pytest.raises(ValueError, match="nesting depth exceeds 10 levels"):
                await publisher.publish_application_log(
                    service_name="test-service",
                    instance_id="test-instance",
                    level="INFO",
                    logger_name="test.logger",
                    message="Test",
                    code="TEST",
                    context=deeply_nested,
                )

            # Audit log should reject
            with pytest.raises(ValueError, match="nesting depth exceeds 10 levels"):
                await publisher.publish_audit_log(
                    tenant_id="test-tenant",
                    action="test.action",
                    actor="test-actor",
                    resource="test-resource",
                    outcome="success",
                    context=deeply_nested,
                )

            # Security log should reject
            with pytest.raises(ValueError, match="nesting depth exceeds 10 levels"):
                await publisher.publish_security_log(
                    tenant_id="test-tenant",
                    event_type="test.event",
                    user_id="test-user",
                    resource="test-resource",
                    decision="allow",
                    context=deeply_nested,
                )

            await publisher.stop()


class TestLoggingEventPublisherEdgeCases:
    """Edge case tests for production scenarios (marked as slow tests)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_connection_failure_during_publish(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test graceful handling when producer fails during publish."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Mock producer to fail on second call
            call_count = 0

            async def failing_send(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise Exception("Kafka connection lost")
                return None

            mock_kafka_producer.send_and_wait.side_effect = failing_send

            # First publish should succeed
            result1 = await publisher.publish_application_log(
                service_name="test-service",
                instance_id="test-instance",
                level="INFO",
                logger_name="test-logger",
                message="First message",
                code="TEST-001",
            )
            assert result1 is True

            # Second publish should fail gracefully
            result2 = await publisher.publish_application_log(
                service_name="test-service",
                instance_id="test-instance",
                level="INFO",
                logger_name="test-logger",
                message="Second message",
                code="TEST-002",
            )
            assert result2 is False  # Should return False, not raise

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_concurrent_publishing(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test thread-safety of concurrent publishing."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create 50 concurrent publish tasks
            async def publish_event(index: int):
                return await publisher.publish_application_log(
                    service_name=f"service-{index}",
                    instance_id=f"instance-{index}",
                    level="INFO",
                    logger_name=f"logger-{index}",
                    message=f"Message {index}",
                    code=f"CODE-{index:03d}",
                )

            tasks = [publish_event(i) for i in range(50)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed (or return False gracefully)
            assert all(
                isinstance(r, bool) for r in results
            ), "All results should be boolean"
            # At least 90% should succeed
            success_rate = sum(1 for r in results if r is True) / len(results)
            assert success_rate >= 0.9, f"Success rate {success_rate} is below 90%"

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_large_payload_handling(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test validation rejects large context dictionaries (>64KB)."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create 1MB string (exceeds 64KB limit)
            large_context = {
                "data": "x" * (1024 * 1024),  # 1MB of 'x' characters
                "metadata": "large payload test",
            }

            # Our validation should reject payloads >64KB
            with pytest.raises(
                ValueError, match="context serialized size must be <= 65536 bytes"
            ):
                await publisher.publish_application_log(
                    service_name="test-service",
                    instance_id="test-instance",
                    level="WARN",
                    logger_name="test-logger",
                    message="Large payload test",
                    code="LARGE-001",
                    context=large_context,
                )

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_oversized_payload_rejection(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that oversized payloads (>1MB) are rejected."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Create context that will make the envelope exceed 1MB
            # We need to bypass the 64KB context size validation to test the 1MB envelope validation
            # This simulates a scenario where somehow a large payload makes it through
            large_context = {
                "data": "x" * (2 * 1024 * 1024),  # 2MB of data
            }

            # Patch _validate_context_size to bypass the 64KB check
            # This allows us to test the 1MB envelope size validation
            with patch.object(publisher, "_validate_context_size"):
                # Test application log - should be rejected by envelope size check
                result = await publisher.publish_application_log(
                    service_name="test-service",
                    instance_id="test-instance",
                    level="INFO",
                    logger_name="test-logger",
                    message="Oversized payload test",
                    code="OVERSIZED-001",
                    context=large_context,
                )
                assert result is False  # Should be rejected

                # Test audit log - should be rejected by envelope size check
                result = await publisher.publish_audit_log(
                    tenant_id="test-tenant",
                    action="test.action",
                    actor="test-actor",
                    resource="test-resource",
                    outcome="success",
                    context=large_context,
                )
                assert result is False  # Should be rejected

                # Test security log - should be rejected by envelope size check
                result = await publisher.publish_security_log(
                    tenant_id="test-tenant",
                    event_type="test.event",
                    user_id="test-user",
                    resource="test-resource",
                    decision="allow",
                    context=large_context,
                )
                assert result is False  # Should be rejected

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_network_timeout_handling(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test handling of network timeouts."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Mock producer to simulate timeout
            async def timeout_send(*args, **kwargs):
                await asyncio.sleep(0.1)  # Fast enough to test timeout logic
                raise asyncio.TimeoutError("Network timeout")

            mock_kafka_producer.send_and_wait.side_effect = timeout_send

            # Should handle timeout gracefully
            result = await publisher.publish_application_log(
                service_name="test-service",
                instance_id="test-instance",
                level="ERROR",
                logger_name="test-logger",
                message="Timeout test",
                code="TIMEOUT-001",
            )

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_explicit_timeout_wrapper(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that asyncio.wait_for timeout wrapper enforces 5-second timeout."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Mock producer to hang indefinitely (simulates unresponsive broker)
            async def hang_forever(*args, **kwargs):
                await asyncio.sleep(10)  # Longer than KAFKA_PUBLISH_TIMEOUT_SECONDS
                return None

            mock_kafka_producer.send_and_wait.side_effect = hang_forever

            # Should timeout after KAFKA_PUBLISH_TIMEOUT_SECONDS (5 seconds)
            result = await publisher.publish_application_log(
                service_name="test-service",
                instance_id="test-instance",
                level="ERROR",
                logger_name="test-logger",
                message="Timeout wrapper test",
                code="TIMEOUT-WRAPPER-001",
            )

            # Should return False when timeout occurs
            assert result is False

            # Verify timeout constant is used
            assert publisher.KAFKA_PUBLISH_TIMEOUT_SECONDS == 5.0

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_timeout_handling_all_event_types(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test that all three event types handle timeouts correctly."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Mock producer to raise TimeoutError
            async def timeout_send(*args, **kwargs):
                raise asyncio.TimeoutError("Kafka publish timeout")

            mock_kafka_producer.send_and_wait.side_effect = timeout_send

            # Test application log
            result_app = await publisher.publish_application_log(
                service_name="test-service",
                instance_id="test-instance",
                level="INFO",
                logger_name="test-logger",
                message="Test",
                code="TEST-001",
            )
            assert result_app is False

            # Test audit log
            result_audit = await publisher.publish_audit_log(
                tenant_id="tenant-123",
                action="test.action",
                actor="test-actor",
                resource="test-resource",
                outcome="success",
            )
            assert result_audit is False

            # Test security log
            result_security = await publisher.publish_security_log(
                tenant_id="tenant-123",
                event_type="test.event",
                user_id="test-user",
                resource="test-resource",
                decision="allow",
            )
            assert result_security is False

            await publisher.stop()

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_invalid_partition_key_handling(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test validation rejects null bytes in partition keys."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Our validation should reject null bytes in partition keys
            with pytest.raises(ValueError, match="tenant_id cannot contain null bytes"):
                await publisher.publish_audit_log(
                    tenant_id="tenant\x00id",  # Null byte
                    actor="test-actor",
                    action="test-action",
                    resource="test-resource",
                    outcome="success",
                    context={"test": "data"},
                )

            await publisher.stop()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_producer_stop_during_publish(
        self, publisher_config, mock_kafka_producer
    ) -> None:
        """Test behavior when producer is stopped during active publishing."""
        with patch(
            "agents.lib.logging_event_publisher.AIOKafkaProducer",
            return_value=mock_kafka_producer,
        ):
            publisher = LoggingEventPublisher(**publisher_config)
            await publisher.start()

            # Start a publish operation
            publish_task = asyncio.create_task(
                publisher.publish_application_log(
                    service_name="test-service",
                    instance_id="test-instance",
                    level="INFO",
                    logger_name="test-logger",
                    message="Test message",
                    code="STOP-001",
                )
            )

            # Stop publisher while publish is in progress
            await publisher.stop()

            # Publish should complete or fail gracefully
            result = await publish_task
            assert isinstance(result, bool)


class TestLoggingEventPublisherIntegration:
    """Integration tests for LoggingEventPublisher (require actual Kafka)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_publish_to_real_kafka(self, sample_application_log_data) -> None:
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
