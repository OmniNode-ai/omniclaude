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
import warnings
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from omnibase_core.enums import EnumClaudeCodeSessionOutcome
from omnibase_infra.utils import ensure_timezone_aware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.functional_validators import BeforeValidator

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
    CONTEXT_INJECTED = "hook.context.injected"
    CONTEXT_UTILIZATION = "hook.context.utilization"
    AGENT_MATCH = "hook.agent.match"
    LATENCY_BREAKDOWN = "hook.latency.breakdown"
    MANIFEST_INJECTED = "hook.manifest.injected"


class HookSource(StrEnum):
    """Sources that can trigger a session start.

    Using StrEnum for type safety, IDE autocompletion, and consistent
    serialization in Kafka events.

    Values:
        STARTUP: Initial Claude Code session launch.
        RESUME: Session resumed after being suspended.
        CLEAR: Session restarted via /clear command.
        COMPACT: Session compacted (context window management).
    """

    STARTUP = "startup"
    RESUME = "resume"
    CLEAR = "clear"
    COMPACT = "compact"


class SessionEndReason(StrEnum):
    """Reasons for session termination.

    Using StrEnum for type safety, IDE autocompletion, and consistent
    serialization in Kafka events.

    Values:
        CLEAR: User issued /clear command.
        LOGOUT: User logged out or closed session explicitly.
        PROMPT_INPUT_EXIT: User exited via prompt input (Ctrl+C, etc.).
        OTHER: Any other termination reason.
    """

    CLEAR = "clear"
    LOGOUT = "logout"
    PROMPT_INPUT_EXIT = "prompt_input_exit"
    OTHER = "other"


class ContextSource(StrEnum):
    """Sources for context injection during session enrichment.

    Using StrEnum for type safety, IDE autocompletion, and consistent
    serialization in Kafka events.

    Values:
        DATABASE: Context loaded from PostgreSQL database (primary source).
        PERSISTENCE_FILE: Context loaded from persistence file storage (deprecated).
        SESSION_AGGREGATOR: Context aggregated from session history.
        RAG_QUERY: Context retrieved via RAG query from vector database.
        FALLBACK_STATIC: Static fallback context when other sources unavailable.
        NONE: No context injection performed.
    """

    DATABASE = "database"
    PERSISTENCE_FILE = "persistence_file"
    SESSION_AGGREGATOR = "session_aggregator"
    RAG_QUERY = "rag_query"
    FALLBACK_STATIC = "fallback_static"
    NONE = "none"


# =============================================================================
# Constants
# =============================================================================

# Privacy: Maximum length for prompt preview to limit exposure of sensitive data
PROMPT_PREVIEW_MAX_LENGTH: int = 100

# Privacy: Patterns that may indicate secrets (compiled for performance)
# These patterns are intentionally simple to avoid false negatives
#
# KNOWN FALSE POSITIVES (intentionally not matched):
#   - Short passwords: "password=short" (less than 8 chars) - not matched to reduce
#     false positives on common non-secret patterns like "password=placeholder"
#   - URL parameters: "reset_password=true" - the boolean "true" is only 4 chars
#     so it won't match the 8+ char requirement
#   - Base64 strings that happen to start with "eyJ" but aren't JWT tokens -
#     we require the full three-part JWT structure to minimize false positives
#
# PATTERN DESIGN PRINCIPLES:
#   1. All patterns are compiled at module load time for O(1) lookup
#   2. Patterns use word boundaries (\b) where appropriate to avoid partial matches
#   3. Minimum length requirements reduce false positives
#   4. Capturing groups (parentheses) are ONLY used when the replacement needs
#      backreferences like \1 or \2. Otherwise, use non-capturing groups (?:...)
#      for alternation.
#
# IMPORTANT: These patterns are designed for use with sub()/subn(), NOT findall().
#   - subn() correctly counts substitutions regardless of capturing groups
#   - findall() with capturing groups returns ONLY captured groups, not full matches,
#     which would cause incorrect counts or unexpected behavior
#   - If you need to count matches without replacing, use sum(1 for _ in pattern.finditer(text))
#
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API keys with common prefixes
    # Note: No capturing groups - sub()/subn() replace the full match
    (re.compile(r"\bsk-[a-zA-Z0-9]{20,}", re.IGNORECASE), "sk-***REDACTED***"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}", re.IGNORECASE), "AKIA***REDACTED***"),
    (re.compile(r"\bghp_[a-zA-Z0-9]{36}", re.IGNORECASE), "ghp_***REDACTED***"),
    (re.compile(r"\bgho_[a-zA-Z0-9]{36}", re.IGNORECASE), "gho_***REDACTED***"),
    (
        re.compile(r"\bxox[baprs]-[a-zA-Z0-9-]{10,}", re.IGNORECASE),
        "xox*-***REDACTED***",
    ),
    # Stripe API keys (publishable, secret, and restricted)
    # Format: (sk|pk|rk)_(live|test)_[a-zA-Z0-9]{24,}
    # Reference: https://stripe.com/docs/keys
    # Note: (?:...) is non-capturing group for alternation, not for backreference
    (
        re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[a-zA-Z0-9]{24,}", re.IGNORECASE),
        "stripe_***REDACTED***",
    ),
    # Google Cloud Platform API keys
    # Format: AIza[0-9A-Za-z-_]{35}
    # Reference: https://cloud.google.com/docs/authentication/api-keys
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}"), "AIza***REDACTED***"),
    # JWT tokens (JSON Web Tokens)
    # Format: base64url(header).base64url(payload).base64url(signature)
    # Header always starts with eyJ (base64 of '{"')
    # Reference: RFC 7519 (JSON Web Token)
    (
        re.compile(r"\beyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*"),
        "jwt_***REDACTED***",
    ),
    # Private keys (PEM format)
    # Matches RSA, EC, DSA, OPENSSH, generic, and encrypted private key headers
    # Reference: RFC 7468 (Textual Encodings of PKIX, PKCS, and CMS Structures)
    # Reference: OpenSSH PROTOCOL.key format for OPENSSH keys
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
        ),
        "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
    ),
    # Bearer tokens
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9._-]{20,}", re.IGNORECASE), r"\1***REDACTED***"),
    # Password in URLs (postgres://user:password@host, mysql://user:password@host, mongodb://...)
    # This pattern intentionally covers all database connection string formats
    (re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
    # Generic secret patterns in key=value format
    # Note: Requires 8+ char values to reduce false positives like "password=true"
    # Word boundary \b ensures we don't match "reset_password" when looking for "password"
    (
        re.compile(
            r"(\b(?:password|passwd|secret|token|api_key|apikey|auth)\s*[=:]\s*)['\"]?[^\s'\"]{8,}['\"]?",
            re.IGNORECASE,
        ),
        r"\1***REDACTED***",
    ),
]

# Flag to track if sanitization has been bypassed (for defensive monitoring)
_SANITIZATION_BYPASS_WARNING_ISSUED: bool = False


# =============================================================================
# Reusable Validators
# =============================================================================


def _validate_timezone_aware(v: datetime | str) -> datetime:
    """Validate and ensure datetime is timezone-aware.

    This is extracted as a reusable function to avoid code duplication
    across all payload models that have emitted_at fields.

    Handles both datetime objects (from Python code) and ISO format strings
    (from JSON deserialization). Pydantic's BeforeValidator receives the raw
    value before type coercion, so this function must handle string input
    when deserializing from JSON.

    Args:
        v: The datetime value to validate (datetime object or ISO format string).

    Returns:
        The timezone-aware datetime.

    Raises:
        ValueError: If the datetime cannot be made timezone-aware or
            if the string cannot be parsed as ISO format.

    Example:
        >>> from datetime import datetime, UTC
        >>> _validate_timezone_aware(datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC))
        datetime.datetime(2025, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        >>> _validate_timezone_aware("2025-01-15T12:00:00+00:00")
        datetime.datetime(2025, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
    """
    # Handle string input from JSON deserialization
    if isinstance(v, str):
        v = datetime.fromisoformat(v)

    result: datetime = ensure_timezone_aware(v)
    return result


# Annotated type for timezone-aware datetime fields.
# Use this instead of datetime + @field_validator to eliminate duplication.
TimezoneAwareDatetime = Annotated[
    datetime,
    BeforeValidator(_validate_timezone_aware),
]


def _sanitize_prompt_preview(
    text: str,
    max_length: int = PROMPT_PREVIEW_MAX_LENGTH,
    *,
    _bypass_sanitization: bool = False,
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

    Known False Positives (intentionally not matched):
        - "password=short" - values under 8 chars are not matched
        - "reset_password=true" - boolean values are too short to match
        - Base64 strings starting with "eyJ" that aren't JWTs - requires full
          three-part JWT structure

    Args:
        text: The raw prompt text to sanitize.
        max_length: Maximum length for the preview (default: PROMPT_PREVIEW_MAX_LENGTH).
        _bypass_sanitization: Internal flag for testing. If True, skips sanitization
            but emits a warning. NEVER use in production code.

    Returns:
        Sanitized and truncated preview string.

    Example:
        >>> _sanitize_prompt_preview("Set OPENAI_API_KEY=sk-1234567890abcdef...")
        'Set OPENAI_API_KEY=sk-***REDACTED***...'

    Warning:
        If _bypass_sanitization is True, a warning is emitted to help identify
        code paths that may leak secrets. This is for defensive programming
        and debugging purposes only.
    """
    global _SANITIZATION_BYPASS_WARNING_ISSUED

    # Defensive warning if sanitization is bypassed
    if _bypass_sanitization:
        if not _SANITIZATION_BYPASS_WARNING_ISSUED:
            warnings.warn(
                "Secret sanitization was bypassed! This may leak sensitive data. "
                "If this is intentional (e.g., testing), ensure proper handling. "
                "Never bypass sanitization in production code.",
                UserWarning,
                stacklevel=2,
            )
            _SANITIZATION_BYPASS_WARNING_ISSUED = True
        # Still truncate even when bypassed
        if len(text) > max_length:
            return text[: max_length - 3] + "..."
        return text

    # Step 1: Redact known secret patterns
    sanitized = text
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    # Step 2: Truncate with ellipsis if needed
    if len(sanitized) > max_length:
        # Reserve 3 chars for "..." suffix
        return sanitized[: max_length - 3] + "..."

    return sanitized


def sanitize_text(text: str) -> str:
    """Public function to sanitize text for secrets without truncation.

    This function applies all secret pattern redactions but does NOT truncate
    the result. Use this when you need to sanitize arbitrary text (not just
    prompt previews) before logging or storing.

    Args:
        text: The raw text to sanitize.

    Returns:
        Sanitized text with secrets redacted.

    Example:
        >>> sanitize_text("Connect to postgres://user:mypassword@host:5432")
        'Connect to postgres://user:***REDACTED***@host:5432'
    """
    sanitized = text
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
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
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

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
    hook_source: HookSource = Field(
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
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    # Session end-specific fields
    reason: SessionEndReason = Field(
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


class ModelSessionOutcome(BaseModel):
    """Session outcome event for feedback loop.

    Emitted at session end to capture the final outcome classification
    (success, failed, abandoned, unknown). This event enables pattern
    learning and success rate tracking in the intelligence system.

    Attributes:
        event_name: Literal discriminator for polymorphic deserialization.
        session_id: Session identifier string.
        outcome: Classification of how the session ended.
        emitted_at: Timestamp when the event was emitted (UTC).

    Example:
        >>> from datetime import UTC, datetime
        >>> event = ModelSessionOutcome(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
        ...     emitted_at=datetime(2025, 1, 15, 12, 30, 0, tzinfo=UTC),
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    event_name: Literal["session.outcome"] = Field(
        default="session.outcome",
        description="Event type discriminator for polymorphic deserialization",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier",
    )
    outcome: EnumClaudeCodeSessionOutcome = Field(
        ...,
        description="Classification of how the session ended (success, failed, abandoned, unknown)",
    )
    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
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
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

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
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

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
# Context Injection Events
# =============================================================================


class ModelHookContextInjectedPayload(BaseModel):
    """Event payload for context injection during session enrichment.

    Emitted when context is injected into a Claude Code session, typically
    during UserPromptSubmit to enrich the session with relevant patterns,
    historical data, or domain-specific context.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the prompt event that triggered context injection.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        context_source: Source from which context was retrieved.
        pattern_count: Number of patterns injected (0-100).
        context_size_bytes: Size of injected context in bytes (0-50000).
        agent_domain: Domain of the agent if context is domain-specific.
        min_confidence_threshold: Minimum confidence threshold for pattern inclusion.
        retrieval_duration_ms: Time taken to retrieve context in milliseconds.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookContextInjectedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     context_source=ContextSource.RAG_QUERY,
        ...     pattern_count=5,
        ...     context_size_bytes=2048,
        ...     agent_domain="api-development",
        ...     min_confidence_threshold=0.8,
        ...     retrieval_duration_ms=150,
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
        description="ID of the prompt event that triggered context injection",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    # Context injection-specific fields
    context_source: ContextSource = Field(
        ...,
        description="Source from which context was retrieved",
    )
    pattern_count: int = Field(
        ...,
        ge=0,
        le=100,
        description="Number of patterns injected (max 100)",
    )
    context_size_bytes: int = Field(
        ...,
        ge=0,
        le=50000,
        description="Size of injected context in bytes (max 50KB)",
    )
    agent_domain: str | None = Field(
        default=None,
        description="Domain of the agent if context is domain-specific",
    )
    min_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for pattern inclusion",
    )
    retrieval_duration_ms: int = Field(
        ...,
        ge=0,
        le=10000,
        description="Time taken to retrieve context in milliseconds (max 10 seconds)",
    )


# =============================================================================
# Injection Metrics Events (OMN-1889)
# =============================================================================


class ModelContextUtilizationPayload(BaseModel):
    """Event payload for context utilization measurement.

    Tracks whether injected context was actually used in Claude's response
    by comparing identifiers between injected context and response text.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the event that triggered this measurement.
        emitted_at: Timestamp when the event was emitted (UTC).
        utilization_score: Ratio of reused identifiers (0.0-1.0).
        method: Detection method used ("identifier_overlap" or "timeout_fallback").
        injected_count: Number of identifiers found in injected context.
        reused_count: Number of injected identifiers found in response.
        detection_duration_ms: Time taken for utilization detection.
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
        description="ID of the event that triggered this measurement",
    )

    # Timestamps
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # Utilization metrics
    utilization_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio of reused identifiers (0.0 = none used, 1.0 = all used)",
    )
    method: Literal["identifier_overlap", "timeout_fallback", "error_fallback"] = Field(
        ...,
        description="Detection method: 'identifier_overlap', 'timeout_fallback', or 'error_fallback'",
    )
    injected_count: int = Field(
        ...,
        ge=0,
        description="Number of identifiers found in injected context",
    )
    reused_count: int = Field(
        ...,
        ge=0,
        description="Number of injected identifiers found in response",
    )
    detection_duration_ms: int = Field(
        ...,
        ge=0,
        le=1000,
        description="Time taken for utilization detection in milliseconds (max 1 second)",
    )


class ModelAgentMatchPayload(BaseModel):
    """Event payload for agent routing accuracy measurement.

    Tracks how well agent routing matched expected behavior, enabling
    feedback loops for routing improvement.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the routing event being evaluated.
        emitted_at: Timestamp when the event was emitted (UTC).
        selected_agent: Agent that was selected by routing.
        expected_agent: Expected agent (from feedback or heuristics), if known.
        match_grade: Quality of match ("exact", "partial", "mismatch", "unknown").
        confidence: Routing confidence score (0.0-1.0).
        routing_method: Method used for routing ("event_routing", "fallback", "cache").
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
        description="ID of the routing event being evaluated",
    )

    # Timestamps
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # Agent match metrics
    selected_agent: str = Field(
        ...,
        min_length=1,
        description="Agent that was selected by routing",
    )
    expected_agent: str | None = Field(
        default=None,
        description="Expected agent from feedback or heuristics, if known",
    )
    match_grade: Literal["exact", "partial", "mismatch", "unknown"] = Field(
        ...,
        description="Quality of match: 'exact', 'partial', 'mismatch', or 'unknown'",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Routing confidence score",
    )
    routing_method: Literal["event_routing", "fallback", "cache"] = Field(
        ...,
        description="Routing method: 'event_routing', 'fallback', or 'cache'",
    )


class ModelLatencyBreakdownPayload(BaseModel):
    """Event payload for detailed hook latency breakdown.

    Provides fine-grained timing for each phase of hook execution to
    identify performance bottlenecks and optimize hook performance.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the prompt event being measured.
        emitted_at: Timestamp when the event was emitted (UTC).
        routing_ms: Time spent on agent routing.
        agent_load_ms: Time spent loading agent YAML.
        context_injection_ms: Time spent on context/pattern injection.
        intelligence_request_ms: Time spent on intelligence requests (optional).
        total_hook_ms: Total hook execution time.
        user_perceived_ms: User-perceived latency (optional).
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
        description="ID of the prompt event being measured",
    )

    # Timestamps
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # Latency breakdown
    routing_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time spent on agent routing in milliseconds",
    )
    agent_load_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time spent loading agent YAML in milliseconds",
    )
    context_injection_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time spent on context/pattern injection in milliseconds",
    )
    intelligence_request_ms: int | None = Field(
        default=None,
        ge=0,
        le=60000,
        description="Time spent on intelligence requests in milliseconds (optional)",
    )
    total_hook_ms: int = Field(
        ...,
        ge=0,
        le=600000,
        description="Total hook execution time in milliseconds",
    )
    user_perceived_ms: int | None = Field(
        default=None,
        ge=0,
        le=600000,
        description="User-perceived latency from prompt to response start (optional)",
    )


# =============================================================================
# Manifest Injection Events
# =============================================================================


class ModelHookManifestInjectedPayload(BaseModel):
    """Event payload for agent manifest injection during UserPromptSubmit.

    Emitted when an agent manifest (YAML) is loaded and injected into the session.
    This provides observability into which agents are being loaded, how long it takes,
    and whether the injection succeeds.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the prompt event that triggered manifest injection.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        agent_name: Name of the agent being loaded (e.g., "agent-api-architect").
        agent_domain: Domain of the agent (e.g., "api-development", "testing").
        injection_success: Whether the manifest injection succeeded.
        injection_duration_ms: Time to load and inject manifest in milliseconds.
        yaml_path: Path to the agent YAML file (optional, for debugging).
        agent_version: Version of the agent definition if specified.
        agent_capabilities: List of capabilities from the agent manifest.
        routing_source: How the agent was selected (explicit, fuzzy_match, fallback).
        error_message: Error details if injection failed.
        error_type: Error classification if injection failed.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelHookManifestInjectedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     agent_name="agent-api-architect",
        ...     agent_domain="api-development",
        ...     injection_success=True,
        ...     injection_duration_ms=45,
        ...     yaml_path="/path/to/agent-api-architect.yaml",
        ...     routing_source="explicit",
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
        description="ID of the prompt event that triggered manifest injection",
    )

    # Timestamps
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    # Agent identification
    agent_name: str = Field(
        ...,
        min_length=1,
        description="Name of the agent being loaded",
    )
    agent_domain: str = Field(
        ...,
        min_length=1,
        description="Domain of the agent",
    )

    # Injection result
    injection_success: bool = Field(
        ...,
        description="Whether the manifest injection succeeded",
    )
    injection_duration_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time to load and inject manifest in milliseconds",
    )

    # Optional metadata
    yaml_path: str | None = Field(
        default=None,
        description="Path to the agent YAML file",
    )
    agent_version: str | None = Field(
        default=None,
        description="Version of the agent definition",
    )
    agent_capabilities: list[str] | None = Field(
        default=None,
        description="List of capabilities from the agent manifest",
    )
    routing_source: str | None = Field(
        default=None,
        description="How the agent was selected (explicit, fuzzy_match, fallback)",
    )

    # Error tracking
    error_message: str | None = Field(
        default=None,
        description="Error details if injection failed",
    )
    error_type: str | None = Field(
        default=None,
        description="Error classification if injection failed",
    )

    @field_validator("correlation_id", mode="after")
    @classmethod
    def validate_correlation_id_not_nil(cls, v: UUID) -> UUID:
        """Ensure correlation_id is an explicit, non-nil UUID.

        Manifest events are critical for distributed tracing. A nil UUID
        (00000000-0000-0000-0000-000000000000) would break correlation
        chains and must be rejected. This enforces that callers provide
        a meaningful correlation identifier, not just a structurally valid one.

        Args:
            v: The correlation_id UUID value to validate.

        Returns:
            The validated UUID if non-nil.

        Raises:
            ValueError: If correlation_id is a nil UUID.
        """
        if v.int == 0:
            raise ValueError(
                "correlation_id must not be a nil UUID for manifest events; "
                "manifest injection requires explicit correlation for distributed tracing"
            )
        return v


# =============================================================================
# Discriminated Union (for deserialization)
# =============================================================================


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
        | ModelHookContextInjectedPayload
        | ModelContextUtilizationPayload
        | ModelAgentMatchPayload
        | ModelLatencyBreakdownPayload
        | ModelHookManifestInjectedPayload
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
            HookEventType.CONTEXT_INJECTED: ModelHookContextInjectedPayload,
            HookEventType.CONTEXT_UTILIZATION: ModelContextUtilizationPayload,
            HookEventType.AGENT_MATCH: ModelAgentMatchPayload,
            HookEventType.LATENCY_BREAKDOWN: ModelLatencyBreakdownPayload,
            HookEventType.MANIFEST_INJECTED: ModelHookManifestInjectedPayload,
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
    | ModelHookToolExecutedPayload
    | ModelHookContextInjectedPayload
    | ModelContextUtilizationPayload
    | ModelAgentMatchPayload
    | ModelLatencyBreakdownPayload
    | ModelHookManifestInjectedPayload,
    Field(description="Union of all hook event payload types"),
]


__all__ = [
    # Constants
    "PROMPT_PREVIEW_MAX_LENGTH",
    # Enums
    "HookEventType",
    "HookSource",
    "SessionEndReason",
    "ContextSource",
    "EnumClaudeCodeSessionOutcome",
    # Annotated types (reusable validators)
    "TimezoneAwareDatetime",
    # Sanitization utilities
    "sanitize_text",
    # Payload models
    "ModelHookSessionStartedPayload",
    "ModelHookSessionEndedPayload",
    "ModelSessionOutcome",
    "ModelHookPromptSubmittedPayload",
    "ModelHookToolExecutedPayload",
    "ModelHookContextInjectedPayload",
    "ModelContextUtilizationPayload",
    "ModelAgentMatchPayload",
    "ModelLatencyBreakdownPayload",
    "ModelHookManifestInjectedPayload",
    # Envelope and types
    "ModelHookEventEnvelope",
    "ModelHookPayload",
]
