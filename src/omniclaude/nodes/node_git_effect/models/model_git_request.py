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

    # Existing 6
    BRANCH_CREATE = "branch_create"
    COMMIT = "commit"
    PUSH = "push"
    PR_CREATE = "pr_create"
    PR_UPDATE = "pr_update"
    PR_CLOSE = "pr_close"
    # New 5 (OMN-2817)
    PR_MERGE = "pr_merge"
    PR_LIST = "pr_list"
    PR_VIEW = "pr_view"
    TAG_CREATE = "tag_create"
    LABEL_ADD = "label_add"


class ModelPRListFilters(BaseModel):
    """Typed filter model mapping directly to gh pr list flags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str | None = Field(
        default=None,
        description="--state open|closed|merged|all",
    )
    head: str | None = Field(
        default=None,
        description="--head branch-name",
    )
    base: str | None = Field(
        default=None,
        description="--base branch-name",
    )
    author: str | None = Field(
        default=None,
        description="--author username",
    )
    label: str | None = Field(
        default=None,
        description="--label label-name",
    )
    search: str | None = Field(
        default=None,
        description="--search query",
    )
    limit: int = Field(
        default=100,
        description="--limit N",
    )


class ModelGitRequest(BaseModel):
    """Input model for git operation requests.

    Attributes:
        operation: The git operation to perform.
        working_directory: cwd for git subprocess calls. If None, uses process cwd.
        repo: "owner/name" for gh -R flag (gh ops only). If None, infer from remote.
        branch_name: Branch name (for branch_create, push).
        base_ref: Base ref for branch creation (for branch_create).
        commit_message: Commit message (for commit).
        force_push: Whether to force push (for push).
        pr_title: Pull request title (for pr_create, pr_update).
        pr_body: Pull request body (for pr_create, pr_update).
        pr_number: Pull request number (for pr_update, pr_close, pr_merge, pr_view, label_add).
        ticket_id: Linear ticket ID for PR stamp block (for pr_create).
        base_branch: Base branch for PR (for pr_create).
        merge_method: Merge method: "squash" | "merge" | "rebase" (for pr_merge).
        use_merge_queue: Pass --merge-queue flag for pr_merge.
        labels: Labels to add (for label_add).
        tag_name: Tag name (for tag_create).
        tag_message: Tag message. None = lightweight, set = annotated (for tag_create).
        json_fields: --json field1,field2 for pr_list/pr_view.
        list_filters: Typed filter model for pr_list.
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: GitOperation = Field(
        ...,
        description="The git operation to perform",
    )
    # Targeting (OMN-2817 1a)
    working_directory: str | None = Field(
        default=None,
        description="cwd for git subprocess calls. If None, uses process cwd",
    )
    repo: str | None = Field(
        default=None,
        description="owner/name for gh -R flag (gh ops only)",
    )
    # Existing fields
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
        description="Pull request number for update/close/merge/view/label_add",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Linear ticket ID for mandatory PR stamp block",
    )
    base_branch: str | None = Field(
        default=None,
        description="Base branch for pull request creation",
    )
    # Merge fields (OMN-2817 1b)
    merge_method: str | None = Field(
        default=None,
        description="Merge method: squash | merge | rebase",
    )
    use_merge_queue: bool = Field(
        default=False,
        description="Pass --merge-queue flag for pr_merge",
    )
    # Label fields (OMN-2817 1b)
    labels: list[str] | None = Field(
        default=None,
        description="Labels to add for label_add operation",
    )
    # Tag fields (OMN-2817 1b)
    tag_name: str | None = Field(
        default=None,
        description="Tag name for tag_create",
    )
    tag_message: str | None = Field(
        default=None,
        description="Tag message. None = lightweight tag, set = annotated tag",
    )
    # Query fields (OMN-2817 1b)
    json_fields: list[str] | None = Field(
        default=None,
        description="--json field1,field2 for pr_list/pr_view",
    )
    list_filters: ModelPRListFilters | None = Field(
        default=None,
        description="Typed filter model for pr_list",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["GitOperation", "ModelGitRequest", "ModelPRListFilters"]
