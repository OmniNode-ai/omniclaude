#!/usr/bin/env python3
"""
End-to-End Tests for Kafka Agent Logging System

Simulates complete agent workflows with Kafka-based action logging,
verifying the entire pipeline from skill execution → Kafka → PostgreSQL.

Tests:
- Complete workflow simulation
- Data integrity across the pipeline
- Latency measurements
- Multi-agent scenarios
- Error recovery

Requires: Docker environment with Kafka/Redpanda and PostgreSQL
"""

import asyncio
import json
import os
import subprocess

# Add config for type-safe settings
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest


sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


# Add paths
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent
        / "claude-artifacts"
        / "skills"
        / "agent-tracking"
        / "log-agent-action"
    ),
)
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "_shared"))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "lib"))

from kafka_agent_action_consumer import KafkaAgentActionConsumer


@pytest.fixture(scope="session")
def kafka_brokers():
    """Kafka brokers for E2E testing."""
    return os.getenv("KAFKA_BROKERS", "localhost:29092")


@pytest.fixture(scope="session")
def postgres_dsn():
    """PostgreSQL DSN for E2E testing."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5436")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = settings.get_effective_postgres_password()
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
async def db_pool(postgres_dsn):
    """Database connection pool."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture
async def __clean_database(db_pool):
    """Clean test data before/after each test."""
    # Cleanup no longer needed - using unique UUIDs that do not conflict
    return
    # Cleanup no longer needed - using unique UUIDs that do not conflict


@pytest.fixture
async def running_consumer(kafka_brokers, postgres_dsn):
    """Start consumer in background for E2E tests."""
    consumer = KafkaAgentActionConsumer(
        kafka_brokers=kafka_brokers,
        topic="agent-actions",
        postgres_dsn=postgres_dsn,
        batch_size=50,
        batch_timeout_seconds=2.0,
    )

    await consumer.start()

    # Start consumer loop in background task
    consumer_task = asyncio.create_task(consumer.consume_loop())

    yield consumer

    # Stop consumer
    await consumer.stop()

    try:
        consumer_task.cancel()
        await consumer_task
    except asyncio.CancelledError:
        pass


class TestEndToEndAgentLogging:
    """End-to-end tests for agent logging system."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("__clean_database")
    async def test_complete_workflow_simulation(
        self, running_consumer, db_pool, wait_for_records
    ):
        """
        Simulate complete agent workflow:
        1. Agent executes action
        2. Skill logs to Kafka
        3. Consumer persists to PostgreSQL
        4. Verify data integrity
        """
        correlation_id = str(uuid.uuid4())

        # Simulate agent workflow with multiple actions
        workflow_actions = [
            {
                "agent": "agent-polymorphic-agent",
                "action_type": "decision",
                "action_name": "analyze_request",
                "details": json.dumps({"request": "create kafka tests"}),
                "duration_ms": 150,
            },
            {
                "agent": "agent-polymorphic-agent",
                "action_type": "tool_call",
                "action_name": "Read",
                "details": json.dumps({"file": "test.py"}),
                "duration_ms": 25,
            },
            {
                "agent": "agent-polymorphic-agent",
                "action_type": "tool_call",
                "action_name": "Write",
                "details": json.dumps({"file": "output.py"}),
                "duration_ms": 50,
            },
            {
                "agent": "agent-polymorphic-agent",
                "action_type": "success",
                "action_name": "task_completed",
                "details": json.dumps({"files_created": 3}),
                "duration_ms": 10,
            },
        ]

        # Execute workflow by calling log-agent-action skill
        for action in workflow_actions:
            cmd: list[str] = [
                "python",
                str(
                    Path(__file__).parent.parent
                    / "claude-artifacts"
                    / "skills"
                    / "agent-tracking"
                    / "log-agent-action"
                    / "execute_kafka.py"
                ),
                "--agent",
                str(action["agent"]),
                "--action-type",
                str(action["action_type"]),
                "--action-name",
                str(action["action_name"]),
                "--correlation-id",
                correlation_id,
                "--debug-mode",  # Force debug mode
            ]

            if "details" in action:
                cmd.extend(["--details", str(action["details"])])

            if "duration_ms" in action:
                cmd.extend(["--duration-ms", str(action["duration_ms"])])

            # Execute skill
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, "DEBUG": "true"},
            )

            assert result.returncode == 0, f"Skill failed: {result.stderr}"

        # Wait for consumer to process all events
        await wait_for_records(
            db_pool,
            correlation_id=correlation_id,
            expected_count=len(workflow_actions),
            timeout_seconds=15.0,
        )

        # Verify all actions were persisted to PostgreSQL
        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                """
                SELECT agent_name, action_type, action_name, action_details, duration_ms
                FROM agent_actions
                WHERE correlation_id = $1
                ORDER BY created_at ASC
                """,
                correlation_id,
            )

            assert len(results) == len(
                workflow_actions
            ), f"Expected {len(workflow_actions)} records, got {len(results)}"

            for i, row in enumerate(results):
                expected = workflow_actions[i]
                assert row["agent_name"] == expected["agent"]
                assert row["action_type"] == expected["action_type"]
                assert row["action_name"] == expected["action_name"]

                if "duration_ms" in expected:
                    assert row["duration_ms"] == expected["duration_ms"]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("__clean_database")
    async def test_multi_agent_scenario(
        self, running_consumer, db_pool, wait_for_records
    ):
        """
        Test multiple agents logging concurrently.
        """
        correlation_id = str(uuid.uuid4())

        # Simulate multiple agents working in parallel
        agents = [
            "agent-api-architect",
            "agent-debug-intelligence",
            "agent-testing",
            "agent-performance",
        ]

        tasks = []
        for agent in agents:
            cmd = [
                "python",
                str(
                    Path(__file__).parent.parent
                    / "claude-artifacts"
                    / "skills"
                    / "agent-tracking"
                    / "log-agent-action"
                    / "execute_kafka.py"
                ),
                "--agent",
                agent,
                "--action-type",
                "tool_call",
                "--action-name",
                f"{agent}_action",
                "--correlation-id",
                correlation_id,
                "--debug-mode",
            ]

            # Run async
            task = asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "DEBUG": "true"},
            )
            tasks.append(task)

        # Wait for all agents to complete
        processes = await asyncio.gather(*tasks)
        await asyncio.gather(*[p.wait() for p in processes])

        # Wait for consumer to process all events
        await wait_for_records(
            db_pool,
            correlation_id=correlation_id,
            expected_count=len(agents),
            timeout_seconds=15.0,
        )

        # Verify all agents logged their actions
        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                """
                SELECT DISTINCT agent_name
                FROM agent_actions
                WHERE correlation_id = $1
                """,
                correlation_id,
            )

            logged_agents = {row["agent_name"] for row in results}
            assert logged_agents == set(
                agents
            ), f"Expected {set(agents)}, got {logged_agents}"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("__clean_database")
    async def test_data_integrity_verification(
        self, running_consumer, db_pool, wait_for_records
    ):
        """
        Verify data integrity across the pipeline:
        - No data loss
        - No corruption
        - Correct ordering
        """
        correlation_id = str(uuid.uuid4())

        # Create structured test data with checksums
        test_data = []
        for i in range(10):
            data = {
                "index": i,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "checksum": f"checksum-{i}",
            }
            test_data.append(data)

            cmd = [
                "python",
                str(
                    Path(__file__).parent.parent
                    / "claude-artifacts"
                    / "skills"
                    / "agent-tracking"
                    / "log-agent-action"
                    / "execute_kafka.py"
                ),
                "--agent",
                "test-agent",
                "--action-type",
                "tool_call",
                "--action-name",
                f"action_{i}",
                "--correlation-id",
                correlation_id,
                "--details",
                json.dumps(data),
                "--debug-mode",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, "DEBUG": "true"},
            )

            assert result.returncode == 0

        # Wait for consumer to process all events
        await wait_for_records(
            db_pool,
            correlation_id=correlation_id,
            expected_count=len(test_data),
            timeout_seconds=15.0,
        )

        # Verify data integrity
        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                """
                SELECT action_name, action_details
                FROM agent_actions
                WHERE correlation_id = $1
                ORDER BY created_at ASC
                """,
                correlation_id,
            )

            assert len(results) == len(
                test_data
            ), f"Expected {len(test_data)} records, got {len(results)}"

            for i, row in enumerate(results):
                details = json.loads(row["action_details"])
                expected = test_data[i]

                # Verify all fields match
                assert details["index"] == expected["index"]
                assert details["checksum"] == expected["checksum"]
                assert row["action_name"] == f"action_{i}"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("__clean_database")
    async def test_latency_measurement(self, running_consumer, db_pool):
        """
        Measure end-to-end latency from skill execution to database persistence.

        Targets:
        - Subprocess execution (includes Python startup, imports, Kafka publish): <1000ms
        - End-to-end persistence: <5s

        Note: Subprocess latency includes overhead from:
        - Python interpreter startup (~100-200ms)
        - Module imports (aiokafka, asyncpg, etc.) (~200-300ms)
        - Kafka connection to remote broker (~100-200ms)
        - Actual publish operation (~50-100ms)

        The 1000ms threshold is realistic for test environments with remote Kafka brokers.
        """
        correlation_id = str(uuid.uuid4())

        # Measure subprocess execution latency (not pure Kafka publish time)
        start_time = time.time()

        cmd = [
            "python",
            str(
                Path(__file__).parent.parent
                / "claude-artifacts"
                / "skills"
                / "agent-tracking"
                / "log-agent-action"
                / "execute_kafka.py"
            ),
            "--agent",
            "test-agent",
            "--action-type",
            "tool_call",
            "--action-name",
            "latency_test",
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "DEBUG": "true"},
        )

        publish_latency = (time.time() - start_time) * 1000  # ms

        assert result.returncode == 0
        assert (
            publish_latency < 1000
        ), f"Publish latency {publish_latency:.2f}ms exceeds 1000ms target"

        # Measure end-to-end latency
        e2e_start = time.time()
        max_wait = 10.0  # 10 seconds max

        while (time.time() - e2e_start) < max_wait:
            async with db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    "SELECT id FROM agent_actions WHERE correlation_id = $1",
                    correlation_id,
                )

                if result:
                    e2e_latency = (time.time() - e2e_start) * 1000  # ms
                    print(f"✅ E2E latency: {e2e_latency:.2f}ms")
                    print(f"✅ Publish latency: {publish_latency:.2f}ms")

                    assert (
                        e2e_latency < 5000
                    ), f"E2E latency {e2e_latency:.2f}ms exceeds 5s target"
                    return

            await asyncio.sleep(0.1)

        pytest.fail(f"Event not persisted within {max_wait}s")

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("__clean_database")
    async def test_error_recovery(
        self, kafka_brokers, postgres_dsn, db_pool, wait_for_records
    ):
        """
        Test error recovery scenarios:
        - Consumer restarts after crash
        - Messages are not lost
        - Duplicate handling works
        """
        correlation_id = str(uuid.uuid4())

        # Start consumer
        consumer = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic="agent-actions",
            postgres_dsn=postgres_dsn,
            group_id="error-recovery-test",
            batch_timeout_seconds=1.0,
        )

        await consumer.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        consumer_task = asyncio.create_task(consumer.consume_loop())

        # Publish event
        cmd = [
            "python",
            str(
                Path(__file__).parent.parent
                / "claude-artifacts"
                / "skills"
                / "agent-tracking"
                / "log-agent-action"
                / "execute_kafka.py"
            ),
            "--agent",
            "test-agent",
            "--action-type",
            "tool_call",
            "--action-name",
            "recovery_test",
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "DEBUG": "true"},
        )

        # Wait for first processing
        await wait_for_records(
            db_pool,
            correlation_id=correlation_id,
            expected_count=1,
            timeout_seconds=10.0,
        )

        # Verify first processing
        async with db_pool.acquire() as conn:
            count1 = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
                correlation_id,
            )
            assert (
                count1 == 1
            ), f"Expected 1 record after first processing, got {count1}"

        # Simulate crash - stop consumer
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Restart consumer with same group_id
        consumer2 = KafkaAgentActionConsumer(
            kafka_brokers=kafka_brokers,
            topic="agent-actions",
            postgres_dsn=postgres_dsn,
            group_id="error-recovery-test",  # Same group
            batch_timeout_seconds=1.0,
        )

        await consumer2.start()

        # Give consumer time to subscribe
        await asyncio.sleep(0.5)

        consumer_task2 = asyncio.create_task(consumer2.consume_loop())

        # Wait a bit to ensure no duplicate processing
        await asyncio.sleep(3.0)

        # Verify no duplicate processing
        async with db_pool.acquire() as conn:
            count2 = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
                correlation_id,
            )
            assert count2 == 1, f"Expected 1 record (no duplicates), got {count2}"

        # Cleanup
        await consumer2.stop()
        consumer_task2.cancel()
        try:
            await consumer_task2
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
