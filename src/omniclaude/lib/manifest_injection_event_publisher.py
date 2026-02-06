#!/usr/bin/env python3
"""
Manifest Injection Event Publisher - Kafka Integration

Publishes agent manifest injection events to Kafka for async logging and observability.
Follows EVENT_BUS_INTEGRATION_PATTERNS standards with OnexEnvelopeV1 wrapping.

Usage:
    from omniclaude.lib.manifest_injection_event_publisher import publish_manifest_injection_event

    await publish_manifest_injection_event(
        agent_name="agent-api-architect",
        agent_domain="api-development",
        correlation_id=correlation_id,
        session_id=session_id,
        injection_success=True,
        injection_duration_ms=45
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- OnexEnvelopeV1 standard event envelope
- Correlation ID tracking for distributed tracing

DESIGN RULE: Non-Blocking Event Emission
=========================================
Event emission is BEST-EFFORT, NEVER blocks execution.

- Manifest injection MUST NOT depend on Kafka
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

from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.kafka_producer_utils import (
    KAFKA_PUBLISH_TIMEOUT_SECONDS,
    KafkaProducerManager,
    build_kafka_topic,
    create_event_envelope,
)

logger = logging.getLogger(__name__)

class ManifestInjectionEventType(str, Enum):
    """Agent manifest injection event types with standardized topic routing.

    Values are derived from TopicBase to ensure single source of truth.
    This prevents drift between event types and actual Kafka topics.
    """

    # Reference TopicBase constants - single source of truth for topic names
    STARTED = TopicBase.MANIFEST_INJECTION_STARTED.value
    COMPLETED = TopicBase.MANIFEST_INJECTED.value
    FAILED = TopicBase.MANIFEST_INJECTION_FAILED.value

    def get_topic_name(self) -> str:
        """
        Get Kafka topic name for this event type.

        Returns topic following ONEX topic naming convention:
        onex.evt.{producer}.{event-name}.v{n}
        """
        return self.value


# Kafka producer manager (shared utilities from kafka_producer_utils)
_producer_manager = KafkaProducerManager(name="manifest-injection")


# Backwards-compatible aliases for tests that reference internal functions
async def get_producer_lock():
    """Get producer lock (delegates to KafkaProducerManager)."""
    return await _producer_manager.get_lock()


async def _get_kafka_producer():
    """Get producer (delegates to KafkaProducerManager)."""
    return await _producer_manager.get_producer()


async def publish_manifest_injection_event(
    agent_name: str,
    correlation_id: str | UUID,
    session_id: str | UUID | None = None,
    agent_domain: str | None = None,
    injection_success: bool = True,
    injection_duration_ms: int | None = None,
    yaml_path: str | None = None,
    agent_version: str | None = None,
    agent_capabilities: list[str] | None = None,
    activation_patterns: list[str] | None = None,
    error_message: str | None = None,
    error_type: str | None = None,
    routing_source: str | None = None,
    event_type: ManifestInjectionEventType = ManifestInjectionEventType.COMPLETED,
    tenant_id: str = "default",
    namespace: str = "onex",
    causation_id: str | None = None,
) -> bool:
    """
    Publish agent manifest injection event to Kafka following EVENT_BUS_INTEGRATION_PATTERNS.

    Events are wrapped in OnexEnvelopeV1 standard envelope and routed to separate topics
    based on event type (started/completed/failed).

    IMPORTANT: This function is non-blocking and best-effort. It will NOT raise
    exceptions on failure - failures are logged but execution continues.

    Args:
        agent_name: Name of the agent being loaded (e.g., "agent-api-architect")
        correlation_id: Required correlation ID for distributed tracing (no auto-generation)
        session_id: Session ID for grouping related executions
        agent_domain: Domain of the agent (e.g., "api-development", "testing")
        injection_success: Whether the manifest injection succeeded
        injection_duration_ms: Time to load and inject manifest
        yaml_path: Path to the agent YAML file (optional, for debugging)
        agent_version: Version of the agent definition
        agent_capabilities: List of agent capabilities from manifest
        activation_patterns: Patterns that triggered this agent selection
        error_message: Error details if failed
        error_type: Error classification
        routing_source: How the agent was selected (explicit, fuzzy_match, fallback)
        event_type: Event type enum (STARTED/COMPLETED/FAILED)
        tenant_id: Tenant identifier for multi-tenancy
        namespace: Event namespace for routing
        causation_id: Causation ID for event chains

    Returns:
        bool: True if published successfully, False otherwise
    """
    try:
        # Convert correlation_id to string (required parameter - no auto-generation)
        correlation_id_str = str(correlation_id)

        if session_id is not None:
            session_id = str(session_id)

        # Build event payload (everything except envelope metadata)
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "session_id": session_id,
            "injection_success": injection_success,
            "injection_duration_ms": injection_duration_ms,
            "yaml_path": yaml_path,
            "agent_version": agent_version,
            "agent_capabilities": agent_capabilities,
            "activation_patterns": activation_patterns,
            "error_message": error_message,
            "error_type": error_type,
            "routing_source": routing_source,
            "emitted_at": datetime.now(UTC).isoformat(),
        }

        # Remove None values to keep payload compact
        payload = {k: v for k, v in payload.items() if v is not None}

        # Wrap payload in OnexEnvelopeV1 standard envelope
        envelope = create_event_envelope(
            event_type_value=event_type.value,
            event_type_name=event_type.name.lower(),
            payload=payload,
            correlation_id=correlation_id_str,
            schema_domain="manifest-injection",
            source="omniclaude",
            tenant_id=tenant_id,
            namespace=namespace,
            causation_id=causation_id,
        )

        # Get producer (uses module-level function for testability)
        producer = await _get_kafka_producer()
        if producer is None:
            logger.debug(
                "Kafka producer unavailable, manifest injection event not published"
            )
            return False

        # Build ONEX-compliant topic name with environment prefix
        topic = build_kafka_topic(event_type.get_topic_name())

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id_str.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published manifest injection event: "
            f"agent={agent_name} | "
            f"correlation_id={correlation_id_str}"
        )
        return True

    except TimeoutError:
        logger.warning(
            f"Timeout publishing manifest injection event "
            f"(event_type={event_type.value}, timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)"
        )
        return False

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.warning(f"Failed to publish manifest injection event: {e}")
        return False


async def publish_manifest_injection_start(
    agent_name: str,
    correlation_id: str | UUID,
    **kwargs: Any,
) -> bool:
    """
    Publish manifest injection start event.

    Convenience method for publishing at the start of manifest injection.
    Publishes to topic: onex.evt.omniclaude.manifest-injection-started.v1
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        correlation_id=correlation_id,
        event_type=ManifestInjectionEventType.STARTED,
        **kwargs,
    )


async def publish_manifest_injection_complete(
    agent_name: str,
    correlation_id: str | UUID,
    injection_duration_ms: int | None = None,
    **kwargs: Any,
) -> bool:
    """
    Publish manifest injection complete event.

    Convenience method for publishing after successful manifest injection.
    Publishes to topic: onex.evt.omniclaude.manifest-injected.v1
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        correlation_id=correlation_id,
        injection_duration_ms=injection_duration_ms,
        injection_success=True,
        event_type=ManifestInjectionEventType.COMPLETED,
        **kwargs,
    )


async def publish_manifest_injection_failed(
    agent_name: str,
    correlation_id: str | UUID,
    error_message: str,
    error_type: str | None = None,
    **kwargs: Any,
) -> bool:
    """
    Publish manifest injection failed event.

    Convenience method for publishing after manifest injection failure.
    Publishes to topic: onex.evt.omniclaude.manifest-injection-failed.v1
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        correlation_id=correlation_id,
        error_message=error_message,
        error_type=error_type,
        injection_success=False,
        event_type=ManifestInjectionEventType.FAILED,
        **kwargs,
    )


async def close_producer() -> None:
    """Close Kafka producer on shutdown."""
    await _producer_manager.close()


# Register cleanup on interpreter exit
atexit.register(_producer_manager.cleanup_sync)


# Synchronous wrapper for backward compatibility
def publish_manifest_injection_event_sync(
    agent_name: str,
    **kwargs: Any,
) -> bool:
    """
    Synchronous wrapper for publish_manifest_injection_event.

    Handles both sync and async calling contexts safely:
    - From sync context: Creates new event loop and runs directly
    - From async context: Uses ThreadPoolExecutor to avoid nested loop issues

    Note: ThreadPoolExecutor per-call overhead is intentional for correctness.
    The alternative (reusing executors) adds complexity and state management
    concerns that aren't justified for event publishing use cases.

    Args:
        agent_name: The agent whose manifest is being injected
        **kwargs: Additional arguments passed to publish_manifest_injection_event

    Returns:
        bool: True if event was published successfully
    """
    import concurrent.futures

    # Check if we're already in an async context
    try:
        asyncio.get_running_loop()
        # Already in async context - use thread pool to avoid nested loop issues
        logger.debug("publish_manifest_injection_event_sync called from async context, using ThreadPoolExecutor")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                publish_manifest_injection_event(
                    agent_name=agent_name,
                    **kwargs,
                ),
            )
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run() directly
        return asyncio.run(
            publish_manifest_injection_event(
                agent_name=agent_name,
                **kwargs,
            )
        )


if __name__ == "__main__":
    # Test manifest injection event publishing
    async def test() -> None:
        logging.basicConfig(level=logging.DEBUG)

        correlation_id = str(uuid4())
        session_id = str(uuid4())

        print("Testing manifest injection events...")
        print(f"Correlation ID: {correlation_id}")

        # Test manifest injection start
        success_start = await publish_manifest_injection_start(
            agent_name="agent-api-architect",
            correlation_id=correlation_id,
            session_id=session_id,
            agent_domain="api-development",
        )
        print(f"Start event: {'OK' if success_start else 'FAILED'}")

        # Test manifest injection complete
        success_complete = await publish_manifest_injection_complete(
            agent_name="agent-api-architect",
            correlation_id=correlation_id,
            session_id=session_id,
            agent_domain="api-development",
            injection_duration_ms=45,
            yaml_path="/path/to/agent-api-architect.yaml",
            agent_capabilities=["api_design", "openapi_generation"],
        )
        print(f"Complete event: {'OK' if success_complete else 'FAILED'}")

        # Test manifest injection failed
        success_failed = await publish_manifest_injection_failed(
            agent_name="agent-nonexistent",
            correlation_id=str(uuid4()),
            error_message="Agent YAML file not found",
            error_type="FileNotFoundError",
            session_id=session_id,
        )
        print(f"Failed event: {'OK' if success_failed else 'FAILED'}")

        await close_producer()

    asyncio.run(test())
