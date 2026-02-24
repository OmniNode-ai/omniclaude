# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Git operation result model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GitResultStatus(StrEnum):
    """Possible outcomes of a git operation."""

    SUCCESS = "success"
    FAILED = "failed"


class ModelGitResult(BaseModel):
    """Output model for git operation results.

    Attributes:
        operation: The git operation that was performed.
        status: Final status of the operation.
        output: Raw stdout output from the git command.
        error: Error detail when status is FAILED.
        pr_url: Pull request URL (populated for pr_create).
        pr_number: Pull request number (populated for pr_create).
        correlation_id: Correlation ID carried through from the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str = Field(
        ...,
        description="The git operation that was performed",
    )
    status: GitResultStatus = Field(
        ...,
        description="Final status of the operation",
    )
    output: str | None = Field(
        default=None,
        description="Raw stdout output from the git command",
    )
    error: str | None = Field(
        default=None,
        description="Error detail when status is FAILED",
    )
    pr_url: str | None = Field(
        default=None,
        description="Pull request URL (populated for pr_create)",
    )
    pr_number: int | None = Field(
        default=None,
        description="Pull request number (populated for pr_create)",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID carried through from the request",
    )


__all__ = ["GitResultStatus", "ModelGitResult"]
