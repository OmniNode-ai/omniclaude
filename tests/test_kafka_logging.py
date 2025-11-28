#!/usr/bin/env python3
"""
Unit Tests for Kafka-Based Agent Action Logging

Tests the Kafka logging skill with mocked Kafka producer for fast, isolated testing.

Coverage:
- Event serialization/deserialization
- Debug mode filtering
- Correlation ID generation
- Error handling
- Topic/partition routing
"""

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


# Add skills path (updated for claude/ consolidation)
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent
        / "claude"
        / "skills"
        / "agent-tracking"
        / "log-agent-action"
    ),
)
sys.path.insert(0, str(Path(__file__).parent.parent / "claude" / "skills" / "_shared"))
sys.path.insert(0, str(Path(__file__).parent.parent / "shared_lib"))


class TestKafkaLoggingUnit:
    """Unit tests for Kafka logging functionality."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Setup test environment."""
        # Import after path setup
        import execute_kafka

        self.execute_kafka = execute_kafka

        # Import kafka_publisher to reset singleton
        sys.path.insert(0, str(Path(__file__).parent.parent / "shared_lib"))
        import kafka_publisher
        from kafka_publisher import close_kafka_producer

        self.kafka_publisher = kafka_publisher

        # Reset singleton before each test
        kafka_publisher._producer_instance = None
        kafka_publisher.KafkaProducer = None

        yield

        # Cleanup after test
        kafka_publisher._producer_instance = None
        kafka_publisher.KafkaProducer = None

    @pytest.fixture
    def mock_kafka_producer(self):
        """Mock Kafka producer for testing."""
        with patch("kafka.KafkaProducer") as mock_producer_class:
            mock_instance = MagicMock()
            mock_producer_class.return_value = mock_instance

            # Mock successful send
            mock_future = MagicMock()
            mock_future.get.return_value = MagicMock(
                topic="agent-actions", partition=0, offset=42
            )
            mock_instance.send.return_value = mock_future

            yield mock_producer_class, mock_instance

    def test_debug_mode_enabled(self, mock_kafka_producer):
        """Test logging works when DEBUG mode is enabled."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details='{"key": "value"}',
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=100,
            )

            result = self.execute_kafka.log_agent_action_kafka(args)

            assert result == 0
            mock_producer_class, mock_instance = mock_kafka_producer
            assert mock_instance.send.called

    def test_debug_mode_disabled_skips_logging(self):
        """Test logging is skipped when DEBUG mode is disabled."""
        with patch.dict(os.environ, {"DEBUG": "false"}, clear=True):
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details=None,
                correlation_id=None,
                debug_mode=False,
            )

            with patch("builtins.print") as mock_print:
                result = self.execute_kafka.log_agent_action_kafka(args)

                assert result == 0
                # Check skipped message was printed
                printed_output = mock_print.call_args[0][0]
                parsed_output = json.loads(printed_output)
                assert parsed_output["skipped"] is True
                assert parsed_output["reason"] == "debug_mode_disabled"

    def test_force_debug_mode_overrides_env(self, mock_kafka_producer):
        """Test --debug-mode flag overrides DEBUG env var."""
        with patch.dict(os.environ, {"DEBUG": "false"}, clear=True):
            args = Mock(
                agent="test-agent",
                action_type="decision",
                action_name="route_selection",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=True,  # Force debug
                duration_ms=None,
            )

            result = self.execute_kafka.log_agent_action_kafka(args)

            assert result == 0
            mock_producer_class, mock_instance = mock_kafka_producer
            assert mock_instance.send.called

    def test_correlation_id_generation(self, mock_kafka_producer):
        """Test correlation ID is auto-generated if not provided."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="read_file",
                details=None,
                correlation_id=None,  # Not provided
                debug_mode=False,
                duration_ms=None,
            )

            with patch("builtins.print") as mock_print:
                result = self.execute_kafka.log_agent_action_kafka(args)

                assert result == 0
                # Verify correlation_id was generated
                printed_output = mock_print.call_args[0][0]
                parsed_output = json.loads(printed_output)
                assert "correlation_id" in parsed_output
                assert parsed_output["correlation_id"] is not None
                # Verify it's a valid UUID
                uuid.UUID(parsed_output["correlation_id"])

    def test_event_serialization(self, mock_kafka_producer):
        """Test event is properly serialized to JSON."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            correlation_id = str(uuid.uuid4())
            args = Mock(
                agent="test-agent",
                action_type="success",
                action_name="task_completed",
                details='{"result": "success", "count": 42}',
                correlation_id=correlation_id,
                debug_mode=False,
                duration_ms=250,
            )

            self.execute_kafka.log_agent_action_kafka(args)

            mock_producer_class, mock_instance = mock_kafka_producer
            send_call = mock_instance.send.call_args

            # Verify topic
            assert send_call[0][0] == "agent-actions"

            # Verify event structure
            event = send_call[1]["value"]
            assert event["correlation_id"] == correlation_id
            assert event["agent_name"] == "test-agent"
            assert event["action_type"] == "success"
            assert event["action_name"] == "task_completed"
            assert event["action_details"]["result"] == "success"
            assert event["action_details"]["count"] == 42
            assert event["duration_ms"] == 250
            assert event["debug_mode"] is True
            assert "timestamp" in event

    def test_partition_key_uses_correlation_id(self, mock_kafka_producer):
        """Test partition key is set to correlation_id for ordering."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            correlation_id = str(uuid.uuid4())
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="grep_search",
                details=None,
                correlation_id=correlation_id,
                debug_mode=False,
                duration_ms=None,
            )

            self.execute_kafka.log_agent_action_kafka(args)

            mock_producer_class, mock_instance = mock_kafka_producer
            send_call = mock_instance.send.call_args

            # Verify partition key
            partition_key = send_call[1]["key"]
            assert partition_key == correlation_id.encode("utf-8")

    def test_kafka_publish_timeout(self, mock_kafka_producer):
        """Test timeout handling for Kafka publish."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            mock_producer_class, mock_instance = mock_kafka_producer

            # Simulate timeout
            mock_future = MagicMock()
            mock_future.get.side_effect = Exception("Timeout waiting for message")
            mock_instance.send.return_value = mock_future

            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=None,
            )

            with patch("sys.stderr"):
                result = self.execute_kafka.log_agent_action_kafka(args)

                # Should return error code
                assert result == 1

    def test_kafka_connection_failure(self):
        """Test graceful handling of Kafka connection failure."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            with patch("kafka.KafkaProducer") as mock_producer_class:
                # Simulate connection failure
                mock_producer_class.side_effect = Exception("Cannot connect to Kafka")

                args = Mock(
                    agent="test-agent",
                    action_type="error",
                    action_name="connection_failed",
                    details='{"error": "timeout"}',
                    correlation_id=str(uuid.uuid4()),
                    debug_mode=False,
                    duration_ms=None,
                )

                with patch("sys.stderr"):
                    result = self.execute_kafka.log_agent_action_kafka(args)

                    # Should return error code
                    assert result == 1

    def test_invalid_json_details_handling(self, mock_kafka_producer):
        """Test handling of invalid JSON in details field."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details='{"invalid": json}',  # Invalid JSON
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=None,
            )

            # Should handle gracefully by using empty dict
            result = self.execute_kafka.log_agent_action_kafka(args)

            assert result == 0
            mock_producer_class, mock_instance = mock_kafka_producer
            send_call = mock_instance.send.call_args
            event = send_call[1]["value"]
            # Should have empty details
            assert event["action_details"] == {}

    def test_action_type_validation(self, mock_kafka_producer):
        """Test all valid action types are accepted."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            valid_types = ["tool_call", "decision", "error", "success"]

            for action_type in valid_types:
                args = Mock(
                    agent="test-agent",
                    action_type=action_type,
                    action_name=f"test_{action_type}",
                    details=None,
                    correlation_id=str(uuid.uuid4()),
                    debug_mode=False,
                    duration_ms=None,
                )

                result = self.execute_kafka.log_agent_action_kafka(args)
                assert result == 0

    def test_producer_reuse(self, mock_kafka_producer):
        """Test Kafka producer is reused across multiple calls (singleton)."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            mock_producer_class, mock_instance = mock_kafka_producer

            # First call
            args1 = Mock(
                agent="test-agent-1",
                action_type="tool_call",
                action_name="action_1",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=None,
            )
            self.execute_kafka.log_agent_action_kafka(args1)

            # Second call
            args2 = Mock(
                agent="test-agent-2",
                action_type="decision",
                action_name="action_2",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=None,
            )
            self.execute_kafka.log_agent_action_kafka(args2)

            # Producer should only be created once (singleton pattern)
            assert mock_producer_class.call_count == 1
            # But send should be called twice (once per log call)
            assert mock_instance.send.call_count == 2

    def test_duration_ms_optional(self, mock_kafka_producer):
        """Test duration_ms is optional and handled correctly."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            # Without duration_ms
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
            )
            # Remove duration_ms attribute
            if hasattr(args, "duration_ms"):
                delattr(args, "duration_ms")

            result = self.execute_kafka.log_agent_action_kafka(args)

            assert result == 0
            mock_producer_class, mock_instance = mock_kafka_producer
            send_call = mock_instance.send.call_args
            event = send_call[1]["value"]
            # duration_ms should be None
            assert event["duration_ms"] is None

    def test_timestamp_format(self, mock_kafka_producer):
        """Test timestamp is in ISO 8601 format."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            args = Mock(
                agent="test-agent",
                action_type="tool_call",
                action_name="test_action",
                details=None,
                correlation_id=str(uuid.uuid4()),
                debug_mode=False,
                duration_ms=None,
            )

            self.execute_kafka.log_agent_action_kafka(args)

            mock_producer_class, mock_instance = mock_kafka_producer
            send_call = mock_instance.send.call_args
            event = send_call[1]["value"]

            # Verify timestamp is valid ISO 8601
            timestamp = event["timestamp"]
            assert "T" in timestamp  # ISO 8601 format
            # Should be parseable as datetime
            from datetime import datetime

            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class TestKafkaProducerConfiguration:
    """Test Kafka producer configuration settings."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Setup test environment."""
        import execute_kafka

        self.execute_kafka = execute_kafka

        # Import kafka_publisher to reset singleton
        sys.path.insert(0, str(Path(__file__).parent.parent / "shared_lib"))
        import kafka_publisher

        self.kafka_publisher = kafka_publisher

        # Reset singleton before each test
        kafka_publisher._producer_instance = None
        kafka_publisher.KafkaProducer = None

        yield

        # Cleanup after test
        kafka_publisher._producer_instance = None
        kafka_publisher.KafkaProducer = None

    def test_producer_compression_enabled(self):
        """Test Kafka producer uses gzip compression."""
        with patch("kafka.KafkaProducer") as mock_producer_class:
            # Force reimport by resetting singleton
            self.kafka_publisher._producer_instance = None
            self.kafka_publisher.KafkaProducer = None

            self.kafka_publisher.get_kafka_producer()

            # Verify producer was created with compression
            call_kwargs = mock_producer_class.call_args[1]
            assert call_kwargs["compression_type"] == "gzip"

    def test_producer_batching_configured(self):
        """Test Kafka producer batching is configured."""
        with patch("kafka.KafkaProducer") as mock_producer_class:
            # Force reimport by resetting singleton
            self.kafka_publisher._producer_instance = None
            self.kafka_publisher.KafkaProducer = None

            self.kafka_publisher.get_kafka_producer()

            call_kwargs = mock_producer_class.call_args[1]
            assert "linger_ms" in call_kwargs
            assert call_kwargs["linger_ms"] == 10  # 10ms batching
            assert "batch_size" in call_kwargs
            assert call_kwargs["batch_size"] == 16384  # 16KB batches

    def test_producer_reliability_settings(self):
        """Test Kafka producer reliability settings."""
        with patch("kafka.KafkaProducer") as mock_producer_class:
            # Force reimport by resetting singleton
            self.kafka_publisher._producer_instance = None
            self.kafka_publisher.KafkaProducer = None

            self.kafka_publisher.get_kafka_producer()

            call_kwargs = mock_producer_class.call_args[1]
            assert call_kwargs["acks"] == 1  # Leader acknowledgment
            assert call_kwargs["retries"] == 3
            assert call_kwargs["max_in_flight_requests_per_connection"] == 5

    def test_custom_kafka_brokers_env_var(self):
        """Test custom Kafka brokers can be set via environment variable."""
        # Clear all Kafka-related env vars and set only KAFKA_BROKERS
        env_vars = {
            "KAFKA_BOOTSTRAP_SERVERS": "",
            "KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS": "",
            "KAFKA_BROKERS": "kafka1:9092,kafka2:9092",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch("kafka.KafkaProducer") as mock_producer_class:
                # Force reimport by resetting singleton
                self.kafka_publisher._producer_instance = None
                self.kafka_publisher.KafkaProducer = None

                self.kafka_publisher.get_kafka_producer()

                call_kwargs = mock_producer_class.call_args[1]
                assert call_kwargs["bootstrap_servers"] == [
                    "kafka1:9092",
                    "kafka2:9092",
                ]

    def test_default_kafka_broker(self):
        """Test default Kafka broker is 192.168.86.200:9092."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("kafka.KafkaProducer") as mock_producer_class:
                # Force reimport by resetting singleton
                self.kafka_publisher._producer_instance = None
                self.kafka_publisher.KafkaProducer = None

                self.kafka_publisher.get_kafka_producer()

                call_kwargs = mock_producer_class.call_args[1]
                assert call_kwargs["bootstrap_servers"] == ["192.168.86.200:9092"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
