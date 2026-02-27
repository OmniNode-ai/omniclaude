# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Wave 2 pipeline observability event models for OMN-2922.

Five new pipeline event types consumed by omnidash Wave 2 projection nodes.

Topics:
    onex.evt.omniclaude.epic-run-updated.v1      (state table, upsert by run_id)
    onex.evt.omniclaude.pr-watch-updated.v1      (state table, upsert by run_id)
    onex.evt.omniclaude.gate-decision.v1         (event table, append-only)
    onex.evt.omniclaude.budget-cap-hit.v1        (state table, upsert by run_id)
    onex.evt.omniclaude.circuit-breaker-tripped.v1 (event table, append-only)

Storage semantics:
    State tables (one row per run_id):
        epic_run_lease        keyed by run_id
        pr_watch_state        keyed by run_id
        pipeline_budget_state keyed by run_id
    Event tables (append-only):
        gate_decisions        keyed by gate_id
        circuit_breaker_events keyed by event_id

Modeled after ModelSkillStartedEvent at model_skill_lifecycle_events.py:27-52.
All models use frozen=True, extra="ignore". emitted_at is explicitly injected
by the emitter (never auto-populated at deserialization time).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelEpicRunUpdatedEvent(BaseModel):
    """State update for an in-flight epic run.

    Emitted at each phase transition by the epic-team orchestrator.
    Consumers upsert into epic_run_lease keyed by run_id.

    Attributes:
        event_id: Unique ID for this event.
        run_id: Epic run identifier — upsert key for epic_run_lease.
        epic_id: Linear epic identifier (e.g. "OMN-2920").
        status: Current run status.
        phase: Current pipeline phase name (optional; not all transitions have a phase).
        tickets_total: Total tickets in this epic run.
        tickets_completed: Number of tickets completed so far.
        tickets_failed: Number of tickets that failed.
        correlation_id: End-to-end correlation identifier.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    run_id: UUID
    epic_id: str
    status: Literal["running", "completed", "failed", "partial", "cancelled"]
    phase: str | None = None
    tickets_total: int = 0
    tickets_completed: int = 0
    tickets_failed: int = 0
    correlation_id: UUID
    emitted_at: datetime
    session_id: str | None = None


class ModelPrWatchUpdatedEvent(BaseModel):
    """State update for an in-flight pr-watch session.

    Emitted at each poll cycle or terminal outcome by the pr-watch orchestrator.
    Consumers upsert into pr_watch_state keyed by run_id.

    Attributes:
        event_id: Unique ID for this event.
        run_id: PR watch run identifier — upsert key for pr_watch_state.
        pr_number: GitHub PR number.
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        ticket_id: Linear ticket identifier (e.g. "OMN-2922").
        status: Current watch status.
        review_cycles_used: Number of pr-review-dev fix cycles consumed.
        watch_duration_hours: Wall-clock hours elapsed since watch started.
        correlation_id: End-to-end correlation identifier.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    run_id: UUID
    pr_number: int
    repo: str
    ticket_id: str
    status: Literal["watching", "approved", "capped", "timeout", "failed"]
    review_cycles_used: int = 0
    watch_duration_hours: float = 0.0
    correlation_id: UUID
    emitted_at: datetime
    session_id: str | None = None


class ModelGateDecisionEvent(BaseModel):
    """Gate outcome emitted by the slack-gate skill.

    Emitted exactly once per gate invocation at each terminal outcome.
    Consumers append to gate_decisions keyed by gate_id (event table).

    Attributes:
        event_id: Unique ID for this event.
        gate_id: Unique identifier for the gate invocation.
        decision: Gate outcome — exactly one of ACCEPTED, REJECTED, TIMEOUT.
        ticket_id: Linear ticket identifier for which the gate was raised.
        gate_type: Gate risk level (HIGH_RISK, MEDIUM_RISK).
        wait_seconds: Wall-clock seconds from gate posting to decision.
        responder: Slack user who responded (None on TIMEOUT).
        correlation_id: End-to-end correlation identifier.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    gate_id: str
    decision: Literal["ACCEPTED", "REJECTED", "TIMEOUT"]
    ticket_id: str
    gate_type: Literal["HIGH_RISK", "MEDIUM_RISK"] = "HIGH_RISK"
    wait_seconds: float = 0.0
    responder: str | None = None
    correlation_id: UUID
    emitted_at: datetime
    session_id: str | None = None


class ModelBudgetCapHitEvent(BaseModel):
    """Emitted when the token budget threshold is exceeded during context injection.

    Consumers upsert into pipeline_budget_state keyed by run_id.
    Consumed by the omnidash /pipeline-budget view.

    Attributes:
        event_id: Unique ID for this event.
        run_id: Pipeline run identifier — upsert key for pipeline_budget_state.
        tokens_used: Actual tokens used at the time of cap.
        tokens_budget: Configured token budget limit.
        cap_reason: Human-readable reason for the cap (e.g. "max_tokens_injected exceeded").
        correlation_id: End-to-end correlation identifier.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    run_id: UUID
    tokens_used: int
    tokens_budget: int
    cap_reason: str = "max_tokens_injected exceeded"
    correlation_id: UUID
    emitted_at: datetime
    session_id: str | None = None


class ModelCircuitBreakerTrippedEvent(BaseModel):
    """Emitted when the Kafka circuit breaker transitions to OPEN state.

    Consumers append to circuit_breaker_events (event table, keyed by event_id).
    Provides visibility into Kafka connectivity issues during Claude Code sessions.

    Attributes:
        event_id: Unique ID for this event.
        session_id: Claude Code session identifier.
        failure_count: Number of consecutive failures that triggered the trip.
        threshold: Configured failure threshold.
        reset_timeout_seconds: Seconds until the breaker will attempt HALF_OPEN.
        last_error: String representation of the last error (if available).
        correlation_id: End-to-end correlation identifier.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    session_id: str
    failure_count: int
    threshold: int
    reset_timeout_seconds: float
    last_error: str | None = None
    correlation_id: UUID
    emitted_at: datetime


__all__ = [
    "ModelEpicRunUpdatedEvent",
    "ModelPrWatchUpdatedEvent",
    "ModelGateDecisionEvent",
    "ModelBudgetCapHitEvent",
    "ModelCircuitBreakerTrippedEvent",
]
