# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation command model — inbound request to the orchestrator.

Consumed from ``onex.cmd.omniclaude.delegate-task.v1``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelDelegationCommand(BaseModel):
    """Inbound delegation request from the user-prompt-submit hook."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    prompt: str = Field(..., min_length=1, description="User prompt to delegate")
    correlation_id: str = Field(default="", description="Correlation ID for tracing")
    session_id: str = Field(default="", description="Claude Code session ID")
    prompt_length: int = Field(default=0, ge=0, description="Original prompt length")
    recipient: Literal["auto", "claude", "opencode", "codex"] = Field(
        default="auto",
        description="Target CLI recipient; 'auto' preserves existing cost-cascade routing",
    )
    wait_for_result: bool = Field(
        default=False,
        description="Block originator until delegation-completed event received",
    )
    working_directory: Path | None = Field(
        default=None,
        description="Working directory for the CLI process; required when recipient != 'auto'",
    )
    codex_sandbox_mode: (
        Literal["read-only", "workspace-write", "danger-full-access"] | None
    ) = Field(
        default=None,
        description="Explicit codex sandbox override; None = auto-select from task_type",
    )

    @model_validator(mode="after")
    def _validate_recipient_constraints(self) -> ModelDelegationCommand:
        if self.recipient == "auto" and self.working_directory is not None:
            raise ValueError("working_directory must be None when recipient='auto'")
        return self


__all__ = ["ModelDelegationCommand"]
