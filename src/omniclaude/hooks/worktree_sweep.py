# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Models for the worktree health sweep.

Defines categorization enums and structured report models used by the
worktree_sweep skill to audit and clean up git worktrees.

Part of OMN-6867: worktree health sweep for close-out pipeline.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumWorktreeStatus(StrEnum):
    """Classification of a worktree's health state."""

    SAFE_TO_DELETE = "safe_to_delete"
    """Branch merged to main, no uncommitted work."""

    LOST_WORK = "lost_work"
    """Branch merged to main BUT has uncommitted changes."""

    STALE = "stale"
    """Branch not merged, clean, last commit >3 days ago, no open PR."""

    ACTIVE = "active"
    """Branch not merged, recent work."""

    DIRTY_ACTIVE = "dirty_active"
    """Branch not merged, has uncommitted work."""


class ModelWorktreeEntry(BaseModel):
    """A single worktree audit result."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to the worktree directory",
    )
    repo: str = Field(
        ...,
        min_length=1,
        description="Repository name (e.g. 'omniclaude')",
    )
    branch: str = Field(
        ...,
        min_length=1,
        description="Current branch name in the worktree",
    )
    status: EnumWorktreeStatus = Field(
        ...,
        description="Categorized health status",
    )
    commits_ahead: int = Field(
        ...,
        ge=0,
        description="Number of commits ahead of main (0 means merged)",
    )
    has_uncommitted: bool = Field(
        ...,
        description="Whether worktree has uncommitted changes",
    )
    last_commit_date: datetime = Field(
        ...,
        description="Date of the most recent commit on the branch",
    )


class ModelWorktreeSweepReport(BaseModel):
    """Aggregated report from a worktree sweep run."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    entries: list[ModelWorktreeEntry] = Field(
        ...,
        description="All audited worktree entries",
    )
    counts_by_status: dict[EnumWorktreeStatus, int] = Field(
        ...,
        description="Count of worktrees per status category",
    )
    cleaned_count: int = Field(
        ...,
        ge=0,
        description="Number of SAFE_TO_DELETE worktrees that were removed",
    )
    tickets_created: int = Field(
        ...,
        ge=0,
        description="Number of Linear tickets created for LOST_WORK items",
    )
