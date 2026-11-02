# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What a PostCompact stamp is read from (OMN-22004, TA.22).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelCompactStampRequest(BaseModel):
    """The compact package the TA.20b reader found, and the transcript it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    package: str = Field(
        default="",
        description="The newest compact_boundary line and every line after it; empty when none.",
    )
    transcript_path: str = Field(
        description="The session transcript, read for the model."
    )
