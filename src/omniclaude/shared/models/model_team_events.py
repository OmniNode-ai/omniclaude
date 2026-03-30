# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unified event schema for all dispatch surfaces (System 6).

Every event carries dispatch_surface and agent_model so omnidash
can show a unified timeline regardless of which surface produced it.

Topics:
    onex.evt.omniclaude.team-task-assigned.v1    (event table, append-only)
    onex.evt.omniclaude.team-task-progress.v1    (event table, append-only)
    onex.evt.omniclaude.team-evidence-written.v1 (event table, append-only)
    onex.evt.omniclaude.team-task-completed.v1   (event table, append-only)

All models use frozen=True, extra="ignore", from_attributes=True. emitted_at
is explicitly injected by the emitter (never auto-populated at deserialization
time).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelTeamEventBase(BaseModel):
    """Base fields for all team lifecycle events."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    task_id: str
    session_id: str
    correlation_id: str
    dispatch_surface: str = Field(
        description="team_worker | headless_claude | local_llm"
    )
    agent_model: str = Field(
        description="claude-opus-4-6 | qwen3-14b | deepseek-r1 | etc."
    )
    emitted_at: datetime


class ModelTaskAssignedEvent(ModelTeamEventBase):
    """Emitted when a task is assigned to an agent on any dispatch surface."""

    agent_name: str
    team_name: str | None = None
    contract_path: str | None = None


class ModelTaskProgressEvent(ModelTeamEventBase):
    """Emitted at phase transitions during task execution."""

    phase: str
    checkpoint_path: str | None = None
    message: str = ""


class ModelEvidenceWrittenEvent(ModelTeamEventBase):
    """Emitted when an evidence artifact is persisted to disk."""

    evidence_type: str = Field(description="self_check | verifier | tiebreaker")
    evidence_path: str
    passed: bool


class ModelTaskCompletedEvent(ModelTeamEventBase):
    """Emitted when a task reaches a terminal state with a verification verdict."""

    verification_verdict: str = Field(description="PASS | FAIL | ESCALATE")
    evidence_path: str | None = None
    token_usage: int | None = None


__all__ = [
    "ModelTeamEventBase",
    "ModelTaskAssignedEvent",
    "ModelTaskProgressEvent",
    "ModelEvidenceWrittenEvent",
    "ModelTaskCompletedEvent",
]
