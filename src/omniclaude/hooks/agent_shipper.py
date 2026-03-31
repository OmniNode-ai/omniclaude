# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Models for the agent-idle shipper.

Defines Pydantic models for detecting stalled agent worktrees and
auto-shipping uncommitted work (commit, push, PR creation).

Part of OMN-6868: Agent idle shipper skill.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumShipperAction(StrEnum):
    """Action taken by the shipper for a stalled worktree."""

    NO_OP = "no_op"
    COMMITTED = "committed"
    PUSHED = "pushed"
    PR_CREATED = "pr_created"
    RECOVERY_TICKET = "recovery_ticket"


class ModelStallDetection(BaseModel):
    """Detection result for a single worktree.

    Captures the git state of a worktree to determine what shipping
    actions are needed.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    worktree_path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to the worktree directory",
    )
    branch: str = Field(
        ...,
        min_length=1,
        description="Current branch name in the worktree",
    )
    repo: str = Field(
        ...,
        min_length=1,
        description="Repository name (e.g., omniclaude)",
    )
    has_staged: bool = Field(
        default=False,
        description="Whether the worktree has staged but uncommitted changes",
    )
    has_unstaged: bool = Field(
        default=False,
        description="Whether the worktree has unstaged modifications",
    )
    has_untracked: bool = Field(
        default=False,
        description="Whether the worktree has untracked files",
    )
    commits_unpushed: int = Field(
        default=0,
        ge=0,
        description="Number of commits ahead of the remote tracking branch",
    )
    has_remote: bool = Field(
        default=False,
        description="Whether the branch has a remote tracking branch",
    )
    has_pr: bool = Field(
        default=False,
        description="Whether an open PR exists for this branch",
    )

    @property
    def has_uncommitted_work(self) -> bool:
        """Return True if the worktree has any uncommitted changes."""
        return self.has_staged or self.has_unstaged or self.has_untracked

    @property
    def needs_shipping(self) -> bool:
        """Return True if the worktree needs any shipping action."""
        return (
            self.has_uncommitted_work
            or self.commits_unpushed > 0
            or (self.has_remote and not self.has_pr and self.commits_unpushed == 0)
        )


class ModelShipperResult(BaseModel):
    """Result of a shipping action on a single worktree."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    worktree_path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to the worktree that was processed",
    )
    action_taken: EnumShipperAction = Field(
        ...,
        description="The highest-level action that was completed",
    )
    pr_url: str | None = Field(
        default=None,
        description="URL of the created PR (if action was PR_CREATED)",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Linear ticket ID extracted from the branch name",
    )
    error: str | None = Field(
        default=None,
        max_length=2000,
        description="Error message if the action failed",
    )


class ModelShipperReport(BaseModel):
    """Aggregate report from a shipper run across all worktrees."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    detections: list[ModelStallDetection] = Field(
        default_factory=list,
        description="All worktree stall detections performed",
    )
    results: list[ModelShipperResult] = Field(
        default_factory=list,
        description="Results of shipping actions taken",
    )
    total_scanned: int = Field(
        default=0,
        ge=0,
        description="Total number of worktrees scanned",
    )
    total_shipped: int = Field(
        default=0,
        ge=0,
        description="Number of worktrees where work was shipped",
    )
    total_failed: int = Field(
        default=0,
        ge=0,
        description="Number of worktrees where shipping failed",
    )
