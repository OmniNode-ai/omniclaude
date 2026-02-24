# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill result model - output from any skill dispatch node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SkillResultStatus(StrEnum):
    """Possible outcomes of a skill invocation."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class ModelSkillResult(BaseModel):
    """Output from any skill dispatch node.

    Captures the outcome of a single skill invocation, including the
    structured output (if any) and any error detail.

    Attributes:
        skill_name: Human-readable skill identifier matching the request.
        status: Final status of the skill invocation.
        output: Raw output text from the skill (None if not available).
        error: Error detail, typically populated when status is FAILED or PARTIAL.
        correlation_id: Correlation ID carried through from the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable skill identifier matching the request",
    )
    status: SkillResultStatus = Field(
        ...,
        description="Final status of the skill invocation",
    )
    output: str | None = Field(
        default=None,
        description="Raw output text from the skill",
    )
    error: str | None = Field(
        default=None,
        description="Error detail when status is FAILED or PARTIAL",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID carried through from the request",
    )


__all__ = ["ModelSkillResult", "SkillResultStatus"]
