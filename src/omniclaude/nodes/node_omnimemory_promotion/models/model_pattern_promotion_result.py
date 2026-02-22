# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Result of a pattern promotion attempt."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_omnimemory_promotion.enums.enum_promotion_status import (
    EnumPromotionStatus,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)


class ModelPatternPromotionResult(BaseModel):
    """Result of a pattern promotion evaluation.

    Attributes:
        status: Outcome of the promotion attempt.
        promoted_pattern: The promoted/bumped pattern; None if status is SKIPPED.
        pattern_key: The key used for pattern lookup.
        criteria_met: Whether promotion criteria were satisfied.
        evidence_count: Actual evidence count evaluated.
        min_evidence_required: Minimum evidence count from criteria.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    status: EnumPromotionStatus = Field(
        ...,
        description="Outcome of the promotion attempt",
    )
    promoted_pattern: ModelPromotedPattern | None = Field(
        default=None,
        description="The promoted/bumped pattern; None if status is SKIPPED",
    )
    pattern_key: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="The key used for pattern lookup",
    )
    criteria_met: bool = Field(
        ...,
        description="Whether promotion criteria were satisfied",
    )
    evidence_count: int = Field(
        ...,
        ge=0,
        description="Actual evidence count evaluated",
    )
    min_evidence_required: int = Field(
        ...,
        ge=1,
        description="Minimum evidence count from criteria",
    )


__all__ = ["ModelPatternPromotionResult"]
