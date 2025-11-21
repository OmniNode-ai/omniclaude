#!/usr/bin/env python3
"""
Provider Selection Event Publisher - Kafka Integration

Publishes AI provider selection events to Kafka for tracking provider/model choices.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from agents.lib.provider_selection_publisher import publish_provider_selection

    await publish_provider_selection(
        provider_name="gemini-flash",
        model_name="gemini-1.5-flash-002",
        correlation_id=correlation_id,
        selection_reason="Cost-effective for high-volume pattern matching",
        selection_criteria={
            "cost_per_token": 0.000001,
            "latency_ms": 50,
            "quality_score": 0.85
        }
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Topic: omninode.agent.provider.selected.v1
- Partition key: correlation_id (for ordering by request)
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type

Event Schema:
    {
        "provider_name": "string",        # Provider name (gemini-flash, claude, etc.)
        "model_name": "string",           # Model name (gemini-1.5-flash-002, etc.)
        "correlation_id": "uuid-v7",      # Request correlation ID
        "selection_reason": "string",     # Human-readable selection rationale
        "selection_criteria": {},         # Structured selection criteria
        "selected_at": "RFC3339"          # Timestamp of selection
    }

Created: 2025-11-13
Reference: OMN-32, EVENT_ALIGNMENT_PLAN.md
"""

import asyncio
import atexit
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4


logger = logging.getLogger(__name__)


# Topic for provider selection events (following standard naming)
PROVIDER_SELECTION_TOPIC = "omninode.agent.provider.selected.v1"

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
        payload: Event payload containing provider selection data
        correlation_id: Correlation ID for distributed tracing
        source: Source service name (default: omniclaude)
        tenant_id: Tenant identifier (default: default)
        namespace: Event namespace (default: omninode)
        causation_id: Optional causation ID for event chains

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event
    """
    return {
        "event_type": PROVIDER_SELECTION_TOPIC,
        "event_id": str(uuid4()),  # Unique event ID for idempotency
        "timestamp": datetime.now(timezone.utc).isoformat(),  # RFC3339 format
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/agent/provider_selected/v1",
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

            # Create producer with optimized settings
            producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",  # Compress events
                acks="all",  # Wait for all replicas
                retries=3,  # Retry on transient failures
                max_in_flight_requests_per_connection=5,
                enable_idempotence=True,  # Exactly-once semantics
            )

            await producer.start()
            _kafka_producer = producer

            # Register cleanup handler
            atexit.register(_sync_cleanup_on_exit)

            logger.info(
                f"Kafka producer started for provider selection events (servers: {bootstrap_servers})"
            )
            return producer

        except Exception as e:
            logger.error(
                f"Failed to initialize Kafka producer for provider selection: {e}",
                exc_info=True,
            )
            return None


async def _cleanup_producer():
    """Cleanup Kafka producer on exit."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Kafka producer for provider selection events stopped")
        except Exception as e:
            logger.error(f"Error stopping provider selection Kafka producer: {e}")
        finally:
            _kafka_producer = None


def _sync_cleanup_on_exit():
    """Synchronous cleanup for atexit - handles event loop closure."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Event loop still running - schedule cleanup
            loop.create_task(_cleanup_producer())
        else:
            # Event loop stopped - run cleanup synchronously
            loop.run_until_complete(_cleanup_producer())
    except RuntimeError:
        # Event loop already closed - call producer.close() directly
        if _kafka_producer and hasattr(_kafka_producer, "close"):
            try:
                _kafka_producer.close()
            except Exception:
                pass  # Best effort cleanup


async def publish_provider_selection(
    provider_name: str,
    model_name: str,
    correlation_id: str,
    selection_reason: str,
    selection_criteria: Optional[Dict[str, Any]] = None,
    causation_id: Optional[str] = None,
) -> bool:
    """
    Publish provider selection event to Kafka.

    Non-blocking async publishing with graceful degradation.
    Logs error but doesn't fail execution if Kafka is unavailable.

    Args:
        provider_name: Provider name (e.g., "gemini-flash", "claude", "openai")
        model_name: Model name (e.g., "gemini-1.5-flash-002", "claude-3-5-sonnet-20241022")
        correlation_id: Request correlation ID for tracing
        selection_reason: Human-readable selection rationale
        selection_criteria: Optional structured selection criteria (cost, latency, quality, etc.)
        causation_id: Optional causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        >>> await publish_provider_selection(
        ...     provider_name="gemini-flash",
        ...     model_name="gemini-1.5-flash-002",
        ...     correlation_id="abc-123",
        ...     selection_reason="Cost-effective for high-volume pattern matching",
        ...     selection_criteria={
        ...         "cost_per_token": 0.000001,
        ...         "latency_ms": 50,
        ...         "quality_score": 0.85
        ...     }
        ... )
        True
    """
    try:
        # Create payload following EVENT_ALIGNMENT_PLAN schema
        payload = {
            "provider_name": provider_name,
            "model_name": model_name,
            "correlation_id": correlation_id,
            "selection_reason": selection_reason,
            "selection_criteria": selection_criteria or {},
            "selected_at": datetime.now(timezone.utc).isoformat(),  # RFC3339 format
        }

        # Wrap in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        # Get or create Kafka producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning(
                "Kafka producer unavailable - provider selection event not published"
            )
            return False

        # Publish to Kafka with partition key = correlation_id (for ordering)
        # This ensures all events for same request land on same partition
        start_time = time.time()
        await producer.send_and_wait(
            topic=PROVIDER_SELECTION_TOPIC,
            value=envelope,
            key=correlation_id.encode("utf-8"),  # Partition key
        )
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Published provider selection event: provider={provider_name}, "
            f"model={model_name}, correlation_id={correlation_id}, "
            f"duration={duration_ms:.1f}ms"
        )
        return True

    except Exception as e:
        logger.error(
            f"Failed to publish provider selection event: {e}",
            exc_info=True,
            extra={
                "provider_name": provider_name,
                "model_name": model_name,
                "correlation_id": correlation_id,
            },
        )
        return False


# Convenience function for synchronous contexts
def publish_provider_selection_sync(
    provider_name: str,
    model_name: str,
    correlation_id: str,
    selection_reason: str,
    selection_criteria: Optional[Dict[str, Any]] = None,
    causation_id: Optional[str] = None,
) -> bool:
    """
    Synchronous wrapper for publish_provider_selection.

    Use this in synchronous code (e.g., hooks, non-async scripts).
    Creates event loop if needed.

    Args:
        provider_name: Provider name
        model_name: Model name
        correlation_id: Request correlation ID
        selection_reason: Human-readable selection rationale
        selection_criteria: Optional structured selection criteria
        causation_id: Optional causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_provider_selection(
            provider_name=provider_name,
            model_name=model_name,
            correlation_id=correlation_id,
            selection_reason=selection_reason,
            selection_criteria=selection_criteria,
            causation_id=causation_id,
        )
    )
