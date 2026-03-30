# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Contract state model for graph navigation.

NOTE: This is a local definition pending omnibase_core export (OMN-2540).
Once omnibase_core publishes ContractState, replace this with:
    from omnibase_core.navigation import ContractState
"""

from __future__ import annotations

from typing import Any, TypedDict  # any-ok: external API boundary

from pydantic import BaseModel, ConfigDict, Field


class ContractStateMetadataDict(TypedDict, total=False):
    """Typed metadata for ModelContractState.

    All keys are optional (total=False) since metadata is populated
    incrementally depending on the navigation context.
    """

    created_at: str
    updated_at: str
    tags: list[str]
    source: str
    version: str


class ModelContractState(BaseModel):
    """Represents the current state of a contract in the navigation graph.

    This is a local stub matching the spec from OMN-2540. It will be
    replaced by the canonical omnibase_core.navigation.ContractState
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
    fields: dict[  # any-ok: pre-existing
        str, Any
    ] = (  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
        Field(  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
            default_factory=dict,
            description="Typed field values present in this state",
        )
    )
    metadata: ContractStateMetadataDict = Field(
        default_factory=ContractStateMetadataDict,
        description="Additional state metadata (timestamps, tags, etc.)",
    )


__all__ = ["ContractStateMetadataDict", "ModelContractState"]
