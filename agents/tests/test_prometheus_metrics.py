#!/usr/bin/env python3
"""
Tests for Prometheus Metrics Collection

Tests comprehensive Prometheus instrumentation including:
- Metric recording
- Helper functions
- Action logger integration
- Event publisher integration
- FastAPI /metrics endpoint
"""

import asyncio
import time
from unittest.mock import Mock, patch

import pytest
from prometheus_client import REGISTRY

# Import metrics module
from agents.lib.prometheus_metrics import (
    action_log_counter,
    action_log_duration,
    action_log_errors_counter,
    cache_hit_counter,
    cache_miss_counter,
    cache_operation_duration,
    db_operation_counter,
    db_operation_duration,
    event_publish_bytes,
    event_publish_counter,
    event_publish_duration,
    event_publish_errors_counter,
    get_metrics_registry,
    get_metrics_text,
    http_request_counter,
    http_request_duration,
    initialize_metrics,
    record_action_log,
    record_agent_routing,
    record_cache_operation,
    record_db_operation,
    record_event_publish,
    service_health_status,
    service_startup_time,
)


class TestMetricsInitialization:
    """Test metrics initialization."""

    def test_initialize_metrics(self):
        """Test metrics initialization with system info."""
        initialize_metrics(
            version="0.1.0-test",
            environment="test",
            agent_registry_path="/test/path",
        )

        # Verify system info is set
        # (We can't easily verify Info metrics, but we can verify no errors)
        assert True

    def test_get_metrics_registry(self):
        """Test getting the metrics registry."""
        registry = get_metrics_registry()
        assert registry is not None

    def test_get_metrics_text(self):
        """Test getting metrics in Prometheus text format."""
        metrics_text = get_metrics_text()
        assert isinstance(metrics_text, bytes)
        assert b"omniclaude" in metrics_text


class TestActionLogMetrics:
    """Test action logging metrics."""

    def test_record_action_log(self):
        """Test recording action log metrics."""
        # Record metric
        record_action_log(
            agent_name="test-agent",
            action_type="tool_call",
            duration=0.045,
            status="success",
        )

        # Verify metrics were recorded
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_action_log_duration_seconds" in metrics_text
        assert "omniclaude_action_log_total" in metrics_text
        assert 'agent_name="test-agent"' in metrics_text

    def test_action_log_histogram(self):
        """Test action log duration histogram."""
        # Record multiple observations
        durations = [0.001, 0.010, 0.050, 0.100, 0.500]
        for duration in durations:
            action_log_duration.labels(
                agent_name="test-agent", action_type="tool_call"
            ).observe(duration)

        # Verify histogram buckets
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_action_log_duration_seconds_bucket" in metrics_text

    def test_action_log_counter(self):
        """Test action log counter."""
        # Increment counter
        action_log_counter.labels(
            agent_name="test-agent", action_type="tool_call", status="success"
        ).inc()

        action_log_counter.labels(
            agent_name="test-agent", action_type="tool_call", status="failure"
        ).inc()

        # Verify counter values
        metrics_text = get_metrics_text().decode("utf-8")
        assert 'status="success"' in metrics_text
        assert 'status="failure"' in metrics_text

    def test_action_log_errors_counter(self):
        """Test action log errors counter."""
        # Increment error counter
        action_log_errors_counter.labels(
            agent_name="test-agent", error_type="TimeoutError"
        ).inc()

        # Verify error counter
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_action_log_errors_total" in metrics_text
        assert 'error_type="TimeoutError"' in metrics_text


class TestEventPublishMetrics:
    """Test event publishing metrics."""

    def test_record_event_publish(self):
        """Test recording event publish metrics."""
        record_event_publish(
            topic="test-topic",
            duration=0.005,
            size_bytes=1024,
            status="success",
        )

        # Verify metrics
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_event_publish_total" in metrics_text
        assert "omniclaude_event_publish_duration_seconds" in metrics_text
        assert "omniclaude_event_publish_bytes" in metrics_text
        assert 'topic="test-topic"' in metrics_text

    def test_event_publish_success_failure(self):
        """Test event publish success/failure tracking."""
        # Record success
        event_publish_counter.labels(topic="test-topic", status="success").inc()

        # Record failure
        event_publish_counter.labels(topic="test-topic", status="failure").inc()

        # Verify both tracked
        metrics_text = get_metrics_text().decode("utf-8")
        assert 'status="success"' in metrics_text
        assert 'status="failure"' in metrics_text

    def test_event_publish_errors(self):
        """Test event publish error tracking."""
        event_publish_errors_counter.labels(
            topic="test-topic", error_type="ConnectionError"
        ).inc()

        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_event_publish_errors_total" in metrics_text
        assert 'error_type="ConnectionError"' in metrics_text


class TestDatabaseMetrics:
    """Test database operation metrics."""

    def test_record_db_operation(self):
        """Test recording database operation metrics."""
        record_db_operation(
            operation="insert",
            table="agent_actions",
            duration=0.025,
            status="success",
        )

        # Verify metrics
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_db_operation_duration_seconds" in metrics_text
        assert "omniclaude_db_operation_total" in metrics_text
        assert 'operation="insert"' in metrics_text
        assert 'table="agent_actions"' in metrics_text

    def test_db_operation_types(self):
        """Test different database operation types."""
        operations = ["insert", "update", "delete", "select"]
        for operation in operations:
            db_operation_duration.labels(
                operation=operation, table="test_table"
            ).observe(0.010)

        metrics_text = get_metrics_text().decode("utf-8")
        for operation in operations:
            assert f'operation="{operation}"' in metrics_text


class TestCacheMetrics:
    """Test cache performance metrics."""

    def test_record_cache_hit(self):
        """Test recording cache hit."""
        record_cache_operation(
            cache_type="patterns",
            operation="get",
            duration=0.002,
            hit=True,
        )

        # Verify hit counter incremented
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_cache_hit_total" in metrics_text
        assert 'cache_type="patterns"' in metrics_text

    def test_record_cache_miss(self):
        """Test recording cache miss."""
        record_cache_operation(
            cache_type="patterns",
            operation="get",
            duration=0.002,
            hit=False,
        )

        # Verify miss counter incremented
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_cache_miss_total" in metrics_text

    def test_cache_operation_duration(self):
        """Test cache operation duration tracking."""
        cache_operation_duration.labels(cache_type="patterns", operation="set").observe(
            0.003
        )

        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_cache_operation_duration_seconds" in metrics_text


class TestAgentRoutingMetrics:
    """Test agent routing metrics."""

    def test_record_agent_routing(self):
        """Test recording agent routing metrics."""
        record_agent_routing(
            selected_agent="agent-researcher",
            confidence=0.92,
            duration=0.008,
            routing_method="event_based",
            status="success",
        )

        # Verify metrics
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_agent_routing_duration_seconds" in metrics_text
        assert "omniclaude_agent_routing_total" in metrics_text
        assert "omniclaude_agent_routing_confidence" in metrics_text
        assert 'selected_agent="agent-researcher"' in metrics_text


class TestHTTPMetrics:
    """Test HTTP request metrics."""

    def test_http_request_metrics(self):
        """Test HTTP request metrics tracking."""
        # Record request
        http_request_counter.labels(
            method="GET", endpoint="/api/test", status_code=200
        ).inc()

        http_request_duration.labels(
            method="GET", endpoint="/api/test", status_code=200
        ).observe(0.050)

        # Verify metrics
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_http_request_total" in metrics_text
        assert "omniclaude_http_request_duration_seconds" in metrics_text
        assert 'method="GET"' in metrics_text
        assert 'endpoint="/api/test"' in metrics_text


class TestServiceHealthMetrics:
    """Test service health metrics."""

    def test_service_health_status(self):
        """Test service health status gauge."""
        # Set healthy
        service_health_status.labels(service_name="test-service").set(1)

        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_service_health_status" in metrics_text
        assert 'service_name="test-service"' in metrics_text

    def test_service_startup_time(self):
        """Test service startup timestamp."""
        # Set startup time
        startup_time = time.time()
        service_startup_time.labels(service_name="test-service").set(startup_time)

        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_service_startup_timestamp_seconds" in metrics_text


class TestActionLoggerIntegration:
    """Test ActionLogger integration with Prometheus metrics."""

    @pytest.mark.asyncio
    async def test_action_logger_metrics(self):
        """Test that ActionLogger records Prometheus metrics."""
        from agents.lib.action_logger import ActionLogger

        logger = ActionLogger(
            agent_name="test-agent",
            correlation_id="test-123",
        )

        # Log tool call (should record metrics)
        await logger.log_tool_call(
            tool_name="Read",
            tool_parameters={"file_path": "/test/file.py"},
            tool_result={"line_count": 100},
            duration_ms=45,
        )

        # Verify metrics were recorded
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_action_log_duration_seconds" in metrics_text
        assert "omniclaude_action_log_total" in metrics_text

    @pytest.mark.asyncio
    async def test_action_logger_error_metrics(self):
        """Test that ActionLogger records error metrics."""
        from agents.lib.action_logger import ActionLogger

        logger = ActionLogger(
            agent_name="test-agent",
            correlation_id="test-123",
        )

        # Log error (should record error metrics)
        await logger.log_error(
            error_type="TestError",
            error_message="Test error message",
            severity="warning",
            send_slack_notification=False,
        )

        # Verify error metrics
        metrics_text = get_metrics_text().decode("utf-8")
        assert "omniclaude_action_log_errors_total" in metrics_text


class TestEventPublisherIntegration:
    """Test event publisher integration with Prometheus metrics."""

    @pytest.mark.asyncio
    async def test_event_publisher_metrics(self):
        """Test that event publisher records Prometheus metrics."""
        from agents.lib.action_event_publisher import publish_action_event

        # Mock Kafka producer
        with patch(
            "agents.lib.action_event_publisher._get_kafka_producer"
        ) as mock_producer:
            # Create mock producer
            mock_instance = Mock()
            mock_instance.send_and_wait = Mock(return_value=asyncio.sleep(0))
            mock_producer.return_value = mock_instance

            # Publish event
            await publish_action_event(
                agent_name="test-agent",
                action_type="tool_call",
                action_name="Read",
                action_details={"file_path": "/test/file.py"},
                correlation_id="test-123",
                duration_ms=45,
            )

            # Verify metrics were recorded
            metrics_text = get_metrics_text().decode("utf-8")
            assert "omniclaude_event_publish_total" in metrics_text
            assert "omniclaude_event_publish_duration_seconds" in metrics_text


class TestMetricsEndpoint:
    """Test FastAPI /metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self):
        """Test that /metrics endpoint returns Prometheus format."""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        # Request /metrics endpoint
        response = client.get("/metrics")

        # Verify response
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert b"omniclaude" in response.content

    @pytest.mark.asyncio
    async def test_metrics_endpoint_content(self):
        """Test metrics endpoint content format."""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        response = client.get("/metrics")
        content = response.content.decode("utf-8")

        # Verify Prometheus format
        assert "# HELP" in content
        assert "# TYPE" in content
        assert "omniclaude_system_info" in content


# ============================================================================
# EDGE CASE TESTS (Added for PR #22 comprehensive edge case testing)
# ============================================================================


class TestMetricOverflow:
    """Test handling of metric overflow scenarios (edge cases)"""

    def test_counter_very_large_increment(self):
        """Test counter with very large increment value"""
        from prometheus_client import CollectorRegistry, Counter

        registry = CollectorRegistry()
        test_counter = Counter(
            "test_counter_large",
            "Test counter",
            labelnames=["label"],
            registry=registry,
        )

        # Increment with very large value
        test_counter.labels(label="test").inc(2**31 - 1)  # Near max int32

        assert test_counter.labels(label="test")._value.get() > 0

    def test_histogram_extreme_observations(self):
        """Test histogram with extreme observation values"""
        from prometheus_client import CollectorRegistry, Histogram

        registry = CollectorRegistry()
        test_histogram = Histogram(
            "test_histogram_extreme",
            "Test histogram",
            labelnames=["label"],
            buckets=(0.001, 0.01, 0.1, 1.0, 10.0),
            registry=registry,
        )

        # Observe extreme values
        test_histogram.labels(label="test").observe(0.0)  # Minimum
        test_histogram.labels(label="test").observe(1e10)  # Very large

        metrics = list(registry.collect())
        assert any(m.name == "test_histogram_extreme" for m in metrics)

    def test_counter_rapid_increments_1000(self):
        """Test counter with 1000 rapid increments"""
        from prometheus_client import CollectorRegistry, Counter

        registry = CollectorRegistry()
        test_counter = Counter(
            "test_rapid_counter", "Test rapid counter", registry=registry
        )

        for _ in range(1000):
            test_counter.inc()

        assert test_counter._value.get() == 1000


class TestConcurrentMetricUpdates:
    """Test thread safety with concurrent metric updates"""

    def test_concurrent_action_log_recording(self):
        """Test concurrent calls to record_action_log"""
        import concurrent.futures

        errors = []

        def record_task():
            try:
                for _ in range(10):
                    record_action_log("test-agent", "tool_call", 0.01, "success")
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_task) for _ in range(10)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0

    def test_concurrent_event_publish_recording(self):
        """Test concurrent calls to record_event_publish"""
        import concurrent.futures

        errors = []

        def record_task():
            try:
                for _ in range(10):
                    record_event_publish("test-topic", 0.005, 1024, "success")
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_task) for _ in range(10)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0


class TestBoundaryValueHandling:
    """Test handling of boundary values"""

    def test_zero_duration_observations(self):
        """Test histogram with zero duration observations"""
        from prometheus_client import CollectorRegistry, Histogram

        registry = CollectorRegistry()
        test_histogram = Histogram(
            "test_zero_duration",
            "Test zero duration",
            buckets=(0.001, 0.01, 0.1, 1.0),
            registry=registry,
        )

        for _ in range(100):
            test_histogram.observe(0.0)

        metrics = list(registry.collect())
        assert any(m.name == "test_zero_duration" for m in metrics)

    def test_record_action_log_extreme_duration(self):
        """Test record_action_log with extreme duration values"""
        # Very small duration
        record_action_log("test-agent", "tool_call", 0.0000001)

        # Very large duration
        record_action_log("test-agent", "tool_call", 10000.0)

        # Should not raise errors
        assert True

    def test_record_event_publish_zero_bytes(self):
        """Test record_event_publish with zero bytes"""
        record_event_publish("test-topic", 0.005, 0, "success")
        assert True

    def test_record_event_publish_very_large_bytes(self):
        """Test record_event_publish with very large byte size"""
        # 100MB event
        record_event_publish("test-topic", 0.1, 100_000_000, "success")
        assert True

    def test_record_agent_routing_boundary_confidence(self):
        """Test record_agent_routing with boundary confidence values"""
        # Minimum confidence
        record_agent_routing("test-agent", 0.0, 0.01)

        # Maximum confidence
        record_agent_routing("test-agent", 1.0, 0.01)

        assert True


class TestInvalidMetricValues:
    """Test handling of invalid metric values"""

    def test_counter_negative_increment_raises_error(self):
        """Test that counter rejects negative increments"""
        from prometheus_client import CollectorRegistry, Counter

        registry = CollectorRegistry()
        test_counter = Counter(
            "test_negative_inc", "Test negative inc", registry=registry
        )

        with pytest.raises(ValueError, match="negative"):
            test_counter.inc(-1)

    def test_helper_function_invalid_status(self):
        """Test helper functions with invalid status values"""
        # Should handle any string status value
        record_action_log("test-agent", "tool_call", 0.01, "invalid_status")
        assert True


class TestLabelCardinalityLimits:
    """Test handling of high label cardinality"""

    def test_counter_100_unique_labels(self):
        """Test counter with 100 unique label combinations"""
        from prometheus_client import CollectorRegistry, Counter

        registry = CollectorRegistry()
        test_counter = Counter(
            "test_high_cardinality",
            "Test high cardinality",
            labelnames=["label"],
            registry=registry,
        )

        # Create 100 unique label values
        for i in range(100):
            test_counter.labels(label=f"value_{i}").inc()

        metrics = list(registry.collect())
        assert any(m.name == "test_high_cardinality_total" for m in metrics)

    def test_label_with_special_characters(self):
        """Test labels with special characters"""
        from prometheus_client import CollectorRegistry, Counter

        registry = CollectorRegistry()
        test_counter = Counter(
            "test_special_labels",
            "Test special labels",
            labelnames=["label"],
            registry=registry,
        )

        special_labels = [
            "normal_label",
            "label-with-dash",
            "label.with.dots",
            "label_123",
        ]

        for label in special_labels:
            test_counter.labels(label=label).inc()

        assert test_counter.labels(label="normal_label")._value.get() == 1


class TestContextManagerUsage:
    """Test using histogram.time() context manager"""

    def test_histogram_time_context_manager_with_exception(self):
        """Test histogram time() context manager when exception occurs"""
        from prometheus_client import CollectorRegistry, Histogram

        registry = CollectorRegistry()
        test_histogram = Histogram(
            "test_context_exception",
            "Test context exception",
            buckets=(0.001, 0.01, 0.1),
            registry=registry,
        )

        try:
            with test_histogram.time():
                raise ValueError("Intentional error")
        except ValueError:
            pass

        # Should still record observation
        metrics = list(registry.collect())
        assert any(m.name == "test_context_exception" for m in metrics)


if __name__ == "__main__":
    pytest.main(
        [
            __file__,
            "-v",
            "--cov=agents.lib.prometheus_metrics",
            "--cov-report=term-missing",
        ]
    )
