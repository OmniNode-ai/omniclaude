# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Watchdog loop health reducer — pure function: state + event -> new state + intents.

This is the permanent reducer logic for the watchdog system. The dispatch surface
changes (file-based shell scripts now, ONEX node handler later), but this reducer
function moves unchanged into node_watchdog_reducer when the time comes.

Architecture:
    reduce(state, event, policy) -> (new_state, intents)

    - State: ModelWatchdogState — the full persisted state (loop-health.json)
    - Event: ModelWatchdogEvent — a thing that happened (run completed, action taken)
    - Intent: typed output objects the caller must execute (restart, investigate, etc.)
    - Policy: ModelEscalationPolicy — declarative config loaded from YAML

The reducer is PURE — no I/O, no timestamps, no UUIDs. The caller injects those.
This makes the reducer deterministic and trivially testable.

Shell dispatch (current):
    state = load_state(state_dir)
    new_state, intents = reduce(state, event, policy)
    save_state(new_state, state_dir)
    for intent in intents: execute_intent(intent)  # restart, create ticket, etc.

ONEX node dispatch (future):
    # Same reduce() call, but state comes from event store and intents become Kafka events.
    handler(state, event) -> reduce(state, event, policy) -> (new_state, intents)

Usage:
    from omniclaude.shared.models.model_watchdog_state import (
        reduce,
        ModelWatchdogState,
        ModelWatchdogEvent,
        load_policy,
        load_state,
        save_state,
    )

    state = load_state(state_dir)
    event = ModelWatchdogEvent(
        kind="run_completed",
        loop="closeout",
        result="fail",
        phase="B1_runtime_sweep",
        error_message="PostgreSQL unreachable",
        timestamp="2026-04-02T20:00:00Z",
        correlation_id="abc-123",
    )
    new_state, intents = reduce(state, event, policy)
    save_state(new_state, state_dir)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EnumWatchdogAction(StrEnum):
    """Escalation action — becomes a Kafka event type in node dispatch."""

    RESTART = "restart"
    INVESTIGATE = "investigate"
    FIX = "fix"
    TICKET = "ticket"
    ALERT_USER = "alert_user"


class EnumWatchdogFsmState(StrEnum):
    """FSM states for the watchdog reducer."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVESTIGATING = "investigating"
    FIXING = "fixing"
    TICKETED = "ticketed"
    BLOCKED = "blocked"


class EnumRunResult(StrEnum):
    """Result of a single loop run."""

    PASS = "pass"  # noqa: S105
    FAIL = "fail"


class EnumWatchdogEventKind(StrEnum):
    """Event types the reducer accepts."""

    RUN_COMPLETED = "run_completed"
    ACTION_TAKEN = "action_taken"


# ---------------------------------------------------------------------------
# Event model (input to the reducer)
# ---------------------------------------------------------------------------


class ModelWatchdogEvent(BaseModel):
    """An event fed into the reducer. Caller constructs this with real timestamps/IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EnumWatchdogEventKind
    loop: str = Field(..., description="Loop name: 'closeout' or 'buildloop'.")
    timestamp: str = Field(
        ..., description="ISO 8601 UTC timestamp, injected by caller."
    )
    correlation_id: str = Field(
        ..., description="Unique ID for this event, injected by caller."
    )

    # Fields for run_completed events
    result: EnumRunResult | None = Field(default=None)
    phase: str | None = Field(
        default=None, description="Phase that failed, or 'complete'."
    )
    error_message: str | None = Field(default=None)

    # Fields for action_taken events
    action: str | None = Field(default=None)
    detail: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Intent models (output from the reducer — caller executes these)
# ---------------------------------------------------------------------------


class ModelWatchdogIntent(BaseModel):
    """Base intent emitted by the reducer. Becomes a Kafka event in node dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_type: str
    loop: str
    correlation_id: str


class IntentRestart(ModelWatchdogIntent):
    """Restart the loop — transient failure, try again."""

    intent_type: str = "restart"


class IntentInvestigate(ModelWatchdogIntent):
    """Investigate root cause — read logs, check state."""

    intent_type: str = "investigate"
    failing_phase: str
    consecutive_failures: int
    last_error: str | None


class IntentFix(ModelWatchdogIntent):
    """Attempt to fix — edit config, clear stale state."""

    intent_type: str = "fix"
    failing_phase: str
    consecutive_failures: int
    last_error: str | None


class IntentCreateTicket(ModelWatchdogIntent):
    """Create a Linear ticket for manual investigation."""

    intent_type: str = "create_ticket"
    failing_phase: str
    consecutive_failures: int
    last_error: str | None


class IntentAlertUser(ModelWatchdogIntent):
    """STOP — do not restart. Alert the user immediately."""

    intent_type: str = "alert_user"
    failing_phase: str
    consecutive_failures: int
    last_error: str | None
    reason: str


class IntentNoOp(ModelWatchdogIntent):
    """No action needed — system is healthy or event was informational."""

    intent_type: str = "noop"


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------


class ModelWatchdogRunRecord(BaseModel):
    """A single run result in the state history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result: EnumRunResult
    phase: str
    error_message: str | None = None
    timestamp: str
    correlation_id: str


class ModelWatchdogActionRecord(BaseModel):
    """An action taken, recorded in state for audit trail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    detail: str = Field(..., max_length=200)
    timestamp: str


class ModelWatchdogLoopState(BaseModel):
    """State for a single loop (closeout or buildloop)."""

    model_config = ConfigDict(extra="forbid")

    runs: list[ModelWatchdogRunRecord] = Field(default_factory=list)
    failure_streaks: dict[str, int] = Field(default_factory=dict)
    escalation_level: int = Field(default=0, ge=0, le=5)
    actions_taken: list[ModelWatchdogActionRecord] = Field(default_factory=list)
    fsm_state: EnumWatchdogFsmState = Field(default=EnumWatchdogFsmState.HEALTHY)


class ModelWatchdogState(BaseModel):
    """Top-level watchdog state. This IS the node's state model."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    loops: dict[str, ModelWatchdogLoopState] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy models
# ---------------------------------------------------------------------------


class ModelEscalationLevel(BaseModel):
    """A single level in the escalation policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: int
    min_streak: int
    max_streak: int
    action: EnumWatchdogAction
    exit_code: int
    description: str


class ModelEscalationPolicy(BaseModel):
    """Declarative escalation policy loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    escalation_levels: list[ModelEscalationLevel] = Field(default_factory=list)
    fsm_transitions: dict[str, dict[str, str]] = Field(default_factory=dict)
    max_history: int = 20
    max_actions: int = 20


# ---------------------------------------------------------------------------
# Check result (for shell script compatibility — wraps intent + context)
# ---------------------------------------------------------------------------


class ModelWatchdogCheckResult(BaseModel):
    """Structured result for shell script callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: EnumWatchdogAction
    level: int
    exit_code: int
    reason: str
    loop: str
    top_failing_phase: str
    consecutive_failures: int
    last_error: str | None
    last_run: str | None
    fsm_state: EnumWatchdogFsmState


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "watchdog-escalation-policy.yaml"
)

_FALLBACK_LEVELS = [
    ModelEscalationLevel(
        level=0,
        min_streak=0,
        max_streak=0,
        action=EnumWatchdogAction.RESTART,
        exit_code=0,
        description="No failures",
    ),
    ModelEscalationLevel(
        level=1,
        min_streak=1,
        max_streak=1,
        action=EnumWatchdogAction.RESTART,
        exit_code=0,
        description="Single failure",
    ),
    ModelEscalationLevel(
        level=2,
        min_streak=2,
        max_streak=2,
        action=EnumWatchdogAction.INVESTIGATE,
        exit_code=2,
        description="Two identical failures",
    ),
    ModelEscalationLevel(
        level=3,
        min_streak=3,
        max_streak=3,
        action=EnumWatchdogAction.FIX,
        exit_code=3,
        description="Three identical failures",
    ),
    ModelEscalationLevel(
        level=4,
        min_streak=4,
        max_streak=4,
        action=EnumWatchdogAction.TICKET,
        exit_code=4,
        description="Four identical failures",
    ),
    ModelEscalationLevel(
        level=5,
        min_streak=5,
        max_streak=999,
        action=EnumWatchdogAction.ALERT_USER,
        exit_code=5,
        description="Five+ identical failures",
    ),
]

_FALLBACK_FSM = {
    "healthy": {"on_pass": "healthy", "on_fail": "degraded"},
    "degraded": {"on_pass": "healthy", "on_fail": "investigating"},
    "investigating": {"on_pass": "healthy", "on_fail": "fixing"},
    "fixing": {"on_pass": "healthy", "on_fail": "ticketed"},
    "ticketed": {"on_pass": "healthy", "on_fail": "blocked"},
    "blocked": {"on_pass": "healthy", "on_fail": "blocked"},
}


def load_policy(policy_path: Path | None = None) -> ModelEscalationPolicy:
    """Load the escalation policy from YAML. Falls back to hardcoded defaults."""
    path = policy_path or _DEFAULT_POLICY_PATH
    if path.exists():
        raw = yaml.safe_load(path.read_text())
        return ModelEscalationPolicy.model_validate(raw)
    return ModelEscalationPolicy(
        escalation_levels=list(_FALLBACK_LEVELS),
        fsm_transitions=dict(_FALLBACK_FSM),
    )


# ---------------------------------------------------------------------------
# Pure reducer — THE core logic. No I/O, no side effects.
# ---------------------------------------------------------------------------


def _ensure_loop(state: ModelWatchdogState, loop_name: str) -> ModelWatchdogLoopState:
    """Get or create a loop state entry. Mutates state."""
    if loop_name not in state.loops:
        state.loops[loop_name] = ModelWatchdogLoopState()
    return state.loops[loop_name]


def _advance_fsm(
    current: EnumWatchdogFsmState,
    fsm_event: str,
    policy: ModelEscalationPolicy,
) -> EnumWatchdogFsmState:
    """Advance the FSM state. Pure."""
    transitions = policy.fsm_transitions.get(current.value, {})
    next_state = transitions.get(fsm_event, current.value)
    try:
        return EnumWatchdogFsmState(next_state)
    except ValueError:
        return current


def _action_for_streak(
    policy: ModelEscalationPolicy, streak: int
) -> ModelEscalationLevel:
    """Find the escalation level for a given streak count. Pure."""
    for level_def in reversed(policy.escalation_levels):
        if level_def.min_streak <= streak <= level_def.max_streak:
            return level_def
    return policy.escalation_levels[-1]


def _top_streak(loop: ModelWatchdogLoopState) -> tuple[str, int]:
    """Find the phase with the highest failure streak. Pure."""
    top_phase = "none"
    top_count = 0
    for phase, count in loop.failure_streaks.items():
        if count > top_count:
            top_phase = phase
            top_count = count
    return top_phase, top_count


def _build_intent(
    level_def: ModelEscalationLevel,
    loop_name: str,
    correlation_id: str,
    failing_phase: str,
    consecutive_failures: int,
    last_error: str | None,
) -> ModelWatchdogIntent:
    """Build the appropriate intent for an escalation level. Pure."""
    base = {"loop": loop_name, "correlation_id": correlation_id}

    if level_def.action == EnumWatchdogAction.RESTART:
        return IntentRestart(**base)

    if level_def.action == EnumWatchdogAction.INVESTIGATE:
        return IntentInvestigate(
            **base,
            failing_phase=failing_phase,
            consecutive_failures=consecutive_failures,
            last_error=last_error,
        )

    if level_def.action == EnumWatchdogAction.FIX:
        return IntentFix(
            **base,
            failing_phase=failing_phase,
            consecutive_failures=consecutive_failures,
            last_error=last_error,
        )

    if level_def.action == EnumWatchdogAction.TICKET:
        return IntentCreateTicket(
            **base,
            failing_phase=failing_phase,
            consecutive_failures=consecutive_failures,
            last_error=last_error,
        )

    # ALERT_USER or unknown
    return IntentAlertUser(
        **base,
        failing_phase=failing_phase,
        consecutive_failures=consecutive_failures,
        last_error=last_error,
        reason=f"Phase '{failing_phase}' has failed {consecutive_failures} times. {level_def.description}.",
    )


def reduce(
    state: ModelWatchdogState,
    event: ModelWatchdogEvent,
    policy: ModelEscalationPolicy,
) -> tuple[ModelWatchdogState, list[ModelWatchdogIntent]]:
    """Pure reducer: state + event -> (new_state, intents).

    No I/O, no timestamps, no UUIDs — all injected via the event.
    This function moves unchanged into node_watchdog_reducer.

    Returns:
        (new_state, intents) — caller persists state and executes intents.
    """
    loop = _ensure_loop(state, event.loop)
    intents: list[ModelWatchdogIntent] = []

    if event.kind == EnumWatchdogEventKind.RUN_COMPLETED:
        assert event.result is not None, "run_completed event must have a result"
        assert event.phase is not None, "run_completed event must have a phase"

        # Record the run
        run = ModelWatchdogRunRecord(
            result=event.result,
            phase=event.phase,
            error_message=event.error_message[:200] if event.error_message else None,
            timestamp=event.timestamp,
            correlation_id=event.correlation_id,
        )
        loop.runs = [run, *loop.runs][: policy.max_history]

        # Update streaks and FSM
        if event.result == EnumRunResult.FAIL:
            loop.failure_streaks[event.phase] = (
                loop.failure_streaks.get(event.phase, 0) + 1
            )
            max_streak = max(loop.failure_streaks.values(), default=0)
            loop.escalation_level = min(max_streak, 5)
            loop.fsm_state = _advance_fsm(loop.fsm_state, "on_fail", policy)

            # Emit escalation intent
            top_phase, top_count = _top_streak(loop)
            level_def = _action_for_streak(policy, top_count)
            intents.append(
                _build_intent(
                    level_def,
                    event.loop,
                    event.correlation_id,
                    top_phase,
                    top_count,
                    event.error_message,
                )
            )
        else:
            # Success resets everything
            loop.failure_streaks = {}
            loop.escalation_level = 0
            loop.fsm_state = _advance_fsm(loop.fsm_state, "on_pass", policy)
            # No intent on success — system is healthy

    elif event.kind == EnumWatchdogEventKind.ACTION_TAKEN:
        assert event.action is not None, "action_taken event must have an action"
        assert event.detail is not None, "action_taken event must have a detail"

        record = ModelWatchdogActionRecord(
            action=event.action,
            detail=event.detail[:200],
            timestamp=event.timestamp,
        )
        loop.actions_taken = [record, *loop.actions_taken][: policy.max_actions]
        # No intent for action recording — it's an acknowledgement

    return state, intents


# ---------------------------------------------------------------------------
# Convenience: check_escalation (reads current state without mutating)
# ---------------------------------------------------------------------------


def check_escalation(
    state: ModelWatchdogState,
    loop_name: str,
    *,
    policy: ModelEscalationPolicy | None = None,
) -> ModelWatchdogCheckResult:
    """Check escalation for a loop. Does NOT mutate state.

    This is a read-only query used by shell scripts (watchdog-check.sh).
    """
    if policy is None:
        policy = load_policy()

    loop = _ensure_loop(state, loop_name)
    top_phase, top_count = _top_streak(loop)
    level_def = _action_for_streak(policy, top_count)

    last_error = None
    last_run_ts = None
    if loop.runs:
        last_run_ts = loop.runs[0].timestamp
        if loop.runs[0].result == EnumRunResult.FAIL:
            last_error = loop.runs[0].error_message

    reason = level_def.description
    if top_count > 0:
        reason = f"Phase '{top_phase}' has failed {top_count} times consecutively. {level_def.description}. Last error: {last_error or 'unknown'}"

    return ModelWatchdogCheckResult(
        action=level_def.action,
        level=level_def.level,
        exit_code=level_def.exit_code,
        reason=reason,
        loop=loop_name,
        top_failing_phase=top_phase,
        consecutive_failures=top_count,
        last_error=last_error,
        last_run=last_run_ts,
        fsm_state=loop.fsm_state,
    )


# ---------------------------------------------------------------------------
# State file I/O (thin shell — not part of the reducer)
# ---------------------------------------------------------------------------

STATE_FILENAME = "loop-health.json"


def load_state(state_dir: Path) -> ModelWatchdogState:
    """Load watchdog state from disk. Returns empty state if missing or corrupt."""
    state_file = state_dir / STATE_FILENAME
    if not state_file.exists():
        return ModelWatchdogState()
    try:
        raw = json.loads(state_file.read_text())
        return ModelWatchdogState.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        corrupt_path = state_file.with_suffix(".corrupt.json")
        state_file.rename(corrupt_path)
        return ModelWatchdogState()


def save_state(state: ModelWatchdogState, state_dir: Path) -> Path:
    """Write watchdog state to disk atomically."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / STATE_FILENAME
    temp_file = state_file.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    temp_file.write_text(json.dumps(state.model_dump(mode="json"), indent=2) + "\n")
    temp_file.rename(state_file)
    return state_file


# ---------------------------------------------------------------------------
# Convenience wrappers (backward compat + shell script callers)
# ---------------------------------------------------------------------------


def record_run(
    state: ModelWatchdogState,
    loop_name: str,
    result: str,
    phase: str,
    error_message: str | None = None,
    *,
    policy: ModelEscalationPolicy | None = None,
    correlation_id: str | None = None,
) -> ModelWatchdogState:
    """Convenience wrapper: build event + reduce. Returns mutated state."""
    if policy is None:
        policy = load_policy()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.RUN_COMPLETED,
        loop=loop_name,
        result=EnumRunResult(result),
        phase=phase,
        error_message=error_message,
        timestamp=ts,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )
    new_state, _intents = reduce(state, event, policy)
    return new_state


def record_action(
    state: ModelWatchdogState,
    loop_name: str,
    action: str,
    detail: str,
    *,
    policy: ModelEscalationPolicy | None = None,
) -> ModelWatchdogState:
    """Convenience wrapper: build event + reduce. Returns mutated state."""
    if policy is None:
        policy = load_policy()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.ACTION_TAKEN,
        loop=loop_name,
        action=action,
        detail=detail,
        timestamp=ts,
        correlation_id=str(uuid.uuid4()),
    )
    new_state, _intents = reduce(state, event, policy)
    return new_state


__all__ = [
    "EnumRunResult",
    "EnumWatchdogAction",
    "EnumWatchdogEventKind",
    "EnumWatchdogFsmState",
    "IntentAlertUser",
    "IntentCreateTicket",
    "IntentFix",
    "IntentInvestigate",
    "IntentNoOp",
    "IntentRestart",
    "ModelEscalationLevel",
    "ModelEscalationPolicy",
    "ModelWatchdogActionRecord",
    "ModelWatchdogCheckResult",
    "ModelWatchdogEvent",
    "ModelWatchdogIntent",
    "ModelWatchdogLoopState",
    "ModelWatchdogRunRecord",
    "ModelWatchdogState",
    "check_escalation",
    "load_policy",
    "load_state",
    "record_action",
    "record_run",
    "reduce",
    "save_state",
]
