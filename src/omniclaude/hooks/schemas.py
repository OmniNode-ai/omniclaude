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
    STATIC_CONTEXT_EDIT_DETECTED = "hook.static.context.edit.detected"


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
        SESSION_AGGREGATOR: Context aggregated from session history.
        RAG_QUERY: Context retrieved via RAG query from vector database.
        FALLBACK_STATIC: Static fallback context when other sources unavailable.
        NONE: No context injection performed.
    """

    DATABASE = "database"
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
# Routing Feedback Events (OMN-1892)
# =============================================================================


class ModelRoutingFeedbackPayload(BaseModel):
    """Event payload for routing feedback reinforcement.

    Emitted at session end when the feedback guardrails determine that
    the routing decision should be reinforced (all gates passed). This
    event enables the intelligence system to learn from successful and
    failed routing decisions.

    Attributes:
        event_name: Literal discriminator for polymorphic deserialization.
        session_id: Session identifier string.
        outcome: Session outcome that triggered feedback (success or failed).
        emitted_at: Timestamp when the event was emitted (UTC).

    Example:
        >>> from datetime import UTC, datetime
        >>> event = ModelRoutingFeedbackPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     outcome="success",
        ...     emitted_at=datetime(2025, 1, 15, 12, 30, 0, tzinfo=UTC),
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    event_name: Literal["routing.feedback"] = Field(
        default="routing.feedback",
        description="Event type discriminator for polymorphic deserialization",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier",
    )
    outcome: Literal["success", "failed"] = Field(
        ...,
        description="Session outcome that triggered feedback",
    )
    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )


class ModelSessionRawOutcomePayload(BaseModel):
    """Event payload for raw session outcome signals (OMN-2356).

    Emitted at session end with only observable facts — no derived scores.
    Derived metrics (utilization_score, agent_match_score) belong in
    omniintelligence's routing-feedback consumer, not in the hook.

    This replaces the no-op feedback loop that emitted hardcoded/zero values.
    omniintelligence consumes this event and computes derived scores from
    the raw signals plus its own context (e.g., context utilization events).

    Attributes:
        event_name: Literal discriminator for polymorphic deserialization.
        session_id: Session identifier string.
        injection_occurred: Whether context injection happened this session.
        patterns_injected_count: Number of patterns injected (0 if no injection).
        tool_calls_count: Total tool calls observed during the session.
        duration_ms: Session duration in milliseconds (0 if unknown).
        agent_selected: Agent name selected by routing (empty string if none).
        routing_confidence: Routing confidence score (0.0-1.0).
        emitted_at: Timestamp when the event was emitted (UTC).

    Note:
        ``utilization_score`` and ``agent_match_score`` are intentionally
        absent. Computing them requires DB reads (Invariant 5 violation).
        omniintelligence's routing-feedback consumer handles derivation.

    Example:
        >>> from datetime import UTC, datetime
        >>> event = ModelSessionRawOutcomePayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     injection_occurred=True,
        ...     patterns_injected_count=3,
        ...     tool_calls_count=12,
        ...     duration_ms=45200,
        ...     agent_selected="omniarchon",
        ...     routing_confidence=0.91,
        ...     emitted_at=datetime(2025, 1, 15, 12, 30, 0, tzinfo=UTC),
        ... )
    """

    # extra="ignore" per CLAUDE.md repo invariant for all frozen event models
    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    event_name: Literal["routing.outcome.raw"] = Field(
        default="routing.outcome.raw",
        description="Event type discriminator for polymorphic deserialization",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier",
    )
    injection_occurred: bool = Field(
        ...,
        description="Whether context injection happened this session",
    )
    patterns_injected_count: int = Field(
        ...,
        ge=0,
        description="Number of patterns injected (0 if no injection occurred)",
    )
    tool_calls_count: int = Field(
        ...,
        ge=0,
        description="Total tool calls observed during the session",
    )
    duration_ms: int = Field(
        ...,
        ge=0,
        description="Session duration in milliseconds (0 if unknown)",
    )
    agent_selected: str = Field(
        default="",
        description="Agent name selected by routing (empty string if none selected)",
    )
    routing_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Routing confidence score from the router (0.0-1.0)",
    )
    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    # Uses TimezoneAwareDatetime for automatic timezone validation
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )


class ModelRoutingFeedbackSkippedPayload(BaseModel):
    """Event payload for routing feedback that was skipped by guardrails.

    Emitted at session end when the feedback guardrails determine that
    the routing decision should NOT be reinforced (a gate failed). This
    event provides observability into why feedback was suppressed.

    Attributes:
        event_name: Literal discriminator for polymorphic deserialization.
        session_id: Session identifier string.
        skip_reason: Why reinforcement was skipped (e.g., NO_INJECTION,
            UNCLEAR_OUTCOME, BELOW_SCORE_THRESHOLD).
        emitted_at: Timestamp when the event was emitted (UTC).

    Example:
        >>> from datetime import UTC, datetime
        >>> event = ModelRoutingFeedbackSkippedPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     skip_reason="NO_INJECTION",
        ...     emitted_at=datetime(2025, 1, 15, 12, 30, 0, tzinfo=UTC),
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    event_name: Literal["routing.skipped"] = Field(
        default="routing.skipped",
        description="Event type discriminator for polymorphic deserialization",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier",
    )
    skip_reason: str = Field(
        ...,
        min_length=1,
        description="Why reinforcement was skipped (NO_INJECTION, UNCLEAR_OUTCOME, BELOW_SCORE_THRESHOLD)",
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
        cohort: Experiment cohort assignment ("treatment" or "control").
            Required by omnidash isExtractionBaseEvent() type guard.
        injection_occurred: Whether context was actually injected this session.
        agent_name: Selected agent name for this session.
        utilization_score: Ratio of reused identifiers (0.0-1.0).
        method: Detection method used ("identifier_overlap" or "timeout_fallback").
        injected_count: Number of identifiers found in injected context.
        reused_count: Number of injected identifiers found in response.
        detection_duration_ms: Time taken for utilization detection.
        user_visible_latency_ms: Total user-visible hook latency in milliseconds.
        cache_hit: Whether patterns were served from cache (vs database).
        patterns_count: Number of patterns injected this session.
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

    # Extraction pipeline fields — required by omnidash isExtractionBaseEvent() type guard
    cohort: str = Field(
        ...,
        min_length=1,
        description=(
            "Experiment cohort assignment ('treatment' or 'control'). "
            "Required by omnidash isExtractionBaseEvent() type guard."
        ),
    )
    injection_occurred: bool = Field(
        ...,
        description="Whether context was actually injected (patterns_count > 0)",
    )
    agent_name: str | None = Field(
        default=None,
        description="Selected agent name for this session (e.g. 'agent-api-architect')",
    )
    user_visible_latency_ms: int | None = Field(
        default=None,
        ge=0,
        le=600000,
        description="Total user-visible hook latency in milliseconds",
    )
    cache_hit: bool = Field(
        default=False,
        description="Whether patterns were served from cache (vs database)",
    )
    patterns_count: int = Field(
        default=0,
        ge=0,
        description="Number of patterns injected this session",
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
        cohort: Experiment cohort assignment ("treatment" or "control").
            Required by omnidash isExtractionBaseEvent() type guard.
        selected_agent: Agent that was selected by routing.
        expected_agent: Expected agent (from feedback or heuristics), if known.
        match_grade: Quality of match ("exact", "partial", "mismatch", "unknown").
        agent_match_score: Graded accuracy of agent selection vs session signals (0.0-1.0).
        confidence: Routing confidence score from the router (0.0-1.0).
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

    # Extraction pipeline field — required by omnidash isExtractionBaseEvent() type guard
    cohort: str = Field(
        ...,
        min_length=1,
        description=(
            "Experiment cohort assignment ('treatment' or 'control'). "
            "Required by omnidash isExtractionBaseEvent() type guard."
        ),
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
    agent_match_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Graded accuracy of agent selection vs session signals (0.0-1.0). "
            "Computed by calculate_agent_match_score() comparing agent triggers "
            "against observed session context signals."
        ),
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Routing confidence score from the router",
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
        cohort: Experiment cohort assignment ("treatment" or "control").
            Required by omnidash isExtractionBaseEvent() type guard.
        routing_time_ms: Time spent on agent routing (renamed from routing_ms).
        retrieval_time_ms: Time spent loading patterns from database.
        injection_time_ms: Time spent on context/pattern injection (renamed from context_injection_ms).
        intelligence_request_ms: Time spent on intelligence requests (optional).
        total_hook_ms: Total hook execution time.
        user_visible_latency_ms: User-visible latency from prompt submit to hook completion
            (renamed from user_perceived_ms).
        cache_hit: Whether patterns were served from cache (vs database).
        agent_load_ms: Time spent loading agent YAML (retained for observability).
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

    # Extraction pipeline field — required by omnidash isExtractionBaseEvent() type guard
    cohort: str = Field(
        ...,
        min_length=1,
        description=(
            "Experiment cohort assignment ('treatment' or 'control'). "
            "Required by omnidash isExtractionBaseEvent() type guard."
        ),
    )

    # Latency breakdown — field names aligned with omnidash latency_breakdowns table
    routing_time_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time spent on agent routing in milliseconds",
    )
    retrieval_time_ms: int | None = Field(
        default=None,
        ge=0,
        le=60000,
        description="Time spent loading patterns from database in milliseconds",
    )
    injection_time_ms: int = Field(
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
    user_visible_latency_ms: int | None = Field(
        default=None,
        ge=0,
        le=600000,
        description="User-visible latency from prompt submit to hook completion in milliseconds",
    )
    cache_hit: bool = Field(
        default=False,
        description="Whether patterns were served from cache (vs database)",
    )
    agent_load_ms: int = Field(
        default=0,
        ge=0,
        le=60000,
        description="Time spent loading agent YAML in milliseconds (observability only)",
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
# Static Context Edit Detection Events (OMN-2237)
# =============================================================================


class ModelChangedFileRecord(BaseModel):
    """Record describing a single changed static context file.

    Embedded as a list element inside ModelStaticContextEditDetectedPayload.

    Attributes:
        file_path: Absolute path to the changed file.
        is_versioned: True if the file is tracked by git.
        git_diff_stat: One-line ``git diff --stat`` summary for versioned files.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        from_attributes=True,
    )

    file_path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to the changed static context file",
    )
    is_versioned: bool = Field(
        ...,
        description="True if the file is tracked by git; False for non-versioned files",
    )
    git_diff_stat: str | None = Field(
        default=None,
        max_length=500,
        description="One-line git diff --stat summary (versioned files only)",
    )


class ModelStaticContextEditDetectedPayload(BaseModel):
    """Event payload for static context file change detection.

    Emitted when the SessionStart hook detects that one or more static context
    files have changed since the previous session.  Static context files include
    repo CLAUDE.md (versioned), ~/.claude/CLAUDE.md, memory files, and
    .local.md plugin configs (non-versioned).

    Versioned files use git diff for change detection; non-versioned files use
    SHA-256 hash comparison.

    Privacy Considerations:
        - ``changed_files`` contains only file paths and git stat summaries,
          never file content, to avoid leaking secrets.
        - The raw content snapshot (for non-versioned files) is stored locally
          in ~/.claude/snapshots/ and is NOT included in this event.

    Attributes:
        entity_id: Session identifier as UUID (partition key for ordering).
        session_id: Session identifier string.
        correlation_id: Correlation ID for distributed tracing.
        causation_id: ID of the session.started event that triggered this scan.
        emitted_at: Timestamp when the hook emitted this event (UTC).
        changed_file_count: Number of files with detected changes.
        changed_files: List of changed file records (path + change metadata).

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> session_id = uuid4()
        >>> event = ModelStaticContextEditDetectedPayload(
        ...     entity_id=session_id,
        ...     session_id=str(session_id),
        ...     correlation_id=session_id,
        ...     causation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
        ...     changed_file_count=2,
        ...     changed_files=[
        ...         ModelChangedFileRecord(
        ...             file_path="/home/user/.claude/CLAUDE.md",
        ...             is_versioned=False,
        ...         ),
        ...     ],
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
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
        description="ID of the session.started event that triggered this scan",
    )

    # Timestamps - MUST be explicitly injected (no default_factory for testability)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    # Change detection fields
    changed_file_count: int = Field(
        ...,
        ge=0,
        description="Number of static context files with detected changes",
    )
    changed_files: list[ModelChangedFileRecord] = Field(
        default_factory=list,
        description=(
            "List of changed static context file records. "
            "Contains only file paths and git stat summaries, never file content."
        ),
    )


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
        | ModelStaticContextEditDetectedPayload
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
            HookEventType.STATIC_CONTEXT_EDIT_DETECTED: ModelStaticContextEditDetectedPayload,
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
    | ModelHookManifestInjectedPayload
    | ModelStaticContextEditDetectedPayload,
    Field(description="Union of all hook event payload types"),
]


# =============================================================================
# Agent Status Events (OMN-1848)
# =============================================================================


class EnumAgentState(StrEnum):
    """Closed enum for agent lifecycle states. Schema version: 1.

    These states are intentionally minimal and closed.
    Adding new states is a BREAKING CHANGE requiring version increment
    and consumer updates.
    """

    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    AWAITING_INPUT = "awaiting_input"
    FINISHED = "finished"
    ERROR = "error"


# NOTE: Not included in ModelHookEventEnvelope — emitted directly via emit daemon, not envelope-wrapped.
class ModelAgentStatusPayload(BaseModel):
    """Event payload for agent status reporting.

    Emitted by agents to report their current lifecycle state via the
    emit daemon. This is an OBSERVATIONAL event — it must never directly
    cause state mutation without passing through a reducer.

    Defined locally in omniclaude (not omnibase_core) per OMN-1848.
    Designed for easy promotion to omnibase_core when OMN-1847 is completed.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    # Identity
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    agent_name: str = Field(
        ...,
        min_length=1,
        description="Name of the reporting agent",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier for ordering",
    )
    agent_instance_id: str | None = Field(
        default=None,
        description="Durable instance ID to disambiguate parallel agents with same name",
    )

    # State
    state: EnumAgentState = Field(
        ...,
        description="Current agent lifecycle state",
    )
    schema_version: Literal[1] = Field(
        default=1,
        description="Schema version for forward compatibility",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable status message (max 500 chars)",
    )

    # Optional progress
    progress: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Progress 0.0-1.0, monotonic within a task",
    )
    current_phase: str | None = Field(
        default=None,
        description="Current workflow phase (e.g., 'research', 'implementation')",
    )
    current_task: str | None = Field(
        default=None,
        description="Current task description",
    )
    blocking_reason: str | None = Field(
        default=None,
        description="Why the agent is blocked (for notification routing)",
    )

    # Timestamps — MUST be explicitly injected (no default_factory)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the status was emitted (UTC). Must be explicitly injected.",
    )

    # Metadata — default_factory=dict creates a fresh dict per instance.
    # The model is frozen (field reassignment blocked), but dict values
    # remain mutable after construction (e.g., payload.metadata["k"] = "v").
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Additional string metadata (new dict per instance)",
    )


# =============================================================================
# LLM Routing Observability Events (OMN-2273)
# =============================================================================


class ModelLlmRoutingDecisionPayload(BaseModel):
    """Event payload for LLM-based routing decisions.

    Emitted after a successful LLM routing decision to provide full
    observability into the routing pipeline, including a determinism
    audit comparing LLM and fuzzy-matching selections.

    Attributes:
        session_id: Session identifier (partition key).
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when the event was emitted (UTC).
        selected_agent: Agent chosen by LLM routing.
        llm_confidence: Confidence score from the LLM selection (0.0-1.0).
        llm_latency_ms: Time spent on the LLM HTTP call in milliseconds.
        fallback_used: True when the LLM fell back to the fuzzy top candidate.
        model_used: Model identifier used for routing (e.g. "Qwen2.5-14B").
        fuzzy_top_candidate: Top candidate from fuzzy matching (for audit).
        llm_selected_candidate: Agent name the LLM returned before validation.
        agreement: True when LLM and fuzzy top candidates agree.
        routing_prompt_version: Prompt template version for longitudinal comparison.

    Note:
        ``extra="ignore"`` is intentional — the payload dict assembled in
        route_via_events_wrapper may carry additional keys that are not
        needed by this schema. Ignoring extras avoids breaking the hook
        when the routing result dict gains new fields.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> event = ModelLlmRoutingDecisionPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     correlation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     selected_agent="agent-api-architect",
        ...     llm_confidence=0.92,
        ...     llm_latency_ms=45,
        ...     fallback_used=False,
        ...     model_used="Qwen2.5-14B",
        ...     fuzzy_top_candidate="agent-api-architect",
        ...     llm_selected_candidate="agent-api-architect",
        ...     agreement=True,
        ...     routing_prompt_version="1.0.0",
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        from_attributes=True,
    )

    # Identity / tracing
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier (partition key for Kafka ordering)",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )

    # Timestamps — MUST be explicitly injected (no default_factory for testability)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # LLM routing outcome
    selected_agent: str = Field(
        ...,
        min_length=1,
        description="Agent chosen by LLM routing",
    )
    llm_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from the LLM selection",
    )
    llm_latency_ms: int = Field(
        ...,
        ge=0,
        le=60000,
        description="Time spent on the LLM HTTP call in milliseconds",
    )
    fallback_used: bool = Field(
        ...,
        description="True when the LLM fell back to the fuzzy top candidate",
    )
    model_used: str = Field(
        ...,
        min_length=1,
        description="Model identifier used for routing (e.g. 'Qwen2.5-14B')",
    )

    # Determinism audit fields
    fuzzy_top_candidate: str | None = Field(
        default=None,
        description="Top candidate from fuzzy matching, for LLM/fuzzy agreement audit",
    )
    llm_selected_candidate: str | None = Field(
        default=None,
        description="Raw agent name the LLM returned before validation/fallback",
    )
    agreement: bool = Field(
        default=False,
        description="True when LLM selection and fuzzy top candidate agree",
    )

    # Longitudinal comparison
    routing_prompt_version: str = Field(
        ...,
        min_length=1,
        description="Routing prompt template version for longitudinal regression comparison",
    )


class ModelLlmRoutingFallbackPayload(BaseModel):
    """Event payload emitted when LLM routing falls back to fuzzy matching.

    Emitted when the LLM routing path (``_route_via_llm``) returns None,
    causing the pipeline to fall through to fuzzy candidate matching.
    Provides observability into why the LLM path was skipped.

    Attributes:
        session_id: Session identifier (partition key).
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when the event was emitted (UTC).
        fallback_reason: Human-readable reason for the fallback.
        llm_url: LLM endpoint URL that was attempted (if known).
        routing_prompt_version: Prompt template version for correlation.

    Note:
        ``extra="ignore"`` is intentional — the routing result dict may
        carry keys that are not relevant to this payload.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> event = ModelLlmRoutingFallbackPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     correlation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     fallback_reason="LLM endpoint unhealthy",
        ...     llm_url="http://192.168.86.100:8200",
        ...     routing_prompt_version="1.0.0",
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        from_attributes=True,
    )

    # Identity / tracing
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier (partition key for Kafka ordering)",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )

    # Timestamps — MUST be explicitly injected (no default_factory for testability)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # Fallback details
    fallback_reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable reason for the fallback (e.g. 'LLM endpoint unhealthy')",
    )
    llm_url: str | None = Field(
        default=None,
        description="LLM endpoint URL that was attempted, if known",
    )
    routing_prompt_version: str = Field(
        ...,
        min_length=1,
        description="Routing prompt template version for correlation",
    )


class ModelTaskDelegatedPayload(BaseModel):
    """Event payload for task delegation with quality gate result (OMN-2281).

    Emitted after each delegation attempt — whether the quality gate passed
    or failed — to allow tracking of delegation success rate (golden metric: >80%).

    Attributes:
        session_id: Session identifier for correlation.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when the event was emitted (UTC). Must be injected explicitly.
        task_type: TaskIntent value (document, test, research).
        handler_used: Endpoint purpose used (doc_gen, test_boilerplate, code_review).
        model_used: Model identifier returned by the endpoint.
        quality_gate_passed: True when the heuristic quality check succeeded.
        quality_gate_reason: Human-readable reason for quality gate failure (max 200 chars).
        delegation_success: True when delegation produced a usable response.
        estimated_savings_usd: Estimated cost savings compared to primary model (>= 0.0).
        latency_ms: Total delegation wall-clock time in milliseconds (>= 0).

    Note:
        ``extra="ignore"`` is intentional — the delegation result dict may carry
        additional keys (e.g., debug fields) that are not needed by this schema.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> event = ModelTaskDelegatedPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     correlation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     task_type="document",
        ...     handler_used="doc_gen",
        ...     model_used="Qwen2.5-72B",
        ...     quality_gate_passed=True,
        ...     quality_gate_reason=None,
        ...     delegation_success=True,
        ...     estimated_savings_usd=0.0112,
        ...     latency_ms=320,
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    # Identity / tracing
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier for correlation",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )

    # Timestamps — MUST be explicitly injected (no default_factory for testability)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the event was emitted (UTC)",
    )

    # Delegation metadata
    task_type: str = Field(
        ...,
        min_length=1,
        description="TaskIntent value: document, test, research",
    )
    handler_used: str = Field(
        ...,
        min_length=1,
        description="Endpoint purpose used: doc_gen, test_boilerplate, code_review",
    )
    model_used: str = Field(
        ...,
        min_length=1,
        description="Model identifier returned by the endpoint",
    )

    # Quality gate outcome
    quality_gate_passed: bool = Field(
        ...,
        description="True when the heuristic quality check succeeded",
    )
    quality_gate_reason: str | None = Field(
        default=None,
        max_length=200,
        description="Human-readable reason for quality gate failure (None when passed)",
    )

    # Delegation outcome
    delegation_success: bool = Field(
        ...,
        description="True when delegation produced a usable response for the user",
    )
    estimated_savings_usd: float = Field(
        ...,
        ge=0.0,
        description="Estimated cost savings compared to primary model in USD",
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Total delegation wall-clock time in milliseconds",
    )


class ModelDelegationShadowComparisonPayload(BaseModel):
    """Event payload for delegation shadow validation comparison (OMN-2283).

    Emitted asynchronously after shadow validation runs a delegated prompt
    through Claude to compare quality.  This event is non-blocking — the local
    model response is returned to the user immediately; Claude's shadow response
    is obtained in a background thread and compared after the fact.

    Purpose: detect quality degradation before users notice it.  Without this,
    the only feedback loop is user complaints.

    Exit criteria: shadow validation is automatically disabled once the daily
    pass rate has met or exceeded the ``exit_threshold`` for
    ``exit_window_days`` consecutive days (default: 95% for 30 days).

    Attributes:
        session_id: Session identifier for correlation.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Delegation initiation timestamp (UTC). Passed from
            orchestrate_delegation; represents when the delegation started, not
            when the comparison result was observed. Must be injected explicitly
            (no default_factory).
        task_type: TaskIntent value (document, test, research).
        local_model: Model identifier used for the delegated (local) response.
        shadow_model: Model identifier used for the shadow (Claude) response.
        local_response_length: Character count of the local model response.
        shadow_response_length: Character count of the shadow (Claude) response.
        length_divergence_ratio: Absolute ratio of length difference to shadow
            length: abs(local_len - shadow_len) / max(shadow_len, 1). Range 0.0+.
            Values > 0.5 indicate significant length divergence.
        keyword_overlap_score: Jaccard similarity of significant word sets
            between local and shadow responses (0.0 = no overlap, 1.0 = identical
            vocabulary). Uses word sets after stop-word removal.
        structural_match: True when both responses have the same top-level
            structural category (e.g., both have code blocks, both are prose).
        quality_gate_passed: True when all comparison metrics are within
            acceptable divergence thresholds.
        divergence_reason: Human-readable explanation of divergence. None only
            when no divergence of any kind occurred (length, keyword, or
            structural). May be non-None even when quality_gate_passed=True
            (e.g., structural mismatch is advisory and does not fail the gate).
        shadow_latency_ms: Wall-clock time for the shadow Claude call in ms.
        sample_rate: The configured sampling rate (0.05 - 0.10) at which this
            shadow check was triggered.
        consecutive_passing_days: Number of consecutive days where the pass rate
            met or exceeded the exit threshold (for exit criteria tracking).
        exit_threshold: The pass-rate threshold (e.g. 0.95) required to count a
            day toward the exit window.
        exit_window_days: Number of consecutive days above threshold required to
            trigger auto-disable (e.g. 30).
        auto_disable_triggered: True when this run is the last before auto-disable
            fires (consecutive_passing_days + 1 >= exit_window_days).

    Note:
        ``extra="ignore"`` is intentional — the shadow comparison result dict may
        carry additional debug fields not needed by this schema.

    Example:
        >>> from datetime import UTC, datetime
        >>> from uuid import uuid4
        >>> event = ModelDelegationShadowComparisonPayload(
        ...     session_id="abc12345-1234-5678-abcd-1234567890ab",
        ...     correlation_id=uuid4(),
        ...     emitted_at=datetime(2025, 1, 15, 12, 5, 0, tzinfo=UTC),
        ...     task_type="document",
        ...     local_model="Qwen2.5-72B",
        ...     shadow_model="claude-sonnet-4-6",
        ...     local_response_length=450,
        ...     shadow_response_length=520,
        ...     length_divergence_ratio=0.135,
        ...     keyword_overlap_score=0.82,
        ...     structural_match=True,
        ...     quality_gate_passed=True,
        ...     divergence_reason=None,
        ...     shadow_latency_ms=1240,
        ...     sample_rate=0.07,
        ...     consecutive_passing_days=12,
        ...     exit_threshold=0.95,
        ...     exit_window_days=30,
        ...     auto_disable_triggered=False,
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    # Identity / tracing
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier for correlation",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )

    # Timestamps — MUST be explicitly injected (no default_factory for testability)
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description=(
            "Delegation initiation timestamp (UTC). Passed from orchestrate_delegation; "
            "represents when the delegation started, not when the comparison result was observed."
        ),
    )

    # Delegation context
    task_type: str = Field(
        ...,
        min_length=1,
        description="TaskIntent value: document, test, research",
    )
    local_model: str = Field(
        ...,
        min_length=1,
        description="Model identifier used for the delegated (local) response",
    )
    shadow_model: str = Field(
        ...,
        min_length=1,
        description="Model identifier used for the shadow (Claude) response",
    )

    # Output comparison metrics
    local_response_length: int = Field(
        ...,
        ge=0,
        description="Character count of the local model response",
    )
    shadow_response_length: int = Field(
        ...,
        ge=0,
        description="Character count of the shadow (Claude) response",
    )
    length_divergence_ratio: float = Field(
        ...,
        ge=0.0,
        le=10.0,
        description=(
            "Absolute ratio of length difference to shadow length: "
            "abs(local_len - shadow_len) / max(shadow_len, 1). "
            "Values > 0.70 indicate significant length divergence (gate threshold). "
            "Capped at 10.0 to ensure bounded downstream consumption."
        ),
    )
    keyword_overlap_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Jaccard similarity of significant word sets (0.0 = no overlap, "
            "1.0 = identical vocabulary). Stop-words excluded."
        ),
    )
    structural_match: bool = Field(
        ...,
        description=(
            "True when both responses share the same top-level structural "
            "category (e.g., both contain code blocks, or both are prose)."
        ),
    )

    # Quality gate outcome
    quality_gate_passed: bool = Field(
        ...,
        description="True when all comparison metrics are within acceptable thresholds",
    )
    divergence_reason: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Human-readable explanation of divergence. None when all metrics pass "
            "(no divergence of any kind). May be set even when quality_gate_passed=True "
            "(e.g., structural mismatch noted as advisory)."
        ),
    )

    # Performance
    shadow_latency_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock time for the shadow Claude API call in milliseconds",
    )

    # Sampling / exit-criteria metadata
    sample_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Configured sampling rate at which this shadow check was triggered",
    )
    consecutive_passing_days: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of consecutive days where the pass rate met or exceeded "
            "exit_threshold (for exit-criteria tracking)."
        ),
    )
    exit_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Daily pass-rate threshold required to count toward the exit window",
    )
    exit_window_days: int = Field(
        default=30,
        ge=1,
        description=(
            "Number of consecutive days above exit_threshold required to trigger "
            "automatic shadow validation disable."
        ),
    )
    auto_disable_triggered: bool = Field(
        default=False,
        description=(
            "True when this run is the last before auto-disable fires "
            "(consecutive_passing_days + 1 >= exit_window_days)."
        ),
    )


__all__ = [
    # Constants
    "PROMPT_PREVIEW_MAX_LENGTH",
    # Enums
    "HookEventType",
    "HookSource",
    "SessionEndReason",
    "ContextSource",
    "EnumClaudeCodeSessionOutcome",
    "EnumAgentState",
    # Annotated types (reusable validators)
    "TimezoneAwareDatetime",
    # Sanitization utilities
    "sanitize_text",
    # Payload models
    "ModelHookSessionStartedPayload",
    "ModelHookSessionEndedPayload",
    "ModelSessionOutcome",
    "ModelRoutingFeedbackPayload",
    "ModelSessionRawOutcomePayload",
    "ModelRoutingFeedbackSkippedPayload",
    "ModelHookPromptSubmittedPayload",
    "ModelHookToolExecutedPayload",
    "ModelHookContextInjectedPayload",
    "ModelContextUtilizationPayload",
    "ModelAgentMatchPayload",
    "ModelLatencyBreakdownPayload",
    "ModelHookManifestInjectedPayload",
    "ModelAgentStatusPayload",
    # Static context edit detection (OMN-2237)
    "ModelChangedFileRecord",
    "ModelStaticContextEditDetectedPayload",
    # LLM routing observability (OMN-2273)
    "ModelLlmRoutingDecisionPayload",
    "ModelLlmRoutingFallbackPayload",
    # Delegation observability (OMN-2281)
    "ModelTaskDelegatedPayload",
    # Shadow validation (OMN-2283)
    "ModelDelegationShadowComparisonPayload",
    # Envelope and types
    "ModelHookEventEnvelope",
    "ModelHookPayload",
]
