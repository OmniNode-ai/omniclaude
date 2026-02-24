# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Git operation request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GitOperation(StrEnum):
    """Supported git operations."""

    BRANCH_CREATE = "branch_create"
    COMMIT = "commit"
    PUSH = "push"
    PR_CREATE = "pr_create"
    PR_UPDATE = "pr_update"
    PR_CLOSE = "pr_close"


class ModelGitRequest(BaseModel):
    """Input model for git operation requests.

    Attributes:
        operation: The git operation to perform.
        branch_name: Branch name (for branch_create, push).
        base_ref: Base ref for branch creation (for branch_create).
        commit_message: Commit message (for commit).
        force_push: Whether to force push (for push).
        pr_title: Pull request title (for pr_create, pr_update).
        pr_body: Pull request body (for pr_create, pr_update).
        pr_number: Pull request number (for pr_update, pr_close).
        ticket_id: Linear ticket ID for PR stamp block (for pr_create).
        base_branch: Base branch for PR (for pr_create).
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: GitOperation = Field(
        ...,
        description="The git operation to perform",
    )
    branch_name: str | None = Field(
        default=None,
        description="Branch name for branch_create or push",
    )
    base_ref: str | None = Field(
        default=None,
        description="Base ref for branch creation",
    )
    commit_message: str | None = Field(
        default=None,
        description="Commit message for commit operation",
    )
    force_push: bool = Field(
        default=False,
        description="Whether to force push",
    )
    pr_title: str | None = Field(
        default=None,
        description="Pull request title",
    )
    pr_body: str | None = Field(
        default=None,
        description="Pull request body",
    )
    pr_number: int | None = Field(
        default=None,
        description="Pull request number for update/close",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Linear ticket ID for mandatory PR stamp block",
    )
    base_branch: str | None = Field(
        default=None,
        description="Base branch for pull request creation",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["GitOperation", "ModelGitRequest"]
