# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Input model for the Plan DAG Generator."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelPlanDagRequest(BaseModel):
    """Request object for the Intent → Plan DAG generation stage.

    Attributes:
        intent_id: ID of the typed Intent object to convert into a DAG.
        intent_type: The classified intent type string (from EnumIntentType).
        intent_summary: Human-readable intent summary used to label work units.
        entity_ids: IDs of entities extracted during NL parsing, used to
            enrich work unit context.
        correlation_id: Correlation UUID for distributed tracing.
        omnimemory_pattern_id: Optional ID of a promoted OmniMemory pattern
            to use instead of full DAG generation (cache hit path).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the typed Intent object",
    )
    intent_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Classified intent type string",
    )
    intent_summary: str = Field(
        default="",
        max_length=500,
        description="Human-readable intent summary",
    )
    entity_ids: tuple[str, ...] = Field(
        default=(),
        description="Entity IDs from NL parsing to enrich work unit context",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )
    omnimemory_pattern_id: str | None = Field(
        default=None,
        description="Optional OmniMemory pattern ID for cache hit path",
    )


__all__ = ["ModelPlanDagRequest"]
