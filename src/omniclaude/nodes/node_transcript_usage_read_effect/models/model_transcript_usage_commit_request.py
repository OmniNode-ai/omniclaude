# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Consume a transcript usage read (OMN-18946).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelTranscriptUsageCommitRequest(BaseModel):
    """The marker state a read returned, to be written once its events landed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    marker_path: str = Field(min_length=1)
    next_offset: int = Field(ge=0)
    seen_ids: tuple[str, ...] = Field(default=())
