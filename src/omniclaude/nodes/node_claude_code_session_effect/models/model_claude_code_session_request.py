# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Claude Code session request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClaudeCodeSessionOperation(StrEnum):
    """Supported Claude Code session operations."""

    SESSION_START = "session_start"
    SESSION_QUERY = "session_query"
    SESSION_END = "session_end"


class ModelClaudeCodeSessionRequest(BaseModel):
    """Input model for Claude Code session operation requests.

    Attributes:
        operation: The session operation to perform.
        working_directory: Working directory for session_start.
        session_id: Session identifier for session_query and session_end.
        prompt: Prompt to submit for session_query.
        skill_name: Human-readable skill name for the ModelSkillResult envelope.
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: ClaudeCodeSessionOperation = Field(
        ...,
        description="The session operation to perform",
    )
    working_directory: str | None = Field(
        default=None,
        description="Working directory for session_start",
    )
    session_id: str | None = Field(
        default=None,
        description="Session identifier for session_query and session_end",
    )
    prompt: str | None = Field(
        default=None,
        description="Prompt to submit for session_query",
    )
    skill_name: str = Field(
        default="claude_code.session",
        min_length=1,
        description="Human-readable skill name for the ModelSkillResult envelope",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["ClaudeCodeSessionOperation", "ModelClaudeCodeSessionRequest"]
