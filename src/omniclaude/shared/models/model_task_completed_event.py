# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Task completed event — emitted when a task reaches a terminal state.

Topic: onex.evt.omniclaude.team-task-completed.v1 (event table, append-only)
"""

from __future__ import annotations

from pydantic import Field

from omniclaude.shared.models.model_team_events import ModelTeamEventBase


class ModelTaskCompletedEvent(ModelTeamEventBase):
    """Emitted when a task reaches a terminal state with a verification verdict."""

    verification_verdict: str = Field(description="PASS | FAIL | ESCALATE")
    evidence_path: str | None = None
    token_usage: int | None = None


__all__ = [
    "ModelTaskCompletedEvent",
]
