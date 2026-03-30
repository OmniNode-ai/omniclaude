# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Task progress event — emitted at phase transitions during task execution.

Topic: onex.evt.omniclaude.team-task-progress.v1 (event table, append-only)
"""

from __future__ import annotations

from omniclaude.shared.models.model_team_events import ModelTeamEventBase


class ModelTaskProgressEvent(ModelTeamEventBase):
    """Emitted at phase transitions during task execution."""

    phase: str
    checkpoint_path: str | None = None
    message: str = ""


__all__ = [
    "ModelTaskProgressEvent",
]
