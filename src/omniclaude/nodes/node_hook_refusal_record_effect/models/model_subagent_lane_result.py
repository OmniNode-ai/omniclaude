# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The lane a subagent's create is made as, or none (OMN-17942).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSubagentLaneResult(BaseModel):
    """``lane`` is empty when no fact confirmed one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lane: str = Field(default="", description="The resolved lane, or empty.")
    helper: str = Field(
        default="",
        description="The lane the sidecar or prompt named, kept when no CLAIM confirmed it.",
    )
    source: str = Field(
        default="",
        description="sidecar+claim, prompt+claim, parent-session+claim, or empty.",
    )
    parent_session_id: str = Field(
        default="", description="The parent session id, for the parent-session source."
    )
