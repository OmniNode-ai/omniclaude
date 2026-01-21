# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Hook event emitter for publishing Claude Code hook events to Kafka.

This module provides the core emission logic for publishing ONEX-formatted
hook events to Kafka/Redpanda. It is designed to be called from Claude Code
hook handlers via a CLI entry point.

Design Decisions (OMN-1400):
    - Uses omnibase_infra.EventBusKafka for async Kafka publishing
    - Wrapped in asyncio.run() at CLI boundary for sync execution
    - Hard 250ms wall-clock timeout on entire emit path
    - Graceful failure: log warning and continue, never crash Claude Code
    - acks=1 for best-effort durability with fast failure
    - No retries within hooks (latency budget is tight)

Architecture:
    - handler_event_emitter.py: Core emission logic (this file)
    - cli_emit.py: CLI entry point with asyncio.run() and timeout
    - Shell scripts: Parse stdin, invoke CLI, exit 0

Performance Targets:
    - Total hook execution: <100ms
    - Kafka publish: <50ms typical, 250ms hard timeout
    - Python startup + emit: ~100-150ms total

See Also:
    - src/omniclaude/hooks/schemas.py for event payload models
    - src/omniclaude/hooks/topics.py for topic definitions
    - OMN-1400 ticket for implementation requirements
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig

from omniclaude.hooks.models import ModelEventPublishResult
from omniclaude.hooks.schemas import (
    HookEventType,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)
from omniclaude.hooks.topics import TopicBase, build_topic

if TYPE_CHECKING:
    from omniclaude.hooks.schemas import ModelHookPayload

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Constants
# =============================================================================

# Kafka configuration optimized for hook latency
# These values prioritize fast failure over reliability
DEFAULT_KAFKA_TIMEOUT_SECONDS: int = 2  # Short timeout for hooks
DEFAULT_KAFKA_MAX_RETRY_ATTEMPTS: int = 0  # No retries (latency budget)
DEFAULT_KAFKA_ACKS: str = "1"  # Leader ack only (faster than "all")


# =============================================================================
# Event Type to Topic Mapping
# =============================================================================

_EVENT_TYPE_TO_TOPIC: dict[HookEventType, TopicBase] = {
    HookEventType.SESSION_STARTED: TopicBase.SESSION_STARTED,
    HookEventType.SESSION_ENDED: TopicBase.SESSION_ENDED,
    HookEventType.PROMPT_SUBMITTED: TopicBase.PROMPT_SUBMITTED,
    HookEventType.TOOL_EXECUTED: TopicBase.TOOL_EXECUTED,
}

_PAYLOAD_TYPE_TO_EVENT_TYPE: dict[type, HookEventType] = {
    ModelHookSessionStartedPayload: HookEventType.SESSION_STARTED,
    ModelHookSessionEndedPayload: HookEventType.SESSION_ENDED,
    ModelHookPromptSubmittedPayload: HookEventType.PROMPT_SUBMITTED,
    ModelHookToolExecutedPayload: HookEventType.TOOL_EXECUTED,
}


# =============================================================================
# Helper Functions
# =============================================================================


def _get_event_type(payload: ModelHookPayload) -> HookEventType:
    """Get the event type for a payload.

    Args:
        payload: The hook event payload.

    Returns:
        The corresponding HookEventType.

    Raises:
        ValueError: If payload type is not recognized.
    """
    payload_type = type(payload)
    event_type = _PAYLOAD_TYPE_TO_EVENT_TYPE.get(payload_type)
    if event_type is None:
        raise ValueError(f"Unknown payload type: {payload_type.__name__}")
    return event_type


def _get_topic_base(event_type: HookEventType) -> TopicBase:
    """Get the topic base for an event type.

    Args:
        event_type: The hook event type.

    Returns:
        The corresponding TopicBase.

    Raises:
        ValueError: If event type has no mapped topic.
    """
    topic_base = _EVENT_TYPE_TO_TOPIC.get(event_type)
    if topic_base is None:
        raise ValueError(f"No topic mapping for event type: {event_type}")
    return topic_base


def _create_kafka_config() -> ModelKafkaEventBusConfig:
    """Create Kafka configuration optimized for hook emission.

    Configuration is loaded from environment variables with hook-specific
    defaults that prioritize latency over reliability.

    Environment Variables:
        KAFKA_BOOTSTRAP_SERVERS: Kafka broker addresses (default: localhost:9092)
        KAFKA_ENVIRONMENT: Environment prefix for topics (default: dev)

    Returns:
        Kafka configuration model.
    """
    # Get environment from env var, default to "dev"
    environment = os.environ.get("KAFKA_ENVIRONMENT", "dev")
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")

    return ModelKafkaEventBusConfig(
        bootstrap_servers=bootstrap_servers,
        environment=environment,
        group="omniclaude-hooks",
        timeout_seconds=DEFAULT_KAFKA_TIMEOUT_SECONDS,
        max_retry_attempts=DEFAULT_KAFKA_MAX_RETRY_ATTEMPTS,
        acks=DEFAULT_KAFKA_ACKS,
        # Circuit breaker settings - allow a few failures before opening
        circuit_breaker_threshold=3,
        circuit_breaker_reset_timeout=10.0,
        # No idempotence needed for observability events
        enable_idempotence=False,
    )


# =============================================================================
# Core Emission Logic
# =============================================================================


async def emit_hook_event(
    payload: ModelHookPayload,
    *,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a hook event to Kafka.

    This is the core emission function that:
    1. Determines the event type from the payload
    2. Wraps the payload in an envelope
    3. Publishes to the appropriate Kafka topic

    The function is designed to never raise exceptions to the caller.
    All errors are caught, logged, and returned as a failed result.

    Args:
        payload: The hook event payload (one of the Model*Payload types).
        environment: Optional environment override for topic prefix.
            If not provided, uses KAFKA_ENVIRONMENT env var or "dev".

    Returns:
        ModelEventPublishResult indicating success or failure.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> payload = ModelHookSessionStartedPayload(
        ...     entity_id=uuid4(),
        ...     session_id="abc123",
        ...     correlation_id=uuid4(),
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime.now(UTC),
        ...     working_directory="/workspace",
        ...     hook_source="startup",
        ... )
        >>> result = await emit_hook_event(payload)
        >>> result.success
        True
    """
    bus: EventBusKafka | None = None
    topic = "unknown"

    try:
        # Determine event type and topic
        event_type = _get_event_type(payload)
        topic_base = _get_topic_base(event_type)

        # Get environment from param, env var, or default
        env = environment or os.environ.get("KAFKA_ENVIRONMENT", "dev")
        topic = build_topic(env, topic_base)

        # Create envelope
        envelope = ModelHookEventEnvelope(
            event_type=event_type,
            payload=payload,
        )

        # Create Kafka config and bus
        config = _create_kafka_config()
        bus = EventBusKafka(config=config)

        # Start producer
        await bus.start()

        # Publish the envelope
        # Use entity_id as partition key for ordering within session
        partition_key = payload.entity_id.bytes
        message_bytes = envelope.model_dump_json().encode("utf-8")

        await bus.publish(
            topic=topic,
            key=partition_key,
            value=message_bytes,
        )

        logger.debug(
            "hook_event_emitted",
            extra={
                "topic": topic,
                "event_type": event_type.value,
                "session_id": payload.session_id,
                "entity_id": str(payload.entity_id),
            },
        )

        return ModelEventPublishResult(
            success=True,
            topic=topic,
            # Note: aiokafka doesn't return partition/offset on publish
            # These would require producer callback handling
            partition=None,
            offset=None,
        )

    except Exception as e:
        # Log warning but don't crash - observability must never break UX
        logger.warning(
            "hook_event_publish_failed",
            extra={
                "topic": topic,
                "error": str(e),
                "error_type": type(e).__name__,
                "session_id": getattr(payload, "session_id", "unknown"),
            },
        )

        return ModelEventPublishResult(
            success=False,
            topic=topic,
            error_message=f"{type(e).__name__}: {e!s}"[:1000],
        )

    finally:
        # Always close the bus if it was created
        if bus is not None:
            try:
                await bus.close()
            except Exception as close_error:
                logger.debug(
                    "kafka_bus_close_error",
                    extra={"error": str(close_error)},
                )


async def emit_session_started(
    session_id: UUID,
    working_directory: str,
    hook_source: str,
    *,
    git_branch: str | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a session started event.

    Convenience function for emitting session.started events with
    automatic timestamp injection and ID generation.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        working_directory: Current working directory of the session.
        hook_source: What triggered the session ("startup", "resume", "clear", "compact").
        git_branch: Current git branch if in a git repository.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    from uuid import uuid4

    payload = ModelHookSessionStartedPayload(
        entity_id=session_id,
        session_id=str(session_id),
        correlation_id=correlation_id or session_id,
        causation_id=causation_id or uuid4(),
        emitted_at=emitted_at or datetime.now(UTC),
        working_directory=working_directory,
        git_branch=git_branch,
        hook_source=hook_source,  # type: ignore[arg-type]
    )

    return await emit_hook_event(payload, environment=environment)


async def emit_session_ended(
    session_id: UUID,
    reason: str,
    *,
    duration_seconds: float | None = None,
    tools_used_count: int = 0,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a session ended event.

    Convenience function for emitting session.ended events.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        reason: What caused the session to end ("clear", "logout", "prompt_input_exit", "other").
        duration_seconds: Total session duration in seconds.
        tools_used_count: Number of tool invocations during the session.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    from uuid import uuid4

    payload = ModelHookSessionEndedPayload(
        entity_id=session_id,
        session_id=str(session_id),
        correlation_id=correlation_id or session_id,
        causation_id=causation_id or uuid4(),
        emitted_at=emitted_at or datetime.now(UTC),
        reason=reason,  # type: ignore[arg-type]
        duration_seconds=duration_seconds,
        tools_used_count=tools_used_count,
    )

    return await emit_hook_event(payload, environment=environment)


async def emit_prompt_submitted(
    session_id: UUID,
    prompt_id: UUID,
    prompt_preview: str,
    prompt_length: int,
    *,
    detected_intent: str | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a prompt submitted event.

    Convenience function for emitting prompt.submitted events.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        prompt_id: Unique identifier for this specific prompt.
        prompt_preview: Sanitized/truncated preview of the prompt (max 100 chars).
        prompt_length: Total character count of the original prompt.
        detected_intent: Classified intent if available.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    from uuid import uuid4

    payload = ModelHookPromptSubmittedPayload(
        entity_id=session_id,
        session_id=str(session_id),
        correlation_id=correlation_id or session_id,
        causation_id=causation_id or uuid4(),
        emitted_at=emitted_at or datetime.now(UTC),
        prompt_id=prompt_id,
        prompt_preview=prompt_preview,
        prompt_length=prompt_length,
        detected_intent=detected_intent,
    )

    return await emit_hook_event(payload, environment=environment)


async def emit_tool_executed(
    session_id: UUID,
    tool_execution_id: UUID,
    tool_name: str,
    *,
    success: bool = True,
    duration_ms: int | None = None,
    summary: str | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a tool executed event.

    Convenience function for emitting tool.executed events.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        tool_execution_id: Unique identifier for this tool execution.
        tool_name: Name of the tool (Read, Write, Edit, Bash, etc.).
        success: Whether the tool execution succeeded.
        duration_ms: Tool execution duration in milliseconds.
        summary: Brief summary of the tool execution result.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    from uuid import uuid4

    payload = ModelHookToolExecutedPayload(
        entity_id=session_id,
        session_id=str(session_id),
        correlation_id=correlation_id or session_id,
        causation_id=causation_id or uuid4(),
        emitted_at=emitted_at or datetime.now(UTC),
        tool_execution_id=tool_execution_id,
        tool_name=tool_name,
        success=success,
        duration_ms=duration_ms,
        summary=summary,
    )

    return await emit_hook_event(payload, environment=environment)


__all__ = [
    # Core emission function
    "emit_hook_event",
    # Convenience functions
    "emit_session_started",
    "emit_session_ended",
    "emit_prompt_submitted",
    "emit_tool_executed",
]
