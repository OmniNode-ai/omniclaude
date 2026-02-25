# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Topic base names and helper for OmniClaude events.

Per OMN-1972, TopicBase values ARE the canonical wire topic names. No environment
prefix is applied. The build_topic() helper still accepts a prefix argument for
validation purposes, but callers should always pass an empty string.
"""

from __future__ import annotations

import re
from enum import StrEnum

from omnibase_core.enums import EnumCoreErrorCode
from omnibase_core.models.errors import ModelOnexError

# Valid topic name pattern: alphanumeric segments separated by single dots
# No leading/trailing dots, no consecutive dots, no special characters except dots
_TOPIC_SEGMENT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class TopicBase(StrEnum):
    """Base topic names (without environment prefix).

    All topics follow ONEX canonical format (OMN-1537):
        onex.{kind}.{producer}.{event-name}.v{n}

    Where:
        - kind: cmd, evt, dlq, intent, snapshot
        - producer: service name (omniclaude, omninode, omniintelligence)
        - event-name: kebab-case event name
        - v{n}: version number
    """

    # ==========================================================================
    # omniclaude event topics (hooks → event bus)
    # ==========================================================================
    SESSION_STARTED = "onex.evt.omniclaude.session-started.v1"
    SESSION_ENDED = "onex.evt.omniclaude.session-ended.v1"
    PROMPT_SUBMITTED = "onex.evt.omniclaude.prompt-submitted.v1"
    TOOL_EXECUTED = "onex.evt.omniclaude.tool-executed.v1"
    AGENT_ACTION = "onex.evt.omniclaude.agent-action.v1"
    LEARNING_PATTERN = "onex.evt.omniclaude.learning-pattern.v1"

    # ==========================================================================
    # omninode routing topics (agent routing commands/events)
    # ==========================================================================
    ROUTING_REQUESTED = "onex.cmd.omninode.routing-requested.v1"
    ROUTING_COMPLETED = "onex.evt.omninode.routing-completed.v1"
    ROUTING_FAILED = "onex.evt.omninode.routing-failed.v1"

    # ==========================================================================
    # Cross-service topics (omniclaude → omniintelligence)
    # ==========================================================================
    # Claude hook event topic (consumed by omniintelligence.NodeClaudeHookEventEffect)
    CLAUDE_HOOK_EVENT = "onex.cmd.omniintelligence.claude-hook-event.v1"
    # Tool content topic for pattern learning (OMN-1702)
    TOOL_CONTENT = "onex.cmd.omniintelligence.tool-content.v1"
    # Session outcome: CMD target for intelligence feedback loop (OMN-1735)
    SESSION_OUTCOME_CMD = "onex.cmd.omniintelligence.session-outcome.v1"
    # Session outcome: EVT target for dashboards / monitoring
    SESSION_OUTCOME_EVT = "onex.evt.omniclaude.session-outcome.v1"

    # ==========================================================================
    # Hook adapter observability topics (migrated to ONEX format, OMN-1552)
    # ==========================================================================
    AGENT_ACTIONS = "onex.evt.omniclaude.agent-actions.v1"
    PERFORMANCE_METRICS = "onex.evt.omniclaude.performance-metrics.v1"
    TRANSFORMATIONS = "onex.evt.omniclaude.agent-transformation.v1"
    DETECTION_FAILURES = "onex.evt.omniclaude.detection-failure.v1"

    # ==========================================================================
    # Context injection topics (OMN-1403)
    # ==========================================================================
    CONTEXT_RETRIEVAL_REQUESTED = "onex.cmd.omniclaude.context-retrieval-requested.v1"
    CONTEXT_RETRIEVAL_COMPLETED = "onex.evt.omniclaude.context-retrieval-completed.v1"
    CONTEXT_INJECTED = "onex.evt.omniclaude.context-injected.v1"
    # Injection tracking event (OMN-1673 INJECT-004)
    INJECTION_RECORDED = "onex.evt.omniclaude.injection-recorded.v1"

    # ==========================================================================
    # Injection metrics topics (OMN-1889)
    # ==========================================================================
    CONTEXT_UTILIZATION = "onex.evt.omniclaude.context-utilization.v1"
    AGENT_MATCH = "onex.evt.omniclaude.agent-match.v1"
    LATENCY_BREAKDOWN = "onex.evt.omniclaude.latency-breakdown.v1"

    # ==========================================================================
    # Routing feedback topics (OMN-1892)
    # ==========================================================================
    ROUTING_FEEDBACK = "onex.evt.omniclaude.routing-feedback.v1"
    ROUTING_FEEDBACK_SKIPPED = "onex.evt.omniclaude.routing-feedback-skipped.v1"
    # Raw session outcome signals (OMN-2356) — replaces no-op derived feedback
    # omniintelligence consumes this and computes derived scores server-side
    ROUTING_OUTCOME_RAW = "onex.evt.omniclaude.routing-outcome-raw.v1"

    # ==========================================================================
    # Routing decision topics (PR-92)
    # ==========================================================================
    ROUTING_DECISION = "onex.evt.omniclaude.routing-decision.v1"

    # ==========================================================================
    # LLM routing observability topics (OMN-2273)
    # ==========================================================================
    LLM_ROUTING_DECISION = "onex.evt.omniclaude.llm-routing-decision.v1"
    LLM_ROUTING_FALLBACK = "onex.evt.omniclaude.llm-routing-fallback.v1"

    # ==========================================================================
    # Notification topics (OMN-1831)
    # ==========================================================================
    NOTIFICATION_BLOCKED = "onex.evt.omniclaude.notification-blocked.v1"
    NOTIFICATION_COMPLETED = "onex.evt.omniclaude.notification-completed.v1"

    # ==========================================================================
    # Phase metrics topics (OMN-2027 - pipeline measurement)
    # ==========================================================================
    PHASE_METRICS = "onex.evt.omniclaude.phase-metrics.v1"

    # ==========================================================================
    # Manifest injection topics (agent loading observability)
    # ==========================================================================
    MANIFEST_INJECTION_STARTED = "onex.evt.omniclaude.manifest-injection-started.v1"
    MANIFEST_INJECTED = "onex.evt.omniclaude.manifest-injected.v1"
    MANIFEST_INJECTION_FAILED = "onex.evt.omniclaude.manifest-injection-failed.v1"

    # ==========================================================================
    # Agent status topics (OMN-1848 - agent lifecycle reporting)
    # ==========================================================================
    AGENT_STATUS = "onex.evt.omniclaude.agent-status.v1"

    # ==========================================================================
    # Transformation topics (agent transformation observability)
    # ==========================================================================
    TRANSFORMATION_STARTED = "onex.evt.omniclaude.transformation-started.v1"
    TRANSFORMATION_COMPLETED = "onex.evt.omniclaude.transformation-completed.v1"
    TRANSFORMATION_FAILED = "onex.evt.omniclaude.transformation-failed.v1"

    # ==========================================================================
    # Execution and observability topics (OMN-1552 migration)
    # ==========================================================================
    EXECUTION_LOGS = "onex.evt.omniclaude.agent-execution-logs.v1"
    AGENT_OBSERVABILITY = "onex.evt.omniclaude.agent-observability.v1"

    # ==========================================================================
    # Pattern compliance wiring (OMN-2263 → OMN-2256)
    # ==========================================================================
    COMPLIANCE_EVALUATE = "onex.cmd.omniintelligence.compliance-evaluate.v1"
    COMPLIANCE_EVALUATED = "onex.evt.omniintelligence.compliance-evaluated.v1"

    # ==========================================================================
    # Static context edit detection topics (OMN-2237)
    # ==========================================================================
    STATIC_CONTEXT_EDIT_DETECTED = "onex.evt.omniclaude.static-context-edit-detected.v1"

    # ==========================================================================
    # Enrichment observability topics (OMN-2274)
    # ==========================================================================
    CONTEXT_ENRICHMENT = "onex.evt.omniclaude.context-enrichment.v1"  # OMN-2274

    # ==========================================================================
    # Delegation observability topics (OMN-2281)
    # ==========================================================================
    TASK_DELEGATED = "onex.evt.omniclaude.task-delegated.v1"

    # ==========================================================================
    # Shadow validation topics (OMN-2283)
    # ==========================================================================
    DELEGATION_SHADOW_COMPARISON = "onex.evt.omniclaude.delegation-shadow-comparison.v1"

    # ==========================================================================
    # Pattern enforcement observability topics (OMN-2442)
    # Consumed by omnidash /enforcement dashboard
    # ==========================================================================
    PATTERN_ENFORCEMENT = "onex.evt.omniclaude.pattern-enforcement.v1"

    # ==========================================================================
    # Intent-to-commit binding topics (OMN-2492)
    # ==========================================================================
    INTENT_COMMIT_BOUND = "onex.evt.omniclaude.intent-commit-bound.v1"

    # ==========================================================================
    # Decision record topics (OMN-2465)
    # Privacy split: evt carries summary only; cmd carries full payload
    # ==========================================================================
    # Observability topic — broad access, summary fields only (no rationale/snapshot)
    DECISION_RECORDED_EVT = "onex.evt.omniintelligence.decision-recorded.v1"
    # Restricted topic — full payload including agent_rationale and reproducibility_snapshot
    DECISION_RECORDED_CMD = "onex.cmd.omniintelligence.decision-recorded.v1"

    # ==========================================================================
    # ChangeFrame emission topics (OMN-2651)
    # ==========================================================================
    CHANGE_FRAME_EMITTED = "onex.evt.omniclaude.change-frame.v1"

    # ==========================================================================
    # Agent trace topics (OMN-2412)
    # ==========================================================================
    AGENT_TRACE_FIX_TRANSITION = "onex.evt.omniclaude.fix-transition.v1"

    # ==========================================================================
    # Quirks Detector topics (OMN-2556)
    # ==========================================================================
    QUIRK_SIGNAL_DETECTED = "onex.evt.quirks.signal-detected.v1"
    """Raw QuirkSignal emitted by NodeQuirkSignalExtractorEffect after detection."""

    QUIRK_FINDING_PRODUCED = "onex.evt.quirks.finding-produced.v1"
    """QuirkFinding emitted by NodeQuirkClassifierCompute after threshold is met."""


def _validate_topic_segment(segment: str, name: str) -> str:
    """Validate a single topic segment (prefix or base segment).

    Args:
        segment: The segment to validate.
        name: Name of the parameter for error messages.

    Returns:
        The stripped segment.

    Raises:
        ModelOnexError: If segment is None, not a string, or empty/whitespace-only.

    Example:
        >>> _validate_topic_segment("dev", "prefix")
        'dev'

        >>> _validate_topic_segment("  staging  ", "prefix")
        'staging'

        >>> _validate_topic_segment("", "prefix")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        ModelOnexError: ...
    """
    if segment is None:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"{name} must not be None",
        )

    if not isinstance(segment, str):
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"{name} must be a string, got {type(segment).__name__}",
        )

    stripped = segment.strip()
    if not stripped:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"{name} must be a non-empty string",
        )

    return stripped


def _validate_topic_name(topic: str) -> None:
    """Validate that a topic name is well-formed.

    A well-formed topic name consists of alphanumeric segments (with underscores
    and hyphens allowed) separated by single dots. No leading/trailing dots,
    no consecutive dots, and no special characters except dots between segments.

    Args:
        topic: The full topic name to validate.

    Returns:
        None. This function validates in-place and raises on error.

    Raises:
        ModelOnexError: If topic name is malformed (leading/trailing dots,
            consecutive dots, empty segments, or invalid characters).

    Example:
        >>> _validate_topic_name("onex.evt.omniclaude.session-started.v1")  # Valid, no error

        >>> _validate_topic_name(".invalid")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        ModelOnexError: ...

        >>> _validate_topic_name("also..invalid")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        ModelOnexError: ...
    """
    # Check for leading/trailing dots
    if topic.startswith("."):
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"Topic name must not start with a dot: {topic!r}",
        )
    if topic.endswith("."):
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"Topic name must not end with a dot: {topic!r}",
        )

    # Check for consecutive dots
    if ".." in topic:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"Topic name must not contain consecutive dots: {topic!r}",
        )

    # Validate each segment
    segments = topic.split(".")
    for segment in segments:
        if not segment:
            # Empty segment (shouldn't happen after above checks, but be defensive)
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.INVALID_INPUT,
                message=f"Topic name contains empty segment: {topic!r}",
            )
        if not _TOPIC_SEGMENT_PATTERN.match(segment):
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.INVALID_INPUT,
                message=f"Topic segment contains invalid characters: {segment!r} in {topic!r}",
            )


def build_topic(prefix: str, base: str) -> str:
    """Build full topic name from prefix and base.

    Args:
        prefix: Topic prefix string. Must be a string without dots.
            If empty or whitespace-only, returns just the base topic name.
            Per OMN-1972, callers should always pass empty string ("") since
            TopicBase values are the canonical wire topic names with no
            environment prefix.
        base: Base topic name from TopicBase (e.g., "omniclaude.session.started.v1").
            Must be a valid dotted topic name.

    Returns:
        Full topic name. If prefix is empty, returns just the base topic name.

    Raises:
        ModelOnexError: If prefix is None, not a string, or contains dots.
        ModelOnexError: If base is empty, None, whitespace-only, or malformed.

    Examples:
        >>> build_topic("", TopicBase.SESSION_STARTED)
        'onex.evt.omniclaude.session-started.v1'

        >>> build_topic("  ", TopicBase.SESSION_STARTED)
        'onex.evt.omniclaude.session-started.v1'

        >>> build_topic(None, TopicBase.SESSION_STARTED)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        ModelOnexError: ...

        >>> build_topic("x.y", TopicBase.SESSION_STARTED)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        ModelOnexError: ...
    """
    # Validate prefix - allow None check but handle empty separately
    if prefix is None:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message="prefix must not be None",
        )

    if not isinstance(prefix, str):
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"prefix must be a string, got {type(prefix).__name__}",
        )

    # Handle empty prefix - return just the base
    stripped_prefix = prefix.strip()
    if not stripped_prefix:
        # Validate base and return it directly
        base = _validate_topic_segment(base, "base")
        _validate_topic_name(base)
        return base

    # Enforce no dots in prefix
    if "." in stripped_prefix:
        raise ModelOnexError(
            error_code=EnumCoreErrorCode.INVALID_INPUT,
            message=f"prefix must not contain dots: {stripped_prefix!r}",
        )

    # Validate base
    base = _validate_topic_segment(base, "base")

    # Build the topic
    topic = f"{stripped_prefix}.{base}"

    # Validate the final topic name
    _validate_topic_name(topic)

    return topic
