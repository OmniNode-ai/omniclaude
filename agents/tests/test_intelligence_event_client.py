#!/usr/bin/env python3
"""
Comprehensive Test Suite for IntelligenceEventClient

Tests event-based intelligence integration with Kafka, including:
- Client lifecycle management (start/stop)
- Request-response pattern with correlation tracking
- Pattern discovery and code analysis operations
- Timeout handling and graceful degradation
- Error handling and edge cases
- Background consumer task management

Coverage Target: >90%
Reference: EVENT_INTELLIGENCE_INTEGRATION_PLAN.md Section 2.1
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from aiokafka.errors import KafkaError

from agents.lib.intelligence_event_client import (
    IntelligenceEventClient,
    IntelligenceEventClientContext,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_config():
    """Test configuration for event client."""
    return {
        "bootstrap_servers": "localhost:29092",
        "enable_intelligence": True,
        "request_timeout_ms": 5000,
    }


@pytest.fixture
def mock_producer():
    """Mock AIOKafkaProducer with all required methods."""
    producer = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.send_and_wait = AsyncMock()
    return producer


@pytest.fixture
def mock_consumer():
    """Mock AIOKafkaConsumer with async iteration support."""
    consumer = AsyncMock()
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()

    # Mock async iteration for background consumer task
    async def mock_aiter():
        # Empty generator that can be controlled per test
        if False:
            yield

    consumer.__aiter__ = mock_aiter
    return consumer


@pytest.fixture
async def event_client(test_config, mock_producer, mock_consumer):
    """Initialized event client with mocked Kafka infrastructure."""
    with (
        patch(
            "agents.lib.intelligence_event_client.AIOKafkaProducer",
            return_value=mock_producer,
        ),
        patch(
            "agents.lib.intelligence_event_client.AIOKafkaConsumer",
            return_value=mock_consumer,
        ),
    ):
        client = IntelligenceEventClient(
            bootstrap_servers=test_config["bootstrap_servers"],
            enable_intelligence=test_config["enable_intelligence"],
            request_timeout_ms=test_config["request_timeout_ms"],
        )
        await client.start()
        yield client
        await client.stop()


@pytest.fixture
def sample_correlation_id():
    """Sample correlation ID for testing."""
    return str(uuid4())


@pytest.fixture
def sample_completed_response(sample_correlation_id):
    """Sample completed response event."""
    return {
        "event_id": str(uuid4()),
        "event_type": "CODE_ANALYSIS_COMPLETED",
        "correlation_id": sample_correlation_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "omniarchon-intelligence",
        "payload": {
            "source_path": "node_*_effect.py",
            "patterns": [
                {
                    "file_path": "node_db_effect.py",
                    "confidence": 0.95,
                    "pattern_type": "effect_node",
                    "code_snippet": "async def execute_effect(self, contract: ModelContractEffect):",
                },
                {
                    "file_path": "node_api_effect.py",
                    "confidence": 0.88,
                    "pattern_type": "effect_node",
                    "code_snippet": "async def execute_effect(self, contract: ModelContractEffect):",
                },
            ],
            "metadata": {
                "total_files_scanned": 150,
                "processing_time_ms": 450,
            },
        },
    }


@pytest.fixture
def sample_failed_response(sample_correlation_id):
    """Sample failed response event."""
    return {
        "event_id": str(uuid4()),
        "event_type": "CODE_ANALYSIS_FAILED",
        "correlation_id": sample_correlation_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "omniarchon-intelligence",
        "payload": {
            "error_code": "PATTERN_NOT_FOUND",
            "error_message": "No patterns found matching criteria",
            "details": {
                "source_path": "node_*_effect.py",
                "scanned_directories": ["/src/nodes"],
            },
        },
    }


# =============================================================================
# Test: Client Initialization and Lifecycle
# =============================================================================


class TestIntelligenceEventClientLifecycle:
    """Test client initialization, startup, and shutdown."""

    def test_init_sets_configuration(self, test_config):
        """Test initialization sets configuration values correctly."""
        client = IntelligenceEventClient(
            bootstrap_servers=test_config["bootstrap_servers"],
            enable_intelligence=test_config["enable_intelligence"],
            request_timeout_ms=test_config["request_timeout_ms"],
        )

        assert client.bootstrap_servers == test_config["bootstrap_servers"]
        assert client.enable_intelligence is True
        assert client.request_timeout_ms == 5000

    def test_init_generates_consumer_group_id(self):
        """Test initialization generates unique consumer group ID."""
        client1 = IntelligenceEventClient()
        client2 = IntelligenceEventClient()

        assert client1.consumer_group_id.startswith("omniclaude-intelligence-")
        assert client2.consumer_group_id.startswith("omniclaude-intelligence-")
        assert client1.consumer_group_id != client2.consumer_group_id

    def test_init_accepts_custom_consumer_group_id(self):
        """Test initialization accepts custom consumer group ID."""
        custom_id = "custom-consumer-group"
        client = IntelligenceEventClient(consumer_group_id=custom_id)

        assert client.consumer_group_id == custom_id

    @pytest.mark.asyncio
    async def test_start_initializes_producer_consumer(
        self, mock_producer, mock_consumer
    ):
        """Test start() initializes Kafka producer and consumer."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
        ):
            client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
            await client.start()

            # Verify producer started
            mock_producer.start.assert_called_once()

            # Verify consumer started
            mock_consumer.start.assert_called_once()

            # Verify started flag set
            assert client._started is True

            await client.stop()

    @pytest.mark.asyncio
    async def test_start_creates_background_consumer_task(
        self, mock_producer, mock_consumer
    ):
        """Test start() creates background consumer task."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
            patch("asyncio.create_task") as mock_create_task,
        ):
            client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
            await client.start()

            # Verify background task created
            mock_create_task.assert_called_once()

            await client.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, mock_producer, mock_consumer):
        """Test start() can be called multiple times safely."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
        ):
            client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

            await client.start()
            await client.start()  # Second call should be no-op

            # Should only start once
            assert mock_producer.start.call_count == 1
            assert mock_consumer.start.call_count == 1

            await client.stop()

    @pytest.mark.asyncio
    async def test_start_skips_when_intelligence_disabled(self):
        """Test start() skips initialization when intelligence disabled."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer"
            ) as MockProducer,
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer"
            ) as MockConsumer,
        ):
            client = IntelligenceEventClient(
                bootstrap_servers="localhost:29092",
                enable_intelligence=False,
            )
            await client.start()

            # Should not create producer/consumer
            MockProducer.assert_not_called()
            MockConsumer.assert_not_called()
            assert client._started is False

    @pytest.mark.asyncio
    async def test_stop_closes_connections(
        self, event_client, mock_producer, mock_consumer
    ):
        """Test stop() gracefully closes Kafka connections."""
        await event_client.stop()

        # Verify producer stopped
        mock_producer.stop.assert_called_once()

        # Verify consumer stopped
        mock_consumer.stop.assert_called_once()

        # Verify started flag cleared
        assert event_client._started is False

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_requests(
        self, mock_producer, mock_consumer, sample_correlation_id
    ):
        """Test stop() cancels pending requests with exception."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
        ):
            client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
            await client.start()

            # Add a pending request
            future = asyncio.Future()
            client._pending_requests[sample_correlation_id] = future

            await client.stop()

            # Verify future was cancelled with exception
            assert future.done()
            with pytest.raises(RuntimeError, match="Client stopped"):
                future.result()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, event_client, mock_producer, mock_consumer):
        """Test stop() can be called multiple times safely."""
        await event_client.stop()
        await event_client.stop()  # Second call should be no-op

        # Should only stop once
        assert mock_producer.stop.call_count == 1
        assert mock_consumer.stop.call_count == 1


# =============================================================================
# Test: Request-Response Pattern
# =============================================================================


class TestRequestResponsePattern:
    """Test request-response pattern with correlation tracking."""

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_publishes_request(
        self, event_client, mock_producer, sample_correlation_id
    ):
        """Test request_pattern_discovery publishes correct event."""
        # Mock response to prevent timeout
        future = asyncio.Future()
        future.set_result([])
        event_client._pending_requests[sample_correlation_id] = future

        with patch.object(event_client, "_publish_and_wait", return_value=[]):
            await event_client.request_pattern_discovery(
                source_path="node_*_effect.py",
                language="python",
                timeout_ms=5000,
            )

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_creates_correlation_id(self, event_client):
        """Test request creates unique correlation ID."""
        with patch.object(
            event_client, "_publish_and_wait", return_value=[]
        ) as mock_publish:
            await event_client.request_pattern_discovery(
                source_path="test.py",
                language="python",
            )

            # Verify correlation_id was created
            call_args = mock_publish.call_args
            correlation_id = call_args[1]["correlation_id"]
            assert UUID(correlation_id)  # Valid UUID format

    @pytest.mark.asyncio
    async def test_request_code_analysis_with_content(self, event_client):
        """Test code analysis request with inline content."""
        with patch.object(
            event_client, "_publish_and_wait", return_value={}
        ) as mock_publish:
            await event_client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                options={"analyze_complexity": True},
            )

            # Verify payload includes content
            call_args = mock_publish.call_args
            payload = call_args[1]["payload"]
            assert payload["payload"]["content"] == "def hello(): pass"
            assert payload["payload"]["language"] == "python"

    @pytest.mark.asyncio
    async def test_request_code_analysis_without_content(self, event_client):
        """Test code analysis request without inline content."""
        with patch.object(
            event_client, "_publish_and_wait", return_value={}
        ) as mock_publish:
            await event_client.request_code_analysis(
                content=None,
                source_path="test.py",
                language="python",
            )

            # Verify payload has None content
            call_args = mock_publish.call_args
            payload = call_args[1]["payload"]
            assert payload["payload"]["content"] is None

    @pytest.mark.asyncio
    async def test_request_uses_custom_timeout(self, event_client):
        """Test request uses custom timeout when provided."""
        custom_timeout = 10000

        with patch.object(
            event_client, "_publish_and_wait", return_value=[]
        ) as mock_publish:
            await event_client.request_pattern_discovery(
                source_path="test.py",
                language="python",
                timeout_ms=custom_timeout,
            )

            # Verify timeout passed through
            call_args = mock_publish.call_args
            assert call_args[1]["timeout_ms"] == custom_timeout


# =============================================================================
# Test: Timeout and Error Handling
# =============================================================================


class TestTimeoutAndErrorHandling:
    """Test timeout handling and error scenarios."""

    @pytest.mark.asyncio
    async def test_request_raises_error_when_client_not_started(self):
        """Test requests fail when client not started."""
        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

        with pytest.raises(RuntimeError, match="Client not started"):
            await client.request_pattern_discovery(
                source_path="test.py",
                language="python",
            )

    @pytest.mark.asyncio
    async def test_request_timeout_raises_timeout_error(self, event_client):
        """Test request timeout raises TimeoutError."""
        # Mock publish_and_wait to raise asyncio.TimeoutError
        with patch.object(
            event_client, "_publish_and_wait", side_effect=asyncio.TimeoutError
        ):
            with pytest.raises(TimeoutError, match="Request timeout"):
                await event_client.request_pattern_discovery(
                    source_path="test.py",
                    language="python",
                    timeout_ms=100,
                )

    @pytest.mark.asyncio
    async def test_start_failure_raises_kafka_error(self):
        """Test start() raises KafkaError on connection failure."""
        with patch(
            "agents.lib.intelligence_event_client.AIOKafkaProducer"
        ) as MockProducer:
            mock_producer = AsyncMock()
            mock_producer.start.side_effect = Exception("Connection refused")
            MockProducer.return_value = mock_producer

            client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

            with pytest.raises(KafkaError, match="Failed to start Kafka client"):
                await client.start()

    @pytest.mark.asyncio
    async def test_kafka_send_error_propagates(
        self, event_client, mock_producer, sample_correlation_id
    ):
        """Test Kafka send errors propagate to caller."""
        mock_producer.send_and_wait.side_effect = KafkaError("Send failed")

        with pytest.raises(KafkaError, match="Send failed"):
            await event_client.request_pattern_discovery(
                source_path="test.py",
                language="python",
            )


# =============================================================================
# Test: Background Consumer Task
# =============================================================================


class TestBackgroundConsumerTask:
    """Test background consumer task for response processing."""

    @pytest.mark.asyncio
    async def test_consume_responses_processes_completed_event(
        self, sample_correlation_id, sample_completed_response
    ):
        """Test consumer task processes completed events."""
        mock_consumer = AsyncMock()
        mock_msg = Mock()
        mock_msg.value = sample_completed_response
        mock_msg.topic = IntelligenceEventClient.TOPIC_COMPLETED

        # Create async generator for consumer
        async def mock_aiter():
            yield mock_msg

        mock_consumer.__aiter__ = mock_aiter

        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
        client._consumer = mock_consumer

        # Create pending request
        future = asyncio.Future()
        client._pending_requests[sample_correlation_id] = future

        # Start consumer task
        task = asyncio.create_task(client._consume_responses())

        # Wait for future to be resolved
        await asyncio.sleep(0.1)

        # Verify future was resolved with payload
        assert future.done()
        result = future.result()
        assert "patterns" in result
        assert len(result["patterns"]) == 2

        task.cancel()

    @pytest.mark.asyncio
    async def test_consume_responses_processes_failed_event(
        self, sample_correlation_id, sample_failed_response
    ):
        """Test consumer task processes failed events."""
        mock_consumer = AsyncMock()
        mock_msg = Mock()
        mock_msg.value = sample_failed_response
        mock_msg.topic = IntelligenceEventClient.TOPIC_FAILED

        # Create async generator for consumer
        async def mock_aiter():
            yield mock_msg

        mock_consumer.__aiter__ = mock_aiter

        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
        client._consumer = mock_consumer

        # Create pending request
        future = asyncio.Future()
        client._pending_requests[sample_correlation_id] = future

        # Start consumer task
        task = asyncio.create_task(client._consume_responses())

        # Wait for future to be resolved
        await asyncio.sleep(0.1)

        # Verify future was resolved with exception
        assert future.done()
        with pytest.raises(KafkaError, match="PATTERN_NOT_FOUND"):
            future.result()

        task.cancel()

    @pytest.mark.asyncio
    async def test_consume_responses_skips_missing_correlation_id(self):
        """Test consumer task skips events without correlation_id."""
        mock_consumer = AsyncMock()
        mock_msg = Mock()
        mock_msg.value = {
            "event_type": "CODE_ANALYSIS_COMPLETED"
        }  # Missing correlation_id

        # Create async generator for consumer
        async def mock_aiter():
            yield mock_msg

        mock_consumer.__aiter__ = mock_aiter

        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
        client._consumer = mock_consumer

        # Start consumer task
        task = asyncio.create_task(client._consume_responses())

        # Wait briefly
        await asyncio.sleep(0.1)

        # No errors should occur
        task.cancel()

    @pytest.mark.asyncio
    async def test_consume_responses_handles_malformed_message(self):
        """Test consumer task handles malformed messages gracefully."""
        mock_consumer = AsyncMock()
        mock_msg = Mock()
        mock_msg.value = None  # Malformed

        # Create async generator for consumer
        async def mock_aiter():
            yield mock_msg

        mock_consumer.__aiter__ = mock_aiter

        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
        client._consumer = mock_consumer

        # Start consumer task
        task = asyncio.create_task(client._consume_responses())

        # Wait briefly
        await asyncio.sleep(0.1)

        # Task should continue despite error
        assert not task.done()

        task.cancel()


# =============================================================================
# Test: Health Check
# =============================================================================


class TestHealthCheck:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_started(self):
        """Test health check returns False when client not started."""
        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")
        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_intelligence_disabled(self):
        """Test health check returns False when intelligence disabled."""
        client = IntelligenceEventClient(
            bootstrap_servers="localhost:29092",
            enable_intelligence=False,
        )
        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_started(
        self, event_client, mock_producer
    ):
        """Test health check returns True when client started."""
        assert await event_client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_producer_none(self, event_client):
        """Test health check returns False when producer is None."""
        event_client._producer = None
        assert await event_client.health_check() is False


# =============================================================================
# Test: Context Manager
# =============================================================================


class TestContextManager:
    """Test IntelligenceEventClientContext context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_starts_and_stops_client(
        self, mock_producer, mock_consumer
    ):
        """Test context manager handles client lifecycle."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
        ):
            async with IntelligenceEventClientContext(
                bootstrap_servers="localhost:29092"
            ) as client:
                assert client._started is True

            # Verify client was stopped
            assert client._started is False

    @pytest.mark.asyncio
    async def test_context_manager_passes_configuration(
        self, mock_producer, mock_consumer
    ):
        """Test context manager passes configuration to client."""
        with (
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaProducer",
                return_value=mock_producer,
            ),
            patch(
                "agents.lib.intelligence_event_client.AIOKafkaConsumer",
                return_value=mock_consumer,
            ),
        ):
            async with IntelligenceEventClientContext(
                bootstrap_servers="custom:9092",
                enable_intelligence=False,
                request_timeout_ms=10000,
            ) as client:
                assert client.bootstrap_servers == "custom:9092"
                assert client.enable_intelligence is False
                assert client.request_timeout_ms == 10000


# =============================================================================
# Test: Payload Creation
# =============================================================================


class TestPayloadCreation:
    """Test request payload creation."""

    def test_create_request_payload_structure(self, sample_correlation_id):
        """Test request payload has correct structure."""
        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

        payload = client._create_request_payload(
            correlation_id=sample_correlation_id,
            content="def test(): pass",
            source_path="test.py",
            language="python",
            options={"include_metrics": True},
        )

        assert payload["correlation_id"] == sample_correlation_id
        assert payload["event_type"] == "CODE_ANALYSIS_REQUESTED"
        assert "event_id" in payload
        assert "timestamp" in payload
        assert payload["service"] == "omniclaude"

        # Check nested payload
        nested = payload["payload"]
        assert nested["source_path"] == "test.py"
        assert nested["content"] == "def test(): pass"
        assert nested["language"] == "python"
        assert nested["operation_type"] == "PATTERN_EXTRACTION"  # Default
        assert nested["options"]["include_metrics"] is True

    def test_create_request_payload_with_operation_type(self, sample_correlation_id):
        """Test request payload respects custom operation type."""
        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

        payload = client._create_request_payload(
            correlation_id=sample_correlation_id,
            content=None,
            source_path="test.py",
            language="python",
            options={"operation_type": "QUALITY_ASSESSMENT"},
        )

        assert payload["payload"]["operation_type"] == "QUALITY_ASSESSMENT"

    def test_create_request_payload_timestamps_iso_format(self, sample_correlation_id):
        """Test request payload timestamp is ISO 8601 format."""
        client = IntelligenceEventClient(bootstrap_servers="localhost:29092")

        payload = client._create_request_payload(
            correlation_id=sample_correlation_id,
            content=None,
            source_path="test.py",
            language="python",
            options={},
        )

        # Verify timestamp is valid ISO 8601
        timestamp = payload["timestamp"]
        assert isinstance(timestamp, str)
        # Should be parseable back to datetime
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


# =============================================================================
# Test: Edge Cases and Boundary Conditions
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_patterns_response(self, event_client):
        """Test handling empty patterns in response."""
        with patch.object(event_client, "_publish_and_wait", return_value=[]):
            patterns = await event_client.request_pattern_discovery(
                source_path="nonexistent.py",
                language="python",
            )

            assert patterns == []

    @pytest.mark.asyncio
    async def test_very_large_response_payload(self, event_client):
        """Test handling very large response payloads."""
        large_patterns = [
            {"file": f"file_{i}.py", "content": "x" * 1000} for i in range(100)
        ]

        with patch.object(
            event_client, "_publish_and_wait", return_value=large_patterns
        ):
            result = await event_client.request_pattern_discovery(
                source_path="*.py",
                language="python",
            )

            assert len(result) == 100

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_same_client(self, event_client):
        """Test multiple concurrent requests through same client."""

        async def mock_publish_and_wait(correlation_id, payload, timeout_ms):
            await asyncio.sleep(0.05)  # Simulate processing
            return []

        with patch.object(
            event_client, "_publish_and_wait", side_effect=mock_publish_and_wait
        ):
            tasks = [
                event_client.request_pattern_discovery(
                    source_path=f"test_{i}.py",
                    language="python",
                )
                for i in range(5)
            ]

            results = await asyncio.gather(*tasks)
            assert len(results) == 5

    def test_topic_names_are_onex_compliant(self):
        """Test topic names follow ONEX event bus naming convention."""
        assert IntelligenceEventClient.TOPIC_REQUEST.startswith(
            "dev.archon-intelligence"
        )
        assert IntelligenceEventClient.TOPIC_COMPLETED.startswith(
            "dev.archon-intelligence"
        )
        assert IntelligenceEventClient.TOPIC_FAILED.startswith(
            "dev.archon-intelligence"
        )

        # Check versioning
        assert ".v1" in IntelligenceEventClient.TOPIC_REQUEST
        assert ".v1" in IntelligenceEventClient.TOPIC_COMPLETED
        assert ".v1" in IntelligenceEventClient.TOPIC_FAILED
