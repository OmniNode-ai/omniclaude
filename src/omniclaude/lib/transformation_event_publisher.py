#!/usr/bin/env python3
"""
Transformation Event Publisher - Kafka Integration

Publishes agent transformation events to Kafka for async logging to PostgreSQL.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from omniclaude.lib.transformation_event_publisher import publish_transformation_event

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
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type
- Automatic secret redaction on user_request field
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

from omniclaude.hooks.schemas import PROMPT_PREVIEW_MAX_LENGTH, _sanitize_prompt_preview
from omniclaude.hooks.topics import TopicBase, build_topic

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


# Event type enumeration following EVENT_BUS_INTEGRATION_PATTERNS
# Values are payload discriminators, NOT topic names.
# Actual Kafka topic is determined by TopicBase.TRANSFORMATIONS via build_topic().
class TransformationEventType(StrEnum):
    """Agent transformation event types with standardized topic routing.

    These values serve as event type discriminators in the payload envelope.
    All transformation events route to the same Kafka topic
    (TopicBase.TRANSFORMATIONS) and are differentiated by this field.
    """

    STARTED = "transformation.started"
    COMPLETED = "transformation.completed"
    FAILED = "transformation.failed"


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
                    thread_name_prefix="transformation-event-publisher",
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


def _redact_user_request(text: str | None) -> str | None:
    """Redact and truncate user_request for privacy safety.

    Applies the same redaction/truncation used for prompt_preview in schemas.py:
    1. Redacts common secret patterns (API keys, passwords, tokens)
    2. Truncates to PROMPT_PREVIEW_MAX_LENGTH (100 chars) with ellipsis

    Args:
        text: Raw user request text, or None.

    Returns:
        Redacted and truncated text, or None if input was None.
    """
    if text is None:
        return None
    return _sanitize_prompt_preview(text, max_length=PROMPT_PREVIEW_MAX_LENGTH)


def _create_event_envelope(
    event_type: TransformationEventType,
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
        "timestamp": datetime.now(UTC).isoformat(),  # RFC3339 format
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/agent/transformation_{event_type.name.lower()}/v1",
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
        # Double-check after acquiring lock (another coroutine may have created it)
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


async def publish_transformation_event(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    correlation_id: str | UUID | None = None,
    session_id: str | UUID | None = None,
    user_request: str | None = None,
    routing_confidence: float | None = None,
    routing_strategy: str | None = None,
    transformation_duration_ms: int | None = None,
    initialization_duration_ms: int | None = None,
    total_execution_duration_ms: int | None = None,
    success: bool = True,
    error_message: str | None = None,
    error_type: str | None = None,
    quality_score: float | None = None,
    context_snapshot: dict[str, Any] | None = None,
    context_keys: list[str] | None = None,
    context_size_bytes: int | None = None,
    agent_definition_id: str | UUID | None = None,
    parent_event_id: str | UUID | None = None,
    event_type: TransformationEventType = TransformationEventType.COMPLETED,
    tenant_id: str = "default",
    namespace: str = "omninode",
    causation_id: str | None = None,
) -> bool:
    """
    Publish agent transformation event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to the
    transformation events topic (TopicBase.TRANSFORMATIONS) with event_type
    discrimination in the payload.

    Args:
        source_agent: Original agent identity (e.g., "polymorphic-agent")
        target_agent: Transformed agent identity (e.g., "agent-api-architect")
        transformation_reason: Why this transformation occurred
        correlation_id: Request correlation ID for distributed tracing
        session_id: Session ID for grouping related executions
        user_request: Original user request triggering transformation.
            PRIVACY: Automatically redacted and truncated to 100 chars.
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
        - user_request is automatically redacted and truncated for privacy
    """
    try:
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        if session_id is not None:
            session_id = str(session_id)

        # PRIVACY: Redact and truncate user_request before including in payload.
        # Applies same secret pattern redaction and 100-char truncation as
        # prompt_preview in schemas.py.
        redacted_user_request = _redact_user_request(user_request)

        # Build event payload (everything except envelope metadata)
        payload = {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "transformation_reason": transformation_reason,
            "session_id": session_id,
            "user_request": redacted_user_request,
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
            "started_at": datetime.now(UTC).isoformat(),
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

        # Build ONEX-compliant topic name using TopicBase
        topic_prefix = _get_kafka_topic_prefix()
        topic = build_topic(topic_prefix, TopicBase.TRANSFORMATIONS)

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published transformation event (OnexEnvelopeV1): {event_type.value} | "
            f"{source_agent} -> {target_agent} | "
            f"correlation_id={correlation_id} | "
            f"topic={topic}"
        )
        return True

    except TimeoutError:
        # Handle timeout specifically for better observability
        logger.error(
            f"Timeout publishing transformation event to Kafka "
            f"(event_type={event_type.value if isinstance(event_type, TransformationEventType) else event_type}, "
            f"source_agent={source_agent}, target_agent={target_agent}, "
            f"timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
            extra={"correlation_id": correlation_id},
        )
        return False

    except Exception:
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
    correlation_id: str | UUID | None = None,
    **kwargs,
) -> bool:
    """
    Publish transformation start event.

    Convenience method for publishing at the start of transformation.
    Routes to TopicBase.TRANSFORMATIONS with event_type=STARTED.
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
    correlation_id: str | UUID | None = None,
    transformation_duration_ms: int | None = None,
    **kwargs,
) -> bool:
    """
    Publish transformation complete event.

    Convenience method for publishing after successful transformation.
    Routes to TopicBase.TRANSFORMATIONS with event_type=COMPLETED.
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
    correlation_id: str | UUID | None = None,
    error_type: str | None = None,
    **kwargs,
) -> bool:
    """
    Publish transformation failed event.

    Convenience method for publishing after transformation failure.
    Routes to TopicBase.TRANSFORMATIONS with event_type=FAILED.
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
def publish_transformation_event_sync(
    source_agent: str, target_agent: str, transformation_reason: str, **kwargs
) -> bool:
    """
    Synchronous wrapper for publish_transformation_event.

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
                publish_transformation_event(
                    source_agent=source_agent,
                    target_agent=target_agent,
                    transformation_reason=transformation_reason,
                    **kwargs,
                )
            )
        except RuntimeError:
            # No running loop - create one, run, and close
            pass

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                publish_transformation_event(
                    source_agent=source_agent,
                    target_agent=target_agent,
                    transformation_reason=transformation_reason,
                    **kwargs,
                )
            )
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error in sync wrapper: {e}", exc_info=True)
        return False


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
        print(f"  Start Event:    {'OK' if success_start else 'FAIL'}")
        print(f"  Complete Event: {'OK' if success_complete else 'FAIL'}")
        print(f"  Failed Event:   {'OK' if success_failed else 'FAIL'}")
        print("=" * 60)

    asyncio.run(test())
