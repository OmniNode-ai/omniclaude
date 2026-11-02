# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The keys a PostCompact event is stamped with (OMN-22004, TA.22).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelCompactStampResult(BaseModel):
    """A field is ``None`` when the transcript does not hold it; never invented."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_tokens: int | None = Field(default=None, ge=1)
    model: str | None = None

    def stamp(self) -> dict[str, int | str]:
        """The payload keys to set: only those the transcript gave."""
        return self.model_dump(exclude_none=True)
