# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Request and result of the retired closeout instruction audit (OMN-20368, OMN-21536).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ModelCloseoutInstructionAuditRequest(BaseModel):
    """The source skill and workflow roots to audit for the retired closeout instruction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    roots: tuple[Path, ...] = Field(
        ..., description="Instruction roots; a missing root is a finding, not a pass"
    )


class ModelCloseoutInstructionAuditResult(BaseModel):
    """One line per retired instruction or unreadable root; empty when the audit is clean."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[str, ...] = Field(
        default=(), description="path:line and the reason, or the missing root"
    )
