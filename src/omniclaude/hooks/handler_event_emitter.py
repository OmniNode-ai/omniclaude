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
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from omnibase_core.enums import EnumCoreErrorCode
from omnibase_core.models.errors import ModelOnexError
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig

from omniclaude.hooks.models import ModelEventPublishResult
from omniclaude.hooks.schemas import (
    HookEventType,
    HookSource,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    SessionEndReason,
)
from omniclaude.hooks.topics import TopicBase, build_topic

if TYPE_CHECKING:
    from omniclaude.hooks.schemas import ModelHookPayload

logger = logging.getLogger(__name__)

# =============================================================================
# Event Config Models (ONEX: Parameter reduction pattern)
# =============================================================================


@dataclass(frozen=True)
class ModelEventTracingConfig:
    """Common tracing configuration for hook event emission.

    Groups related tracing parameters that are shared across all emit_*
    functions to reduce function signature complexity per ONEX guidelines.

    Attributes:
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the event/trigger that caused this event.
        emitted_at: Event timestamp (defaults to now UTC if not provided).
        environment: Kafka environment prefix (e.g., "dev", "staging", "prod").
    """

    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    emitted_at: datetime | None = None
    environment: str | None = None


@dataclass(frozen=True)
class ModelToolExecutedConfig:
    """Configuration for tool executed events.

    Groups parameters for emit_tool_executed() to reduce function signature
    complexity per ONEX parameter guidelines.

    Attributes:
        session_id: Unique session identifier.
        tool_execution_id: Unique identifier for this tool execution.
        tool_name: Name of the tool (Read, Write, Edit, Bash, etc.).
        success: Whether the tool execution succeeded.
        duration_ms: Tool execution duration in milliseconds.
        summary: Brief summary of the tool execution result.
        tracing: Optional tracing configuration.
    """

    session_id: UUID
    tool_execution_id: UUID
    tool_name: str
    success: bool = True
    duration_ms: int | None = None
    summary: str | None = None
    tracing: ModelEventTracingConfig = field(default_factory=ModelEventTracingConfig)


@dataclass(frozen=True)
class ModelPromptSubmittedConfig:
    """Configuration for prompt submitted events.

    Groups parameters for emit_prompt_submitted() to reduce function signature
    complexity per ONEX parameter guidelines.

    Attributes:
        session_id: Unique session identifier.
        prompt_id: Unique identifier for this specific prompt.
        prompt_preview: Sanitized/truncated preview of the prompt.
        prompt_length: Total character count of the original prompt.
        detected_intent: Classified intent if available.
        tracing: Optional tracing configuration.
    """

    session_id: UUID
    prompt_id: UUID
    prompt_preview: str
    prompt_length: int
    detected_intent: str | None = None
    tracing: ModelEventTracingConfig = field(default_factory=ModelEventTracingConfig)


@dataclass(frozen=True)
class ModelSessionStartedConfig:
    """Configuration for session started events.

    Groups parameters for emit_session_started() to reduce function signature
    complexity per ONEX parameter guidelines.

    Attributes:
        session_id: Unique session identifier.
        working_directory: Current working directory of the session.
        hook_source: What triggered the session start.
        git_branch: Current git branch if in a git repository.
        tracing: Optional tracing configuration.
    """

    session_id: UUID
    working_directory: str
    hook_source: HookSource
    git_branch: str | None = None
    tracing: ModelEventTracingConfig = field(default_factory=ModelEventTracingConfig)


@dataclass(frozen=True)
class ModelSessionEndedConfig:
    """Configuration for session ended events.

    Groups parameters for emit_session_ended() to reduce function signature
    complexity per ONEX parameter guidelines.

    Attributes:
        session_id: Unique session identifier.
        reason: What caused the session to end.
        duration_seconds: Total session duration in seconds.
        tools_used_count: Number of tool invocations during the session.
        tracing: Optional tracing configuration.
    """

    session_id: UUID
    reason: SessionEndReason
    duration_seconds: float | None = None
    tools_used_count: int = 0
    tracing: ModelEventTracingConfig = field(default_factory=ModelEventTracingConfig)


# =============================================================================
# Configuration Constants
# =============================================================================

# Kafka configuration optimized for hook latency
# These values prioritize fast failure over reliability
#
# DEFAULT_KAFKA_TIMEOUT_SECONDS: Short timeout for production hooks where
# latency is critical. Can be overridden via KAFKA_HOOK_TIMEOUT_SECONDS
# environment variable for integration tests that need more time to connect
# to remote Kafka brokers.
DEFAULT_KAFKA_TIMEOUT_SECONDS: int = 2  # Short timeout for hooks
DEFAULT_KAFKA_MAX_RETRY_ATTEMPTS: int = 0  # No retries (latency budget)
DEFAULT_KAFKA_ACKS: str = "all"  # Using "all" due to aiokafka bug with string "1"


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
        ModelOnexError: If payload type is not recognized.
    """
    payload_type = type(payload)
    event_type = _PAYLOAD_TYPE_TO_EVENT_TYPE.get(payload_type)
    if event_type is None:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"Unknown payload type: {payload_type.__name__}",
        )
    return event_type


def _get_topic_base(event_type: HookEventType) -> TopicBase:
    """Get the topic base for an event type.

    Args:
        event_type: The hook event type.

    Returns:
        The corresponding TopicBase.

    Raises:
        ModelOnexError: If event type has no mapped topic.
    """
    topic_base = _EVENT_TYPE_TO_TOPIC.get(event_type)
    if topic_base is None:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"No topic mapping for event type: {event_type}",
        )
    return topic_base


def _create_kafka_config() -> ModelKafkaEventBusConfig:
    """Create Kafka configuration optimized for hook emission.

    Configuration is loaded from environment variables with hook-specific
    defaults that prioritize latency over reliability.

    Environment Variables:
        KAFKA_BOOTSTRAP_SERVERS: Kafka broker addresses (required)
        KAFKA_ENVIRONMENT: Environment prefix for topics (default: dev)
        KAFKA_HOOK_TIMEOUT_SECONDS: Connection timeout in seconds (default: 2)
            Set to higher value (e.g., 30) for integration tests with remote brokers.

    Returns:
        Kafka configuration model.

    Raises:
        ModelOnexError: If KAFKA_BOOTSTRAP_SERVERS is not set.
    """
    # Get environment from env var, default to "dev"
    environment = os.environ.get("KAFKA_ENVIRONMENT", "dev")
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap_servers:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message="KAFKA_BOOTSTRAP_SERVERS environment variable is required",
        )

    # Allow timeout override for integration tests
    # Production hooks use short timeout (2s) for fast failure
    # Integration tests may need longer timeout (30s) for remote brokers
    timeout_str = os.environ.get("KAFKA_HOOK_TIMEOUT_SECONDS")
    if timeout_str is not None:
        try:
            timeout_seconds = int(timeout_str)
        except ValueError:
            timeout_seconds = DEFAULT_KAFKA_TIMEOUT_SECONDS
    else:
        timeout_seconds = DEFAULT_KAFKA_TIMEOUT_SECONDS

    return ModelKafkaEventBusConfig(
        bootstrap_servers=bootstrap_servers,
        environment=environment,
        group="omniclaude-hooks",
        timeout_seconds=timeout_seconds,
        max_retry_attempts=DEFAULT_KAFKA_MAX_RETRY_ATTEMPTS,
        acks=DEFAULT_KAFKA_ACKS,
        # Circuit breaker settings: Allow 5 failures before opening circuit to
        # handle transient broker issues during high-volume Claude Code sessions.
        # With 10s reset timeout, this prevents excessive reconnection attempts
        # while still recovering quickly from temporary network issues.
        circuit_breaker_threshold=5,
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
        #
        # Partition Key Strategy: Session-based ordering
        # -----------------------------------------------
        # We use entity_id (session UUID) as the partition key to guarantee
        # strict ordering of events within a session. UUID.bytes returns 16
        # bytes which Kafka hashes to determine the target partition.
        #
        # Trade-off: Ordering vs Distribution
        # ------------------------------------
        # This approach prioritizes event ordering over uniform partition
        # distribution. UUID hashing does not guarantee even distribution
        # across partitions, which could theoretically cause "hot partitions"
        # where some partitions receive more traffic than others.
        #
        # Why this is acceptable for Claude Code hooks:
        # - Low event volume: ~4-10 events per session (start, prompts, tools, end)
        # - Short session duration: Most sessions are minutes, not hours
        # - Observability-only: These events are for analytics/learning, not
        #   critical path processing. Slight consumer lag is acceptable.
        # - Ordering requirement: Session events MUST be processed in order
        #   for accurate session reconstruction and duration calculation.
        #
        # Alternative considered: Random partitioning (key=None)
        # - Would provide better distribution across partitions
        # - BUT would lose event ordering guarantees within a session
        # - Consumers would need complex reordering logic
        # - Not worth the complexity for our low-volume observability use case
        #
        # If volume increases significantly (e.g., 1000+ concurrent sessions),
        # consider: (1) increasing partition count, or (2) using a hash of
        # session_id modulo a smaller key space for better distribution.
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

        error_msg = f"{type(e).__name__}: {e!s}"
        return ModelEventPublishResult(
            success=False,
            topic=topic,
            error_message=(
                error_msg[:997] + "..." if len(error_msg) > 1000 else error_msg
            ),
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


async def emit_session_started_from_config(
    config: ModelSessionStartedConfig,
) -> ModelEventPublishResult:
    """Emit a session started event from config object.

    Args:
        config: Session started configuration containing all event data.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    tracing = config.tracing
    payload = ModelHookSessionStartedPayload(
        entity_id=config.session_id,
        session_id=str(config.session_id),
        correlation_id=tracing.correlation_id or config.session_id,
        causation_id=tracing.causation_id or uuid4(),
        emitted_at=tracing.emitted_at or datetime.now(UTC),
        working_directory=config.working_directory,
        git_branch=config.git_branch,
        hook_source=config.hook_source,
    )

    return await emit_hook_event(payload, environment=tracing.environment)


async def emit_session_started(
    session_id: UUID,
    working_directory: str,
    hook_source: HookSource,
    *,
    git_branch: str | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a session started event.

    Note:
        Consider using emit_session_started_from_config() with
        ModelSessionStartedConfig for better parameter organization.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        working_directory: Current working directory of the session.
        hook_source: What triggered the session (HookSource enum).
        git_branch: Current git branch if in a git repository.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.

    .. deprecated::
        Use :func:`emit_session_started_from_config` with
        :class:`ModelSessionStartedConfig` instead.
    """
    # ONEX: exempt - backwards compatibility wrapper for config-based method
    warnings.warn(
        "emit_session_started() is deprecated, use emit_session_started_from_config() "
        "with ModelSessionStartedConfig instead",
        DeprecationWarning,
        stacklevel=2,
    )
    config = ModelSessionStartedConfig(
        session_id=session_id,
        working_directory=working_directory,
        hook_source=hook_source,
        git_branch=git_branch,
        tracing=ModelEventTracingConfig(
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            environment=environment,
        ),
    )
    return await emit_session_started_from_config(config)


async def emit_session_ended_from_config(
    config: ModelSessionEndedConfig,
) -> ModelEventPublishResult:
    """Emit a session ended event from config object.

    Args:
        config: Session ended configuration containing all event data.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    tracing = config.tracing
    payload = ModelHookSessionEndedPayload(
        entity_id=config.session_id,
        session_id=str(config.session_id),
        correlation_id=tracing.correlation_id or config.session_id,
        causation_id=tracing.causation_id or uuid4(),
        emitted_at=tracing.emitted_at or datetime.now(UTC),
        reason=config.reason,
        duration_seconds=config.duration_seconds,
        tools_used_count=config.tools_used_count,
    )

    return await emit_hook_event(payload, environment=tracing.environment)


async def emit_session_ended(
    session_id: UUID,
    reason: SessionEndReason,
    *,
    duration_seconds: float | None = None,
    tools_used_count: int = 0,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    environment: str | None = None,
) -> ModelEventPublishResult:
    """Emit a session ended event.

    Note:
        Consider using emit_session_ended_from_config() with
        ModelSessionEndedConfig for better parameter organization.

    Args:
        session_id: Unique session identifier (also used as entity_id).
        reason: What caused the session to end (SessionEndReason enum).
        duration_seconds: Total session duration in seconds.
        tools_used_count: Number of tool invocations during the session.
        correlation_id: Correlation ID for tracing (defaults to session_id).
        causation_id: Causation ID for event chain (generated if not provided).
        emitted_at: Event timestamp (defaults to now UTC).
        environment: Kafka environment prefix.

    Returns:
        ModelEventPublishResult indicating success or failure.

    .. deprecated::
        Use :func:`emit_session_ended_from_config` with
        :class:`ModelSessionEndedConfig` instead.
    """
    # ONEX: exempt - backwards compatibility wrapper for config-based method
    warnings.warn(
        "emit_session_ended() is deprecated, use emit_session_ended_from_config() "
        "with ModelSessionEndedConfig instead",
        DeprecationWarning,
        stacklevel=2,
    )
    config = ModelSessionEndedConfig(
        session_id=session_id,
        reason=reason,
        duration_seconds=duration_seconds,
        tools_used_count=tools_used_count,
        tracing=ModelEventTracingConfig(
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            environment=environment,
        ),
    )
    return await emit_session_ended_from_config(config)


async def emit_prompt_submitted_from_config(
    config: ModelPromptSubmittedConfig,
) -> ModelEventPublishResult:
    """Emit a prompt submitted event from config object.

    Args:
        config: Prompt submitted configuration containing all event data.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    tracing = config.tracing
    payload = ModelHookPromptSubmittedPayload(
        entity_id=config.session_id,
        session_id=str(config.session_id),
        correlation_id=tracing.correlation_id or config.session_id,
        causation_id=tracing.causation_id or uuid4(),
        emitted_at=tracing.emitted_at or datetime.now(UTC),
        prompt_id=config.prompt_id,
        prompt_preview=config.prompt_preview,
        prompt_length=config.prompt_length,
        detected_intent=config.detected_intent,
    )

    return await emit_hook_event(payload, environment=tracing.environment)


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

    Note:
        Consider using emit_prompt_submitted_from_config() with
        ModelPromptSubmittedConfig for better parameter organization.

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

    .. deprecated::
        Use :func:`emit_prompt_submitted_from_config` with
        :class:`ModelPromptSubmittedConfig` instead.
    """
    # ONEX: exempt - backwards compatibility wrapper for config-based method
    warnings.warn(
        "emit_prompt_submitted() is deprecated, use emit_prompt_submitted_from_config() "
        "with ModelPromptSubmittedConfig instead",
        DeprecationWarning,
        stacklevel=2,
    )
    config = ModelPromptSubmittedConfig(
        session_id=session_id,
        prompt_id=prompt_id,
        prompt_preview=prompt_preview,
        prompt_length=prompt_length,
        detected_intent=detected_intent,
        tracing=ModelEventTracingConfig(
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            environment=environment,
        ),
    )
    return await emit_prompt_submitted_from_config(config)


async def emit_tool_executed_from_config(
    config: ModelToolExecutedConfig,
) -> ModelEventPublishResult:
    """Emit a tool executed event from config object.

    Args:
        config: Tool executed configuration containing all event data.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    tracing = config.tracing
    payload = ModelHookToolExecutedPayload(
        entity_id=config.session_id,
        session_id=str(config.session_id),
        correlation_id=tracing.correlation_id or config.session_id,
        causation_id=tracing.causation_id or uuid4(),
        emitted_at=tracing.emitted_at or datetime.now(UTC),
        tool_execution_id=config.tool_execution_id,
        tool_name=config.tool_name,
        success=config.success,
        duration_ms=config.duration_ms,
        summary=config.summary,
    )

    return await emit_hook_event(payload, environment=tracing.environment)


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

    Note:
        Consider using emit_tool_executed_from_config() with
        ModelToolExecutedConfig for better parameter organization.

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

    .. deprecated::
        Use :func:`emit_tool_executed_from_config` with
        :class:`ModelToolExecutedConfig` instead.
    """
    # ONEX: exempt - backwards compatibility wrapper for config-based method
    warnings.warn(
        "emit_tool_executed() is deprecated, use emit_tool_executed_from_config() "
        "with ModelToolExecutedConfig instead",
        DeprecationWarning,
        stacklevel=2,
    )
    config = ModelToolExecutedConfig(
        session_id=session_id,
        tool_execution_id=tool_execution_id,
        tool_name=tool_name,
        success=success,
        duration_ms=duration_ms,
        summary=summary,
        tracing=ModelEventTracingConfig(
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            environment=environment,
        ),
    )
    return await emit_tool_executed_from_config(config)


__all__ = [
    # Config models
    "ModelEventTracingConfig",
    "ModelToolExecutedConfig",
    "ModelPromptSubmittedConfig",
    "ModelSessionStartedConfig",
    "ModelSessionEndedConfig",
    # Core emission function
    "emit_hook_event",
    # Config-based convenience functions
    "emit_session_started_from_config",
    "emit_session_ended_from_config",
    "emit_prompt_submitted_from_config",
    "emit_tool_executed_from_config",
    # Backwards-compatible convenience functions
    "emit_session_started",
    "emit_session_ended",
    "emit_prompt_submitted",
    "emit_tool_executed",
]
