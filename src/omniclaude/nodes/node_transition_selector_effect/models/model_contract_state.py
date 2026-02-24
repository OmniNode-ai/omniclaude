# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Contract state model for graph navigation.

NOTE: This is a local definition pending omnibase_core export (OMN-2540).
Once omnibase_core publishes ContractState, replace this with:
    from omnibase_core.models.navigation import ContractState
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelContractState(BaseModel):
    """Represents the current state of a contract in the navigation graph.

    This is a local stub matching the spec from OMN-2540. It will be
    replaced by the canonical omnibase_core.models.navigation.ContractState
    once that PR lands.

    Attributes:
        state_id: Unique identifier for this state within the graph.
        node_type: The ONEX node type this state belongs to (Effect, Compute,
            Reducer, Orchestrator).
        fields: Typed field values present in this state.
        metadata: Additional state metadata (e.g., timestamps, tags).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for this state within the graph",
    )
    node_type: str = Field(
        ...,
        min_length=1,
        description="ONEX node type (Effect, Compute, Reducer, Orchestrator)",
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Typed field values present in this state",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional state metadata (timestamps, tags, etc.)",
    )


__all__ = ["ModelContractState"]
