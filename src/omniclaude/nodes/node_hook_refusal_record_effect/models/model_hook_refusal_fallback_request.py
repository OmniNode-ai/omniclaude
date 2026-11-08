# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What the shell seam knows when no interpreter could record a refusal (OMN-23017).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelHookRefusalFallbackRequest(BaseModel):
    """One refusal the recorder could not write, with the interpreters that failed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    guard: str = Field(description="The refusing guard's id.")
    reason: str = Field(description="The refusal class the guard gave.")
    detail: str = Field(default="", description="The refusal's first line.")
    hooks_lib: str = Field(description="The plugin hook library directory.")
    import_error: str = Field(
        default="", description="The first line the last failing interpreter printed."
    )
    interpreters: tuple[str, ...] = Field(
        default=(), description="The interpreters that failed to import the recorder."
    )
