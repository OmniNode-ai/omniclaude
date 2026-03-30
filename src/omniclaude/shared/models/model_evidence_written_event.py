# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Evidence written event — emitted when an evidence artifact is persisted.

Topic: onex.evt.omniclaude.team-evidence-written.v1 (event table, append-only)
"""

from __future__ import annotations

from pydantic import Field

from omniclaude.shared.models.model_team_events import ModelTeamEventBase


class ModelEvidenceWrittenEvent(ModelTeamEventBase):
    """Emitted when an evidence artifact is persisted to disk."""

    evidence_type: str = Field(description="self_check | verifier | tiebreaker")
    evidence_path: str
    passed: bool


__all__ = [
    "ModelEvidenceWrittenEvent",
]
