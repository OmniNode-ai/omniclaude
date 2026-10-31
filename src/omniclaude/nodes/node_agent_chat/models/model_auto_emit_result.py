# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The result HandlerAutoEmit.handle returns (OMN-21742).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelAutoEmitResult(BaseModel):
    """Whether the publisher's file write succeeded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    published: bool = Field(description="True if the file write succeeded.")
