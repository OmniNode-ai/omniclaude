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
- Shared producer connection management (via kafka_publisher_base)
- OnexEnvelopeV1 standard event envelope
- Event types aligned with TopicBase constants
- Correlation ID tracking for distributed tracing
"""

import asyncio
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from omniclaude.hooks.topics import TopicBase, build_topic
from omniclaude.lib.kafka_publisher_base import (
    KAFKA_PUBLISH_TIMEOUT_SECONDS,
    close_shared_producer,
    create_event_envelope,
    get_kafka_topic_prefix,
    publish_to_kafka,
    publish_to_kafka_sync,
)

logger = logging.getLogger(__name__)


# Event type enumeration with simple discriminator values.
# Values are payload discriminators, NOT topic names.
# Actual Kafka topic is determined by TopicBase via _EVENT_TYPE_TO_TOPIC mapping.
class ManifestInjectionEventType(StrEnum):
    """Manifest injection event types with TopicBase-aligned routing.

    These values serve as event type discriminators in the payload envelope.
    They are intentionally simple strings (not full topic names) to separate
    the concerns of event identification from topic routing. The Kafka topic
    is selected from TopicBase based on the _EVENT_TYPE_TO_TOPIC mapping:
    - CONTEXT_INJECTED -> TopicBase.CONTEXT_INJECTED
    - INJECTION_RECORDED -> TopicBase.INJECTION_RECORDED
    - CONTEXT_RETRIEVAL_REQUESTED -> TopicBase.CONTEXT_RETRIEVAL_REQUESTED
    - CONTEXT_RETRIEVAL_COMPLETED -> TopicBase.CONTEXT_RETRIEVAL_COMPLETED
    """

    CONTEXT_INJECTED = "manifest.context-injected"
    INJECTION_RECORDED = "manifest.injection-recorded"
    CONTEXT_RETRIEVAL_REQUESTED = "manifest.context-retrieval-requested"
    CONTEXT_RETRIEVAL_COMPLETED = "manifest.context-retrieval-completed"


# Mapping from event type to TopicBase for topic routing
_EVENT_TYPE_TO_TOPIC: dict[ManifestInjectionEventType, TopicBase] = {
    ManifestInjectionEventType.CONTEXT_INJECTED: TopicBase.CONTEXT_INJECTED,
    ManifestInjectionEventType.INJECTION_RECORDED: TopicBase.INJECTION_RECORDED,
    ManifestInjectionEventType.CONTEXT_RETRIEVAL_REQUESTED: TopicBase.CONTEXT_RETRIEVAL_REQUESTED,
    ManifestInjectionEventType.CONTEXT_RETRIEVAL_COMPLETED: TopicBase.CONTEXT_RETRIEVAL_COMPLETED,
}


async def publish_manifest_injection_event(
    agent_name: str,
    correlation_id: str | UUID,
    injection_type: ManifestInjectionEventType = ManifestInjectionEventType.INJECTION_RECORDED,
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
        correlation_id: Request correlation ID for distributed tracing (required).
            Callers must provide an explicit correlation_id to ensure proper
            correlation across distributed events. Auto-generation is not
            supported to prevent orphaned correlation chains.
        injection_type: Event type enum (determines topic routing)
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
        # correlation_id is required - convert to string for Kafka serialization
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

        # Build schema ref for this event type
        schema_ref = f"registry://{namespace}/manifest/injection_{injection_type.name.lower()}/v1"

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = create_event_envelope(
            event_type_value=injection_type.value,
            payload=payload,
            correlation_id=correlation_id,
            schema_ref=schema_ref,
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Build ONEX-compliant topic name using TopicBase
        topic_prefix = get_kafka_topic_prefix()
        topic_base = _EVENT_TYPE_TO_TOPIC.get(
            injection_type, TopicBase.INJECTION_RECORDED
        )
        topic = build_topic(topic_prefix, topic_base)

        # Publish to Kafka
        result = await publish_to_kafka(topic, envelope, correlation_id)

        if result:
            logger.debug(
                "Published manifest injection event: %s | agent=%s | "
                "correlation_id=%s | topic=%s",
                injection_type.value,
                agent_name,
                correlation_id,
                topic,
            )
        return result

    except TimeoutError:
        logger.error(
            "Timeout publishing manifest injection event to Kafka "
            "(injection_type=%s, agent_name=%s, timeout=%ss)",
            injection_type.value,
            agent_name,
            KAFKA_PUBLISH_TIMEOUT_SECONDS,
            extra={"correlation_id": correlation_id},
        )
        return False

    except Exception:
        logger.error(
            "Failed to publish manifest injection event: %s",
            injection_type.value if isinstance(injection_type, ManifestInjectionEventType) else injection_type,
            exc_info=True,
        )
        return False


async def publish_context_injected(
    agent_name: str,
    correlation_id: str | UUID,
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
        correlation_id=correlation_id,
        injection_type=ManifestInjectionEventType.CONTEXT_INJECTED,
        pattern_count=pattern_count,
        context_size_bytes=context_size_bytes,
        context_source=context_source,
        retrieval_duration_ms=retrieval_duration_ms,
        **kwargs,
    )


async def publish_injection_recorded(
    agent_name: str,
    correlation_id: str | UUID,
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
        correlation_id=correlation_id,
        injection_type=ManifestInjectionEventType.INJECTION_RECORDED,
        pattern_count=pattern_count,
        context_size_bytes=context_size_bytes,
        **kwargs,
    )


# Re-export close for backwards compatibility
close_producer = close_shared_producer


# Synchronous wrapper for backward compatibility
def publish_manifest_injection_event_sync(
    agent_name: str,
    correlation_id: str | UUID,
    **kwargs,
) -> bool:
    """
    Synchronous wrapper for publish_manifest_injection_event.

    Handles running/non-running event loop scenarios.
    Use async version when possible for best performance.

    Args:
        agent_name: Agent receiving the manifest injection.
        correlation_id: Request correlation ID (required for proper tracing).
        **kwargs: Additional keyword arguments forwarded to the async function.
    """
    return publish_to_kafka_sync(
        publish_manifest_injection_event(
            agent_name=agent_name,
            correlation_id=correlation_id,
            **kwargs,
        )
    )


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
