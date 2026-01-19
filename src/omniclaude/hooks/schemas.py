# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""ONEX-compliant event schemas for Claude Code hooks.

This module provides ONEX-compatible event payload models for Claude Code hooks,
following the registration events pattern from omnibase_infra. These models
are designed for event sourcing with proper causation tracking.

IMPORTANT: Timestamp fields (emitted_at) have NO default_factory (no datetime.now()).
This is intentional per ONEX architecture - producers must explicitly inject timestamps.
This ensures:
    - Deterministic testing (fixed time in tests)
    - Consistent ordering (no clock skew between services)
    - Explicit time injection (no hidden time dependencies)

Key Design Decisions:
    - entity_id: Used as partition key for Kafka ordering guarantees.
      For Claude Code hooks, entity_id equals session_id (UUID form).
    - causation_id: Links events in a causal chain. For session.started,
      this may be a synthetic ID; for subsequent events, it references
      the previous event's message_id.
    - correlation_id: Groups all events in a logical workflow for tracing.

See Also:
    - omnibase_infra/models/registration/events/ for pattern reference
    - docs/design/ONEX_RUNTIME_REGISTRATION_TICKET_PLAN.md
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from omnibase_infra.utils import ensure_timezone_aware
from pydantic import BaseModel, ConfigDict, Field, field_validator

# =============================================================================
# Session Events
# =============================================================================


class ModelHookSessionStartedPayload(BaseModel):
    """Event payload for Claude Code session start.

    Emitted when a Claude Code session starts (startup, resume, clear, compact).
    This is the first event in a session lifecycle and establishes the
    correlation_id used by all subsequent events in the session.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string (same as entity_id in string form).
        correlation_id: Correlation ID for distributed tracing (usually equals entity_id
            for the first event in a session).
        causation_id: For session.started, this is typically a synthetic UUID
            representing the external trigger (e.g., user launching Claude Code).
        emitted_at: Timestamp when the hook emitted this event (UTC).
        working_directory: Current working directory of the session.
        git_branch: Current git branch if in a git repository.
        hook_source: What triggered the session start.

    Time Injection:
        The `emitted_at` field must be explicitly provided. Do NOT use
        datetime.now() in production - use the injected timestamp from
        the hook handler context.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookSessionStartedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        ...     working_directory="/workspace/myproject",
        ...     git_branch="main",
        ...     hook_source="startup",
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    # Entity identification (partition key)
    entity_id: UUID = Field(
        ...,
        description="Session identifier as UUID (partition key for ordering)",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier string",
    )

    # Tracing and causation
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    causation_id: UUID = Field(
        ...,
        description="ID of the event or trigger that caused this event",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    emitted_at: datetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that emitted_at is timezone-aware."""
        return ensure_timezone_aware(v)

    # Session-specific fields
    working_directory: str = Field(
        ...,
        description="Current working directory of the session",
    )
    git_branch: str | None = Field(
        default=None,
        description="Current git branch if in a git repository",
    )
    hook_source: Literal["startup", "resume", "clear", "compact"] = Field(
        ...,
        description="What triggered the session start",
    )


class ModelHookSessionEndedPayload(BaseModel):
    """Event payload for Claude Code session end.

    Emitted when a Claude Code session ends (clear, logout, exit, or other).
    This is the final event in a session lifecycle.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the previous event in the session chain.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        reason: What caused the session to end.
        duration_seconds: Total session duration if available.
        tools_used_count: Number of tool invocations during the session.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookSessionEndedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 30, 0, tzinfo=UTC),
        ...     reason="clear",
        ...     duration_seconds=1800.0,
        ...     tools_used_count=42,
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    # Entity identification (partition key)
    entity_id: UUID = Field(
        ...,
        description="Session identifier as UUID (partition key for ordering)",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier string",
    )

    # Tracing and causation
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    causation_id: UUID = Field(
        ...,
        description="ID of the previous event in the session chain",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    emitted_at: datetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that emitted_at is timezone-aware."""
        return ensure_timezone_aware(v)

    # Session end-specific fields
    reason: Literal["clear", "logout", "prompt_input_exit", "other"] = Field(
        ...,
        description="What caused the session to end",
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Total session duration in seconds if available",
    )
    tools_used_count: int = Field(
        default=0,
        ge=0,
        description="Number of tool invocations during the session",
    )


# =============================================================================
# Prompt Events
# =============================================================================


class ModelHookPromptSubmittedPayload(BaseModel):
    """Event payload for user prompt submission.

    Emitted when a user submits a prompt in Claude Code (UserPromptSubmit hook).
    This event captures metadata about the prompt without storing the full
    prompt content (privacy-conscious design).

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the previous event in the session chain.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        prompt_id: Unique identifier for this specific prompt.
        prompt_preview: First N characters of the prompt (privacy-safe preview).
        prompt_length: Total character count of the prompt.
        detected_intent: Classified intent if available (workflow, question, etc.).

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookPromptSubmittedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     prompt_id=uuid4(),
        ...     prompt_preview="Fix the bug in the authentication...",
        ...     prompt_length=150,
        ...     detected_intent="fix",
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    # Entity identification (partition key)
    entity_id: UUID = Field(
        ...,
        description="Session identifier as UUID (partition key for ordering)",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier string",
    )

    # Tracing and causation
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    causation_id: UUID = Field(
        ...,
        description="ID of the previous event in the session chain",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    emitted_at: datetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that emitted_at is timezone-aware."""
        return ensure_timezone_aware(v)

    # Prompt-specific fields
    prompt_id: UUID = Field(
        ...,
        description="Unique identifier for this specific prompt",
    )
    prompt_preview: str = Field(
        ...,
        max_length=200,
        description="First N characters of the prompt (privacy-safe preview)",
    )
    prompt_length: int = Field(
        ...,
        ge=0,
        description="Total character count of the prompt",
    )
    detected_intent: str | None = Field(
        default=None,
        description="Classified intent if available (workflow, question, fix, etc.)",
    )


# =============================================================================
# Tool Events
# =============================================================================


class ModelHookToolExecutedPayload(BaseModel):
    """Event payload for tool execution (PostToolUse hook).

    Emitted after a tool completes execution in Claude Code. This event
    captures tool execution metadata for observability and learning.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the prompt event that triggered this tool use.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        tool_execution_id: Unique identifier for this tool execution.
        tool_name: Name of the tool (Read, Write, Edit, Bash, etc.).
        success: Whether the tool execution succeeded.
        duration_ms: Tool execution duration in milliseconds.
        summary: Brief summary of the tool execution result.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookToolExecutedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 30, tzinfo=UTC),
        ...     tool_execution_id=uuid4(),
        ...     tool_name="Read",
        ...     success=True,
        ...     duration_ms=45,
        ...     summary="Read 150 lines from /workspace/src/main.py",
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    # Entity identification (partition key)
    entity_id: UUID = Field(
        ...,
        description="Session identifier as UUID (partition key for ordering)",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier string",
    )

    # Tracing and causation
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    causation_id: UUID = Field(
        ...,
        description="ID of the prompt event that triggered this tool use",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    emitted_at: datetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that emitted_at is timezone-aware."""
        return ensure_timezone_aware(v)

    # Tool execution-specific fields
    tool_execution_id: UUID = Field(
        ...,
        description="Unique identifier for this tool execution",
    )
    tool_name: str = Field(
        ...,
        min_length=1,
        description="Name of the tool (Read, Write, Edit, Bash, Grep, Glob, Task, etc.)",
    )
    success: bool = Field(
        default=True,
        description="Whether the tool execution succeeded",
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Tool execution duration in milliseconds",
    )
    summary: str | None = Field(
        default=None,
        max_length=500,
        description="Brief summary of the tool execution result",
    )


# =============================================================================
# Discriminated Union (for deserialization)
# =============================================================================


# Event type literals for discriminator
EventType = Literal[
    "hook.session.started",
    "hook.session.ended",
    "hook.prompt.submitted",
    "hook.tool.executed",
]


class ModelHookEventEnvelope(BaseModel):
    """Envelope wrapper for hook events with event type discriminator.

    This envelope wraps hook event payloads with metadata for Kafka transport.
    It includes the event type discriminator for polymorphic deserialization.

    Attributes:
        event_type: Discriminator for the event type.
        schema_version: Version of the event schema.
        source: Source service identifier.
        payload: The event payload (one of the hook payload types).

    Note:
        For direct Kafka publishing, you may serialize just the payload
        and include event_type in Kafka headers. This envelope is provided
        for scenarios requiring self-describing messages.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    event_type: EventType = Field(
        ...,
        description="Event type discriminator",
    )
    schema_version: Literal["1.0.0"] = Field(
        default="1.0.0",
        description="Version of the event schema",
    )
    source: Literal["omniclaude"] = Field(
        default="omniclaude",
        description="Source service identifier",
    )

    # Payload - using Annotated union with discriminator would require
    # a discriminator field in each payload. For simplicity, we use
    # the outer event_type as discriminator and validate consistency.
    payload: (
        ModelHookSessionStartedPayload
        | ModelHookSessionEndedPayload
        | ModelHookPromptSubmittedPayload
        | ModelHookToolExecutedPayload
    ) = Field(
        ...,
        description="The event payload",
    )


# Type alias for discriminated union of all hook payloads
ModelHookPayload = Annotated[
    ModelHookSessionStartedPayload
    | ModelHookSessionEndedPayload
    | ModelHookPromptSubmittedPayload
    | ModelHookToolExecutedPayload,
    Field(description="Union of all hook event payload types"),
]


__all__ = [
    # Payload models
    "ModelHookSessionStartedPayload",
    "ModelHookSessionEndedPayload",
    "ModelHookPromptSubmittedPayload",
    "ModelHookToolExecutedPayload",
    # Envelope and types
    "ModelHookEventEnvelope",
    "ModelHookPayload",
    "EventType",
]
