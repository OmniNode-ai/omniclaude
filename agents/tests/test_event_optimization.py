#!/usr/bin/env python3
"""
Agent Framework: Event Processing Optimization Tests

Performance target: p95 latency ≤200ms (from ~500ms baseline)

Test coverage:
- Batch processor functionality
- Event optimizer with circuit breaker
- Connection pooling
- Performance benchmarks
- Latency measurements
"""

import asyncio
import time
from typing import List
from uuid import uuid4

import pytest

from agents.lib.batch_processor import BatchConfig, BatchProcessor
from agents.lib.codegen_events import BaseEvent, CodegenAnalysisRequest
from agents.lib.event_optimizer import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    EventOptimizer,
    OptimizerConfig,
)

# Mark all tests in this module as integration tests (require database)
pytestmark = pytest.mark.integration

# ============================================================================
# Batch Processor Tests
# ============================================================================


@pytest.mark.asyncio
async def test_batch_processor_full_batch():
    """Test batch processor triggers on full batch"""
    processed_batches = []

    async def processor(batch: List[BaseEvent]) -> None:
        processed_batches.append(len(batch))

    config = BatchConfig(max_batch_size=5, max_wait_ms=1000, enable_metrics=False)
    bp = BatchProcessor(processor, config=config, persistence=None)

    # Add events to fill batch
    for i in range(5):
        result = await bp.add_event(f"event-{i}")
        if i < 4:
            assert result is None  # Not flushed yet
        # Last event should trigger flush

    # Wait a bit for async processing
    await asyncio.sleep(0.1)

    assert len(processed_batches) == 1
    assert processed_batches[0] == 5

    await bp.cleanup()


@pytest.mark.asyncio
async def test_batch_processor_timeout_flush():
    """Test batch processor flushes on timeout"""
    processed_batches = []

    async def processor(batch: List[BaseEvent]) -> None:
        processed_batches.append(len(batch))

    config = BatchConfig(max_batch_size=10, max_wait_ms=100, enable_metrics=False)
    bp = BatchProcessor(processor, config=config, persistence=None)

    # Add fewer events than batch size
    for i in range(3):
        await bp.add_event(f"event-{i}")

    # Wait for timeout
    await asyncio.sleep(0.2)

    assert len(processed_batches) == 1
    assert processed_batches[0] == 3

    await bp.cleanup()


@pytest.mark.asyncio
async def test_batch_processor_manual_flush():
    """Test manual batch flush"""
    processed_batches = []

    async def processor(batch: List[BaseEvent]) -> None:
        processed_batches.append(len(batch))

    config = BatchConfig(max_batch_size=10, max_wait_ms=1000, enable_metrics=False)
    bp = BatchProcessor(processor, config=config, persistence=None)

    # Add events
    for i in range(3):
        await bp.add_event(f"event-{i}")

    # Manual flush
    await bp.flush()

    assert len(processed_batches) == 1
    assert processed_batches[0] == 3

    await bp.cleanup()


@pytest.mark.asyncio
async def test_batch_processor_error_handling():
    """Test batch processor handles errors"""
    call_count = 0

    async def failing_processor(batch: List[BaseEvent]) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Processing failed")

    config = BatchConfig(max_batch_size=3, enable_metrics=False)
    bp = BatchProcessor(failing_processor, config=config, persistence=None)

    # Add events - should trigger flush when batch is full
    # The flush will raise an error
    with pytest.raises(ValueError, match="Processing failed"):
        for i in range(3):
            await bp.add_event(f"event-{i}")

    # Should have attempted processing
    assert call_count == 1

    # Batch should be cleared even on error
    assert len(bp.batch) == 0

    await bp.cleanup()


# ============================================================================
# Circuit Breaker Tests
# ============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_failures():
    """Test circuit breaker opens after threshold failures"""
    config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout_ms=1000)
    cb = CircuitBreaker(config)

    async def failing_func():
        raise ValueError("Simulated failure")

    # Trigger failures
    for i in range(3):
        with pytest.raises(ValueError):
            await cb.call(failing_func)

    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 3


@pytest.mark.asyncio
async def test_circuit_breaker_rejects_when_open():
    """Test circuit breaker rejects calls when open"""
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_ms=10000)
    cb = CircuitBreaker(config)

    async def failing_func():
        raise ValueError("Simulated failure")

    # Open circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing_func)

    assert cb.state == CircuitState.OPEN

    # Should reject next call
    async def success_func():
        return "success"

    with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
        await cb.call(success_func)


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    """Test circuit breaker transitions to half-open and recovers"""
    config = CircuitBreakerConfig(
        failure_threshold=2, recovery_timeout_ms=100, success_threshold=2
    )
    cb = CircuitBreaker(config)

    async def failing_func():
        raise ValueError("Simulated failure")

    # Open circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing_func)

    assert cb.state == CircuitState.OPEN

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # Next call should transition to half-open
    async def success_func():
        return "success"

    result = await cb.call(success_func)
    assert result == "success"
    assert cb.state == CircuitState.HALF_OPEN

    # Another success should close circuit
    result = await cb.call(success_func)
    assert result == "success"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_reopens_on_half_open_failure():
    """Test circuit breaker reopens on failure in half-open state"""
    config = CircuitBreakerConfig(
        failure_threshold=2, recovery_timeout_ms=100, success_threshold=2
    )
    cb = CircuitBreaker(config)

    async def failing_func():
        raise ValueError("Simulated failure")

    async def success_func():
        return "success"

    # Open circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing_func)

    assert cb.state == CircuitState.OPEN

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # Transition to half-open with success
    await cb.call(success_func)
    assert cb.state == CircuitState.HALF_OPEN

    # Failure in half-open should reopen
    with pytest.raises(ValueError):
        await cb.call(failing_func)

    assert cb.state == CircuitState.OPEN


# ============================================================================
# Event Optimizer Tests
# ============================================================================


class DummyProducer:
    """Mock Kafka producer for testing"""

    def __init__(self):
        self.sent_messages = []
        self.send_delay_ms = 0

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, topic, payload):
        if self.send_delay_ms > 0:
            await asyncio.sleep(self.send_delay_ms / 1000.0)
        self.sent_messages.append((topic, payload))

        # Return a simple awaitable
        class FakeFuture:
            async def __await__(self):
                return None

        return FakeFuture()

    async def send_and_wait(self, topic, payload):
        if self.send_delay_ms > 0:
            await asyncio.sleep(self.send_delay_ms / 1000.0)
        self.sent_messages.append((topic, payload))


@pytest.mark.asyncio
async def test_event_optimizer_single_publish(monkeypatch):
    """Test event optimizer publishes single event"""
    dummy = DummyProducer()

    # Mock producer pool
    async def mock_get_producer(self):
        return dummy

    async def mock_return_producer(self, producer):
        pass

    config = OptimizerConfig(enable_metrics=False)
    optimizer = EventOptimizer("localhost:9092", config=config)

    monkeypatch.setattr(
        optimizer, "_get_producer", mock_get_producer.__get__(optimizer)
    )
    monkeypatch.setattr(
        optimizer, "_return_producer", mock_return_producer.__get__(optimizer)
    )

    # Publish event
    event = CodegenAnalysisRequest()
    event.correlation_id = uuid4()
    event.payload = {"test": "data"}

    await optimizer.publish_event(event)

    assert len(dummy.sent_messages) == 1
    topic, payload = dummy.sent_messages[0]
    assert topic == event.to_kafka_topic()

    await optimizer.cleanup()


@pytest.mark.asyncio
async def test_event_optimizer_batch_publish(monkeypatch):
    """Test event optimizer publishes batch efficiently"""
    dummy = DummyProducer()

    # Mock producer pool
    async def mock_get_producer(self):
        return dummy

    async def mock_return_producer(self, producer):
        pass

    config = OptimizerConfig(enable_metrics=False)
    optimizer = EventOptimizer("localhost:9092", config=config)

    monkeypatch.setattr(
        optimizer, "_get_producer", mock_get_producer.__get__(optimizer)
    )
    monkeypatch.setattr(
        optimizer, "_return_producer", mock_return_producer.__get__(optimizer)
    )

    # Create batch of events
    events = []
    for i in range(10):
        event = CodegenAnalysisRequest()
        event.correlation_id = uuid4()
        event.payload = {"index": i}
        events.append(event)

    await optimizer.publish_batch(events)

    assert len(dummy.sent_messages) == 10

    await optimizer.cleanup()


@pytest.mark.asyncio
async def test_event_optimizer_circuit_breaker_integration(monkeypatch):
    """Test event optimizer uses circuit breaker"""
    config = OptimizerConfig(enable_metrics=False)
    circuit_config = CircuitBreakerConfig(failure_threshold=2)
    optimizer = EventOptimizer(
        "localhost:9092", config=config, circuit_config=circuit_config
    )

    # Mock publisher to fail
    async def failing_publish(event):
        raise ValueError("Network error")

    monkeypatch.setattr(optimizer, "_publish_event_internal", failing_publish)

    # Trigger failures to open circuit
    event = CodegenAnalysisRequest()
    for i in range(2):
        with pytest.raises(ValueError):
            await optimizer.publish_event(event)

    assert optimizer.circuit_breaker.state == CircuitState.OPEN

    # Next call should be rejected by circuit breaker
    with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
        await optimizer.publish_event(event)

    await optimizer.cleanup()


# ============================================================================
# Performance Benchmarks
# ============================================================================


@pytest.mark.asyncio
async def test_batch_processing_performance():
    """
    Benchmark batch processing performance.

    Target: p95 latency ≤200ms for batches of 10 events
    """
    latencies = []

    async def fast_processor(batch: List[BaseEvent]) -> None:
        # Simulate minimal processing
        await asyncio.sleep(0.001)

    config = BatchConfig(max_batch_size=10, max_wait_ms=50, enable_metrics=False)
    bp = BatchProcessor(fast_processor, config=config, persistence=None)

    # Process multiple batches and measure latency
    for batch_num in range(10):
        start = time.time()

        # Add full batch
        for i in range(10):
            await bp.add_event(f"event-{batch_num}-{i}")

        # Wait for processing
        await asyncio.sleep(0.1)

        latency_ms = (time.time() - start) * 1000
        latencies.append(latency_ms)

    await bp.cleanup()

    # Calculate p95
    latencies.sort()
    p95_index = int(len(latencies) * 0.95)
    p95_latency = latencies[p95_index]

    print(f"\nBatch processing p95 latency: {p95_latency:.2f}ms")
    print(f"Batch processing avg latency: {sum(latencies) / len(latencies):.2f}ms")

    # Target: p95 ≤200ms
    assert p95_latency <= 200, f"p95 latency {p95_latency:.2f}ms exceeds 200ms target"


@pytest.mark.asyncio
async def test_event_optimizer_throughput(monkeypatch):
    """
    Benchmark event optimizer throughput.

    Measure time to publish 100 events in batches.
    """
    dummy = DummyProducer()
    dummy.send_delay_ms = 5  # Simulate 5ms network latency

    # Mock producer pool
    async def mock_get_producer(self):
        return dummy

    async def mock_return_producer(self, producer):
        pass

    config = OptimizerConfig(enable_metrics=False)
    batch_config = BatchConfig(max_batch_size=10)
    optimizer = EventOptimizer(
        "localhost:9092", config=config, batch_config=batch_config
    )

    monkeypatch.setattr(
        optimizer, "_get_producer", mock_get_producer.__get__(optimizer)
    )
    monkeypatch.setattr(
        optimizer, "_return_producer", mock_return_producer.__get__(optimizer)
    )

    # Create events
    events = []
    for i in range(100):
        event = CodegenAnalysisRequest()
        event.correlation_id = uuid4()
        event.payload = {"index": i}
        events.append(event)

    # Measure batch publish time
    start = time.time()
    await optimizer.publish_batch(events)
    duration_ms = (time.time() - start) * 1000

    throughput = len(events) / (duration_ms / 1000.0)

    print(f"\nEvent optimizer throughput: {throughput:.2f} events/sec")
    print(f"Total time for 100 events: {duration_ms:.2f}ms")

    assert len(dummy.sent_messages) == 100

    await optimizer.cleanup()


@pytest.mark.asyncio
async def test_single_vs_batch_comparison(monkeypatch):
    """
    Compare single event publishing vs batch publishing.

    Demonstrates performance improvement from batching.
    """
    dummy = DummyProducer()
    dummy.send_delay_ms = 5

    # Mock producer pool
    async def mock_get_producer(self):
        return dummy

    async def mock_return_producer(self, producer):
        pass

    config = OptimizerConfig(enable_metrics=False)
    optimizer = EventOptimizer("localhost:9092", config=config)

    monkeypatch.setattr(
        optimizer, "_get_producer", mock_get_producer.__get__(optimizer)
    )
    monkeypatch.setattr(
        optimizer, "_return_producer", mock_return_producer.__get__(optimizer)
    )

    # Create test events
    events = []
    for i in range(20):
        event = CodegenAnalysisRequest()
        event.correlation_id = uuid4()
        event.payload = {"index": i}
        events.append(event)

    # Test 1: Publish individually
    dummy.sent_messages.clear()
    start = time.time()
    for event in events:
        await optimizer.publish_event(event)
    single_duration_ms = (time.time() - start) * 1000

    # Test 2: Publish as batch
    dummy.sent_messages.clear()
    start = time.time()
    await optimizer.publish_batch(events)
    batch_duration_ms = (time.time() - start) * 1000

    improvement_pct = (
        (single_duration_ms - batch_duration_ms) / single_duration_ms
    ) * 100

    print(f"\nSingle publish: {single_duration_ms:.2f}ms")
    print(f"Batch publish: {batch_duration_ms:.2f}ms")
    print(f"Improvement: {improvement_pct:.1f}%")

    # Batch should be faster
    assert batch_duration_ms < single_duration_ms

    await optimizer.cleanup()


@pytest.mark.asyncio
async def test_latency_percentiles():
    """
    Measure latency percentiles for batch processing.

    Reports p50, p95, p99 latencies.
    """
    latencies = []

    async def processor(batch: List[BaseEvent]) -> None:
        # Simulate variable processing time
        await asyncio.sleep(0.005 + (len(batch) * 0.001))

    config = BatchConfig(max_batch_size=10, max_wait_ms=50, enable_metrics=False)
    bp = BatchProcessor(processor, config=config, persistence=None)

    # Process 100 batches
    for batch_num in range(100):
        start = time.time()

        batch_size = (batch_num % 10) + 1  # Variable batch sizes
        for i in range(batch_size):
            await bp.add_event(f"event-{batch_num}-{i}")

        if batch_size == 10:
            # Full batch triggers immediate flush
            await asyncio.sleep(0.02)
        else:
            # Wait for timeout flush
            await asyncio.sleep(0.1)

        latency_ms = (time.time() - start) * 1000
        latencies.append(latency_ms)

    await bp.cleanup()

    # Calculate percentiles
    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    print("\nLatency percentiles:")
    print(f"  p50: {p50:.2f}ms")
    print(f"  p95: {p95:.2f}ms")
    print(f"  p99: {p99:.2f}ms")

    # Verify target
    assert p95 <= 200, f"p95 latency {p95:.2f}ms exceeds 200ms target"
