# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One transcript read for usage not yet counted (OMN-18946).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Most of a transcript the first read of a session thread takes, from its end.
FIRST_READ_BYTES = 8 * 1024 * 1024


class ModelTranscriptUsageReadRequest(BaseModel):
    """Which transcript, and which session thread's marker decides what is new."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transcript_path: str = Field(min_length=1)
    state_dir: str = Field(
        min_length=1, description="Where the per-thread marker is kept."
    )
    session_id: str = Field(min_length=1)
    agent_id: str | None = Field(
        default=None, description="None is the session's main thread."
    )
    include_sidechain: bool = Field(
        default=False,
        description=(
            "A subagent's own transcript marks every entry sidechain, so a "
            "SubagentStop reads it with this set; the main thread does not."
        ),
    )
    first_read_bytes: int = Field(default=FIRST_READ_BYTES, ge=1)
