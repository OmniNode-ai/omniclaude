# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""A single ambiguity signal detected on a Plan DAG work unit."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_ambiguity_gate.enums.enum_ambiguity_type import (
    EnumAmbiguityType,
)


class ModelAmbiguityFlag(BaseModel):
    """A typed ambiguity signal on a Plan DAG work unit.

    Attributes:
        ambiguity_type: Typed category of ambiguity detected.
        description: Human-readable explanation of the ambiguity.
        suggested_resolution: Actionable suggestion to resolve the ambiguity.
        field_name: Name of the work unit field where the ambiguity was found.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    ambiguity_type: EnumAmbiguityType = Field(
        ...,
        description="Typed category of ambiguity detected",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Human-readable explanation of the ambiguity",
    )
    suggested_resolution: str = Field(
        default="",
        max_length=512,
        description="Actionable suggestion to resolve the ambiguity",
    )
    field_name: str = Field(
        default="",
        max_length=128,
        description="Work unit field where the ambiguity originates",
    )


__all__ = ["ModelAmbiguityFlag"]
