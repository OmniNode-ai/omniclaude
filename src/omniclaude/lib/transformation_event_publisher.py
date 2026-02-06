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
- Separate topics per event type (started/completed/failed)
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type

DESIGN RULE: Non-Blocking Event Emission
=========================================
Event emission is BEST-EFFORT, NEVER blocks execution.

- Transformation correctness MUST NOT depend on Kafka
- If publishing fails: log + metric, never block
- Buffer briefly, then drop if unavailable
- This is an INVARIANT - do not "fix" by adding blocking
"""

import asyncio
import atexit
import json
import logging
import os
import re
import threading
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID, uuid4

from omniclaude.hooks.topics import TopicBase, build_topic

logger = logging.getLogger(__name__)

# Maximum length for user_request in event payloads (security: prevent sensitive data leakage)
MAX_USER_REQUEST_LENGTH = 500

# Patterns for sensitive data redaction (same patterns used in prompt_preview)
_SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[OPENAI_KEY_REDACTED]"),  # OpenAI API keys
    (re.compile(r"AKIA[A-Z0-9]{16}"), "[AWS_KEY_REDACTED]"),  # AWS access keys
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "[GITHUB_TOKEN_REDACTED]"),  # GitHub PATs
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "[GITHUB_TOKEN_REDACTED]"),  # GitHub OAuth
    (re.compile(r"xox[baprs]-[a-zA-Z0-9-]+"), "[SLACK_TOKEN_REDACTED]"),  # Slack tokens
    (re.compile(r"-----BEGIN [A-Z]+ PRIVATE KEY-----"), "[PRIVATE_KEY_REDACTED]"),  # PEM keys
    (re.compile(r"Bearer [a-zA-Z0-9._-]+"), "[BEARER_TOKEN_REDACTED]"),  # Bearer tokens
    (re.compile(r":[^:@\s]{8,}@"), ":[PASSWORD_REDACTED]@"),  # Passwords in URLs
]


def _sanitize_user_request(user_request: str | None) -> str | None:
    """
    Sanitize user_request for safe inclusion in event payloads.

    - Truncates to MAX_USER_REQUEST_LENGTH characters
    - Redacts known sensitive patterns (API keys, tokens, passwords)
    - Returns None if input is None

    This follows the same privacy patterns as prompt_preview in schemas.py.
    """
    if user_request is None:
        return None

    # Redact sensitive patterns
    sanitized = user_request
    for pattern, replacement in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    # Truncate to max length
    if len(sanitized) > MAX_USER_REQUEST_LENGTH:
        sanitized = sanitized[:MAX_USER_REQUEST_LENGTH] + "...[TRUNCATED]"

    return sanitized

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


class TransformationEventType(str, Enum):
    """Agent transformation event types with standardized topic routing.

    Values are derived from TopicBase to ensure single source of truth.
    This prevents drift between event types and actual Kafka topics.

    Topic names use hyphens (not dots) per ONEX naming convention.
    """

    # Reference TopicBase constants - single source of truth for topic names
    STARTED = TopicBase.TRANSFORMATION_STARTED.value
    COMPLETED = TopicBase.TRANSFORMATION_COMPLETED.value
    FAILED = TopicBase.TRANSFORMATION_FAILED.value

    def get_topic_name(self) -> str:
        """
        Get Kafka topic name for this event type.

        Returns topic following ONEX topic naming convention:
        onex.evt.{producer}.{event-name}.v{n}
        """
        return self.value


# Lazy-loaded Kafka producer (singleton)
_kafka_producer: Any | None = None
_producer_lock: asyncio.Lock | None = None
_producer_lock_loop: asyncio.AbstractEventLoop | None = None
_lock_creation_lock = threading.Lock()  # Protects asyncio.Lock creation


def _get_kafka_topic_prefix() -> str:
    """Get Kafka topic prefix (environment) from environment.

    Returns:
        Topic prefix (e.g., "dev", "staging", "prod"). Defaults to "dev".
    """
    env_prefix = os.getenv("KAFKA_TOPIC_PREFIX") or os.getenv("KAFKA_ENVIRONMENT")
    return env_prefix if env_prefix else "dev"


def _get_kafka_bootstrap_servers() -> str | None:
    """
    Get Kafka bootstrap servers from environment.

    Per CLAUDE.md: No localhost defaults - explicit configuration required.
    Hardcoded fallbacks are a security/reliability concern in production.

    Returns:
        Bootstrap servers string, or None if not configured.
    """
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set. Kafka publishing disabled. "
            "Set KAFKA_BOOTSTRAP_SERVERS environment variable to enable event publishing."
        )
        return None
    return servers


def _create_event_envelope(
    event_type: TransformationEventType,
    payload: dict[str, Any],
    correlation_id: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "onex",
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
        namespace: Event namespace (default: onex)
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
        "schema_ref": f"registry://{namespace}/transformation/{event_type.name.lower()}/v1",
        "payload": payload,
    }


async def get_producer_lock() -> asyncio.Lock:
    """
    Get or create the producer lock lazily under a running event loop.

    This ensures asyncio.Lock() is never created at module level, which
    would cause RuntimeError in Python 3.12+ when no event loop exists.

    The lock is bound to the event loop that created it. If called from a
    different loop (e.g., via ThreadPoolExecutor+asyncio.run()), a new lock
    is created to avoid cross-loop RuntimeError in Python 3.12+.

    Thread-Safety Guarantee:
        Uses double-checked locking pattern with a threading.Lock to prevent
        race conditions where multiple coroutines (potentially from different
        threads) could create duplicate Lock instances on first call.
        - Once created, the lock is never replaced

        See tests/lib/test_transformation_event_publisher.py for concurrency tests.

    Returns:
        asyncio.Lock: The singleton producer lock instance
    """
    global _producer_lock, _producer_lock_loop
    current_loop = asyncio.get_running_loop()
    if _producer_lock is not None and _producer_lock_loop is current_loop:
        return _producer_lock
    with _lock_creation_lock:
        if _producer_lock is None or _producer_lock_loop is not current_loop:
            _producer_lock = asyncio.Lock()
            _producer_lock_loop = current_loop
    return _producer_lock


async def _get_kafka_producer() -> Any | None:
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
        # Re-read global after acquiring lock - another coroutine may have created it
        # cast() required because mypy narrows _kafka_producer to None after line 161
        # but async yield point allows other coroutines to modify the global
        current_producer = cast("Any | None", _kafka_producer)
        if current_producer is not None:
            return current_producer

        try:
            from aiokafka import AIOKafkaProducer

            bootstrap_servers = _get_kafka_bootstrap_servers()
            if bootstrap_servers is None:
                return None

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
            logger.warning(
                "aiokafka not installed. Transformation events will not be published. "
                "aiokafka is an optional dependency for Kafka event publishing. "
                "Install with: pip install aiokafka>=0.9.0"
            )
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize Kafka producer: {e}")
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
    namespace: str = "onex",
    causation_id: str | None = None,
    # Validation outcome tracking
    validation_outcome: str | None = None,  # "allowed", "warned", "blocked"
    validation_metrics: dict[str, Any] | None = None,
) -> bool:
    """
    Publish agent transformation event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to separate topics
    based on event type (started/completed/failed).

    IMPORTANT: This function is non-blocking and best-effort. It will NOT raise
    exceptions on failure - failures are logged but execution continues.

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
        validation_outcome: Validator outcome (allowed/warned/blocked)
        validation_metrics: Metrics from transformation validation

    Returns:
        bool: True if published successfully, False otherwise
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
        # Sanitize user_request to prevent sensitive data leakage (MAJOR security fix)
        sanitized_user_request = _sanitize_user_request(user_request)

        payload: dict[str, Any] = {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "transformation_reason": transformation_reason,
            "session_id": session_id,
            "user_request": sanitized_user_request,
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
            "validation_outcome": validation_outcome,
            "validation_metrics": validation_metrics,
            "emitted_at": datetime.now(UTC).isoformat(),
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
            logger.debug(
                "Kafka producer unavailable, transformation event not published"
            )
            return False

        # Build ONEX-compliant topic name with environment prefix
        topic_prefix = _get_kafka_topic_prefix()
        topic = build_topic(topic_prefix, event_type.get_topic_name())

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published transformation event: {topic} | "
            f"{source_agent} → {target_agent} | "
            f"correlation_id={correlation_id}"
        )
        return True

    except TimeoutError:
        # Handle timeout specifically for better observability
        logger.warning(
            f"Timeout publishing transformation event "
            f"(event_type={event_type.value}, timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)"
        )
        return False

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.warning(f"Failed to publish transformation event: {e}")
        return False


async def publish_transformation_start(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    correlation_id: str | UUID | None = None,
    **kwargs: Any,
) -> bool:
    """
    Publish transformation start event.

    Convenience method for publishing at the start of transformation.
    Publishes to topic: onex.evt.omniclaude.transformation-started.v1
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
    **kwargs: Any,
) -> bool:
    """
    Publish transformation complete event.

    Convenience method for publishing after successful transformation.
    Publishes to topic: onex.evt.omniclaude.transformation-completed.v1
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
    **kwargs: Any,
) -> bool:
    """
    Publish transformation failed event.

    Convenience method for publishing after transformation failure.
    Publishes to topic: onex.evt.omniclaude.transformation-failed.v1
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


async def close_producer() -> None:
    """Close Kafka producer on shutdown."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Kafka producer closed")
        except Exception as e:
            logger.warning(f"Error closing Kafka producer: {e}")
        finally:
            _kafka_producer = None


def _cleanup_producer_sync() -> None:
    """
    Synchronous wrapper for close_producer() to be called by atexit.

    This ensures the Kafka producer is closed when the Python interpreter
    exits, preventing resource leak warnings.
    """
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            # Try to get existing event loop
            try:
                asyncio.get_running_loop()
                # Loop is running, can't cleanup synchronously
                return
            except RuntimeError:
                pass

            # Create a new event loop for cleanup (asyncio.get_event_loop()
            # is deprecated in Python 3.12+)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(close_producer())
            except Exception:
                # If async cleanup fails, fall through to direct cleanup below
                pass
            finally:
                loop.close()

            if _kafka_producer is not None:
                # Async cleanup didn't fully work - directly close underlying components
                # NOTE: Accessing _client is necessary because AIOKafkaProducer
                # doesn't expose a synchronous close() method.
                try:
                    client = getattr(_kafka_producer, "_client", None)
                    if client is not None:
                        close_method = getattr(client, "close", None)
                        if close_method is not None and callable(close_method):
                            close_method()
                    _kafka_producer = None
                    logger.debug("Kafka producer closed (synchronous cleanup)")
                except (AttributeError, TypeError):
                    _kafka_producer = None
                except Exception:
                    _kafka_producer = None

        except Exception:
            _kafka_producer = None


# Register cleanup on interpreter exit
atexit.register(_cleanup_producer_sync)


# Synchronous wrapper for backward compatibility
def publish_transformation_event_sync(
    source_agent: str,
    target_agent: str,
    transformation_reason: str,
    **kwargs: Any,
) -> bool:
    """
    Synchronous wrapper for publish_transformation_event.

    Handles both sync and async calling contexts safely:
    - From sync context: Creates new event loop and runs directly
    - From async context: Uses ThreadPoolExecutor to avoid nested loop issues

    Note: ThreadPoolExecutor per-call overhead is intentional for correctness.
    The alternative (reusing executors) adds complexity and state management
    concerns that aren't justified for event publishing use cases.

    Args:
        source_agent: The agent initiating transformation
        target_agent: The agent being transformed into
        transformation_reason: Why the transformation occurred
        **kwargs: Additional arguments passed to publish_transformation_event

    Returns:
        bool: True if event was published successfully
    """
    import concurrent.futures

    # Check if we're already in an async context
    try:
        asyncio.get_running_loop()
        # Already in async context - use thread pool to avoid nested loop issues
        logger.debug("publish_transformation_event_sync called from async context, using ThreadPoolExecutor")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                publish_transformation_event(
                    source_agent=source_agent,
                    target_agent=target_agent,
                    transformation_reason=transformation_reason,
                    **kwargs,
                ),
            )
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run() directly
        return asyncio.run(
            publish_transformation_event(
                source_agent=source_agent,
                target_agent=target_agent,
                transformation_reason=transformation_reason,
                **kwargs,
            )
        )


# NOTE: Inline tests moved to tests/lib/test_transformation_event_publisher.py
# Run tests with: pytest tests/lib/test_transformation_event_publisher.py -v
