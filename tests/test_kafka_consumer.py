#!/usr/bin/env python3
"""
Integration Tests for Kafka Agent Action Consumer

Tests the Kafka consumer with real Kafka/Redpanda and PostgreSQL instances.
Requires Docker environment (see docker-compose.test.yml).

Coverage:
- Kafka message consumption
- Batch inserts to PostgreSQL
- Idempotency (duplicate handling)
- Error handling and retry logic
- Graceful shutdown
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest
from kafka import KafkaProducer


# Add agents lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "lib"))
from kafka_agent_action_consumer import KafkaAgentActionConsumer


@pytest.fixture(scope="session")
def kafka_brokers():
    """Kafka brokers for testing (from environment or default)."""
    return os.getenv("KAFKA_BROKERS", "localhost:29092")


@pytest.fixture(scope="session")
def postgres_dsn():
    """PostgreSQL DSN for testing (loads from .env via conftest.py)."""
    # Try to use pre-built DSN from .env first
    dsn = os.getenv("PG_DSN")
    if dsn:
        return dsn

    # Fallback to standard PostgreSQL environment variables
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5436")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")  # Must be set in environment
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
async def db_pool(postgres_dsn):
    """Database connection pool for testing."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture
async def _clean_database(db_pool):
    """Clean test data from database before each test."""
    # Cleanup happens at the end of each test
    return
    # Note: Individual tests verify their own data, no pattern-based cleanup needed


@pytest.fixture
def kafka_producer(kafka_brokers):
    """Kafka producer for publishing test events."""
    producer = KafkaProducer(
        bootstrap_servers=kafka_brokers.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
    )
    yield producer
    producer.close()


@pytest.fixture
def test_topic():
    """Test topic name (unique per test run)."""
    return f"agent-actions-test-{uuid.uuid4().hex[:8]}"


class TestKafkaConsumerIntegration:
    """Integration tests for Kafka consumer with PostgreSQL."""

    @pytest.mark.asyncio
    async def test_consumer_starts_and_stops(
        self, kafka_brokers, postgres_dsn, test_topic
    ):
        """Test consumer can start and stop gracefully."""
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
        )

        await consumer.start()
        assert consumer.running is True
        assert consumer.consumer is not None
        assert consumer.db_pool is not None

        await consumer.stop()
        assert consumer.running is False
        assert consumer.consumer is None
        assert consumer.db_pool is None

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_consume_single_event(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
        wait_for_records,
    ):
        """Test consuming and persisting a single event."""
        # Publish test event
        correlation_id = str(uuid.uuid4())
        event = {
            "correlation_id": correlation_id,
            "agent_name": "test-agent",
            "action_type": "tool_call",
            "action_name": "test_action",
            "action_details": {"key": "value"},
            "debug_mode": True,
            "duration_ms": 100,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        kafka_producer.send(test_topic, value=event)
        kafka_producer.flush()

        # Start consumer
        # Use unique consumer group to avoid conflicts with parallel tests
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id=f"test-consume-single-{uuid.uuid4().hex[:8]}",
            batch_timeout_seconds=1.0,  # Short timeout for testing
        )

        await consumer.start()

        # Give consumer time to subscribe to topic
        await asyncio.sleep(0.5)

        # Start consumer loop in background
        consumer_task = asyncio.create_task(consumer.consume_loop())

        try:
            # Wait for record to appear in database
            await wait_for_records(
                db_pool,
                correlation_id=correlation_id,
                expected_count=1,
                timeout_seconds=5.0,
            )

            # Verify event was persisted with correct data
            async with db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    "SELECT * FROM agent_actions WHERE correlation_id = $1",
                    correlation_id,
                )

                assert result is not None
                assert result["agent_name"] == "test-agent"
                assert result["action_type"] == "tool_call"
                assert result["action_name"] == "test_action"
                assert result["debug_mode"] is True
                assert result["duration_ms"] == 100
        finally:
            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_batch_insert_performance(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
    ):
        """Test batch insertion of multiple events."""
        # Publish 50 test events
        correlation_ids = []
        for i in range(50):
            correlation_id = str(uuid.uuid4())
            correlation_ids.append(correlation_id)

            event = {
                "correlation_id": correlation_id,
                "agent_name": f"test-agent-{i}",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {"index": i},
                "debug_mode": True,
                "duration_ms": i * 10,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            kafka_producer.send(test_topic, value=event)

        kafka_producer.flush()

        # Start consumer with batch processing
        # Use unique consumer group to avoid conflicts with parallel tests
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id=f"test-batch-insert-{uuid.uuid4().hex[:8]}",
            batch_size=25,  # Process in batches of 25
            batch_timeout_seconds=1.0,
        )

        await consumer.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        # Start consumer loop in background
        consumer_task = asyncio.create_task(consumer.consume_loop())

        try:
            # Wait for all records with polling
            start_time = asyncio.get_event_loop().time()
            timeout = 10.0

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                async with db_pool.acquire() as conn:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = ANY($1::uuid[])",
                        correlation_ids,
                    )

                    if count >= 50:
                        break

                await asyncio.sleep(0.2)

            # Verify all events were persisted
            async with db_pool.acquire() as conn:
                final_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = ANY($1::uuid[])",
                    correlation_ids,
                )

                assert final_count == 50, f"Expected 50 records, got {final_count}"
        finally:
            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_idempotency_duplicate_handling(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
        wait_for_records,
    ):
        """Test consumer handles duplicate events correctly (idempotency)."""
        correlation_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create duplicate event
        event = {
            "correlation_id": correlation_id,
            "agent_name": "test-agent",
            "action_type": "tool_call",
            "action_name": "duplicate_test",
            "action_details": {},
            "debug_mode": True,
            "duration_ms": 100,
            "timestamp": timestamp,  # Same timestamp
        }

        # Publish same event twice
        kafka_producer.send(test_topic, value=event)
        kafka_producer.send(test_topic, value=event)
        kafka_producer.flush()

        # Start consumer
        # Use unique consumer group to avoid conflicts with parallel tests
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id=f"test-idempotency-{uuid.uuid4().hex[:8]}",
            batch_timeout_seconds=1.0,
        )

        await consumer.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        # Start consumer loop in background
        consumer_task = asyncio.create_task(consumer.consume_loop())

        try:
            # Wait for at least one record to appear
            await wait_for_records(
                db_pool,
                correlation_id=correlation_id,
                expected_count=1,
                timeout_seconds=5.0,
            )

            # Wait a bit more to ensure any duplicate would have been processed
            await asyncio.sleep(2.0)

            # Verify only one event was inserted (duplicate was skipped)
            async with db_pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM agent_actions
                    WHERE correlation_id = $1 AND action_name = 'duplicate_test'
                    """,
                    correlation_id,
                )

                assert count == 1, f"Expected 1 record (idempotent), got {count}"
        finally:
            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_error_handling_invalid_json(
        self, kafka_brokers, postgres_dsn, db_pool, test_topic
    ):
        """Test consumer handles invalid JSON gracefully."""
        # Publish invalid JSON directly (bypass producer serializer)
        from kafka import KafkaProducer

        raw_producer = KafkaProducer(
            bootstrap_servers=kafka_brokers.split(","),
            # No serializer - send raw bytes
        )

        # Send invalid JSON
        raw_producer.send(test_topic, value=b"{invalid json}")
        raw_producer.flush()
        raw_producer.close()

        # Consumer should handle gracefully and continue
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            batch_timeout_seconds=1.0,
        )

        await consumer.start()

        try:
            # Should not crash
            await asyncio.wait_for(consumer.consume_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # Expected
        except Exception as e:
            pytest.fail(f"Consumer crashed on invalid JSON: {e}")
        finally:
            await consumer.stop()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_consumer_offset_commit(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
    ):
        """Test consumer commits offsets after successful processing."""
        correlation_id = str(uuid.uuid4())

        event = {
            "correlation_id": correlation_id,
            "agent_name": "test-agent",
            "action_type": "tool_call",
            "action_name": "offset_test",
            "action_details": {},
            "debug_mode": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        kafka_producer.send(test_topic, value=event)
        kafka_producer.flush()

        # First consumer instance
        consumer1 = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id="test-offset-group",
            batch_timeout_seconds=1.0,
        )

        await consumer1.start()

        try:
            await asyncio.wait_for(consumer1.consume_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await consumer1.stop()

        # Verify event was persisted
        async with db_pool.acquire() as conn:
            count1 = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
                correlation_id,
            )
            assert count1 == 1

        # Start second consumer with same group_id
        # If offset was committed, it should not re-process the message
        consumer2 = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id="test-offset-group",  # Same group
            batch_timeout_seconds=1.0,
        )

        await consumer2.start()

        try:
            await asyncio.wait_for(consumer2.consume_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await consumer2.stop()

        # Count should still be 1 (not re-processed)
        async with db_pool.acquire() as conn:
            count2 = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
                correlation_id,
            )
            assert count2 == 1  # Still 1, not duplicated

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_clean_database")
    async def test_different_action_types(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
    ):
        """Test consuming events with different action types."""
        action_types = ["tool_call", "decision", "error", "success"]
        correlation_ids = {}

        for action_type in action_types:
            correlation_id = str(uuid.uuid4())
            correlation_ids[action_type] = correlation_id

            event = {
                "correlation_id": correlation_id,
                "agent_name": "test-agent",
                "action_type": action_type,
                "action_name": f"test_{action_type}",
                "action_details": {"type": action_type},
                "debug_mode": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            kafka_producer.send(test_topic, value=event)

        kafka_producer.flush()

        # Start consumer
        # Use unique consumer group to avoid conflicts with parallel tests
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            group_id=f"test-action-types-{uuid.uuid4().hex[:8]}",
            batch_timeout_seconds=1.0,
        )

        await consumer.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        # Start consumer loop in background
        consumer_task = asyncio.create_task(consumer.consume_loop())

        try:
            # Wait for all records with polling
            start_time = asyncio.get_event_loop().time()
            timeout = 10.0
            all_correlation_ids = list(correlation_ids.values())

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                async with db_pool.acquire() as conn:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = ANY($1::uuid[])",
                        all_correlation_ids,
                    )

                    if count >= len(action_types):
                        break

                await asyncio.sleep(0.2)

            # Verify all action types were persisted
            async with db_pool.acquire() as conn:
                for action_type in action_types:
                    result = await conn.fetchrow(
                        """
                        SELECT * FROM agent_actions
                        WHERE correlation_id = $1 AND action_type = $2
                        """,
                        correlation_ids[action_type],
                        action_type,
                    )

                    assert (
                        result is not None
                    ), f"Missing record for action_type: {action_type}"
                    assert result["action_type"] == action_type
        finally:
            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass


class TestConsumerPerformance:
    """Performance tests for Kafka consumer."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.usefixtures("_clean_database")
    async def test_high_throughput_processing(
        self,
        kafka_producer,
        kafka_brokers,
        postgres_dsn,
        db_pool,
        test_topic,
    ):
        """Test consumer can handle high throughput (1000+ events)."""
        num_events = 1000
        test_run_id = str(uuid.uuid4())

        # Publish 1000 events
        for i in range(num_events):
            event = {
                "correlation_id": str(uuid.uuid4()),
                "agent_name": f"agent-{i % 10}",
                "action_type": "tool_call",
                "action_name": f"action_{i}",
                "action_details": {"index": i, "test_run_id": test_run_id},
                "debug_mode": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            kafka_producer.send(test_topic, value=event)

        kafka_producer.flush()

        # Start consumer
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic=test_topic,
            postgres_dsn=postgres_dsn,
            batch_size=100,  # Process in batches of 100
            batch_timeout_seconds=2.0,
        )

        await consumer.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        # Start consumer loop in background
        consumer_task = asyncio.create_task(consumer.consume_loop())

        try:
            # Wait for all events to be processed (with polling)
            start_time = asyncio.get_event_loop().time()
            timeout = 60.0  # Increase timeout for 1000 events

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                async with db_pool.acquire() as conn:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM agent_actions WHERE action_details->>'test_run_id' = $1",
                        test_run_id,
                    )

                    if count >= num_events:
                        break

                await asyncio.sleep(0.5)

            # Verify all events were processed
            async with db_pool.acquire() as conn:
                final_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM agent_actions WHERE action_details->>'test_run_id' = $1",
                    test_run_id,
                )

                # Should have processed all 1000 events
                assert (
                    final_count == num_events
                ), f"Expected {num_events} events, got {final_count}"
        finally:
            await consumer.stop()
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not slow"])
