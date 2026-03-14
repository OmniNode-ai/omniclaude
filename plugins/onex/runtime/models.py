# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic models for the skill bootstrapper runtime.

SkillContext and SkillResult are the typed input/output contracts for skill
invocation through the bootstrapper. Error classes provide structured failure
reporting with actionable messages.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillContext(BaseModel):
    """Context passed to a skill handler at invocation time."""

    session_id: str = Field(description="Claude Code session identifier")
    skill_name: str = Field(description="Canonical skill name (e.g., ci-watch)")
    invocation_id: str = Field(description="Unique per-invocation UUID (dedup key)")
    working_directory: str = Field(description="CWD at invocation time")
    ticket_id: str | None = Field(
        default=None, description="Linear ticket if invoked from a pipeline"
    )
    worktree_path: str | None = Field(
        default=None, description="Git worktree path if applicable"
    )

    model_config = {"frozen": True, "extra": "ignore"}


class SkillResult(BaseModel):
    """Structured result returned by the bootstrapper after skill execution.

    The bootstrapper owns construction of this model. Handlers return raw
    ``dict[str, Any]`` which the bootstrapper wraps into ``output``.
    """

    success: bool = Field(description="Whether the skill completed without error")
    skill_name: str = Field(description="Echoes the invoked skill name")
    invocation_id: str = Field(description="Echoes the invocation UUID")
    output: dict[str, Any] = Field(
        default_factory=dict,
        description="Handler-produced structured output (never None, empty dict on error)",
    )
    error: str | None = Field(
        default=None, description="Error message if success=False"
    )
    error_type: str | None = Field(
        default=None, description="Error class name (e.g., SkillNotFoundError)"
    )
    duration_ms: int = Field(default=0, description="Wall-clock execution time")
    handler_used: str | None = Field(
        default=None, description="Handler class name that executed"
    )
    runtime_mode: str = Field(
        default="skill-bootstrapper",
        description='Runtime mode: "skill-bootstrapper" or "mcp"',
    )

    model_config = {"frozen": True, "extra": "ignore"}


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class SkillNotFoundError(Exception):
    """Raised when invoke() receives a skill_name that is not registered."""


class SkillInputValidationError(Exception):
    """Raised when inputs fail schema validation before handler dispatch."""


class SkillConfigurationError(Exception):
    """Raised when handler resolution fails (e.g., unsupported runtime value)."""


class SkillExecutionError(Exception):
    """Raised when a handler raises during execution."""
