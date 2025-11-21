#!/usr/bin/env python3
"""
Confidence Scoring Event Publisher - Kafka Integration

Publishes agent confidence scoring events to Kafka for async logging to PostgreSQL.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from agents.lib.confidence_scoring_publisher import publish_confidence_scored

    await publish_confidence_scored(
        agent_name="agent-api-architect",
        confidence_score=0.92,
        routing_strategy="enhanced_fuzzy_matching",
        correlation_id=correlation_id,
        factors={
            "trigger_score": 0.95,
            "context_score": 0.88,
            "capability_score": 0.90,
            "historical_score": 0.85
        }
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type
- Partition key: correlation_id (following EVENT_BUS_INTEGRATION_GUIDE)

Reference:
- EVENT_ALIGNMENT_PLAN.md: Task 1.7 (OMN-33)
- Partition key policy: correlation_id (agent.confidence family)
"""

import asyncio
import atexit
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


logger = logging.getLogger(__name__)

# Event type constant following EVENT_BUS_INTEGRATION_PATTERNS
EVENT_TYPE = "omninode.agent.confidence.scored.v1"
TOPIC_NAME = "omninode.agent.confidence.scored.v1"

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
        payload: Event payload containing confidence scoring data
        correlation_id: Correlation ID for distributed tracing
        source: Source service name (default: omniclaude)
        tenant_id: Tenant identifier (default: default)
        namespace: Event namespace (default: omninode)
        causation_id: Optional causation ID for event chains

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event
    """
    return {
        "event_type": EVENT_TYPE,
        "event_id": str(uuid4()),  # Unique event ID for idempotency
        "timestamp": datetime.now(timezone.utc).isoformat(),  # RFC3339 format
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/agent/confidence_scored/v1",
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


async def publish_confidence_scored(
    agent_name: str,
    confidence_score: float,
    routing_strategy: str,
    correlation_id: Optional[str | UUID] = None,
    factors: Optional[Dict[str, Any]] = None,
    scored_at: Optional[str] = None,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: Optional[str] = None,
) -> bool:
    """
    Publish agent confidence scoring event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and published to:
    - Topic: omninode.agent.confidence.scored.v1
    - Partition key: correlation_id (for request→result ordering)

    Args:
        agent_name: Selected agent name (e.g., "agent-api-architect")
        confidence_score: Overall confidence score (0.0-1.0)
        routing_strategy: Strategy used for routing (e.g., "enhanced_fuzzy_matching")
        correlation_id: Request correlation ID for distributed tracing
        factors: Confidence scoring factors (dict with trigger_score, context_score, etc.)
        scored_at: ISO8601/RFC3339 timestamp when scoring occurred (auto-generated if None)
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        >>> await publish_confidence_scored(
        ...     agent_name="agent-api-architect",
        ...     confidence_score=0.92,
        ...     routing_strategy="enhanced_fuzzy_matching",
        ...     correlation_id="abc-123",
        ...     factors={
        ...         "trigger_score": 0.95,
        ...         "context_score": 0.88,
        ...         "capability_score": 0.90,
        ...         "historical_score": 0.85
        ...     }
        ... )

    Note:
        - Uses correlation_id as partition key for workflow coherence
        - Events are idempotent using correlation_id + event_type
        - Gracefully degrades when Kafka unavailable
        - Follows partition key policy from EVENT_BUS_INTEGRATION_GUIDE
    """
    try:
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        # Generate scored_at timestamp if not provided
        if scored_at is None:
            scored_at = datetime.now(timezone.utc).isoformat()

        # Build event payload (following schema from EVENT_ALIGNMENT_PLAN.md)
        payload = {
            "agent_name": agent_name,
            "confidence_score": confidence_score,
            "routing_strategy": routing_strategy,
            "correlation_id": correlation_id,
            "scored_at": scored_at,
            "factors": factors or {},
        }

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
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
                "Kafka producer unavailable, confidence scoring event not published"
            )
            return False

        # Use correlation_id as partition key for workflow coherence
        # (preserves request→result ordering per routing decision)
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka
        await producer.send_and_wait(TOPIC_NAME, value=envelope, key=partition_key)

        logger.debug(
            f"Published confidence scoring event (OnexEnvelopeV1): {EVENT_TYPE} | "
            f"agent={agent_name} | confidence={confidence_score:.2%} | "
            f"strategy={routing_strategy} | correlation_id={correlation_id}"
        )
        return True

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(
            f"Failed to publish confidence scoring event: {EVENT_TYPE}",
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


# Synchronous wrapper for backward compatibility
def publish_confidence_scored_sync(
    agent_name: str,
    confidence_score: float,
    routing_strategy: str,
    **kwargs,
) -> bool:
    """
    Synchronous wrapper for publish_confidence_scored.

    Creates new event loop if needed. Use async version when possible.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_confidence_scored(
            agent_name=agent_name,
            confidence_score=confidence_score,
            routing_strategy=routing_strategy,
            **kwargs,
        )
    )


if __name__ == "__main__":
    # Test confidence scoring event publishing
    async def test():
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        correlation_id = str(uuid4())

        # Test confidence scoring event
        print("Testing confidence scoring event...")
        success = await publish_confidence_scored(
            agent_name="agent-api-architect",
            confidence_score=0.92,
            routing_strategy="enhanced_fuzzy_matching",
            correlation_id=correlation_id,
            factors={
                "trigger_score": 0.95,
                "context_score": 0.88,
                "capability_score": 0.90,
                "historical_score": 0.85,
            },
        )
        print(f"Confidence scoring event published: {success}")

        # Close producer
        print("\nClosing producer...")
        await close_producer()

        print("\n" + "=" * 60)
        print("Test Summary:")
        print(f"  Confidence Scoring Event: {'✅' if success else '❌'}")
        print("=" * 60)

    asyncio.run(test())
