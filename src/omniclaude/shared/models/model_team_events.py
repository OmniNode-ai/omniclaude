# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unified event schema base for all dispatch surfaces (System 6).

Every event carries dispatch_surface and agent_model so omnidash
can show a unified timeline regardless of which surface produced it.

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


__all__ = [
    "ModelTeamEventBase",
]
