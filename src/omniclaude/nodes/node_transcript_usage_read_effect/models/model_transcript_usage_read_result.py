# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What one transcript read found, and the marker state that consumes it (OMN-18946).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_transcript_usage_read_effect.models.model_usage_totals import (
    ModelUsageTotals,
)


class ModelTranscriptUsageReadResult(BaseModel):
    """Per-model totals plus the marker state the caller commits once it has
    journalled them. Nothing is consumed by a read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    totals: tuple[ModelUsageTotals, ...] = Field(
        default=(), description="One entry per model, sorted by model id."
    )
    partial_window: bool = Field(
        default=False,
        description="True when the first read took only the transcript's tail.",
    )
    marker_path: str = Field(min_length=1)
    next_offset: int = Field(ge=0)
    seen_ids: tuple[str, ...] = Field(default=())
