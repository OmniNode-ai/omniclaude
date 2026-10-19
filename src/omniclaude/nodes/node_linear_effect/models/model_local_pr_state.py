# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Request and result of a local PR merge-state read (OMN-20368).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelLocalPrStateRequest(BaseModel):
    """One PR whose merge state is read from the PR watcher and the canonical clone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="owner/name, or the bare repository name")
    number: int = Field(..., gt=0, description="The pull request number")


class ModelLocalPrStateResult(BaseModel):
    """What the local sources say about one PR. ``error`` is set when neither proves a state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str = Field(..., description="MERGED, OPEN, CLOSED or UNKNOWN")
    title: str = ""
    head_sha: str = Field(default="", description="The PR head, from the watcher")
    merge_commit_sha: str = Field(
        default="", description="The squash commit on the base branch, from the clone"
    )
    merged_at: str = ""
    closing_notes: tuple[str, ...] = Field(
        default=(), description="A closed PR's body, where a superseded-by note lives"
    )
    error: str | None = Field(
        default=None,
        description="Why neither source could prove a state, naming the PR",
    )
