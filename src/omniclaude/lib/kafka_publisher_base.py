#!/usr/bin/env python3
"""Shared Kafka Publisher Infrastructure.

Extracts common Kafka producer management, event envelope creation,
and sync/async wrappers used by all event publishers.

Provides a single shared Kafka producer singleton to avoid duplicate
connections and resource consumption across publishers.

Usage:
    from omniclaude.lib.kafka_publisher_base import (
        get_shared_producer,
        close_shared_producer,
        create_event_envelope,
        get_kafka_bootstrap_servers,
        get_kafka_topic_prefix,
        publish_to_kafka,
        publish_to_kafka_sync,
        KAFKA_PUBLISH_TIMEOUT_SECONDS,
    )
"""

import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0

# Shared Kafka producer (singleton across all publishers)
_kafka_producer: Any | None = None
_producer_lock: asyncio.Lock | None = None

# Threading lock for thread-safe asyncio.Lock creation (double-checked locking)
_lock_creation_lock = threading.Lock()

# Shared ThreadPoolExecutor for sync-from-async fallback
_thread_pool: concurrent.futures.ThreadPoolExecutor | None = None
_thread_pool_lock = threading.Lock()


def _get_thread_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Get or create a shared ThreadPoolExecutor for sync wrapper fallback.

    Uses double-checked locking for thread safety.

    Returns:
        ThreadPoolExecutor instance (shared singleton).
    """
    global _thread_pool
    if _thread_pool is None:
        with _thread_pool_lock:
            if _thread_pool is None:
                _thread_pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="kafka-event-publisher",
                )
    return _thread_pool


def get_kafka_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment.

    Resolution order:
    1. KAFKA_BOOTSTRAP_SERVERS environment variable
    2. Configurable fallback via KAFKA_FALLBACK_HOST and KAFKA_FALLBACK_PORT
    3. localhost:9092 as safe default

    Returns:
        Kafka bootstrap servers connection string.
    """
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if servers:
        return servers

    # Use configurable fallback - no hardcoded IPs
    fallback_host = os.environ.get("KAFKA_FALLBACK_HOST", "localhost")
    fallback_port = os.environ.get("KAFKA_FALLBACK_PORT", "9092")
    default_servers = f"{fallback_host}:{fallback_port}"
    logger.warning(
        "KAFKA_BOOTSTRAP_SERVERS not set, using fallback: %s. "
        "Set KAFKA_BOOTSTRAP_SERVERS environment variable for production use.",
        default_servers,
    )
    return default_servers


def get_kafka_topic_prefix() -> str:
    """Get Kafka topic prefix from environment variables.

    Returns:
        Empty string. Topics are realm-agnostic per ONEX convention (OMN-1972):
        TopicBase values ARE the wire topic names, no environment prefix.
    """
    return ""


def create_event_envelope(
    event_type_value: str,
    payload: dict[str, Any],
    correlation_id: str,
    schema_ref: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> dict[str, Any]:
    """Create OnexEnvelopeV1 standard event envelope.

    Following EVENT_BUS_INTEGRATION_PATTERNS standards for consistent event structure.

    Args:
        event_type_value: Event type string value (discriminator in payload).
        payload: Event payload data.
        correlation_id: Correlation ID for distributed tracing.
        schema_ref: Schema registry reference for this event type.
        source: Source service name (default: omniclaude).
        tenant_id: Tenant identifier (default: default).
        namespace: Event namespace (default: omninode).
        causation_id: Optional causation ID for event chains.

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event.
    """
    return {
        "event_type": event_type_value,
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": schema_ref,
        "payload": payload,
    }


async def _get_producer_lock() -> asyncio.Lock:
    """Get or create the producer lock lazily under a running event loop.

    Uses double-checked locking with a threading.Lock to ensure thread-safe
    creation of the asyncio.Lock.

    Returns:
        asyncio.Lock: The producer lock instance.
    """
    global _producer_lock

    if _producer_lock is None:
        with _lock_creation_lock:
            if _producer_lock is None:
                _producer_lock = asyncio.Lock()

    return _producer_lock


async def get_shared_producer():
    """Get or create shared Kafka producer (async singleton pattern).

    Returns:
        AIOKafkaProducer instance or None if unavailable.
    """
    global _kafka_producer

    producer = _kafka_producer
    if producer is not None:
        return producer

    lock = await _get_producer_lock()
    async with lock:
        producer = _kafka_producer
        if producer is not None:
            return producer

        try:
            from aiokafka import AIOKafkaProducer

            bootstrap_servers = get_kafka_bootstrap_servers()

            producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",
                linger_ms=10,
                acks=1,
                max_batch_size=16384,
                request_timeout_ms=5000,
            )

            await producer.start()
            _kafka_producer = producer
            logger.info("Shared Kafka producer initialized: %s", bootstrap_servers)
            return producer

        except ImportError:
            logger.error(
                "aiokafka not installed. Install with: pip install aiokafka"
            )
            return None
        except Exception:
            logger.error("Failed to initialize Kafka producer", exc_info=True)
            return None


async def publish_to_kafka(
    topic: str,
    envelope: dict[str, Any],
    partition_key: str,
) -> bool:
    """Publish an event envelope to a Kafka topic.

    Args:
        topic: Full Kafka topic name.
        envelope: OnexEnvelopeV1 event envelope.
        partition_key: Partition key (typically correlation_id).

    Returns:
        True if published successfully, False if producer unavailable.

    Raises:
        TimeoutError: If publish exceeds KAFKA_PUBLISH_TIMEOUT_SECONDS.
        Exception: Other Kafka errors propagate to caller for handling.
    """
    producer = await get_shared_producer()
    if producer is None:
        logger.warning("Kafka producer unavailable, event not published")
        return False

    await asyncio.wait_for(
        producer.send_and_wait(
            topic, value=envelope, key=partition_key.encode("utf-8")
        ),
        timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
    )
    return True


async def close_shared_producer():
    """Close shared Kafka producer on shutdown."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Shared Kafka producer closed")
        except Exception:
            logger.error("Error closing shared Kafka producer", exc_info=True)
        finally:
            _kafka_producer = None


def _cleanup_producer_sync():
    """Synchronous cleanup for atexit handler."""
    global _kafka_producer, _thread_pool
    if _kafka_producer is not None:
        try:
            try:
                asyncio.get_running_loop()
                return
            except RuntimeError:
                pass

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(close_shared_producer())
            finally:
                loop.close()

        except Exception as e:
            logger.debug("Error during atexit producer cleanup: %s", e)
            _kafka_producer = None

    if _thread_pool is not None:
        try:
            _thread_pool.shutdown(wait=False)
        except Exception:
            pass
        _thread_pool = None


atexit.register(_cleanup_producer_sync)


def _run_in_new_loop(coro) -> Any:
    """Create a new event loop in the current thread and run the coroutine."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _run_async_in_new_thread(coro) -> Any:
    """Run an async coroutine in a new thread with its own event loop."""
    pool = _get_thread_pool()
    future = pool.submit(_run_in_new_loop, coro)
    return future.result(timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS + 5)


def publish_to_kafka_sync(coro) -> bool:
    """Synchronous wrapper for async publish coroutines.

    Handles three scenarios:
    1. No event loop running: Creates a new loop, runs, and closes it.
    2. Event loop running: Delegates to a background thread.
    3. Fallback: Returns False on any unexpected error.

    Args:
        coro: The publish coroutine to execute.

    Returns:
        True if published successfully, False otherwise.
    """
    try:
        try:
            asyncio.get_running_loop()
            return _run_async_in_new_thread(coro)
        except RuntimeError:
            pass

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    except Exception:
        logger.error("Error in sync publish wrapper", exc_info=True)
        return False
