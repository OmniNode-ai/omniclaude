#!/usr/bin/env python3
"""
Manifest Injection Event Publisher - Kafka Integration

Publishes manifest injection events to Kafka for async logging to PostgreSQL.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from omniclaude.lib.manifest_injection_event_publisher import (
        publish_manifest_injection_event,
    )

    await publish_manifest_injection_event(
        agent_name="agent-api-architect",
        injection_type=ManifestInjectionEventType.CONTEXT_INJECTED,
        correlation_id=correlation_id,
        pattern_count=5,
        context_size_bytes=2048,
        retrieval_duration_ms=150,
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Event types aligned with TopicBase constants
- Correlation ID tracking for distributed tracing
- Thread-safe singleton producer with double-checked locking
"""

import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from omniclaude.hooks.topics import TopicBase, build_topic

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


# Event type enumeration aligned with TopicBase constants.
# Values are payload discriminators, NOT topic names.
# Actual Kafka topic is determined by TopicBase via build_topic().
class ManifestInjectionEventType(StrEnum):
    """Manifest injection event types aligned with TopicBase constants.

    These values serve as event type discriminators in the payload envelope.
    The Kafka topic is selected from TopicBase based on the event type:
    - CONTEXT_INJECTED -> TopicBase.CONTEXT_INJECTED
    - INJECTION_RECORDED -> TopicBase.INJECTION_RECORDED
    - CONTEXT_RETRIEVAL_REQUESTED -> TopicBase.CONTEXT_RETRIEVAL_REQUESTED
    - CONTEXT_RETRIEVAL_COMPLETED -> TopicBase.CONTEXT_RETRIEVAL_COMPLETED
    """

    CONTEXT_INJECTED = TopicBase.CONTEXT_INJECTED.value
    INJECTION_RECORDED = TopicBase.INJECTION_RECORDED.value
    CONTEXT_RETRIEVAL_REQUESTED = TopicBase.CONTEXT_RETRIEVAL_REQUESTED.value
    CONTEXT_RETRIEVAL_COMPLETED = TopicBase.CONTEXT_RETRIEVAL_COMPLETED.value


# Mapping from event type to TopicBase for topic routing
_EVENT_TYPE_TO_TOPIC: dict[ManifestInjectionEventType, str] = {
    ManifestInjectionEventType.CONTEXT_INJECTED: TopicBase.CONTEXT_INJECTED,
    ManifestInjectionEventType.INJECTION_RECORDED: TopicBase.INJECTION_RECORDED,
    ManifestInjectionEventType.CONTEXT_RETRIEVAL_REQUESTED: TopicBase.CONTEXT_RETRIEVAL_REQUESTED,
    ManifestInjectionEventType.CONTEXT_RETRIEVAL_COMPLETED: TopicBase.CONTEXT_RETRIEVAL_COMPLETED,
}


# Lazy-loaded Kafka producer (singleton)
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
                    thread_name_prefix="manifest-injection-event-publisher",
                )
    return _thread_pool


def _get_kafka_bootstrap_servers() -> str:
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
        f"KAFKA_BOOTSTRAP_SERVERS not set, using fallback: {default_servers}. "
        f"Set KAFKA_BOOTSTRAP_SERVERS environment variable for production use."
    )
    return default_servers


def _get_kafka_topic_prefix() -> str:
    """Get Kafka topic prefix (environment) from environment variables.

    Returns:
        Topic prefix (e.g., "dev", "staging", "prod"). Defaults to "dev".
    """
    env_prefix = os.environ.get("KAFKA_TOPIC_PREFIX") or os.environ.get(
        "KAFKA_ENVIRONMENT"
    )
    return env_prefix if env_prefix else "dev"


def _create_event_envelope(
    event_type: ManifestInjectionEventType,
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
        event_type: Manifest injection event type enum
        payload: Event payload containing injection data
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
        "schema_ref": f"registry://{namespace}/manifest/injection_{event_type.name.lower()}/v1",
        "payload": payload,
    }


async def get_producer_lock() -> asyncio.Lock:
    """
    Get or create the producer lock lazily under a running event loop.

    Uses double-checked locking with a threading.Lock to ensure thread-safe
    creation of the asyncio.Lock. This prevents race conditions where multiple
    coroutines could create separate lock instances.

    This ensures asyncio.Lock() is never created at module level, which
    would cause RuntimeError in Python 3.12+ when no event loop exists.

    Returns:
        asyncio.Lock: The producer lock instance
    """
    global _producer_lock

    # First check (no lock) - fast path for already-initialized case
    if _producer_lock is None:
        # Acquire threading lock for creation
        with _lock_creation_lock:
            # Second check (with lock) - ensures only one coroutine creates the lock
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

    # Check if producer already exists - use local reference for type narrowing
    producer = _kafka_producer
    if producer is not None:
        return producer

    # Get the lock (created lazily under running event loop)
    lock = await get_producer_lock()
    async with lock:
        # Double-check after acquiring lock
        producer = _kafka_producer
        if producer is not None:
            return producer

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
            logger.error(
                "aiokafka not installed. Install with: pip install aiokafka"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            return None


async def publish_manifest_injection_event(
    agent_name: str,
    injection_type: ManifestInjectionEventType = ManifestInjectionEventType.INJECTION_RECORDED,
    correlation_id: str | UUID | None = None,
    session_id: str | UUID | None = None,
    pattern_count: int | None = None,
    context_size_bytes: int | None = None,
    context_source: str | None = None,
    retrieval_duration_ms: int | None = None,
    agent_domain: str | None = None,
    min_confidence_threshold: float | None = None,
    manifest_sections: list[str] | None = None,
    injection_metadata: dict[str, Any] | None = None,
    success: bool = True,
    error_message: str | None = None,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> bool:
    """
    Publish manifest injection event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to the
    appropriate TopicBase topic based on injection_type.

    Args:
        agent_name: Agent receiving the manifest injection
        injection_type: Event type enum (determines topic routing)
        correlation_id: Request correlation ID for distributed tracing
        session_id: Session ID for grouping related executions
        pattern_count: Number of patterns injected
        context_size_bytes: Size of injected context in bytes
        context_source: Source of the context (e.g., "database", "rag_query")
        retrieval_duration_ms: Time to retrieve context in milliseconds
        agent_domain: Domain of the agent for domain-specific context
        min_confidence_threshold: Minimum confidence threshold for pattern inclusion
        manifest_sections: List of manifest sections included
        injection_metadata: Additional metadata about the injection
        success: Whether injection succeeded
        error_message: Error details if failed
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise

    Note:
        - Uses correlation_id as partition key for workflow coherence
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

        # Build event payload
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "session_id": session_id,
            "pattern_count": pattern_count,
            "context_size_bytes": context_size_bytes,
            "context_source": context_source,
            "retrieval_duration_ms": retrieval_duration_ms,
            "agent_domain": agent_domain,
            "min_confidence_threshold": min_confidence_threshold,
            "manifest_sections": manifest_sections,
            "injection_metadata": injection_metadata,
            "success": success,
            "error_message": error_message,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

        # Remove None values to keep payload compact
        payload = {k: v for k, v in payload.items() if v is not None}

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = _create_event_envelope(
            event_type=injection_type,
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
                "Kafka producer unavailable, manifest injection event not published"
            )
            return False

        # Build ONEX-compliant topic name using TopicBase
        topic_prefix = _get_kafka_topic_prefix()
        topic_base = _EVENT_TYPE_TO_TOPIC.get(
            injection_type, TopicBase.INJECTION_RECORDED
        )
        topic = build_topic(topic_prefix, topic_base)

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published manifest injection event: {injection_type.value} | "
            f"agent={agent_name} | "
            f"correlation_id={correlation_id} | "
            f"topic={topic}"
        )
        return True

    except TimeoutError:
        logger.error(
            f"Timeout publishing manifest injection event to Kafka "
            f"(injection_type={injection_type.value}, agent_name={agent_name}, "
            f"timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
            extra={"correlation_id": correlation_id},
        )
        return False

    except Exception:
        logger.error(
            f"Failed to publish manifest injection event: "
            f"{injection_type.value if isinstance(injection_type, ManifestInjectionEventType) else injection_type}",
            exc_info=True,
        )
        return False


async def publish_context_injected(
    agent_name: str,
    correlation_id: str | UUID | None = None,
    pattern_count: int | None = None,
    context_size_bytes: int | None = None,
    context_source: str | None = None,
    retrieval_duration_ms: int | None = None,
    **kwargs,
) -> bool:
    """
    Publish context injection completed event.

    Convenience method for publishing when context has been injected.
    Routes to TopicBase.CONTEXT_INJECTED.
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        injection_type=ManifestInjectionEventType.CONTEXT_INJECTED,
        correlation_id=correlation_id,
        pattern_count=pattern_count,
        context_size_bytes=context_size_bytes,
        context_source=context_source,
        retrieval_duration_ms=retrieval_duration_ms,
        **kwargs,
    )


async def publish_injection_recorded(
    agent_name: str,
    correlation_id: str | UUID | None = None,
    pattern_count: int | None = None,
    context_size_bytes: int | None = None,
    **kwargs,
) -> bool:
    """
    Publish injection recorded event.

    Convenience method for recording injection metadata.
    Routes to TopicBase.INJECTION_RECORDED.
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        injection_type=ManifestInjectionEventType.INJECTION_RECORDED,
        correlation_id=correlation_id,
        pattern_count=pattern_count,
        context_size_bytes=context_size_bytes,
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

    Uses a new event loop for cleanup, properly closing it afterwards.
    If an event loop is already running (should not happen at atexit),
    defers to async cleanup.
    """
    global _kafka_producer, _thread_pool
    if _kafka_producer is not None:
        try:
            # Check if an event loop is already running
            try:
                asyncio.get_running_loop()
                # Loop is running, can't cleanup synchronously.
                # This will be handled by async cleanup.
                return
            except RuntimeError:
                # No running loop - expected at atexit, proceed with cleanup
                pass

            # Create a new event loop for cleanup, ensuring it is closed after use
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(close_producer())
            finally:
                loop.close()

        except Exception as e:
            # Best effort cleanup - don't raise on exit
            logger.debug(f"Error during atexit producer cleanup: {e}")
            # Ensure producer is cleared to avoid repeated cleanup attempts
            _kafka_producer = None

    # Clean up shared thread pool
    if _thread_pool is not None:
        try:
            _thread_pool.shutdown(wait=False)
        except Exception:
            pass
        _thread_pool = None


# Register cleanup on interpreter exit
atexit.register(_cleanup_producer_sync)


def _run_async_in_new_thread(coro) -> Any:
    """Run an async coroutine in a new thread with its own event loop.

    Used as a fallback when the sync wrapper is called from within
    an already-running event loop (e.g., Jupyter notebooks, nested async).

    Args:
        coro: The coroutine to execute.

    Returns:
        The result of the coroutine.
    """
    pool = _get_thread_pool()
    future = pool.submit(_run_in_new_loop, coro)
    return future.result(timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS + 5)


def _run_in_new_loop(coro) -> Any:
    """Create a new event loop in the current thread and run the coroutine.

    Args:
        coro: The coroutine to execute.

    Returns:
        The result of the coroutine.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Synchronous wrapper for backward compatibility
def publish_manifest_injection_event_sync(
    agent_name: str, **kwargs
) -> bool:
    """
    Synchronous wrapper for publish_manifest_injection_event.

    Handles three scenarios:
    1. No event loop running: Creates a new loop, runs, and closes it.
    2. Event loop running: Delegates to a background thread to avoid
       RuntimeError from nested run_until_complete calls.
    3. Fallback: Returns False on any unexpected error.

    Use async version when possible for best performance.
    """
    try:
        # Check if there's already a running event loop
        try:
            asyncio.get_running_loop()
            # Running loop exists - use thread-based fallback
            return _run_async_in_new_thread(
                publish_manifest_injection_event(
                    agent_name=agent_name,
                    **kwargs,
                )
            )
        except RuntimeError:
            # No running loop - create one, run, and close
            pass

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                publish_manifest_injection_event(
                    agent_name=agent_name,
                    **kwargs,
                )
            )
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error in sync wrapper: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    # Test manifest injection event publishing
    async def test():
        logging.basicConfig(level=logging.DEBUG)

        # Test context injected event
        print("Testing context injected event...")
        success_injected = await publish_context_injected(
            agent_name="agent-api-architect",
            correlation_id=str(uuid4()),
            pattern_count=5,
            context_size_bytes=2048,
            context_source="database",
            retrieval_duration_ms=150,
        )
        print(f"Context injected event published: {success_injected}")

        # Test injection recorded event
        print("\nTesting injection recorded event...")
        success_recorded = await publish_injection_recorded(
            agent_name="agent-researcher",
            correlation_id=str(uuid4()),
            pattern_count=3,
            context_size_bytes=1024,
        )
        print(f"Injection recorded event published: {success_recorded}")

        # Close producer
        print("\nClosing producer...")
        await close_producer()

        print("\n" + "=" * 60)
        print("Test Summary:")
        print(f"  Context Injected: {'OK' if success_injected else 'FAIL'}")
        print(f"  Injection Recorded: {'OK' if success_recorded else 'FAIL'}")
        print("=" * 60)

    asyncio.run(test())
