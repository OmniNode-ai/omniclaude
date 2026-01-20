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

Privacy Considerations:
    This module handles potentially sensitive data from user sessions. Key
    privacy-sensitive fields and their handling:

    - **prompt_preview**: User prompt content, truncated to 100 chars and
      automatically sanitized to redact common secret patterns (API keys,
      passwords, tokens). Despite sanitization, treat as potentially sensitive.
      See _sanitize_prompt_preview() and PROMPT_PREVIEW_MAX_LENGTH.

    - **working_directory**: File system path that may reveal usernames,
      project names, or organizational structure. Consider anonymizing in
      aggregated analytics.

    - **git_branch**: Branch names may contain ticket IDs, feature names,
      or developer identifiers. Treat as potentially identifying.

    - **summary** (tool execution): May contain file paths, code snippets,
      or error messages with sensitive data. Limited to 500 chars.

    - **session_id / entity_id**: Tracking identifiers that link user activity.
      Implement appropriate data retention policies.

    Data Retention Recommendations:
        - Raw events: 30-90 days (operational needs)
        - Aggregated metrics: Longer retention acceptable
        - Prompt previews: Shortest possible retention
        - Apply GDPR/CCPA deletion requirements as applicable

    Access Control Recommendations:
        - Limit access to raw events to authorized operators
        - Anonymize data for analytics and ML training
        - Audit access to privacy-sensitive fields

See Also:
    - omnibase_infra/models/registration/events/ for pattern reference
    - docs/design/ONEX_RUNTIME_REGISTRATION_TICKET_PLAN.md
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from omnibase_infra.utils import ensure_timezone_aware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =============================================================================
# Event Types
# =============================================================================


class HookEventType(StrEnum):
    """Event types for Claude Code hooks.

    Using StrEnum for type safety and IDE autocompletion.
    Values are used as Kafka message type identifiers.
    """

    SESSION_STARTED = "hook.session.started"
    SESSION_ENDED = "hook.session.ended"
    PROMPT_SUBMITTED = "hook.prompt.submitted"
    TOOL_EXECUTED = "hook.tool.executed"


# =============================================================================
# Constants
# =============================================================================

# Privacy: Maximum length for prompt preview to limit exposure of sensitive data
PROMPT_PREVIEW_MAX_LENGTH: int = 100

# Privacy: Patterns that may indicate secrets (compiled for performance)
# These patterns are intentionally simple to avoid false negatives
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API keys with common prefixes
    (re.compile(r"\b(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE), "sk-***REDACTED***"),
    (re.compile(r"\b(AKIA[A-Z0-9]{16})", re.IGNORECASE), "AKIA***REDACTED***"),
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{36})", re.IGNORECASE), "ghp_***REDACTED***"),
    (re.compile(r"\b(gho_[a-zA-Z0-9]{36})", re.IGNORECASE), "gho_***REDACTED***"),
    (
        re.compile(r"\b(xox[baprs]-[a-zA-Z0-9-]{10,})", re.IGNORECASE),
        "xox*-***REDACTED***",
    ),
    # Stripe API keys (publishable, secret, and restricted)
    # Format: (sk|pk|rk)_(live|test)_[a-zA-Z0-9]{24,}
    # Reference: https://stripe.com/docs/keys
    (
        re.compile(r"\b((?:sk|pk|rk)_(?:live|test)_[a-zA-Z0-9]{24,})", re.IGNORECASE),
        "stripe_***REDACTED***",
    ),
    # Google Cloud Platform API keys
    # Format: AIza[0-9A-Za-z-_]{35}
    # Reference: https://cloud.google.com/docs/authentication/api-keys
    (re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})"), "AIza***REDACTED***"),
    # Private keys (PEM format)
    # Matches RSA, EC, generic, and encrypted private key headers
    # Reference: RFC 7468 (Textual Encodings of PKIX, PKCS, and CMS Structures)
    (
        re.compile(r"-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----"),
        "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
    ),
    # Bearer tokens
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9._-]{20,}", re.IGNORECASE), r"\1***REDACTED***"),
    # Password in URLs (postgres://user:password@host)
    (re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
    # Generic secret patterns in key=value format
    (
        re.compile(
            r"((?:password|passwd|secret|token|api_key|apikey|auth)\s*[=:]\s*)['\"]?[^\s'\"]{8,}['\"]?",
            re.IGNORECASE,
        ),
        r"\1***REDACTED***",
    ),
]


# =============================================================================
# Reusable Validators
# =============================================================================


def _validate_timezone_aware(v: datetime) -> datetime:
    """Validate and ensure datetime is timezone-aware.

    This is extracted as a reusable function to avoid code duplication
    across all payload models that have emitted_at fields.

    Args:
        v: The datetime value to validate.

    Returns:
        The timezone-aware datetime.

    Raises:
        ValueError: If the datetime cannot be made timezone-aware.
    """
    result: datetime = ensure_timezone_aware(v)
    return result


def _sanitize_prompt_preview(
    text: str, max_length: int = PROMPT_PREVIEW_MAX_LENGTH
) -> str:
    """Sanitize and truncate prompt preview for privacy safety.

    This function performs two privacy-protecting operations:
    1. Redacts common secret patterns (API keys, passwords, tokens)
    2. Truncates to max_length with ellipsis indicator

    Privacy Considerations:
        - Prompt previews may inadvertently contain sensitive data
        - This sanitizer uses pattern matching which may have false negatives
        - For maximum security, producers should pre-sanitize prompts
        - Downstream consumers should treat previews as potentially sensitive

    Args:
        text: The raw prompt text to sanitize.
        max_length: Maximum length for the preview (default: PROMPT_PREVIEW_MAX_LENGTH).

    Returns:
        Sanitized and truncated preview string.

    Example:
        >>> _sanitize_prompt_preview("Set OPENAI_API_KEY=sk-1234567890abcdef...")
        'Set OPENAI_API_KEY=sk-***REDACTED***...'
    """
    # Step 1: Redact known secret patterns
    sanitized = text
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    # Step 2: Truncate with ellipsis if needed
    if len(sanitized) > max_length:
        # Reserve 3 chars for "..." suffix
        return sanitized[: max_length - 3] + "..."

    return sanitized


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
        return _validate_timezone_aware(v)

    # Session-specific fields
    # PRIVACY: working_directory may reveal usernames, project names, or org structure.
    # Consider anonymizing in aggregated analytics or when sharing externally.
    working_directory: str = Field(
        ...,
        description=(
            "Current working directory of the session. "
            "PRIVACY: May contain usernames or organizational paths. "
            "Anonymize in aggregated analytics."
        ),
    )
    # PRIVACY: git_branch may contain ticket IDs, feature names, or developer identifiers.
    git_branch: str | None = Field(
        default=None,
        description=(
            "Current git branch if in a git repository. "
            "PRIVACY: May contain ticket IDs or developer identifiers."
        ),
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
        return _validate_timezone_aware(v)

    # Session end-specific fields
    reason: Literal["clear", "logout", "prompt_input_exit", "other"] = Field(
        ...,
        description="What caused the session to end",
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
        le=86400 * 30,  # Max 30 days (2,592,000 seconds)
        description="Total session duration in seconds if available (max 30 days)",
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

    Privacy Guidelines:
        - The prompt_preview field is automatically sanitized to redact common
          secret patterns (API keys, passwords, tokens, bearer tokens).
        - The preview is truncated to PROMPT_PREVIEW_MAX_LENGTH (100 chars) to
          minimize exposure of sensitive data.
        - Despite sanitization, treat prompt_preview as potentially containing
          sensitive information - apply appropriate access controls.
        - For maximum security, pre-sanitize prompts before event emission.
        - Implement appropriate data retention policies for events containing
          prompt_preview data.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the previous event in the session chain.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        prompt_id: Unique identifier for this specific prompt.
        prompt_preview: Sanitized and truncated preview of the prompt (max 100 chars).
            Automatically redacts common secret patterns. See _sanitize_prompt_preview.
        prompt_length: Total character count of the original (unsanitized) prompt.
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
        return _validate_timezone_aware(v)

    # Prompt-specific fields
    prompt_id: UUID = Field(
        ...,
        description="Unique identifier for this specific prompt",
    )
    prompt_preview: str = Field(
        ...,
        max_length=PROMPT_PREVIEW_MAX_LENGTH,
        description=(
            "Sanitized and truncated preview of the prompt (max 100 chars). "
            "Common secret patterns are automatically redacted. "
            "PRIVACY WARNING: Despite sanitization, may still contain sensitive data. "
            "Apply appropriate access controls and data retention policies."
        ),
    )
    prompt_length: int = Field(
        ...,
        ge=0,
        description="Total character count of the original (unsanitized) prompt",
    )
    detected_intent: str | None = Field(
        default=None,
        description="Classified intent if available (workflow, question, fix, etc.)",
    )

    @field_validator("prompt_preview", mode="before")
    @classmethod
    def sanitize_prompt_preview(cls, v: object) -> str | object:
        """Sanitize prompt preview for privacy safety.

        This validator automatically:
        1. Redacts common secret patterns (API keys, passwords, tokens)
        2. Truncates to PROMPT_PREVIEW_MAX_LENGTH with "..." suffix

        Args:
            v: The raw prompt preview value (any type before validation).

        Returns:
            Sanitized and truncated preview string, or original value if not a string.
        """
        if not isinstance(v, str):
            return v  # Let Pydantic handle type validation
        return _sanitize_prompt_preview(v)


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
        return _validate_timezone_aware(v)

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
        le=3600000,  # Max 1 hour (3,600,000 milliseconds)
        description="Tool execution duration in milliseconds (max 1 hour)",
    )
    # PRIVACY: summary may contain file paths, code snippets, or error messages
    # that could include sensitive data. Apply same caution as prompt_preview.
    summary: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Brief summary of the tool execution result. "
            "PRIVACY: May contain file paths, code snippets, or error messages "
            "with sensitive data. Not automatically sanitized - producers should "
            "avoid including secrets. Apply appropriate access controls."
        ),
    )


# =============================================================================
# Discriminated Union (for deserialization)
# =============================================================================


# Type alias for backwards compatibility (deprecated, use HookEventType instead)
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
        event_type: Discriminator for the event type (HookEventType enum).
        schema_version: Version of the event schema.
        source: Source service identifier.
        payload: The event payload (one of the hook payload types).

    Note:
        For direct Kafka publishing, you may serialize just the payload
        and include event_type in Kafka headers. This envelope is provided
        for scenarios requiring self-describing messages.

    Validation:
        The model_validator ensures that the event_type matches the payload type.
        For example, HookEventType.SESSION_STARTED requires a
        ModelHookSessionStartedPayload.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    event_type: HookEventType = Field(
        ...,
        description="Event type discriminator (HookEventType enum)",
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

    @model_validator(mode="after")
    def validate_event_type_matches_payload(self) -> ModelHookEventEnvelope:
        """Validate that event_type matches the payload type.

        This ensures type safety by verifying that the discriminator value
        (event_type) corresponds to the correct payload model.

        Returns:
            Self if validation passes.

        Raises:
            ValueError: If event_type does not match the payload type.
        """
        expected_types: dict[HookEventType, type] = {
            HookEventType.SESSION_STARTED: ModelHookSessionStartedPayload,
            HookEventType.SESSION_ENDED: ModelHookSessionEndedPayload,
            HookEventType.PROMPT_SUBMITTED: ModelHookPromptSubmittedPayload,
            HookEventType.TOOL_EXECUTED: ModelHookToolExecutedPayload,
        }
        expected = expected_types.get(self.event_type)
        if expected and not isinstance(self.payload, expected):
            raise ValueError(
                f"event_type {self.event_type} requires payload type {expected.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        return self


# Type alias for discriminated union of all hook payloads
ModelHookPayload = Annotated[
    ModelHookSessionStartedPayload
    | ModelHookSessionEndedPayload
    | ModelHookPromptSubmittedPayload
    | ModelHookToolExecutedPayload,
    Field(description="Union of all hook event payload types"),
]


__all__ = [
    # Constants
    "PROMPT_PREVIEW_MAX_LENGTH",
    # Event type enum
    "HookEventType",
    # Payload models
    "ModelHookSessionStartedPayload",
    "ModelHookSessionEndedPayload",
    "ModelHookPromptSubmittedPayload",
    "ModelHookToolExecutedPayload",
    # Envelope and types
    "ModelHookEventEnvelope",
    "ModelHookPayload",
    "EventType",  # Deprecated, kept for backwards compatibility
]
