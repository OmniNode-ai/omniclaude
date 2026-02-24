# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Work unit model — a node in the Plan DAG."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_plan_dag_generator.enums.enum_work_unit_type import (
    EnumWorkUnitType,
)


class ModelWorkUnit(BaseModel):
    """A single work unit node in the Plan DAG.

    Each work unit represents a discrete piece of work that maps to a
    single executable ticket at the compilation stage (OMN-2503).

    Attributes:
        unit_id: Stable identifier for this work unit within the DAG.
        title: Short human-readable title for the work unit.
        description: Full description of what this work unit entails.
        unit_type: Category of work (maps to ticket template type).
        estimated_scope: T-shirt sizing estimate (XS/S/M/L/XL).
        context: Additional structured context (key/value pairs).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this work unit within the DAG",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Short human-readable title for the work unit",
    )
    description: str = Field(
        default="",
        max_length=4000,
        description="Full description of what this work unit entails",
    )
    unit_type: EnumWorkUnitType = Field(
        default=EnumWorkUnitType.GENERIC,
        description="Category of work (maps to ticket template type)",
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


__all__ = ["ModelWorkUnit"]
