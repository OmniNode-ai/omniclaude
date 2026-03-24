# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Topic base names and helper for OmniClaude events.

Per OMN-1972, TopicBase values ARE the canonical wire topic names. No environment
prefix is applied. The build_topic() helper validates and returns the canonical
topic name (prefix parameter removed in OMN-5212).
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
    # Utilization scoring: CMD target for LLM-based scoring (OMN-5505)
    UTILIZATION_SCORING_CMD = "onex.cmd.omniintelligence.utilization-scoring.v1"

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
    # TOMBSTONED (OMN-2622): folded into ROUTING_FEEDBACK via feedback_status field.
    # Producer removed; topic no longer provisioned.
    # ROUTING_FEEDBACK_SKIPPED = "onex.evt.omniclaude.routing-feedback-skipped.v1"
    #
    # TOMBSTONED (OMN-2622): deprecated — no named consumer, raw signals not
    # suitable for long-term storage. Producer removed; topic no longer provisioned.
    # ROUTING_OUTCOME_RAW = "onex.evt.omniclaude.routing-outcome-raw.v1"

    # ==========================================================================
    # Routing decision topics (PR-92)
    # ==========================================================================
    ROUTING_DECISION = "onex.evt.omniclaude.routing-decision.v1"
    # Cross-domain CMD topic: producer=omniclaude, domain=omniintelligence.
    # Internal control plane — not an observability topic. No contract topic_base
    # (schema supports one topic_base per contract); governed via topic_allowlist.yaml.
    # Lifecycle: internal_control (OMN-3294)
    ROUTING_DECISION_CMD = "onex.cmd.omniintelligence.routing-decision.v1"  # noqa: arch-topic-naming

    # ==========================================================================
    # GitHub PR status topics (OMN-3294)
    # Lifecycle: Integration (stable) — governed by node_github_pr_watcher_effect/contract.yaml
    # ==========================================================================
    GITHUB_PR_STATUS = "onex.evt.omniclaude.github-pr-status.v1"
    # DLQ / error topic for the PR watcher node
    PR_WATCHER_FAILED = "onex.evt.omniclaude.pr-watcher-failed.v1"

    # ==========================================================================
    # Epic status topics (OMN-3294)
    # Lifecycle: Integration (stable) — governed by node_agent_inbox_effect/contract.yaml
    # ==========================================================================
    EPIC_STATUS = "onex.evt.omniclaude.epic-status.v1"

    # ==========================================================================
    # Personality logging telemetry topics (OMN-3294)
    # Lifecycle: Telemetry (best-effort, may be sampled) — governed by
    #            node_personality_logging_effect/contract.yaml
    # Note: Telemetry topics may be sampled or dropped. No business logic may
    #       hard-depend on them.
    # ==========================================================================
    LOG_EVENT_EMITTED = "onex.evt.omniclaude.log-event-emitted.v1"
    LOG_EVENT_RENDERED = "onex.evt.omniclaude.log-event-rendered.v1"

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
    # DLQ for agent observability consumer (OMN-2959 — fixed from invalid f"{topic}-dlq")
    AGENT_OBSERVABILITY_DLQ = "onex.evt.omniclaude.agent-observability-dlq.v1"

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
    # Decision store event bus topics (OMN-2766)
    # ==========================================================================
    DECISION_RECORDED_EVT_OMNICLAUDE = "onex.evt.omniclaude.decision-recorded.v1"
    DECISION_STATUS_CHANGED_EVT = "onex.evt.omniclaude.decision-status-changed.v1"
    DECISION_CONFLICT_DETECTED_EVT = "onex.evt.omniclaude.decision-conflict-detected.v1"
    DECISION_CONFLICT_STATUS_CHANGED = (
        "onex.evt.omniclaude.decision-conflict-status-changed.v1"
    )

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
    QUIRK_SIGNAL_DETECTED = "onex.evt.omniclaude.quirk-signal-detected.v1"
    """Raw QuirkSignal emitted by NodeQuirkSignalExtractorEffect after detection."""

    QUIRK_FINDING_PRODUCED = "onex.evt.omniclaude.quirk-finding-produced.v1"
    """QuirkFinding emitted by NodeQuirkClassifierCompute after threshold is met."""

    # ==========================================================================
    # Skill lifecycle topics (OMN-2773)
    # Convention: event_type = dotted form, topic = dashed form.
    # ==========================================================================
    SKILL_STARTED = "onex.evt.omniclaude.skill-started.v1"
    """Emitted before skill dispatch; join key is run_id."""

    SKILL_COMPLETED = "onex.evt.omniclaude.skill-completed.v1"
    """Emitted after skill dispatch (success or failure); join key is run_id."""

    # ==========================================================================
    # Friction observation topics (OMN-5747)
    # ==========================================================================
    FRICTION_OBSERVED = "onex.evt.omniclaude.friction-observed.v1"
    """Contract-driven friction classification output; partition key is session_id."""

    # ==========================================================================
    # Wave 2 pipeline observability topics (OMN-2922)
    # Consumed by omnidash Wave 2 projection nodes.
    # ==========================================================================
    EPIC_RUN_UPDATED = "onex.evt.omniclaude.epic-run-updated.v1"
    """State update for an in-flight epic run (one row per run_id in epic_run_lease)."""

    PR_WATCH_UPDATED = "onex.evt.omniclaude.pr-watch-updated.v1"
    """State update for an in-flight pr-watch session (one row per run_id in pr_watch_state)."""

    GATE_DECISION = "onex.evt.omniclaude.gate-decision.v1"
    """Append-only gate outcome (ACCEPTED, REJECTED, TIMEOUT) emitted by slack-gate."""

    BUDGET_CAP_HIT = "onex.evt.omniclaude.budget-cap-hit.v1"
    """Emitted when the token budget threshold is exceeded during context injection."""

    CIRCUIT_BREAKER_TRIPPED = "onex.evt.omniclaude.circuit-breaker-tripped.v1"
    """Emitted when the Kafka circuit breaker transitions to OPEN state."""

    # ==========================================================================
    # PR changeset and outcome topics (OMN-3138)
    # Delta Intelligence Phase 0 — emitted by pr-queue-pipeline for downstream
    # contract change tracking and merge gate decisions.
    # ==========================================================================
    PR_CHANGESET_CREATED = "onex.evt.omniclaude.pr-changeset-created.v1"
    """Emitted on PR open/update with detected contract changes."""

    MERGE_GATE_DECISION = "onex.evt.omniclaude.merge-gate-decision.v1"
    """Emitted with Tier A gate check results for contract changes."""

    PR_OUTCOME = "onex.evt.omniclaude.pr-outcome.v1"
    """Emitted after merge or revert detected for a tracked PR."""

    # ==========================================================================
    # PR validation rollup topics (OMN-3930 - MEI pipeline measurement)
    # ==========================================================================
    PR_VALIDATION_ROLLUP = "onex.evt.omniclaude.pr-validation-rollup.v1"
    """Emitted at pipeline completion with aggregated validation tax metrics and VTS."""

    # ==========================================================================
    # Correlation trace topics (OMN-5047)
    # Consumed by omnidash /trace page via correlation_trace_spans table.
    # ==========================================================================
    CORRELATION_TRACE = "onex.evt.omniclaude.correlation-trace.v1"
    """Trace span event emitted during active sessions for omnidash /trace page."""

    # ==========================================================================
    # DoD (Definition of Done) telemetry topics (OMN-5197)
    # Consumed by omnidash /dod dashboard via dod_verify_runs and
    # dod_guard_events tables.
    # ==========================================================================
    DOD_VERIFY_COMPLETED = "onex.evt.omniclaude.dod-verify-completed.v1"
    """Emitted after every DoD evidence verification run."""

    DOD_GUARD_FIRED = "onex.evt.omniclaude.dod-guard-fired.v1"
    """Emitted on every DoD guard interception (pre-tool-use hook)."""

    # ==========================================================================
    # Context integrity audit topics (OMN-5230)
    # Emitted by audit hooks for dispatch validation, scope enforcement,
    # budget tracking, return path control, and compression lifecycle.
    # ==========================================================================
    AUDIT_DISPATCH_VALIDATED = "onex.evt.omniclaude.audit-dispatch-validated.v1"
    """Emitted when a task dispatch is validated against its contract."""

    AUDIT_SCOPE_VIOLATION = "onex.evt.omniclaude.audit-scope-violation.v1"
    """Emitted when a scope boundary violation is detected during execution."""

    AUDIT_CONTEXT_BUDGET_EXCEEDED = (
        "onex.evt.omniclaude.audit-context-budget-exceeded.v1"
    )
    """Emitted when context budget usage is tracked or exceeded."""

    AUDIT_RETURN_BOUNDED = "onex.evt.omniclaude.audit-return-bounded.v1"
    """Emitted when return path size is evaluated against constraints."""

    AUDIT_COMPRESSION_TRIGGERED = "onex.evt.omniclaude.audit-compression-triggered.v1"
    """Emitted when context compression is triggered by budget or time limits."""

    AUDIT_RUN_REQUESTED = "onex.cmd.omniclaude.audit-run-requested.v1"
    """Command requesting an on-demand audit run for a session or task tree."""

    AUDIT_RUN_COMPLETED = "onex.evt.omniclaude.audit-run-completed.v1"
    """Emitted when an on-demand audit run completes with summary results."""

    # ==========================================================================
    # Validator catch topics (OMN-5549)
    # Emitted when a validator blocks or catches an issue during a session.
    # Consumed by the savings estimation pipeline for severity-weighted attribution.
    # ==========================================================================
    VALIDATOR_CATCH = "onex.evt.omniclaude.validator-catch.v1"
    """Emitted when a validator (poly-enforcer, bash-guard, pre-commit) catches an issue."""

    # ==========================================================================
    # Plan review topics (OMN-6128)
    # ==========================================================================
    PLAN_REVIEW_COMPLETED = "onex.evt.omniclaude.plan-review-completed.v1"
    """Emitted after hostile-reviewer convergence loop completes."""

    # ==========================================================================
    # Multi-model hostile reviewer topics (OMN-6188)
    # Emitted by aggregate_reviews.py on review completion or failure.
    # ==========================================================================
    HOSTILE_REVIEWER_COMPLETED = "onex.evt.omniclaude.hostile-reviewer-completed.v1"
    """Emitted when multi-model hostile review completes with aggregated findings."""

    HOSTILE_REVIEWER_FAILED = "onex.evt.omniclaude.hostile-reviewer-failed.v1"
    """Emitted when multi-model hostile review fails (no models produced results)."""


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


def build_topic(base: str) -> str:
    """Return the canonical topic name after validation.

    Since OMN-5212, the ``prefix`` parameter has been removed. All topics use
    canonical ONEX names with no environment prefix.

    Args:
        base: Canonical topic name from ``TopicBase``.

    Returns:
        The validated canonical topic name.

    Raises:
        ModelOnexError: If *base* is empty, None, whitespace-only, or malformed.

    Examples:
        >>> build_topic(TopicBase.SESSION_STARTED)
        'onex.evt.omniclaude.session-started.v1'
    """
    base = _validate_topic_segment(base, "base")
    _validate_topic_name(base)
    return base
