#!/usr/bin/env python3
"""
Transformation Event Publisher - Kafka Integration

Publishes agent transformation events to Kafka for async logging to PostgreSQL.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from agents.lib.transformation_event_publisher import publish_transformation_event

    await publish_transformation_event(
        source_agent="polymorphic-agent",
        target_agent="agent-api-architect",
        transformation_reason="API design task detected",
        correlation_id=correlation_id,
        routing_confidence=0.92,
        transformation_duration_ms=45
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Separate topics per event type (started/completed/failed)
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type
"""

import asyncio
import atexit
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


# Event type enumeration following EVENT_BUS_INTEGRATION_PATTERNS
class TransformationEventType(str, Enum):
    """Agent transformation event types with standardized topic routing."""

    STARTED = "omninode.agent.transformation.started.v1"
    COMPLETED = "omninode.agent.transformation.completed.v1"
    FAILED = "omninode.agent.transformation.failed.v1"

    def get_topic_name(self) -> str:
        """
        Get Kafka topic name for this event type.

        Returns topic in format: omninode.agent.transformation.{action}.v1
        Following EVENT_BUS_INTEGRATION_PATTERNS standard.
        """
        return self.value


# Lazy-loaded Kafka producer (singleton)
_kafka_producer = None
_producer_lock = None


def _get_kafka_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment."""
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        # Fallback to default for local development
        servers = "localhost:29092"
        logger.warning(f"KAFKA_BOOTSTRAP_SERVERS not set, using default: {servers}")
    return servers


def _create_event_envelope(
    event_type: TransformationEventType,
    payload: Dict[str, Any],
    correlation_id: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create OnexEnvelopeV1 standard event envelope.

    Following EVENT_BUS_INTEGRATION_PATTERNS standards for consistent event structure.

    Args:
        event_type: Transformation event type enum
        payload: Event payload containing transformation data
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
        "timestamp": datetime.now(timezone.utc).isoformat(),  # RFC3339 format
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/agent/transformation_{event_type.name.lower()}/v1",
        "payload": payload,
    }


async def get_producer_lock():
    """
    Get or create the producer lock lazily under a running event loop.

    This ensures asyncio.Lock() is never created at module level, which
    would cause RuntimeError in Python 3.12+ when no event loop exists.

    Returns:
        asyncio.Lock: The producer lock instance
    """
    global _producer_lock
    if _producer_lock is None:
        _producer_lock = asyncio.Lock()
    return _producer_lock


async def _get_kafka_producer():
    """
    Get or create Kafka producer (async singleton pattern).

    Returns:
        AIOKafkaProducer instance or None if unavailable
    """
    global _kafka_producer

    if _kafka_producer is not None:
        return _kafka_producer

    # Get the lock (created lazily under running event loop)
    async with await get_producer_lock():
        # Double-check after acquiring lock
        if _kafka_producer is not None:
            return _kafka_producer

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


async def publish_transformation_event(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    correlation_id: Optional[str | UUID] = None,
    session_id: Optional[str | UUID] = None,
    user_request: Optional[str] = None,
    routing_confidence: Optional[float] = None,
    routing_strategy: Optional[str] = None,
    transformation_duration_ms: Optional[int] = None,
    initialization_duration_ms: Optional[int] = None,
    total_execution_duration_ms: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None,
    quality_score: Optional[float] = None,
    context_snapshot: Optional[Dict[str, Any]] = None,
    context_keys: Optional[list[str]] = None,
    context_size_bytes: Optional[int] = None,
    agent_definition_id: Optional[str | UUID] = None,
    parent_event_id: Optional[str | UUID] = None,
    event_type: TransformationEventType = TransformationEventType.COMPLETED,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: Optional[str] = None,
) -> bool:
    """
    Publish agent transformation event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to separate topics
    based on event type (started/completed/failed).

    Args:
        source_agent: Original agent identity (e.g., "polymorphic-agent")
        target_agent: Transformed agent identity (e.g., "agent-api-architect")
        transformation_reason: Why this transformation occurred
        correlation_id: Request correlation ID for distributed tracing
        session_id: Session ID for grouping related executions
        user_request: Original user request triggering transformation
        routing_confidence: Router confidence score (0.0-1.0)
        routing_strategy: Routing strategy used (e.g., "explicit", "fuzzy_match")
        transformation_duration_ms: Time to complete transformation
        initialization_duration_ms: Time to initialize target agent
        total_execution_duration_ms: Total execution time of target agent
        success: Whether transformation succeeded
        error_message: Error details if failed
        error_type: Error classification
        quality_score: Output quality score (0.0-1.0)
        context_snapshot: Full context at transformation time
        context_keys: Keys of context items passed to target agent
        context_size_bytes: Size of context for performance tracking
        agent_definition_id: Link to agent definition used
        parent_event_id: For nested transformations
        event_type: Event type enum (STARTED/COMPLETED/FAILED)
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Note:
        - Uses correlation_id as partition key for workflow coherence
        - Events are idempotent using correlation_id + event_type
        - Gracefully degrades when Kafka unavailable
    """
    try:
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        if session_id is not None:
            session_id = str(session_id)

        # Build event payload (everything except envelope metadata)
        payload = {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "transformation_reason": transformation_reason,
            "session_id": session_id,
            "user_request": user_request,
            "routing_confidence": routing_confidence,
            "routing_strategy": routing_strategy,
            "transformation_duration_ms": transformation_duration_ms,
            "initialization_duration_ms": initialization_duration_ms,
            "total_execution_duration_ms": total_execution_duration_ms,
            "success": success,
            "error_message": error_message,
            "error_type": error_type,
            "quality_score": quality_score,
            "context_snapshot": context_snapshot,
            "context_keys": context_keys,
            "context_size_bytes": context_size_bytes,
            "agent_definition_id": (
                str(agent_definition_id) if agent_definition_id else None
            ),
            "parent_event_id": str(parent_event_id) if parent_event_id else None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        # Remove None values to keep payload compact
        payload = {k: v for k, v in payload.items() if v is not None}

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
            event_type=event_type,
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
                "Kafka producer unavailable, transformation event not published"
            )
            return False

        # Get topic name from event type enum (separate topics per event type)
        topic = event_type.get_topic_name()

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published transformation event (OnexEnvelopeV1): {event_type.value} | "
            f"{source_agent} → {target_agent} | "
            f"correlation_id={correlation_id} | "
            f"topic={topic}"
        )
        return True

    except asyncio.TimeoutError:
        # Handle timeout specifically for better observability
        logger.error(
            f"Timeout publishing transformation event to Kafka "
            f"(event_type={event_type.value if isinstance(event_type, TransformationEventType) else event_type}, "
            f"source_agent={source_agent}, target_agent={target_agent}, "
            f"timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
            extra={"correlation_id": correlation_id},
        )
        return False

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(
            f"Failed to publish transformation event: {event_type.value if isinstance(event_type, TransformationEventType) else event_type}",
            exc_info=True,
        )
        return False


async def publish_transformation_start(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    correlation_id: Optional[str | UUID] = None,
    **kwargs,
) -> bool:
    """
    Publish transformation start event.

    Convenience method for publishing at the start of transformation.
    Publishes to topic: omninode.agent.transformation.started.v1
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        event_type=TransformationEventType.STARTED,
        **kwargs,
    )


async def publish_transformation_complete(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    correlation_id: Optional[str | UUID] = None,
    transformation_duration_ms: Optional[int] = None,
    **kwargs,
) -> bool:
    """
    Publish transformation complete event.

    Convenience method for publishing after successful transformation.
    Publishes to topic: omninode.agent.transformation.completed.v1
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        transformation_duration_ms=transformation_duration_ms,
        success=True,
        event_type=TransformationEventType.COMPLETED,
        **kwargs,
    )


async def publish_transformation_failed(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    error_message: str,
    correlation_id: Optional[str | UUID] = None,
    error_type: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    Publish transformation failed event.

    Convenience method for publishing after transformation failure.
    Publishes to topic: omninode.agent.transformation.failed.v1
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        error_message=error_message,
        error_type=error_type,
        success=False,
        event_type=TransformationEventType.FAILED,
        **kwargs,
    )


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


# Synchronous wrapper for backward compatibility
def publish_transformation_event_sync(
    source_agent: str, target_agent: str, transformation_reason: str, **kwargs
) -> bool:
    """
    Synchronous wrapper for publish_transformation_event.

    Creates new event loop if needed. Use async version when possible.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_transformation_event(
            source_agent=source_agent,
            target_agent=target_agent,
            transformation_reason=transformation_reason,
            **kwargs,
        )
    )


if __name__ == "__main__":
    # Test transformation event publishing
    async def test():
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        correlation_id = str(uuid4())

        # Test transformation start
        print("Testing transformation start event...")
        success_start = await publish_transformation_start(
            source_agent="polymorphic-agent",
            target_agent="agent-api-architect",
            transformation_reason="API design task detected",
            correlation_id=correlation_id,
            routing_confidence=0.92,
            routing_strategy="fuzzy_match",
            user_request="Design a REST API for user management",
        )
        print(f"Start event published: {success_start}")

        # Test transformation complete
        print("\nTesting transformation complete event...")
        success_complete = await publish_transformation_complete(
            source_agent="polymorphic-agent",
            target_agent="agent-api-architect",
            transformation_reason="API design task detected",
            correlation_id=correlation_id,
            routing_confidence=0.92,
            routing_strategy="fuzzy_match",
            transformation_duration_ms=45,
            user_request="Design a REST API for user management",
        )
        print(f"Complete event published: {success_complete}")

        # Test transformation failed
        print("\nTesting transformation failed event...")
        correlation_id_failed = str(uuid4())
        success_failed = await publish_transformation_failed(
            source_agent="polymorphic-agent",
            target_agent="agent-api-architect",
            transformation_reason="API design task detected",
            error_message="Agent initialization failed",
            error_type="InitializationError",
            correlation_id=correlation_id_failed,
        )
        print(f"Failed event published: {success_failed}")

        # Close producer
        print("\nClosing producer...")
        await close_producer()

        print("\n" + "=" * 60)
        print("Test Summary:")
        print(f"  Start Event:    {'✅' if success_start else '❌'}")
        print(f"  Complete Event: {'✅' if success_complete else '❌'}")
        print(f"  Failed Event:   {'✅' if success_failed else '❌'}")
        print("=" * 60)

    asyncio.run(test())
