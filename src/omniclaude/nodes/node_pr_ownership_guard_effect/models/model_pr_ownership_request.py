# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One Bash command to judge against the lane-ownership claims (OMN-20685).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelPrOwnershipRequest(BaseModel):
    """The command and the operands that name the lane asking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str = Field(description="The Bash command about to run.")
    cwd: str | None = Field(
        default=None,
        description="The caller's directory, which can name a worktree lane.",
    )
    default_repo: str | None = Field(
        default=None,
        description="The repository implied by the cwd, for --repo omitted.",
    )
    hooks_lib: str | None = Field(
        default=None,
        description="The plugin hook library directory; its siblings hold the claim registry.",
    )
    env: dict[str, str] | None = Field(
        default=None,
        description="The environment lane and run identity resolve from; the process's own when absent.",
    )
