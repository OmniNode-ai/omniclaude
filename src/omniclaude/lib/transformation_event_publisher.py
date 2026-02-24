#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
- Shared producer connection management (via kafka_publisher_base)
- OnexEnvelopeV1 standard event envelope
- Correlation ID tracking for distributed tracing
- Idempotency support via correlation_id + event_type
- Automatic secret redaction on user_request field
"""

import asyncio
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from omniclaude.hooks.schemas import PROMPT_PREVIEW_MAX_LENGTH, _sanitize_prompt_preview
from omniclaude.hooks.topics import TopicBase, build_topic
from omniclaude.lib.kafka_publisher_base import (
    KAFKA_PUBLISH_TIMEOUT_SECONDS,
    close_shared_producer,
    create_event_envelope,
    publish_to_kafka,
    publish_to_kafka_sync,
)

logger = logging.getLogger(__name__)


# Event type enumeration following EVENT_BUS_INTEGRATION_PATTERNS
# Values are payload discriminators, NOT topic names.
# Actual Kafka topic is determined by _EVENT_TYPE_TO_TOPIC mapping via build_topic().
class TransformationEventType(StrEnum):
    """Agent transformation event types with standardized topic routing.

    These values serve as event type discriminators in the payload envelope.
    Each event type routes to its own ONEX-compliant topic via
    _EVENT_TYPE_TO_TOPIC (e.g., STARTED -> TopicBase.TRANSFORMATION_STARTED).
    """

    STARTED = "transformation.started"
    COMPLETED = "transformation.completed"
    FAILED = "transformation.failed"


# Mapping from event type to TopicBase for per-event topic routing.
# Each transformation event type routes to its own ONEX-compliant topic
# instead of the legacy TopicBase.TRANSFORMATIONS catch-all.
_EVENT_TYPE_TO_TOPIC: dict[TransformationEventType, TopicBase] = {
    TransformationEventType.STARTED: TopicBase.TRANSFORMATION_STARTED,
    TransformationEventType.COMPLETED: TopicBase.TRANSFORMATION_COMPLETED,
    TransformationEventType.FAILED: TopicBase.TRANSFORMATION_FAILED,
}


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

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to
    per-event-type ONEX topics (e.g., TopicBase.TRANSFORMATION_STARTED)
    via the _EVENT_TYPE_TO_TOPIC mapping.

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

        # Build schema ref for this event type
        schema_ref = f"registry://{namespace}/agent/transformation_{event_type.name.lower()}/v1"

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = create_event_envelope(
            event_type_value=event_type.value,
            payload=payload,
            correlation_id=correlation_id,
            schema_ref=schema_ref,
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Build ONEX-compliant topic name using per-event TopicBase routing
        # No environment prefix per OMN-1972
        topic_base = _EVENT_TYPE_TO_TOPIC.get(
            event_type, TopicBase.TRANSFORMATION_COMPLETED
        )
        topic = build_topic("", topic_base)

        # Publish to Kafka
        result = await publish_to_kafka(topic, envelope, correlation_id)

        if result:
            logger.debug(
                "Published transformation event (OnexEnvelopeV1): %s | "
                "%s -> %s | correlation_id=%s | topic=%s",
                event_type.value,
                source_agent,
                target_agent,
                correlation_id,
                topic,
            )
        return result

    except TimeoutError:
        logger.error(
            "Timeout publishing transformation event to Kafka "
            "(event_type=%s, source_agent=%s, target_agent=%s, timeout=%ss)",
            event_type.value if isinstance(event_type, TransformationEventType) else event_type,
            source_agent,
            target_agent,
            KAFKA_PUBLISH_TIMEOUT_SECONDS,
            extra={"correlation_id": correlation_id},
        )
        return False

    except Exception:
        logger.error(
            "Failed to publish transformation event: %s",
            event_type.value if isinstance(event_type, TransformationEventType) else event_type,
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
    Routes to TopicBase.TRANSFORMATION_STARTED.
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
    Routes to TopicBase.TRANSFORMATION_COMPLETED.
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
    Routes to TopicBase.TRANSFORMATION_FAILED.
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


# Re-export close for backwards compatibility
close_producer = close_shared_producer


# Synchronous wrapper for backward compatibility
def publish_transformation_event_sync(
    source_agent: str, target_agent: str, transformation_reason: str, **kwargs
) -> bool:
    """
    Synchronous wrapper for publish_transformation_event.

    Handles running/non-running event loop scenarios.
    Use async version when possible for best performance.
    """
    return publish_to_kafka_sync(
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
        print(f"  Start Event:    {'OK' if success_start else 'FAIL'}")
        print(f"  Complete Event: {'OK' if success_complete else 'FAIL'}")
        print(f"  Failed Event:   {'OK' if success_failed else 'FAIL'}")
        print("=" * 60)

    asyncio.run(test())
