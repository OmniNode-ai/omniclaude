# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill lifecycle event models for OMN-2773.

Emitted by handle_skill_requested() on every skill invocation.
``run_id`` is the join key: started and completed for the same invocation
share the same ``run_id`` and are guaranteed to land on the same Kafka
partition (partition_key_field="run_id" in the event registry).

Topics:
    onex.evt.omniclaude.skill-started.v1
    onex.evt.omniclaude.skill-completed.v1
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelSkillStartedEvent(BaseModel):
    """Emitted before task_dispatcher() is called for a skill invocation.

    Attributes:
        event_id: Unique ID for this event (handler is authoritative).
        run_id: Shared with the corresponding completed event — join key.
        skill_name: Human-readable skill identifier (e.g. "pr-review").
        skill_id: Repo-relative skill path (e.g. "plugins/onex/skills/pipeline-metrics").
        repo_id: Repository identifier (e.g. "omniclaude") — prevents cross-repo collisions.
        correlation_id: End-to-end correlation ID from the originating request.
        args_count: Count of args provided (not values — privacy).
        emitted_at: UTC timestamp when the event was emitted.
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    run_id: UUID
    skill_name: str
    skill_id: str
    repo_id: str
    correlation_id: UUID
    args_count: int
    emitted_at: datetime
    session_id: str | None = None


class ModelSkillCompletedEvent(BaseModel):
    """Emitted after task_dispatcher() returns (or raises) for a skill invocation.

    Attributes:
        event_id: Unique ID for this event.
        run_id: Shared with the corresponding started event — join key.
        skill_name: Human-readable skill identifier matching the started event.
        repo_id: Repository identifier — prevents cross-repo collisions.
        correlation_id: End-to-end correlation ID from the originating request.
        status: Outcome — exactly one of "success", "failed", "partial". Locked
            to prevent string drift in consumers.
        duration_ms: Wall-clock duration from perf_counter(); NTP-immune.
        error_type: Exception class name if task_dispatcher raised, else None.
        started_emit_failed: True if the skill.started emission failed.
            Consumers can use this to detect orphaned completed events.
        emitted_at: UTC timestamp when the event was emitted.
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    run_id: UUID
    skill_name: str
    repo_id: str
    correlation_id: UUID
    status: Literal["success", "failed", "partial"]
    duration_ms: int
    error_type: str | None = None
    started_emit_failed: bool = False
    emitted_at: datetime
    session_id: str | None = None


__all__ = [
    "ModelSkillStartedEvent",
    "ModelSkillCompletedEvent",
]
