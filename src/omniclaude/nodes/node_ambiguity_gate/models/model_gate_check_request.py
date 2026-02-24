# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Input model for the ambiguity gate check."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelGateCheckRequest(BaseModel):
    """Request to run the ambiguity gate on a single Plan DAG work unit.

    Attributes:
        unit_id: ID of the work unit to check.
        unit_title: Title of the work unit.
        unit_description: Full description of the work unit.
        unit_type: Type string of the work unit.
        estimated_scope: T-shirt scope estimate.
        context: Structured context key/value pairs.
        dag_id: ID of the containing Plan DAG.
        intent_id: ID of the originating Intent object.
        correlation_id: Correlation UUID for distributed tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the work unit to check",
    )
    unit_title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Title of the work unit",
    )
    unit_description: str = Field(
        default="",
        max_length=4000,
        description="Full description of the work unit",
    )
    unit_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Type string of the work unit",
    )
    estimated_scope: str = Field(
        default="M",
        pattern=r"^(XS|S|M|L|XL)$",
        description="T-shirt size estimate (XS/S/M/L/XL)",
    )
    context: tuple[tuple[str, str], ...] = Field(
        default=(),
        description="Additional structured context as (key, value) pairs",
    )
    dag_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the containing Plan DAG",
    )
    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the originating Intent object",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )


__all__ = ["ModelGateCheckRequest"]
