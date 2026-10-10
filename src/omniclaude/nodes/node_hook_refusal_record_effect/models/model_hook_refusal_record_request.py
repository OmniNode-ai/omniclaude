# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One hook refusal to record, as the calling guard states it (OMN-20685).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: One row per (guard, reason, lane) per hour.
DEFAULT_WINDOW_SECONDS = 3600


class ModelHookRefusalRecordRequest(BaseModel):
    """The refusal's own facts plus the operands that name its lane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    guard: str = Field(description="The refusing guard's id.")
    reason: str = Field(
        description="A short stable token for the refusal class, not a sentence."
    )
    detail: str = Field(default="", description="The refusal's first line.")
    cwd: str | None = Field(
        default=None, description="The directory the hook fired in."
    )
    transcript_path: str | None = Field(default=None)
    session_id: str | None = Field(default=None)
    agent_id: str | None = Field(default=None)
    payload: dict[str, object] | None = Field(
        default=None,
        description="The hook's own stdin payload; its fields win over the operands above.",
    )
    window_seconds: int = Field(
        default=DEFAULT_WINDOW_SECONDS, ge=0, description="The rate-limit window."
    )
    ledger: str | None = Field(
        default=None, description="Ledger file; defaults to the registry root's."
    )
    timeout: str = Field(default="120s", description="onex-ledger lock timeout.")
    print_row: bool = Field(
        default=False, description="Return the row instead of appending it."
    )
