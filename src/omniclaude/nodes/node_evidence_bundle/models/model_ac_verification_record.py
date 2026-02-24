# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Per-AC verification record captured during ticket execution."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_evidence_bundle.enums.enum_ac_verdict import EnumAcVerdict


class ModelAcVerificationRecord(BaseModel):
    """Result of evaluating a single acceptance criterion.

    Attributes:
        criterion_id: ID of the acceptance criterion evaluated.
        verdict: PASS/FAIL/SKIPPED/ERROR outcome.
        actual_value: Observed value from verification command execution.
        error_message: Error details if verdict is ERROR; empty otherwise.
        verified_at: Explicit timestamp of when verification ran.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    criterion_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="ID of the acceptance criterion evaluated",
    )
    verdict: EnumAcVerdict = Field(
        ...,
        description="PASS/FAIL/SKIPPED/ERROR outcome",
    )
    actual_value: str = Field(
        default="",
        max_length=1024,
        description="Observed value from verification command execution",
    )
    error_message: str = Field(
        default="",
        max_length=2048,
        description="Error details if verdict is ERROR; empty otherwise",
    )
    verified_at: datetime = Field(
        ...,
        description="Explicit timestamp of when verification ran",
    )


__all__ = ["ModelAcVerificationRecord"]
