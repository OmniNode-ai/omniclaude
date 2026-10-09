# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What recording one hook refusal did (OMN-20685).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumHookRefusalRecordStatus(StrEnum):
    """How a refusal was dealt with."""

    EMITTED = "emitted"
    SUPPRESSED = "suppressed"
    PRINTED = "printed"
    FAILED = "failed"


class ModelHookRefusalRecordResult(BaseModel):
    """The outcome: a status, the process exit code and the row, if one was built."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EnumHookRefusalRecordStatus
    exit_code: int = Field(description="0 unless the refusal could not be recorded.")
    row: str = Field(default="", description="The ledger row, empty when none was due.")
    key: str = Field(default="", description="The refusal class's dedupe key.")
    messages: tuple[str, ...] = Field(
        default=(), description="Redacted diagnostics for the caller's stderr."
    )
