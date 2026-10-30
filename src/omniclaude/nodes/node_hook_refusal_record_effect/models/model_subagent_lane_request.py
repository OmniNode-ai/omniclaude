# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The facts a PreToolUse payload gives about a subagent (OMN-17942).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSubagentLaneRequest(BaseModel):
    """A subagent's identity operands and the environment that locates the ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(description="The payload's agent_id.")
    session_id: str = Field(default="", description="The parent harness session id.")
    transcript_path: str = Field(
        default="", description="The payload's (parent) transcript path."
    )
    agent_transcript_path: str = Field(
        default="",
        description="The agent's own transcript path, when the payload has it.",
    )
    environ: dict[str, str] = Field(
        default_factory=dict,
        description="ONEX_LEDGER_PATH, OMNI_HOME and the session-start state directories.",
    )
    allow_parent: bool = Field(
        default=True,
        description="Whether an interactive session's helper may use its parent session's lane.",
    )
