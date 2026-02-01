# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pydantic backing model for the hook session started contract.

This module provides type-safe access to the hook session started configuration
defined in contract_hook_session_started.yaml. It replaces manual yaml.safe_load +
isinstance checks with validated Pydantic models.

The contract defines the interface for the session started hook effect node,
which emits events to Kafka when a Claude Code session starts.

Usage:
    >>> from omniclaude.hooks.contracts.contract_hook_session_started import (
    ...     HookSessionStartedContract,
    ... )
    >>> contract = HookSessionStartedContract.load()
    >>> print(contract.node_type)
    'EFFECT'
    >>> print(contract.event_bus.topic_base)
    'onex.evt.omniclaude.session-started.v1'

See Also:
    - contract_hook_session_started.yaml for the source YAML contract
    - OMN-1399: Claude Code hooks schema for ONEX event emission
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.contracts.contract_experiment_cohort import Metadata, Version
from omniclaude.hooks.contracts.contract_hook_tool_executed import (
    Capability,
    Dependency,
    EventBus,
    ModelReference,
    Runtime,
    TimestampPolicy,
)
from omniclaude.hooks.contracts.schema import ModelJsonSchemaDefinition

# =============================================================================
# Root Contract Model
# =============================================================================


class HookSessionStartedContract(BaseModel):
    """Root model for the hook session started contract.

    This model validates the entire contract_hook_session_started.yaml structure
    and provides type-safe access to all configuration values.

    Attributes:
        name: Contract name identifier.
        contract_name: Contract name (typically same as name).
        node_name: Node name for ONEX compatibility.
        version: Semantic version of the contract.
        node_version: Node implementation version.
        node_type: ONEX node type (EFFECT for this node).
        description: Human-readable description of the node purpose.
        input_model: Reference to the input model.
        output_model: Reference to the output model.
        event_bus: Event bus configuration for Kafka publishing.
        runtime: Runtime configuration for the node.
        timestamp_policy: ONEX timestamp policy configuration.
        dependencies: List of node dependencies.
        capabilities: List of capabilities provided by the node.
        definitions: JSON Schema definitions for models.
        metadata: Contract metadata for documentation and tracking.

    Example:
        >>> contract = HookSessionStartedContract.load()
        >>> contract.node_type
        'EFFECT'
        >>> contract.event_bus.topic_base
        'onex.evt.omniclaude.session-started.v1'
        >>> contract.runtime.timeout_ms
        500
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Contract name identifier",
    )
    contract_name: str = Field(
        ...,
        min_length=1,
        description="Contract name (typically same as name)",
    )
    node_name: str = Field(
        ...,
        min_length=1,
        description="Node name for ONEX compatibility",
    )
    version: Version = Field(
        ...,
        description="Semantic version of the contract",
    )
    node_version: Version = Field(
        ...,
        description="Node implementation version",
    )
    node_type: Literal["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"] = Field(
        ...,
        description="ONEX node type",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the node purpose",
    )
    input_model: ModelReference = Field(
        ...,
        description="Reference to the input model",
    )
    output_model: ModelReference = Field(
        ...,
        description="Reference to the output model",
    )
    event_bus: EventBus = Field(
        ...,
        description="Event bus configuration for Kafka publishing",
    )
    runtime: Runtime = Field(
        ...,
        description="Runtime configuration for the node",
    )
    timestamp_policy: TimestampPolicy = Field(
        ...,
        description="ONEX timestamp policy configuration",
    )
    dependencies: list[Dependency] = Field(
        ...,
        min_length=1,
        description="List of node dependencies",
    )
    capabilities: list[Capability] = Field(
        ...,
        min_length=1,
        description="List of capabilities provided by the node",
    )
    definitions: dict[str, ModelJsonSchemaDefinition] = Field(
        ...,
        description="JSON Schema definitions for models",
    )
    metadata: Metadata = Field(
        ...,
        description="Contract metadata for documentation and tracking",
    )

    @classmethod
    def load(cls, path: Path | None = None) -> Self:
        """Load and validate the hook session started contract from YAML.

        Args:
            path: Optional path to the YAML contract file. If not provided,
                defaults to contract_hook_session_started.yaml in the same directory.

        Returns:
            Validated HookSessionStartedContract instance.

        Raises:
            FileNotFoundError: If the contract file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            pydantic.ValidationError: If the contract fails validation.

        Example:
            >>> contract = HookSessionStartedContract.load()
            >>> contract.event_bus.topic_base
            'onex.evt.omniclaude.session-started.v1'
        """
        if path is None:
            path = Path(__file__).parent / "contract_hook_session_started.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.model_validate(data)


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Re-exported shared models (from contract_hook_tool_executed)
    "Capability",
    "Dependency",
    "EventBus",
    "ModelReference",
    "Runtime",
    "TimestampPolicy",
    # Root contract
    "HookSessionStartedContract",
    # Re-export from shared schema module for convenience
    "ModelJsonSchemaDefinition",
]
