#!/usr/bin/env python3
"""
Quality Gate Event Publisher - Kafka Integration

Publishes quality gate validation events to Kafka for async logging to PostgreSQL.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from agents.lib.quality_gate_publisher import publish_quality_gate_passed, publish_quality_gate_failed

    # Publish quality gate passed event
    await publish_quality_gate_passed(
        gate_name="input_validation",
        correlation_id=correlation_id,
        score=0.95,
        threshold=0.80,
        metrics={"validation_checks": 12, "passed_checks": 12}
    )

    # Publish quality gate failed event
    await publish_quality_gate_failed(
        gate_name="onex_compliance",
        correlation_id=correlation_id,
        score=0.65,
        threshold=0.80,
        failure_reasons=["Missing type hints", "Bare Any types detected"],
        recommendations=["Add type hints to all methods", "Replace Any with specific types"]
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Separate topic for failed events
- Correlation ID tracking for distributed tracing
- Partition key policy: correlation_id for workflow coherence
"""

import asyncio
import atexit
import json
import logging
import os
from asyncio import Lock
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

logger = logging.getLogger(__name__)


# Event type enumeration following EVENT_BUS_INTEGRATION_PATTERNS
class QualityGateEventType(str, Enum):
    """Quality gate event types with standardized topic routing."""

    PASSED = "omninode.agent.quality.gate.passed.v1"
    FAILED = "omninode.agent.quality.gate.failed.v1"

    def get_topic_name(self) -> str:
        """
        Get Kafka topic name for this event type.

        Returns topic in format: omninode.agent.quality.gate.{action}.v1
        Following EVENT_BUS_INTEGRATION_PATTERNS standard.
        """
        return self.value


# Lazy-loaded Kafka producer (singleton)
_kafka_producer = None
_producer_locks: WeakKeyDictionary = WeakKeyDictionary()


def _get_kafka_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment."""
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        # Fallback to default for local development
        servers = "localhost:29092"
        logger.warning(f"KAFKA_BOOTSTRAP_SERVERS not set, using default: {servers}")
    return servers


def _create_event_envelope(
    event_type: QualityGateEventType,
    payload: dict[str, Any],
    correlation_id: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> dict[str, Any]:
    """
    Create OnexEnvelopeV1 standard event envelope.

    Following EVENT_BUS_INTEGRATION_PATTERNS standards for consistent event structure.

    Args:
        event_type: Quality gate event type enum
        payload: Event payload containing quality gate data
        correlation_id: Correlation ID for distributed tracing
        source: Source service name (default: omniclaude)
        tenant_id: Tenant identifier (default: default)
        namespace: Event namespace (default: omninode)
        causation_id: Optional causation ID for event chains

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event
    """
    return {
        "event_type": event_type.value,
        "event_id": str(uuid4()),  # Unique event ID for idempotency
        "timestamp": datetime.now(UTC).isoformat(),  # RFC3339 format
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/agent/quality_gate_{event_type.name.lower()}/v1",
        "payload": payload,
    }


async def get_producer_lock() -> asyncio.Lock:
    """
    Get or create the producer lock for the current event loop.

    Uses WeakKeyDictionary to store per-event-loop locks, preventing
    "RuntimeError: Lock is bound to a different event loop" when
    switching between async and sync publishing contexts.

    Locks are automatically cleaned up when event loops are garbage collected.

    Returns:
        asyncio.Lock: Lock instance for the current event loop

    Raises:
        RuntimeError: If no event loop is running
    """
    # Get the current running event loop
    loop = asyncio.get_running_loop()

    # Get or create lock for this event loop
    if loop not in _producer_locks:
        _producer_locks[loop] = asyncio.Lock()

    return cast(Lock, _producer_locks[loop])


async def _get_kafka_producer():
    """
    Get or create Kafka producer (async singleton pattern).

    Returns:
        AIOKafkaProducer instance or None if unavailable
    """
    global _kafka_producer

    if _kafka_producer is not None:
        return _kafka_producer  # type: ignore[unreachable]

    # Get the lock (created lazily under running event loop)
    async with await get_producer_lock():
        # Double-check after acquiring lock
        if _kafka_producer is not None:
            return _kafka_producer  # type: ignore[unreachable]

        try:
            from aiokafka import AIOKafkaProducer

            bootstrap_servers = _get_kafka_bootstrap_servers()

            producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",
                linger_ms=10,  # Batch for 10ms
                acks=1,  # Leader acknowledgment (balance speed/reliability)
                max_batch_size=16384,  # 16KB batches
                request_timeout_ms=5000,  # 5 second timeout
            )

            await producer.start()
            _kafka_producer = producer
            logger.info(f"Kafka producer initialized: {bootstrap_servers}")
            return producer

        except ImportError:
            logger.error("aiokafka not installed. Install with: pip install aiokafka")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            return None


async def publish_quality_gate_passed(
    gate_name: str,
    correlation_id: str | UUID | None = None,
    score: float | None = None,
    threshold: float | None = None,
    metrics: dict[str, Any] | None = None,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> bool:
    """
    Publish quality gate passed event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and published to:
    omninode.agent.quality.gate.passed.v1

    Args:
        gate_name: Name of the quality gate that passed (e.g., "input_validation", "type_safety")
        correlation_id: Request correlation ID for distributed tracing
        score: Quality score achieved (0.0-1.0)
        threshold: Minimum required threshold (0.0-1.0)
        metrics: Additional metrics dictionary
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Note:
        - Uses correlation_id as partition key for workflow coherence
        - Events are idempotent using correlation_id + gate_name + timestamp
        - Gracefully degrades when Kafka unavailable
    """
    try:
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        # Build event payload (everything except envelope metadata)
        payload = {
            "gate_name": gate_name,
            "correlation_id": correlation_id,
            "score": score,
            "threshold": threshold,
            "passed_at": datetime.now(UTC).isoformat(),  # RFC3339
            "metrics": metrics or {},
        }

        # Remove None values to keep payload compact
        payload = {k: v for k, v in payload.items() if v is not None}

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
            event_type=QualityGateEventType.PASSED,
            payload=payload,
            correlation_id=correlation_id,
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Get producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning(
                "Kafka producer unavailable, quality gate passed event not published"
            )
            return False

        # Get topic name from event type enum
        topic = QualityGateEventType.PASSED.get_topic_name()

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka
        await producer.send_and_wait(topic, value=envelope, key=partition_key)

        logger.debug(
            f"Published quality gate passed event (OnexEnvelopeV1): "
            f"gate={gate_name} | score={score} | threshold={threshold} | "
            f"correlation_id={correlation_id} | topic={topic}"
        )
        return True

    except Exception:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(
            f"Failed to publish quality gate passed event: {gate_name}",
            exc_info=True,
        )
        return False


async def publish_quality_gate_failed(
    gate_name: str,
    correlation_id: str | UUID | None,
    score: float,
    threshold: float,
    failure_reasons: list[str],
    recommendations: list[str] | None = None,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> bool:
    """
    Publish quality gate failed event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and published to:
    omninode.agent.quality.gate.failed.v1

    Args:
        gate_name: Name of the quality gate that failed (e.g., "onex_compliance", "type_safety")
        correlation_id: Request correlation ID for distributed tracing
        score: Quality score achieved (0.0-1.0)
        threshold: Minimum required threshold (0.0-1.0)
        failure_reasons: List of reasons why the gate failed
        recommendations: List of recommendations to fix failures
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Note:
        - Uses correlation_id as partition key for workflow coherence
        - Events are idempotent using correlation_id + gate_name + timestamp
        - Gracefully degrades when Kafka unavailable
    """
    try:
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        # Build event payload (everything except envelope metadata)
        payload = {
            "gate_name": gate_name,
            "correlation_id": correlation_id,
            "score": score,
            "threshold": threshold,
            "failed_at": datetime.now(UTC).isoformat(),  # RFC3339
            "failure_reasons": failure_reasons,
            "recommendations": recommendations or [],
        }

        # Remove None values to keep payload compact
        payload = {k: v for k, v in payload.items() if v is not None}

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
            event_type=QualityGateEventType.FAILED,
            payload=payload,
            correlation_id=correlation_id,
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Get producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning(
                "Kafka producer unavailable, quality gate failed event not published"
            )
            return False

        # Get topic name from event type enum
        topic = QualityGateEventType.FAILED.get_topic_name()

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka
        await producer.send_and_wait(topic, value=envelope, key=partition_key)

        logger.debug(
            f"Published quality gate failed event (OnexEnvelopeV1): "
            f"gate={gate_name} | score={score:.2f} | threshold={threshold:.2f} | "
            f"correlation_id={correlation_id} | topic={topic}"
        )
        return True

    except Exception:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(
            f"Failed to publish quality gate failed event: {gate_name}",
            exc_info=True,
        )
        return False


async def close_producer():
    """Close Kafka producer on shutdown."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Kafka producer closed")
        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")
        finally:
            _kafka_producer = None


def _cleanup_producer_sync():
    """
    Synchronous wrapper for close_producer() to be called by atexit.

    This ensures the Kafka producer is closed when the Python interpreter
    exits, preventing resource leak warnings.

    Note: This function attempts graceful cleanup, but if the event loop
    is already closed (e.g., after asyncio.run()), it will forcefully
    close the producer's client connection to avoid resource warnings.
    """
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            # Try to get existing event loop
            try:
                loop = asyncio.get_running_loop()
                # Loop is running, can't cleanup synchronously
                # This will be handled by async cleanup
                return
            except RuntimeError:
                # No running loop, try to get the main event loop
                pass

            # Try to use existing event loop if available and not closed
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    loop.run_until_complete(close_producer())
                    return
            except RuntimeError:
                pass

            # Event loop is closed. The producer was created on a closed loop.
            # We can't use async cleanup, so directly close the underlying components.
            # This prevents ResourceWarning about unclosed producers.
            try:
                # Close all internal components to prevent resource warnings
                if hasattr(_kafka_producer, "_client") and _kafka_producer._client:
                    _kafka_producer._client.close()

                # Close sender if it exists
                if hasattr(_kafka_producer, "_sender"):
                    _kafka_producer._sender = None

                # Mark as closed
                if hasattr(_kafka_producer, "_closed"):
                    _kafka_producer._closed = True

                # Mark producer as None to prevent further cleanup attempts
                _kafka_producer = None
                logger.debug("Kafka producer fully closed (synchronous cleanup)")
            except Exception as inner_e:
                logger.debug(f"Error during synchronous client close: {inner_e}")
                # Last resort: just set to None
                _kafka_producer = None

        except Exception as e:
            # Best effort cleanup - don't raise on exit
            logger.debug(f"Error during atexit producer cleanup: {e}")
            # Ensure producer is cleared to avoid repeated cleanup attempts
            _kafka_producer = None


# Register cleanup on interpreter exit
atexit.register(_cleanup_producer_sync)


# Synchronous wrappers for backward compatibility
def publish_quality_gate_passed_sync(
    gate_name: str,
    **kwargs,
) -> bool:
    """
    Synchronous wrapper for publish_quality_gate_passed.

    Creates new event loop if needed. Use async version when possible.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_quality_gate_passed(gate_name=gate_name, **kwargs)
    )


def publish_quality_gate_failed_sync(
    gate_name: str,
    correlation_id: str | UUID | None,
    score: float,
    threshold: float,
    failure_reasons: list[str],
    **kwargs,
) -> bool:
    """
    Synchronous wrapper for publish_quality_gate_failed.

    Creates new event loop if needed. Use async version when possible.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_quality_gate_failed(
            gate_name=gate_name,
            correlation_id=correlation_id,
            score=score,
            threshold=threshold,
            failure_reasons=failure_reasons,
            **kwargs,
        )
    )


if __name__ == "__main__":
    # Test quality gate event publishing
    async def test():
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        correlation_id = str(uuid4())

        # Test quality gate passed event
        print("Testing quality gate passed event...")
        success_passed = await publish_quality_gate_passed(
            gate_name="input_validation",
            correlation_id=correlation_id,
            score=0.95,
            threshold=0.80,
            metrics={
                "validation_checks": 12,
                "passed_checks": 12,
                "execution_time_ms": 45,
            },
        )
        print(f"Quality gate passed event published: {success_passed}")

        # Test quality gate failed event
        print("\nTesting quality gate failed event...")
        correlation_id_2 = str(uuid4())
        success_failed = await publish_quality_gate_failed(
            gate_name="onex_compliance",
            correlation_id=correlation_id_2,
            score=0.65,
            threshold=0.80,
            failure_reasons=[
                "Missing type hints on 3 methods",
                "Found 2 instances of bare 'Any' type",
                "Invalid node class name 'NodeTestEffect'",
            ],
            recommendations=[
                "Add type hints to all method signatures",
                "Replace bare 'Any' with Dict[str, Any] or specific types",
                "Ensure node class follows pattern: Node<Domain><Service><Type>",
            ],
        )
        print(f"Quality gate failed event published: {success_failed}")

        # Test another quality gate failure
        print("\nTesting type safety gate failure...")
        correlation_id_3 = str(uuid4())
        success_failed_2 = await publish_quality_gate_failed(
            gate_name="type_safety",
            correlation_id=correlation_id_3,
            score=0.45,
            threshold=0.70,
            failure_reasons=[
                "Methods missing return type annotations",
                "Incomplete generic types detected (Dict, List without type parameters)",
            ],
            recommendations=[
                "Add return type annotations to all methods",
                "Specify type parameters for all generic types",
            ],
        )
        print(f"Type safety gate failed event published: {success_failed_2}")

        # Close producer
        print("\nClosing producer...")
        await close_producer()

        print("\n" + "=" * 60)
        print("Test Summary:")
        print(f"  Passed Event:                {'✅' if success_passed else '❌'}")
        print(f"  ONEX Compliance Failed Event: {'✅' if success_failed else '❌'}")
        print(f"  Type Safety Failed Event:     {'✅' if success_failed_2 else '❌'}")
        print("=" * 60)

    asyncio.run(test())
