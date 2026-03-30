# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Task assigned event — emitted when a task is assigned on any dispatch surface.

Topic: onex.evt.omniclaude.team-task-assigned.v1 (event table, append-only)
"""

from __future__ import annotations

from omniclaude.shared.models.model_team_events import ModelTeamEventBase


class ModelTaskAssignedEvent(ModelTeamEventBase):
    """Emitted when a task is assigned to an agent on any dispatch surface."""

    agent_name: str
    team_name: str | None = None
    contract_path: str | None = None


__all__ = [
    "ModelTaskAssignedEvent",
]
