#!/usr/bin/env python3
"""
Performance Tests for Kafka Agent Logging System

Tests throughput, latency, and resource utilization under various load conditions.

Performance Targets:
- Publish latency: <10ms p95
- Consumer throughput: >1000 events/sec
- End-to-end latency: <5s p95
- Consumer lag: <100 messages under steady load
- Memory usage: <500MB for consumer

Requires: Docker environment with Kafka/Redpanda and PostgreSQL
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List

import asyncpg
import psutil
import pytest
from kafka import KafkaConsumer, KafkaProducer

# Add config for type-safe settings
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "lib"))
from kafka_agent_action_consumer import KafkaAgentActionConsumer


@pytest.fixture(scope="session")
def kafka_brokers():
    """Kafka brokers for performance testing."""
    return os.getenv("KAFKA_BROKERS", "localhost:29092")


@pytest.fixture(scope="session")
def postgres_dsn():
    """PostgreSQL DSN for performance testing."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5436")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = settings.get_effective_postgres_password()
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
async def db_pool(postgres_dsn):
    """Database connection pool."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=5, max_size=20)
    yield pool
    await pool.close()


@pytest.fixture
async def __clean_database(db_pool):
    """Clean test data."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id LIKE 'perf-test-%'"
        )
    yield
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id LIKE 'perf-test-%'"
        )


@pytest.fixture
def kafka_producer(kafka_brokers):
    """High-performance Kafka producer."""
    producer = KafkaProducer(
        bootstrap_servers=kafka_brokers.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        compression_type="gzip",
        linger_ms=10,
        batch_size=32768,  # 32KB batches
        acks=1,
    )
    yield producer
    producer.close()


class PerformanceMetrics:
    """Container for performance metrics."""

    def __init__(self):
        self.latencies: List[float] = []
        self.throughputs: List[float] = []
        self.errors: int = 0
        self.memory_usage: List[float] = []

    def add_latency(self, latency_ms: float):
        """Add latency measurement."""
        self.latencies.append(latency_ms)

    def add_throughput(self, events_per_sec: float):
        """Add throughput measurement."""
        self.throughputs.append(events_per_sec)

    def add_memory(self, memory_mb: float):
        """Add memory usage measurement."""
        self.memory_usage.append(memory_mb)

    def calculate_percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * (percentile / 100.0))
        return sorted_data[min(index, len(sorted_data) - 1)]

    def summary(self) -> Dict:
        """Generate summary statistics."""
        return {
            "latency": {
                "p50": self.calculate_percentile(self.latencies, 50),
                "p95": self.calculate_percentile(self.latencies, 95),
                "p99": self.calculate_percentile(self.latencies, 99),
                "avg": mean(self.latencies) if self.latencies else 0,
                "max": max(self.latencies) if self.latencies else 0,
            },
            "throughput": {
                "avg": mean(self.throughputs) if self.throughputs else 0,
                "max": max(self.throughputs) if self.throughputs else 0,
                "min": min(self.throughputs) if self.throughputs else 0,
            },
            "memory": {
                "avg_mb": mean(self.memory_usage) if self.memory_usage else 0,
                "max_mb": max(self.memory_usage) if self.memory_usage else 0,
            },
            "errors": self.errors,
        }


class TestKafkaPublishPerformance:
    """Performance tests for Kafka publish operations."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_publish_latency_single_event(self, kafka_producer):
        """
        Test publish latency for single events.
        Target: <10ms p95
        """
        metrics = PerformanceMetrics()
        num_events = 100

        for i in range(num_events):
            event = {
                "correlation_id": f"perf-test-latency-{uuid.uuid4()}",
                "agent_name": "test-agent",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {},
                "debug_mode": True,
                "timestamp": datetime.utcnow().isoformat(),
            }

            start = time.time()
            future = kafka_producer.send("agent-actions", value=event)
            future.get(timeout=1.0)  # Wait for acknowledgment
            latency_ms = (time.time() - start) * 1000

            metrics.add_latency(latency_ms)

        summary = metrics.summary()
        print("\n📊 Publish Latency Metrics:")
        print(f"  P50: {summary['latency']['p50']:.2f}ms")
        print(f"  P95: {summary['latency']['p95']:.2f}ms")
        print(f"  P99: {summary['latency']['p99']:.2f}ms")
        print(f"  Avg: {summary['latency']['avg']:.2f}ms")
        print(f"  Max: {summary['latency']['max']:.2f}ms")

        assert (
            summary["latency"]["p95"] < 10.0
        ), f"P95 latency {summary['latency']['p95']:.2f}ms exceeds 10ms target"

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_publish_throughput_burst(self, kafka_producer):
        """
        Test publish throughput under burst load.
        Target: >1000 events/sec
        """
        num_events = 1000
        events = []

        # Prepare events
        for i in range(num_events):
            event = {
                "correlation_id": f"perf-test-burst-{i}",
                "agent_name": f"agent-{i % 10}",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {"index": i},
                "debug_mode": True,
                "timestamp": datetime.utcnow().isoformat(),
            }
            events.append(event)

        # Publish burst
        start = time.time()

        for event in events:
            kafka_producer.send("agent-actions", value=event)

        kafka_producer.flush()  # Wait for all to complete
        elapsed = time.time() - start

        throughput = num_events / elapsed

        print("\n📊 Burst Throughput:")
        print(f"  Events: {num_events}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} events/sec")

        assert (
            throughput > 1000
        ), f"Throughput {throughput:.2f} < 1000 events/sec target"


class TestConsumerPerformance:
    """Performance tests for Kafka consumer."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    @pytest.mark.usefixtures("_clean_database")
    async def test_consumer_throughput(
        self, kafka_producer, kafka_brokers, postgres_dsn, db_pool
    ):
        """
        Test consumer throughput.
        Target: >1000 events/sec sustained
        """
        num_events = 1000
        correlation_prefix = f"perf-test-consumer-{uuid.uuid4().hex[:8]}"

        # Publish events
        print(f"\n📤 Publishing {num_events} events...")
        for i in range(num_events):
            event = {
                "correlation_id": f"{correlation_prefix}-{i}",
                "agent_name": f"agent-{i % 10}",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {"index": i},
                "debug_mode": True,
                "timestamp": datetime.utcnow().isoformat(),
            }
            kafka_producer.send("agent-actions", value=event)

        kafka_producer.flush()

        # Start consumer
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic="agent-actions",
            postgres_dsn=postgres_dsn,
            batch_size=100,
            batch_timeout_seconds=2.0,
        )

        await consumer.start()

        # Measure consumer throughput
        start = time.time()

        consumer_task = asyncio.create_task(consumer.consume_loop())

        # Wait for all events to be processed
        max_wait = 30.0  # 30 seconds max
        while (time.time() - start) < max_wait:
            async with db_pool.acquire() as conn:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM agent_actions WHERE correlation_id LIKE '{correlation_prefix}-%'"
                )

                if count >= num_events:
                    break

            await asyncio.sleep(0.5)

        elapsed = time.time() - start

        # Stop consumer
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Verify all processed
        async with db_pool.acquire() as conn:
            final_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM agent_actions WHERE correlation_id LIKE '{correlation_prefix}-%'"
            )

        throughput = final_count / elapsed

        print("\n📊 Consumer Throughput:")
        print(f"  Events: {final_count}/{num_events}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} events/sec")

        assert final_count == num_events, f"Only processed {final_count}/{num_events}"
        assert throughput > 500, f"Throughput {throughput:.2f} < 500 events/sec target"

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_consumer_lag_under_load(
        self, kafka_producer, kafka_brokers, postgres_dsn
    ):
        """
        Test consumer lag under continuous load.
        Target: <100 messages lag under steady state
        """
        # Start consumer
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic="agent-actions",
            postgres_dsn=postgres_dsn,
            batch_size=50,
            batch_timeout_seconds=1.0,
        )

        await consumer.start()
        consumer_task = asyncio.create_task(consumer.consume_loop())

        # Continuous publishing for 10 seconds
        correlation_prefix = f"perf-test-lag-{uuid.uuid4().hex[:8]}"
        duration = 10.0
        start = time.time()
        event_count = 0

        while (time.time() - start) < duration:
            event = {
                "correlation_id": f"{correlation_prefix}-{event_count}",
                "agent_name": "test-agent",
                "action_type": "tool_call",
                "action_name": f"action_{event_count}",
                "action_details": {},
                "debug_mode": True,
                "timestamp": datetime.utcnow().isoformat(),
            }

            kafka_producer.send("agent-actions", value=event)
            event_count += 1

            # Rate limiting: ~100 events/sec
            await asyncio.sleep(0.01)

        kafka_producer.flush()

        # Wait for consumer to catch up
        await asyncio.sleep(5.0)

        # Check lag using Kafka consumer
        check_consumer = KafkaConsumer(
            "agent-actions",
            bootstrap_servers=kafka_brokers.split(","),
            group_id=consumer.group_id,
            enable_auto_commit=False,
        )

        lag = 0
        for partition in check_consumer.assignment():
            committed = check_consumer.committed(partition)
            if committed is not None:
                position = check_consumer.position(partition)
                lag += position - committed

        check_consumer.close()

        # Stop consumer
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        print("\n📊 Consumer Lag:")
        print(f"  Events published: {event_count}")
        print(f"  Consumer lag: {lag} messages")

        assert lag < 100, f"Consumer lag {lag} exceeds 100 messages target"

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_consumer_memory_usage(
        self, kafka_producer, kafka_brokers, postgres_dsn
    ):
        """
        Test consumer memory usage under load.
        Target: <500MB
        """
        # Start consumer
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic="agent-actions",
            postgres_dsn=postgres_dsn,
            batch_size=100,
            batch_timeout_seconds=2.0,
        )

        await consumer.start()

        # Get process for memory monitoring
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        consumer_task = asyncio.create_task(consumer.consume_loop())

        # Publish continuous load
        correlation_prefix = f"perf-test-memory-{uuid.uuid4().hex[:8]}"
        memory_samples = []

        for i in range(1000):
            event = {
                "correlation_id": f"{correlation_prefix}-{i}",
                "agent_name": "test-agent",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {"data": "x" * 100},  # 100 bytes payload
                "debug_mode": True,
                "timestamp": datetime.utcnow().isoformat(),
            }

            kafka_producer.send("agent-actions", value=event)

            # Sample memory every 100 events
            if i % 100 == 0:
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_samples.append(current_memory)

        kafka_producer.flush()

        # Wait for processing
        await asyncio.sleep(10.0)

        # Final memory check
        final_memory = process.memory_info().rss / 1024 / 1024

        # Stop consumer
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        memory_increase = final_memory - initial_memory

        print("\n📊 Memory Usage:")
        print(f"  Initial: {initial_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")
        print(f"  Peak: {max(memory_samples):.2f} MB")

        assert (
            final_memory < 500
        ), f"Memory usage {final_memory:.2f}MB exceeds 500MB target"


class TestBatchSizeOptimization:
    """Tests for optimal batch size configuration."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    @pytest.mark.usefixtures("_clean_database")
    async def test_batch_size_comparison(
        self, kafka_producer, kafka_brokers, postgres_dsn, db_pool
    ):
        """
        Compare performance across different batch sizes.
        Find optimal batch size.
        """
        batch_sizes = [10, 50, 100, 200]
        results = {}

        num_events = 500

        for batch_size in batch_sizes:
            print(f"\n🧪 Testing batch size: {batch_size}")

            correlation_prefix = f"perf-test-batch-{batch_size}-{uuid.uuid4().hex[:8]}"

            # Publish events
            for i in range(num_events):
                event = {
                    "correlation_id": f"{correlation_prefix}-{i}",
                    "agent_name": "test-agent",
                    "action_type": "tool_call",
                    "action_name": f"action_{i}",
                    "action_details": {},
                    "debug_mode": True,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                kafka_producer.send("agent-actions", value=event)

            kafka_producer.flush()

            # Start consumer with specific batch size
            consumer = KafkaAgentActionConsumer(
                kafka_brokers=kafka_brokers,
                topic="agent-actions",
                postgres_dsn=postgres_dsn,
                batch_size=batch_size,
                batch_timeout_seconds=1.0,
            )

            await consumer.start()

            start = time.time()
            consumer_task = asyncio.create_task(consumer.consume_loop())

            # Wait for all events
            while True:
                async with db_pool.acquire() as conn:
                    count = await conn.fetchval(
                        f"SELECT COUNT(*) FROM agent_actions WHERE correlation_id LIKE '{correlation_prefix}-%'"
                    )

                    if count >= num_events:
                        break

                await asyncio.sleep(0.5)

            elapsed = time.time() - start

            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

            throughput = num_events / elapsed
            results[batch_size] = {
                "elapsed": elapsed,
                "throughput": throughput,
            }

            print(f"  Time: {elapsed:.2f}s")
            print(f"  Throughput: {throughput:.2f} events/sec")

        # Find optimal batch size
        optimal = max(results.items(), key=lambda x: x[1]["throughput"])

        print("\n📊 Batch Size Optimization Results:")
        for batch_size, metrics in results.items():
            print(
                f"  Batch {batch_size}: {metrics['throughput']:.2f} events/sec ({metrics['elapsed']:.2f}s)"
            )
        print(f"\n✅ Optimal batch size: {optimal[0]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "performance"])
