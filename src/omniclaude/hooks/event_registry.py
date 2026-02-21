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

    Handles two payload shapes:

    **New shape** (OMN-2027): Hook sends ``prompt_preview``, ``prompt_length``,
    and ``prompt_b64``. This transform strips ``prompt_b64`` (full prompt) and
    re-sanitizes ``prompt_preview`` for defense-in-depth.

    **Legacy shape**: Hook sends a raw ``prompt`` field. This transform creates
    a sanitized preview, records original length, and removes the full prompt.

    The resulting payload is suitable for the observability topic where
    we want metadata about prompts without storing full content.

    Args:
        payload: Original event payload (new or legacy shape).

    Returns:
        Transformed payload with:
        - prompt_preview: Sanitized, truncated preview (max 100 chars)
        - prompt_length: Original prompt length in characters
        - All other original fields preserved
        - Full prompt fields removed (prompt, prompt_b64)

    Example:
        >>> payload = {"prompt_preview": "Fix the bug...", "prompt_b64": "RnVsbA==", "prompt_length": 42, "session_id": "xyz"}
        >>> result = transform_for_observability(payload)
        >>> "prompt_b64" not in result  # Full prompt removed
        True
        >>> "prompt_preview" in result  # Preview preserved
        True
    """
    # Create a copy to avoid mutating the original
    result: dict[str, object] = dict(payload)

    # New payload shape (OMN-2027): hook sends prompt_preview + prompt_b64
    # instead of a raw "prompt" field. Detect via prompt_b64 presence.
    if "prompt_b64" in payload:
        # prompt_preview and prompt_length are already set by the hook.
        # Just strip the full-prompt fields that must not reach the evt topic.
        result.pop("prompt_b64", None)
        result.pop("prompt", None)

        # Re-sanitize prompt_preview for defense-in-depth (hook truncates
        # to 100 chars but does not run full secret redaction).
        preview = payload.get("prompt_preview", "")
        if not isinstance(preview, str):
            preview = str(preview) if preview is not None else ""
        result["prompt_preview"] = _sanitize_prompt_preview(
            preview, max_length=PROMPT_PREVIEW_MAX_LENGTH
        )
        return result

    # Legacy payload shape: raw "prompt" field (backwards compatibility)
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
            TopicBase values ARE the wire topic names (no environment prefix per OMN-1972).
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
            return dict(payload)
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
        ...     required_fields=["prompt_preview", "session_id"],
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
    # Session outcome event (OMN-1735, FEEDBACK-008)
    # Fan-out to BOTH intelligence (CMD) and observability (EVT):
    #   - CMD: triggers pattern_feedback_effect in omniintelligence
    #   - EVT: dashboards, monitoring, generic subscribers
    "session.outcome": EventRegistration(
        event_type="session.outcome",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.SESSION_OUTCOME_CMD,
                transform=None,  # Passthrough — full payload to intelligence
                description="Session outcome for intelligence feedback loop",
            ),
            FanOutRule(
                topic_base=TopicBase.SESSION_OUTCOME_EVT,
                transform=None,  # Passthrough — same payload for observability
                description="Session outcome for dashboards and monitoring",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "outcome"],
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
        required_fields=["prompt_preview", "session_id"],
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
    # =========================================================================
    # Routing Feedback Events (OMN-1892)
    # =========================================================================
    "routing.feedback": EventRegistration(
        event_type="routing.feedback",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.ROUTING_FEEDBACK,
                transform=None,  # Passthrough
                description="Routing feedback for reinforcement learning",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "outcome"],
    ),
    "routing.skipped": EventRegistration(
        event_type="routing.skipped",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.ROUTING_FEEDBACK_SKIPPED,
                transform=None,  # Passthrough
                description="Routing feedback skipped (guardrail gate failed)",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "skip_reason"],
    ),
    # Raw session outcome signals (OMN-2356)
    # Replaces the no-op derived feedback loop (injection_occurred=False hardcoded).
    # omniintelligence's routing-feedback consumer computes derived scores from
    # these raw observable facts + context utilization events.
    # No derived scores (utilization_score, agent_match_score) in this event —
    # computing them here requires DB reads (Invariant 5 violation).
    "routing.outcome.raw": EventRegistration(
        event_type="routing.outcome.raw",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.ROUTING_OUTCOME_RAW,
                transform=None,  # Passthrough — no sensitive data in raw signals
                description="Raw session outcome signals for omniintelligence feedback loop",
            ),
        ],
        partition_key_field="session_id",
        required_fields=[
            "session_id",
            "injection_occurred",
            "tool_calls_count",
            "duration_ms",
        ],
    ),
    # =========================================================================
    # Injection Tracking Events (OMN-1673 INJECT-004)
    # =========================================================================
    "injection.recorded": EventRegistration(
        event_type="injection.recorded",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.INJECTION_RECORDED,
                transform=None,  # Passthrough - full payload
                description="Injection tracking for A/B analysis and outcome attribution",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["injection_id", "session_id", "cohort"],
    ),
    # =========================================================================
    # Metrics Events (OMN-1889)
    # =========================================================================
    "context.utilization": EventRegistration(
        event_type="context.utilization",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.CONTEXT_UTILIZATION,
                transform=None,  # Passthrough
                description="Context utilization metrics for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    "agent.match": EventRegistration(
        event_type="agent.match",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.AGENT_MATCH,
                transform=None,  # Passthrough
                description="Agent match metrics for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    "latency.breakdown": EventRegistration(
        event_type="latency.breakdown",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.LATENCY_BREAKDOWN,
                transform=None,  # Passthrough
                description="Latency breakdown metrics for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    # =========================================================================
    # Routing Decision (PR-92)
    # =========================================================================
    "routing.decision": EventRegistration(
        event_type="routing.decision",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.ROUTING_DECISION,
                transform=None,  # Passthrough
                description="Routing decision event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    # =========================================================================
    # LLM Routing Observability Events (OMN-2273)
    # =========================================================================
    "llm.routing.decision": EventRegistration(
        event_type="llm.routing.decision",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.LLM_ROUTING_DECISION,
                transform=None,  # Passthrough — no sensitive data in routing metadata
                description="LLM routing decision with determinism audit fields",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "selected_agent", "routing_prompt_version"],
    ),
    "llm.routing.fallback": EventRegistration(
        event_type="llm.routing.fallback",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.LLM_ROUTING_FALLBACK,
                transform=None,  # Passthrough
                description="LLM routing fallback — pipeline fell through to fuzzy matching",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "fallback_reason", "routing_prompt_version"],
    ),
    # =========================================================================
    # Context Enrichment Observability Events (OMN-2274, OMN-2441)
    # =========================================================================
    "context.enrichment": EventRegistration(
        event_type="context.enrichment",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.CONTEXT_ENRICHMENT,
                transform=None,  # Passthrough — no sensitive data in enrichment metadata
                description="Per-channel enrichment observability event",
            ),
        ],
        partition_key_field="session_id",
        # OMN-2441: 'channel' replaces 'enrichment_type' — payloads without 'channel' are intentionally rejected.
        # Audited: no caller invokes validate_payload("context.enrichment", ...) with the old
        # 'enrichment_type' field — the only call site is embedded_publisher.py which forwards
        # the payload as-is from enrichment_observability_emitter.py (which already emits
        # 'channel').  No callers need updating.
        # Manually verified at OMN-2441; re-audit if new validate_payload("context.enrichment", ...) call sites are added.
        required_fields=["session_id", "channel"],
    ),
    # =========================================================================
    # Notification Events (OMN-1831)
    # =========================================================================
    "notification.blocked": EventRegistration(
        event_type="notification.blocked",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.NOTIFICATION_BLOCKED,
                transform=None,  # Passthrough
                description="Notification blocked event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    "notification.completed": EventRegistration(
        event_type="notification.completed",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.NOTIFICATION_COMPLETED,
                transform=None,  # Passthrough
                description="Notification completed event for observability",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id"],
    ),
    # =========================================================================
    # Phase Metrics (OMN-2027 - pipeline measurement)
    # =========================================================================
    "phase.metrics": EventRegistration(
        event_type="phase.metrics",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.PHASE_METRICS,
                transform=None,  # Passthrough (pre-sanitized by metrics_emitter)
                description="Phase instrumentation metrics for pipeline observability",
            ),
        ],
        partition_key_field=None,  # No partition key; events are round-robin distributed
        required_fields=["event_id", "event_type", "timestamp_iso", "payload"],
    ),
    # =========================================================================
    # Pattern Compliance (OMN-2263 → OMN-2256)
    # =========================================================================
    # No fan-out, no payload transform — full content goes to the intelligence
    # cmd topic which is already access-restricted. Content must reach
    # omniintelligence intact for content-aware compliance checking.
    "compliance.evaluate": EventRegistration(
        event_type="compliance.evaluate",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.COMPLIANCE_EVALUATE,
                transform=None,  # Passthrough — full content to intelligence
                description="Compliance evaluation request to omniintelligence",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "source_path", "applicable_patterns"],
    ),
    # =========================================================================
    # Static Context Edit Detection (OMN-2237)
    # =========================================================================
    "static.context.edit.detected": EventRegistration(
        event_type="static.context.edit.detected",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.STATIC_CONTEXT_EDIT_DETECTED,
                transform=None,  # Passthrough — no content, only paths and stats
                description="Static context file change detected between sessions",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "changed_file_count"],
    ),
    # =========================================================================
    # Delegation Shadow Validation (OMN-2283)
    # =========================================================================
    "delegation.shadow.comparison": EventRegistration(
        event_type="delegation.shadow.comparison",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.DELEGATION_SHADOW_COMPARISON,
                transform=None,  # Passthrough — no sensitive data in comparison metrics
                description="Shadow validation comparison result for quality monitoring",
            ),
        ],
        partition_key_field="session_id",
        required_fields=["session_id", "correlation_id"],
    ),
    # =========================================================================
    # Agent Status (OMN-1848 - agent lifecycle reporting)
    # =========================================================================
    # NOTE: agent_name and session_id may carry the sentinel value "unknown".
    # This indicates the caller did not provide these fields explicitly and
    # the corresponding environment variables (AGENT_NAME, SESSION_ID) were
    # also unset. Consumers should treat "unknown" as "not provided", not as
    # a literal agent name or session identifier.
    "agent.status": EventRegistration(
        event_type="agent.status",
        fan_out=[
            FanOutRule(
                topic_base=TopicBase.AGENT_STATUS,
                transform=None,  # Passthrough (pre-validated by agent_status_emitter)
                description="Agent lifecycle status for observability and coordination",
            ),
        ],
        # Known limitation: when session_id falls back to "unknown" (env var
        # unset and caller omits it), all such events hash to the same Kafka
        # partition, creating a hot-partition.  Acceptable for low-volume
        # fallback traffic; revisit if "unknown" events become frequent.
        partition_key_field="session_id",
        required_fields=["agent_name", "session_id", "state", "message"],
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
        >>> missing = validate_payload("prompt.submitted", {"prompt_preview": "hello"})
        >>> "session_id" in missing  # session_id is required
        True
        >>> missing = validate_payload("prompt.submitted", {"prompt_preview": "hello", "session_id": "xyz"})
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
        >>> key = get_partition_key("prompt.submitted", {"session_id": "abc123", "prompt_preview": "hello"})
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
