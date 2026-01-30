# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Event registry defining daemon routing and fan-out rules.

This module provides the event registry for the emit daemon, defining how
hook events are routed to Kafka topics. The key feature is **fan-out support**:
a single event type can be published to multiple topics with different
payload transformations.

Architecture:
    ```
    Hook Script (user-prompt-submit.sh)
           |
           | emit_daemon_send(event_type="prompt.submitted", payload={...})
           v
    +-------------+
    | Emit Daemon |
    +-------------+
           |
           | EVENT_REGISTRY lookup for "prompt.submitted"
           v
    +------------------+
    | FanOutRegistry   |
    +------------------+
           |
           +------------------+------------------+
           |                                     |
           v                                     v
    +----------------------+         +------------------------+
    | CLAUDE_HOOK_EVENT    |         | PROMPT_SUBMITTED       |
    | (full prompt)        |         | (sanitized preview)    |
    +----------------------+         +------------------------+
           |                                     |
           v                                     v
    onex.cmd.omniintelligence.     onex.evt.omniclaude.
    claude-hook-event.v1           prompt-submitted.v1
    ```

Key Design Decisions:
    - **Fan-out at daemon level**: The hook sends one event; the daemon handles
      duplication and transformation. This keeps hooks simple and fast.
    - **Transform functions**: Each fan-out rule can specify an optional
      transform function that modifies the payload before publishing.
    - **Passthrough by default**: If no transform is specified, the payload
      is published as-is.

Privacy Considerations:
    - The observability topic receives a sanitized, truncated prompt preview
    - The intelligence topic receives the full prompt for analysis
    - This separation allows different retention/access policies per topic

Related Tickets:
    - OMN-1631: Emit daemon fan-out support
    - OMN-1632: Event registry for omniclaude hooks

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from omniclaude.hooks.schemas import (
    PROMPT_PREVIEW_MAX_LENGTH,
    _sanitize_prompt_preview,
)
from omniclaude.hooks.topics import TopicBase

# Type alias for payload transform functions
# Transform: dict -> dict (receives payload, returns transformed payload)
PayloadTransform = Callable[[dict[str, object]], dict[str, object]]


# =============================================================================
# Transform Functions
# =============================================================================


def transform_for_observability(payload: dict[str, object]) -> dict[str, object]:
    """Transform prompt payload for observability topic.

    This transform:
    1. Extracts the full prompt from the payload
    2. Creates a sanitized, truncated preview (max 100 chars)
    3. Records the original prompt length
    4. Removes the full prompt from the output

    The resulting payload is suitable for the observability topic where
    we want metadata about prompts without storing full content.

    Args:
        payload: Original event payload containing 'prompt' field.

    Returns:
        Transformed payload with:
        - prompt_preview: Sanitized, truncated preview (max 100 chars)
        - prompt_length: Original prompt length in characters
        - All other original fields preserved
        - 'prompt' field removed (replaced by preview)

    Example:
        >>> payload = {"prompt": "Fix the bug in auth.py with API key sk-abc123...", "session_id": "xyz"}
        >>> result = transform_for_observability(payload)
        >>> "prompt" not in result  # Full prompt removed
        True
        >>> "prompt_preview" in result  # Preview added
        True
        >>> "prompt_length" in result  # Length added
        True
        >>> "sk-" not in result["prompt_preview"]  # Secrets redacted
        True
    """
    # Create a copy to avoid mutating the original
    result: dict[str, object] = dict(payload)

    # Extract the full prompt
    full_prompt = payload.get("prompt", "")
    if not isinstance(full_prompt, str):
        full_prompt = str(full_prompt) if full_prompt is not None else ""

    # Record the original length before any processing
    result["prompt_length"] = len(full_prompt)

    # Create sanitized, truncated preview
    # _sanitize_prompt_preview handles both secret redaction and truncation
    result["prompt_preview"] = _sanitize_prompt_preview(
        full_prompt, max_length=PROMPT_PREVIEW_MAX_LENGTH
    )

    # Remove the full prompt from the payload
    # The observability topic should only have the preview
    result.pop("prompt", None)

    return result


def transform_passthrough(payload: dict[str, object]) -> dict[str, object]:
    """Passthrough transform - returns payload unchanged.

    This is the default transform when no modification is needed.
    Explicitly defined for clarity and testability.

    Args:
        payload: Original event payload.

    Returns:
        The original payload unchanged.
    """
    return payload


# =============================================================================
# Fan-Out Rule Models
# =============================================================================


@dataclass(frozen=True)
class FanOutRule:
    """A single fan-out rule specifying a target topic and optional transform.

    Attributes:
        topic_base: The base topic name from TopicBase enum.
            The daemon will resolve this to the full topic name with
            environment prefix (e.g., "dev.onex.evt.omniclaude.prompt-submitted.v1").
        transform: Optional function to transform the payload before publishing.
            If None, the payload is passed through unchanged.
            Transform signature: (dict[str, object]) -> dict[str, object]
        description: Human-readable description of what this rule does.
            Used for logging and debugging.

    Example:
        >>> rule = FanOutRule(
        ...     topic_base=TopicBase.PROMPT_SUBMITTED,
        ...     transform=transform_for_observability,
        ...     description="Sanitized preview for observability",
        ... )
    """

    topic_base: TopicBase
    transform: PayloadTransform | None = None
    description: str = ""

    def apply_transform(self, payload: dict[str, object]) -> dict[str, object]:
        """Apply the transform to the payload.

        Args:
            payload: The original event payload.

        Returns:
            Transformed payload, or original if no transform is defined.
        """
        if self.transform is None:
            return payload
        return self.transform(payload)


@dataclass(frozen=True)
class EventRegistration:
    """Registration for a single event type with fan-out rules.

    Each event type can have multiple fan-out rules, allowing the daemon
    to publish the same event to multiple topics with different payloads.

    Attributes:
        event_type: The semantic event type identifier (e.g., "prompt.submitted").
            This matches the event_type field in ModelDaemonEmitRequest.
        fan_out: List of fan-out rules defining target topics and transforms.
            Events are published to ALL targets in this list.
        partition_key_field: Optional field name to use as Kafka partition key.
            Events with the same partition key go to the same partition,
            ensuring ordering for that key.
        required_fields: List of field names that must be present in the payload.
            Validation fails if any required field is missing.

    Example:
        >>> reg = EventRegistration(
        ...     event_type="prompt.submitted",
        ...     fan_out=[
        ...         FanOutRule(topic_base=TopicBase.CLAUDE_HOOK_EVENT),
        ...         FanOutRule(topic_base=TopicBase.PROMPT_SUBMITTED, transform=transform_for_observability),
        ...     ],
        ...     partition_key_field="session_id",
        ...     required_fields=["prompt", "session_id"],
        ... )
    """

    event_type: str
    fan_out: list[FanOutRule] = field(default_factory=list)
    partition_key_field: str | None = None
    required_fields: list[str] = field(default_factory=list)


# =============================================================================
# Event Registry
# =============================================================================


# Registry mapping event types to their fan-out rules
# This is the central configuration for the emit daemon's routing logic
EVENT_REGISTRY: dict[str, EventRegistration] = {
    # =========================================================================
    # Session Events
    # =========================================================================
    "session.started": EventRegistration(
        event_type="session.started",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.SESSION_STARTED,
                transform=None,  # Passthrough
                description="Session start event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    "session.ended": EventRegistration(
        event_type="session.ended",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.SESSION_ENDED,
                transform=None,  # Passthrough
                description="Session end event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    # =========================================================================
    # Prompt Events (Fan-out to TWO topics)
    # =========================================================================
    "prompt.submitted": EventRegistration(
        event_type="prompt.submitted",
        fan_out=[
            # Target 1: Intelligence topic - Full prompt for analysis
            # The intelligence service needs the complete prompt to:
            # - Classify user intent
            # - Learn workflow patterns
            # - Optimize RAG retrieval
            FanOutRule(
                topic_base=TopicBase.CLAUDE_HOOK_EVENT,
                transform=None,  # Passthrough - full prompt
                description="Full prompt to intelligence service for analysis",
            ),
            # Target 2: Observability topic - Sanitized preview
            # The observability topic receives only:
            # - prompt_preview: 100-char sanitized preview with secrets redacted
            # - prompt_length: Original prompt length
            # This allows metrics and dashboards without storing sensitive data
            FanOutRule(
                topic_base=TopicBase.PROMPT_SUBMITTED,
                transform=transform_for_observability,
                description="Sanitized 100-char preview for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["prompt", "session_id"],
    ),
    # =========================================================================
    # Tool Events
    # =========================================================================
    "tool.executed": EventRegistration(
        event_type="tool.executed",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.TOOL_EXECUTED,
                transform=None,  # Passthrough
                description="Tool execution event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["tool_name", "session_id"],
    ),
}


# =============================================================================
# Registry Helper Functions
# =============================================================================


def get_registration(event_type: str) -> EventRegistration | None:
    """Get the registration for an event type.

    Args:
        event_type: The semantic event type identifier.

    Returns:
        The EventRegistration if found, None otherwise.

    Example:
        >>> reg = get_registration("prompt.submitted")
        >>> reg is not None
        True
        >>> len(reg.fan_out)
        2
    """
    return EVENT_REGISTRY.get(event_type)


def list_event_types() -> list[str]:
    """List all registered event types.

    Returns:
        List of registered event type identifiers.

    Example:
        >>> types = list_event_types()
        >>> "prompt.submitted" in types
        True
        >>> "session.started" in types
        True
    """
    return list(EVENT_REGISTRY.keys())


def validate_payload(event_type: str, payload: dict[str, object]) -> list[str]:
    """Validate that a payload has all required fields for an event type.

    Args:
        event_type: The semantic event type identifier.
        payload: The event payload to validate.

    Returns:
        List of missing field names (empty if valid).

    Raises:
        KeyError: If the event type is not registered.

    Example:
        >>> missing = validate_payload("prompt.submitted", {"prompt": "hello"})
        >>> "session_id" in missing  # session_id is required
        True
        >>> missing = validate_payload("prompt.submitted", {"prompt": "hello", "session_id": "xyz"})
        >>> len(missing)
        0
    """
    registration = EVENT_REGISTRY.get(event_type)
    if registration is None:
        raise KeyError(f"Unknown event type: {event_type}")

    missing = [field for field in registration.required_fields if field not in payload]
    return missing


def get_partition_key(event_type: str, payload: dict[str, object]) -> str | None:
    """Extract the partition key from a payload based on the event registration.

    Args:
        event_type: The semantic event type identifier.
        payload: The event payload.

    Returns:
        The partition key value as a string, or None if not configured.

    Raises:
        KeyError: If the event type is not registered.

    Example:
        >>> key = get_partition_key("prompt.submitted", {"session_id": "abc123", "prompt": "hello"})
        >>> key
        'abc123'
    """
    registration = EVENT_REGISTRY.get(event_type)
    if registration is None:
        raise KeyError(f"Unknown event type: {event_type}")

    if registration.partition_key_field is None:
        return None

    value = payload.get(registration.partition_key_field)
    if value is None:
        return None

    return str(value)


__all__ = [
    # Transform functions
    "transform_for_observability",
    "transform_passthrough",
    # Data classes
    "FanOutRule",
    "EventRegistration",
    # Registry
    "EVENT_REGISTRY",
    # Helper functions
    "get_registration",
    "list_event_types",
    "validate_payload",
    "get_partition_key",
    # Type aliases
    "PayloadTransform",
]
