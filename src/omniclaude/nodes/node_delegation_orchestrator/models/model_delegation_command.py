# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation command model — inbound request to the orchestrator.

Consumed from ``onex.cmd.omniclaude.delegate-task.v1``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelDelegationCommand(BaseModel):
    """Inbound delegation request from the user-prompt-submit hook.

    Attributes:
        prompt: The user prompt to delegate.
        correlation_id: Correlation ID for distributed tracing.
        session_id: Claude Code session ID.
        prompt_length: Length of the original prompt in characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    prompt: str = Field(..., min_length=1, description="User prompt to delegate")
    correlation_id: str = Field(default="", description="Correlation ID for tracing")
    session_id: str = Field(default="", description="Claude Code session ID")
    prompt_length: int = Field(default=0, ge=0, description="Original prompt length")


__all__ = ["ModelDelegationCommand"]
