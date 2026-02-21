# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Input model for the OmniMemory pattern promotion handler."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_omnimemory_promotion.models.model_promotion_criteria import (
    ModelPromotionCriteria,
)

# Type aliases matching PromotedPatternProtocol from OMN-2502
_WorkUnitSpec = tuple[str, str, str, str]  # (local_id, title, unit_type, scope)
_DepSpec = tuple[str, str]  # (from_local_id, to_local_id)


class ModelPatternPromotionRequest(BaseModel):
    """Request to evaluate and potentially promote a ticket generation pattern.

    Attributes:
        intent_type: Intent type this pattern serves.
        unit_specs: Work unit template specs.
        dep_specs: Dependency template specs.
        evidence_bundle_ids: IDs of successful evidence bundles supporting this pattern.
        evidence_count: Count of successful evidence bundles.
        criteria: Promotion eligibility criteria.
        correlation_id: Correlation UUID for distributed tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    intent_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Intent type this pattern serves",
    )
    unit_specs: tuple[_WorkUnitSpec, ...] = Field(
        ...,
        description="Work unit template specs as (local_id, title, unit_type, scope)",
    )
    dep_specs: tuple[_DepSpec, ...] = Field(
        default=(),
        description="Dependency template specs as (from_local_id, to_local_id)",
    )
    evidence_bundle_ids: tuple[str, ...] = Field(
        ...,
        description="IDs of successful evidence bundles supporting this pattern",
    )
    evidence_count: int = Field(
        ...,
        ge=0,
        description="Count of successful evidence bundles",
    )
    criteria: ModelPromotionCriteria = Field(
        default_factory=ModelPromotionCriteria,
        description="Promotion eligibility criteria",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )


__all__ = ["ModelPatternPromotionRequest"]
