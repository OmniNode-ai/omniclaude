# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Real-bus integration tests for ONEX routing emission via Kafka.

Ticket: OMN-1928 — [P5] Validation
Parent: OMN-1922 (Extract Agent Routing to ONEX Nodes)

These tests connect to the LIVE Redpanda instance at 192.168.86.200:29092
and verify that routing decision events:
    1. Are published to onex.evt.omniclaude.routing-decision.v1
    2. Can be consumed with correct schema
    3. Preserve all fields from ModelEmissionRequest
    4. Meet latency targets (<100ms p95)

Run with:
    source .env && KAFKA_INTEGRATION_TESTS=real \\
        pytest tests/integration/test_onex_kafka_real_bus.py -v

Requirements:
    - KAFKA_BOOTSTRAP_SERVERS must be set (e.g., 192.168.86.200:29092)
    - KAFKA_INTEGRATION_TESTS must equal "real" (disables conftest mock)
    - Topic onex.evt.omniclaude.routing-decision.v1 must exist on broker
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest

# --------------------------------------------------------------------------
# Path setup
# --------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parents[2]
_SRC = _PROJECT_ROOT / "src"
_HOOKS_LIB = _PROJECT_ROOT / "plugins" / "onex" / "hooks" / "lib"

for p in (_SRC, _HOOKS_LIB):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelConfidenceBreakdown,
)
from omniclaude.nodes.node_routing_emission_effect.handler_routing_emitter import (
    TOPIC_EVT,
    HandlerRoutingEmitter,
)
from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionRequest,
)

# --------------------------------------------------------------------------
# Markers — all tests require real Kafka
# --------------------------------------------------------------------------

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.slow,
]

# Skip entire module unless KAFKA_INTEGRATION_TESTS=real
_REAL_BUS = os.getenv("KAFKA_INTEGRATION_TESTS") == "real"
if not _REAL_BUS:
    pytest.skip(
        "Skipping real-bus tests (set KAFKA_INTEGRATION_TESTS=real to enable)",
        allow_module_level=True,
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _get_bootstrap_servers() -> str:
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS environment variable is required")
    return servers


RoutingPolicy = Literal["trigger_match", "explicit_request", "fallback_default"]


def _make_emission_request(
    agent: str = "agent-testing",
    confidence: float = 0.85,
    policy: RoutingPolicy = "trigger_match",
    session_id: str | None = None,
) -> ModelEmissionRequest:
    """Build a valid ModelEmissionRequest for testing."""
    return ModelEmissionRequest(
        correlation_id=uuid4(),
        session_id=session_id or f"real-bus-test-{uuid4().hex[:12]}",
        selected_agent=agent,
        confidence=confidence,
        confidence_breakdown=ModelConfidenceBreakdown(
            total=confidence,
            trigger_score=confidence,
            context_score=0.7,
            capability_score=0.5,
            historical_score=0.5,
            explanation=f"Real-bus integration test for {agent}",
        ),
        routing_policy=policy,
        routing_path="local",
        prompt_preview="Integration test: validate ONEX routing emission",
        prompt_length=50,
        emitted_at=datetime.now(UTC),
    )


async def _consume_one(
    topic: str,
    match_fn: Any,
    timeout_seconds: float = 10.0,
) -> dict[str, Any] | None:
    """Consume messages until match_fn returns True or timeout."""
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return None

    group = f"real-bus-test-{uuid4().hex[:8]}"
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=_get_bootstrap_servers(),
        group_id=group,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        consumer_timeout_ms=int(timeout_seconds * 1000),
    )

    try:
        await consumer.start()
        # Seek to end so we only see new messages
        await consumer.seek_to_end()
        await asyncio.sleep(0.3)

        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_seconds:
            result = await consumer.getmany(timeout_ms=500, max_records=50)
            for _tp, records in result.items():
                for record in records:
                    try:
                        payload: dict[str, Any] = json.loads(
                            record.value.decode("utf-8")
                        )
                        if match_fn(payload):
                            return payload
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        return None
    finally:
        await consumer.stop()


def _make_real_kafka_emit_fn() -> Any:
    """Create an emit_fn that publishes directly to Kafka via aiokafka.

    Each call creates a fresh producer connection.  This is suitable for
    correctness tests where connection overhead doesn't matter.

    Returns a synchronous function matching the EmitFn signature:
        (event_type: str, payload: dict) -> bool
    """
    try:
        from aiokafka import AIOKafkaProducer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return None

    async def _async_publish(event_type: str, payload: dict[str, object]) -> bool:
        """Publish payload to the routing decision topic."""
        producer = AIOKafkaProducer(
            bootstrap_servers=_get_bootstrap_servers(),
        )
        try:
            await producer.start()
            message = json.dumps(payload).encode("utf-8")
            key = payload.get("session_id", "unknown")
            if isinstance(key, str):
                key = key.encode("utf-8")
            await producer.send_and_wait(
                TOPIC_EVT,
                value=message,
                key=key,
            )
            return True
        except Exception as e:
            print(f"Real Kafka publish failed: {e}")
            return False
        finally:
            await producer.stop()

    def sync_publish(event_type: str, payload: dict[str, object]) -> bool:
        """Synchronous wrapper for async publish."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_async_publish(event_type, payload))
        finally:
            loop.close()

    return sync_publish


async def _emit_with_persistent_producer(
    producer: Any,
    payload: dict[str, object],
) -> bool:
    """Publish a single message using a pre-started producer."""
    message = json.dumps(payload).encode("utf-8")
    key = payload.get("session_id", "unknown")
    if isinstance(key, str):
        key = key.encode("utf-8")
    await producer.send_and_wait(TOPIC_EVT, value=message, key=key)
    return True


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
async def kafka_health():
    """Skip if Kafka is unreachable."""
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return

    consumer = AIOKafkaConsumer(
        bootstrap_servers=_get_bootstrap_servers(),
        group_id=f"health-{uuid4().hex[:8]}",
    )
    try:
        await asyncio.wait_for(consumer.start(), timeout=5.0)
        await consumer.stop()
    except Exception as e:
        pytest.skip(f"Kafka unreachable at {_get_bootstrap_servers()}: {e}")


# --------------------------------------------------------------------------
# Tests: Real Kafka emission via HandlerRoutingEmitter
# --------------------------------------------------------------------------


class TestRealBusRoutingEmission:
    """End-to-end tests: HandlerRoutingEmitter -> real Kafka -> consume."""

    async def test_emit_routing_decision_reaches_kafka(self, kafka_health) -> None:
        """Emit a routing decision via HandlerRoutingEmitter and consume it."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        request = _make_emission_request(
            agent="agent-api-architect",
            confidence=0.92,
            policy="trigger_match",
        )

        # Start consumer BEFORE emitting
        consumer_task = asyncio.create_task(
            _consume_one(
                TOPIC_EVT,
                match_fn=lambda p: p.get("session_id") == request.session_id,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        # Emit via handler
        result = await emitter.emit_routing_decision(request)
        assert result.success is True, f"Emission failed: {result.error}"
        assert result.duration_ms >= 0.0

        # Consume from Kafka
        message = await consumer_task
        assert message is not None, (
            f"Routing decision not found on {TOPIC_EVT} "
            f"(session_id={request.session_id})"
        )

        # Validate payload fields
        assert message["selected_agent"] == "agent-api-architect"
        assert message["confidence"] == 0.92
        assert message["routing_policy"] == "trigger_match"
        assert message["routing_path"] == "local"
        assert message["session_id"] == request.session_id
        assert message["prompt_length"] == 50
        assert len(message["prompt_preview"]) <= 100
        assert message["correlation_id"] == str(request.correlation_id)

    async def test_emitted_confidence_breakdown_schema(self, kafka_health) -> None:
        """Verify confidence_breakdown is correctly serialized on Kafka."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        request = _make_emission_request(confidence=0.78)

        consumer_task = asyncio.create_task(
            _consume_one(
                TOPIC_EVT,
                match_fn=lambda p: p.get("session_id") == request.session_id,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        result = await emitter.emit_routing_decision(request)
        assert result.success is True

        message = await consumer_task
        assert message is not None

        breakdown = message["confidence_breakdown"]
        assert isinstance(breakdown, dict)
        assert breakdown["total"] == 0.78
        assert breakdown["trigger_score"] == 0.78
        assert breakdown["context_score"] == 0.7
        assert breakdown["capability_score"] == 0.5
        assert breakdown["historical_score"] == 0.5
        assert "explanation" in breakdown
        assert len(breakdown["explanation"]) > 0

    async def test_emitted_at_timestamp_is_iso8601(self, kafka_health) -> None:
        """Verify emitted_at is a valid ISO-8601 timestamp."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        before = datetime.now(UTC)
        request = _make_emission_request()
        after = datetime.now(UTC)

        consumer_task = asyncio.create_task(
            _consume_one(
                TOPIC_EVT,
                match_fn=lambda p: p.get("session_id") == request.session_id,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        result = await emitter.emit_routing_decision(request)
        assert result.success is True

        message = await consumer_task
        assert message is not None

        ts_str = message["emitted_at"]
        # Parse ISO-8601
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        emitted_at = datetime.fromisoformat(ts_str)
        assert emitted_at >= before
        assert emitted_at <= after

    async def test_routing_policies_preserved(self, kafka_health) -> None:
        """Verify all three routing policies round-trip through Kafka."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        for policy in ("trigger_match", "explicit_request", "fallback_default"):
            request = _make_emission_request(policy=policy)

            consumer_task = asyncio.create_task(
                _consume_one(
                    TOPIC_EVT,
                    match_fn=lambda p, sid=request.session_id: p.get("session_id")
                    == sid,
                    timeout_seconds=10.0,
                )
            )
            await asyncio.sleep(0.5)

            result = await emitter.emit_routing_decision(request)
            assert result.success is True, f"Failed for policy={policy}: {result.error}"

            message = await consumer_task
            assert message is not None, f"No message for policy={policy}"
            assert message["routing_policy"] == policy


# --------------------------------------------------------------------------
# Tests: Performance validation with real Kafka
# --------------------------------------------------------------------------


class TestRealBusEmissionPerformance:
    """Latency benchmarks against real Kafka with persistent producer.

    Uses a persistent producer connection to measure actual publish latency,
    matching production behavior where the emit daemon holds a long-lived
    Kafka connection.  Targets: p50 <50ms, p95 <100ms.
    """

    async def test_emission_latency_targets(self, kafka_health) -> None:
        """Emit 20 routing decisions via persistent producer, measure p50/p95."""
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=_get_bootstrap_servers(),
        )
        await producer.start()

        try:
            latencies: list[float] = []
            n = 20

            for i in range(n):
                request = _make_emission_request(
                    agent=f"agent-perf-{i}",
                    session_id=f"perf-{uuid4().hex[:8]}",
                )
                payload = HandlerRoutingEmitter._build_payload(
                    request, request.correlation_id
                )

                start = time.monotonic()
                await _emit_with_persistent_producer(producer, payload)
                elapsed_ms = (time.monotonic() - start) * 1000.0

                latencies.append(elapsed_ms)

            latencies.sort()
            p50 = statistics.median(latencies)
            p95_idx = int(len(latencies) * 0.95)
            p95 = latencies[min(p95_idx, len(latencies) - 1)]

            print(f"\n--- Real Kafka Emission Latency ({n} samples, persistent) ---")
            print(f"  p50: {p50:.2f}ms")
            print(f"  p95: {p95:.2f}ms")
            print(f"  min: {min(latencies):.2f}ms")
            print(f"  max: {max(latencies):.2f}ms")

            # Acceptance criteria from OMN-1928
            assert p95 < 100.0, f"p95 latency {p95:.2f}ms exceeds 100ms target"
            assert p50 < 50.0, f"p50 latency {p50:.2f}ms exceeds 50ms target"
        finally:
            await producer.stop()


# --------------------------------------------------------------------------
# Tests: Golden corpus field agreement on Kafka
# --------------------------------------------------------------------------


class TestRealBusGoldenCorpusFields:
    """Verify golden corpus tolerance fields survive Kafka round-trip."""

    async def test_confidence_tolerance(self, kafka_health) -> None:
        """Confidence value must round-trip through Kafka within ±0.05."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        test_values = [0.0, 0.25, 0.5, 0.75, 0.85, 0.95, 1.0]

        for expected_confidence in test_values:
            request = _make_emission_request(confidence=expected_confidence)

            consumer_task = asyncio.create_task(
                _consume_one(
                    TOPIC_EVT,
                    match_fn=lambda p, sid=request.session_id: p.get("session_id")
                    == sid,
                    timeout_seconds=10.0,
                )
            )
            await asyncio.sleep(0.5)

            result = await emitter.emit_routing_decision(request)
            assert result.success is True

            message = await consumer_task
            assert message is not None, (
                f"No message for confidence={expected_confidence}"
            )

            actual = message["confidence"]
            tolerance = 0.05
            assert abs(actual - expected_confidence) <= tolerance, (
                f"Confidence mismatch: expected {expected_confidence}, "
                f"got {actual} (tolerance ±{tolerance})"
            )

    async def test_selected_agent_exact_match(self, kafka_health) -> None:
        """selected_agent must be exact match after Kafka round-trip."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        agents = [
            "polymorphic-agent",
            "agent-api-architect",
            "agent-debugger",
            "agent-testing",
        ]

        for agent in agents:
            request = _make_emission_request(agent=agent)

            consumer_task = asyncio.create_task(
                _consume_one(
                    TOPIC_EVT,
                    match_fn=lambda p, sid=request.session_id: p.get("session_id")
                    == sid,
                    timeout_seconds=15.0,
                )
            )
            # Allow more time for consumer to subscribe and join group
            await asyncio.sleep(1.5)

            result = await emitter.emit_routing_decision(request)
            assert result.success is True

            message = await consumer_task
            assert message is not None, f"No message for agent={agent}"
            assert message["selected_agent"] == agent, (
                f"Agent mismatch: expected {agent}, got {message['selected_agent']}"
            )

    async def test_routing_policy_exact_match(self, kafka_health) -> None:
        """routing_policy must be exact match after Kafka round-trip."""
        emit_fn = _make_real_kafka_emit_fn()
        emitter = HandlerRoutingEmitter(emit_fn=emit_fn)

        for policy in ("trigger_match", "explicit_request", "fallback_default"):
            request = _make_emission_request(policy=policy)

            consumer_task = asyncio.create_task(
                _consume_one(
                    TOPIC_EVT,
                    match_fn=lambda p, sid=request.session_id: p.get("session_id")
                    == sid,
                    timeout_seconds=10.0,
                )
            )
            await asyncio.sleep(0.5)

            result = await emitter.emit_routing_decision(request)
            assert result.success is True

            message = await consumer_task
            assert message is not None, f"No message for policy={policy}"
            assert message["routing_policy"] == policy, (
                f"Policy mismatch: expected {policy}, got {message['routing_policy']}"
            )
