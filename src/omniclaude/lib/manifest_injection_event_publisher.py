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
import json
import logging
import os
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


class ManifestInjectionEventType(str, Enum):
    """Agent manifest injection event types with standardized topic routing.

    Topic names MUST match the canonical definitions in omniclaude/hooks/topics.py
    (TopicBase enum) to ensure consumers receive events correctly.
    """

    # Topic names use hyphens (not dots) per ONEX naming convention
    STARTED = "onex.evt.omniclaude.manifest-injection-started.v1"
    COMPLETED = "onex.evt.omniclaude.manifest-injected.v1"
    FAILED = "onex.evt.omniclaude.manifest-injection-failed.v1"

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


def _get_kafka_bootstrap_servers() -> str:
    """
    Get Kafka bootstrap servers from environment.

    Per CLAUDE.md: No localhost defaults - explicit configuration required.
    """
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        # Log warning but provide sensible default for development
        # Production should always have KAFKA_BOOTSTRAP_SERVERS set
        servers = "192.168.86.200:29092"
        logger.warning(
            f"KAFKA_BOOTSTRAP_SERVERS not set, using default: {servers}. "
            "Set this explicitly in production."
        )
    return servers


def _create_event_envelope(
    event_type: ManifestInjectionEventType,
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
        event_type: Manifest injection event type enum
        payload: Event payload containing injection data
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
        "schema_ref": f"registry://{namespace}/manifest-injection/{event_type.name.lower()}/v1",
        "payload": payload,
    }


async def get_producer_lock() -> asyncio.Lock:
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
                "aiokafka not installed. Manifest injection events will not be published. "
                "Install with: pip install aiokafka"
            )
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize Kafka producer: {e}")
            return None


async def publish_manifest_injection_event(
    agent_name: str,
    correlation_id: str | UUID | None = None,
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
        correlation_id: Request correlation ID for distributed tracing
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
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

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
                "Kafka producer unavailable, manifest injection event not published"
            )
            return False

        # Get topic name from event type enum (separate topics per event type)
        topic = event_type.get_topic_name()

        # Use correlation_id as partition key for workflow coherence
        partition_key = correlation_id.encode("utf-8")

        # Publish to Kafka with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=envelope, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        logger.debug(
            f"Published manifest injection event: {event_type.value} | "
            f"agent={agent_name} | "
            f"correlation_id={correlation_id}"
        )
        return True

    except TimeoutError:
        # Handle timeout specifically for better observability
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
    correlation_id: str | UUID | None = None,
    **kwargs: Any,
) -> bool:
    """
    Publish manifest injection start event.

    Convenience method for publishing at the start of manifest injection.
    Publishes to topic: onex.evt.omniclaude.manifest-injection.started.v1
    """
    return await publish_manifest_injection_event(
        agent_name=agent_name,
        correlation_id=correlation_id,
        event_type=ManifestInjectionEventType.STARTED,
        **kwargs,
    )


async def publish_manifest_injection_complete(
    agent_name: str,
    correlation_id: str | UUID | None = None,
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
    error_message: str,
    correlation_id: str | UUID | None = None,
    error_type: str | None = None,
    **kwargs: Any,
) -> bool:
    """
    Publish manifest injection failed event.

    Convenience method for publishing after manifest injection failure.
    Publishes to topic: onex.evt.omniclaude.manifest-injection.failed.v1
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

            # Try to use existing event loop if available and not closed
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    loop.run_until_complete(close_producer())
                    return
            except RuntimeError:
                pass

            # Event loop is closed - directly close underlying components
            try:
                if hasattr(_kafka_producer, "_client") and _kafka_producer._client:
                    _kafka_producer._client.close()
                _kafka_producer = None
                logger.debug("Kafka producer closed (synchronous cleanup)")
            except Exception:
                _kafka_producer = None

        except Exception:
            _kafka_producer = None


# Register cleanup on interpreter exit
atexit.register(_cleanup_producer_sync)


# Synchronous wrapper for backward compatibility
def publish_manifest_injection_event_sync(
    agent_name: str,
    **kwargs: Any,
) -> bool:
    """
    Synchronous wrapper for publish_manifest_injection_event.

    Creates new event loop if needed. Use async version when possible.

    WARNING: Do not call this from async code (within a running event loop).
    Doing so will raise RuntimeError. Use `publish_manifest_injection_event` directly
    in async contexts, or call via `asyncio.run_coroutine_threadsafe()`.

    Raises:
        RuntimeError: If called from within a running event loop
    """
    # Check if we're already in an async context
    try:
        asyncio.get_running_loop()
        # If we get here, there IS a running loop - we cannot use run_until_complete
        raise RuntimeError(
            "Cannot call publish_manifest_injection_event_sync from within a running event loop. "
            "Use `await publish_manifest_injection_event(...)` instead, or run in a separate thread."
        )
    except RuntimeError as e:
        # If the error is our own, re-raise it
        if "Cannot call publish_manifest_injection_event_sync" in str(e):
            raise
        # Otherwise, no running loop exists - create one for sync execution
        pass

    # No running loop - safe to create and run synchronously
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            publish_manifest_injection_event(
                agent_name=agent_name,
                **kwargs,
            )
        )
    finally:
        loop.close()


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
            error_message="Agent YAML file not found",
            error_type="FileNotFoundError",
            correlation_id=str(uuid4()),
            session_id=session_id,
        )
        print(f"Failed event: {'OK' if success_failed else 'FAILED'}")

        await close_producer()

    asyncio.run(test())
