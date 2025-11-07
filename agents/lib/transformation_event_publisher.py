#!/usr/bin/env python3
"""
Transformation Event Publisher - Kafka Integration

Publishes agent transformation events to Kafka for async logging to PostgreSQL.
Lightweight, non-blocking, with graceful degradation if Kafka is unavailable.

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
- JSON serialization with datetime handling
- Correlation ID tracking for distributed tracing
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

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
    event_type: str = "transformation_complete",
) -> bool:
    """
    Publish agent transformation event to Kafka.

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
        event_type: Event type (transformation_start, transformation_complete, transformation_failed)

    Returns:
        bool: True if published successfully, False otherwise
    """
    try:
        # Generate IDs if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        if session_id is not None:
            session_id = str(session_id)

        # Build event payload
        event = {
            "event_type": event_type,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "transformation_reason": transformation_reason,
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        # Remove None values to keep payload compact
        event = {k: v for k, v in event.items() if v is not None}

        # Get producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning(
                "Kafka producer unavailable, transformation event not published"
            )
            return False

        # Publish to Kafka
        topic = "agent-transformation-events"
        partition_key = correlation_id.encode("utf-8")

        await producer.send_and_wait(topic, value=event, key=partition_key)

        logger.debug(
            f"Published transformation event: {source_agent} → {target_agent} "
            f"(correlation_id={correlation_id})"
        )
        return True

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(f"Failed to publish transformation event: {e}", exc_info=True)
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
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        event_type="transformation_start",
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
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        transformation_duration_ms=transformation_duration_ms,
        success=True,
        event_type="transformation_complete",
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
    """
    return await publish_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        transformation_reason=transformation_reason,
        correlation_id=correlation_id,
        error_message=error_message,
        error_type=error_type,
        success=False,
        event_type="transformation_failed",
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

        # Test transformation complete
        success = await publish_transformation_complete(
            source_agent="polymorphic-agent",
            target_agent="agent-api-architect",
            transformation_reason="API design task detected",
            correlation_id=str(uuid4()),
            routing_confidence=0.92,
            routing_strategy="fuzzy_match",
            transformation_duration_ms=45,
            user_request="Design a REST API for user management",
        )

        print(f"Transformation event published: {success}")

        # Close producer
        await close_producer()

    asyncio.run(test())
