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
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from omniclaude.hooks.schemas import sanitize_text
from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.kafka_producer_utils import (
    KAFKA_PUBLISH_TIMEOUT_SECONDS,
    KafkaProducerManager,
    build_kafka_topic,
    create_event_envelope,
)

logger = logging.getLogger(__name__)

# Maximum length for user_request in event payloads (security: prevent sensitive data leakage)
MAX_USER_REQUEST_LENGTH = 500


def _sanitize_user_request(user_request: str | None) -> str | None:
    """
    Sanitize user_request for safe inclusion in event payloads.

    - Redacts known sensitive patterns using canonical patterns from schemas.py
    - Truncates to MAX_USER_REQUEST_LENGTH characters
    - Returns None if input is None
    """
    if user_request is None:
        return None

    # Use canonical redaction from schemas.py (single source of truth)
    sanitized = sanitize_text(user_request)

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


# Kafka producer manager (shared utilities from kafka_producer_utils)
_producer_manager = KafkaProducerManager(name="transformation")


# Backwards-compatible aliases for tests that reference internal functions
async def get_producer_lock():
    """Get producer lock (delegates to KafkaProducerManager)."""
    return await _producer_manager.get_lock()


async def _get_kafka_producer():
    """Get producer (delegates to KafkaProducerManager)."""
    return await _producer_manager.get_producer()


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
        envelope = create_event_envelope(
            event_type_value=event_type.value,
            event_type_name=event_type.name.lower(),
            payload=payload,
            correlation_id=correlation_id,
            schema_domain="transformation",
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Get producer (uses module-level function for testability)
        producer = await _get_kafka_producer()
        if producer is None:
            logger.debug(
                "Kafka producer unavailable, transformation event not published"
            )
            return False

        # Build ONEX-compliant topic name with environment prefix
        topic = build_kafka_topic(event_type.get_topic_name())

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published transformation event: "
            f"{source_agent} → {target_agent} | "
            f"correlation_id={correlation_id}"
        )
        return True

    except TimeoutError:
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
    await _producer_manager.close()


# Register cleanup on interpreter exit
atexit.register(_producer_manager.cleanup_sync)


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
