# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Result of the ambiguity gate check for a single work unit."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_ambiguity_gate.enums.enum_gate_verdict import EnumGateVerdict
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_flag import (
    ModelAmbiguityFlag,
)


class ModelGateCheckResult(BaseModel):
    """Outcome of the ambiguity gate for a single Plan DAG work unit.

    Attributes:
        unit_id: ID of the checked work unit.
        verdict: PASS if unambiguous; FAIL if any unresolved ambiguity detected.
        ambiguity_flags: All ambiguity flags detected on this unit.
        dag_id: ID of the containing Plan DAG.
        intent_id: ID of the originating Intent object.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the checked work unit",
    )
    verdict: EnumGateVerdict = Field(
        ...,
        description="PASS if unambiguous; FAIL if any unresolved ambiguity detected",
    )
    ambiguity_flags: tuple[ModelAmbiguityFlag, ...] = Field(
        default=(),
        description="All ambiguity flags detected on this unit",
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


__all__ = ["ModelGateCheckResult"]
