# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Whether a transcript usage read was consumed (OMN-18946).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelTranscriptUsageCommitResult(BaseModel):
    """``committed`` false means the marker was not written and usage may repeat."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    committed: bool
    reason: str = Field(default="", description="The failure's type, never a path.")
