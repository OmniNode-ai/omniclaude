# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pydantic backing model for the hook session ended contract.

This module provides type-safe access to the session ended hook configuration
defined in contract_hook_session_ended.yaml. It replaces manual yaml.safe_load +
isinstance checks with validated Pydantic models.

The contract defines the effect node interface for emitting session ended
events to Kafka, including:
- Input/output model references for type-safe I/O
- Event bus configuration for Kafka publishing
- Runtime constraints and capabilities
- ONEX timestamp policy compliance

Usage:
    >>> from omniclaude.hooks.contracts.contract_hook_session_ended import (
    ...     HookSessionEndedContract,
    ... )
    >>> contract = HookSessionEndedContract.load()
    >>> print(contract.event_bus.topic_base)
    'onex.evt.omniclaude.session-ended.v1'
    >>> print(contract.runtime.timeout_ms)
    500

See Also:
    - contract_hook_session_ended.yaml for the source YAML contract
    - OMN-1399: Define Claude Code hooks schema for ONEX event emission
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.contracts.contract_experiment_cohort import (
    Metadata,
    Version,
)
from omniclaude.hooks.contracts.contract_hook_tool_executed import (
    Capability,
    Dependency,
    EventBus,
    ModelReference,
    Runtime,
    TimestampPolicy,
)

# =============================================================================
# Root Contract Model
# =============================================================================


class HookSessionEndedContract(BaseModel):
    """Root model for the hook session ended contract.

    This model validates the entire contract_hook_session_ended.yaml structure
    and provides type-safe access to all configuration values.

    The contract defines an EFFECT node that publishes session ended events
    to Kafka when a Claude Code session terminates.

    Attributes:
        name: Contract name identifier.
        contract_name: Contract name (typically same as name).
        node_name: Node name for ONEX compatibility.
        version: Semantic version of the contract.
        node_version: Node implementation version.
        node_type: ONEX node type (EFFECT for this contract).
        description: Human-readable description of the contract purpose.
        input_model: Reference to the input Pydantic model.
        output_model: Reference to the output Pydantic model.
        event_bus: Kafka event bus configuration.
        runtime: Runtime execution configuration.
        timestamp_policy: ONEX timestamp handling policy.
        dependencies: List of required dependencies.
        capabilities: List of capabilities provided by this node.
        definitions: JSON Schema-like model definitions for documentation.
        metadata: Contract metadata for documentation and tracking.

    Example:
        >>> contract = HookSessionEndedContract.load()
        >>> contract.event_bus.topic_base
        'onex.evt.omniclaude.session-ended.v1'
        >>> contract.event_bus.partition_key_field
        'entity_id'
        >>> contract.runtime.timeout_ms
        500
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    # Contract identifiers
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

    # Versioning
    version: Version = Field(
        ...,
        description="Semantic version of the contract",
    )
    node_version: Version = Field(
        ...,
        description="Node implementation version",
    )

    # Node type
    node_type: str = Field(
        ...,
        pattern="^EFFECT$",
        description="ONEX node type (must be EFFECT for hook event emitters)",
    )

    # Description
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the contract purpose",
    )

    # I/O Models
    input_model: ModelReference = Field(
        ...,
        description="Reference to the input Pydantic model",
    )
    output_model: ModelReference = Field(
        ...,
        description="Reference to the output Pydantic model",
    )

    # Configuration
    event_bus: EventBus = Field(
        ...,
        description="Kafka event bus configuration",
    )
    runtime: Runtime = Field(
        ...,
        description="Runtime execution configuration",
    )
    timestamp_policy: TimestampPolicy = Field(
        ...,
        description="ONEX timestamp handling policy",
    )

    # Dependencies and capabilities
    dependencies: list[Dependency] = Field(
        ...,
        min_length=1,
        description="List of required dependencies",
    )
    capabilities: list[Capability] = Field(
        ...,
        min_length=1,
        description="List of capabilities provided by this node",
    )

    # Model definitions (JSON Schema-like documentation)
    definitions: dict[str, Any] = Field(
        ...,
        description="JSON Schema-like model definitions for documentation",
    )

    # Metadata
    metadata: Metadata = Field(
        ...,
        description="Contract metadata for documentation and tracking",
    )

    @classmethod
    def load(cls, path: Path | None = None) -> Self:
        """Load and validate the hook session ended contract from YAML.

        Args:
            path: Optional path to the YAML contract file. If not provided,
                defaults to contract_hook_session_ended.yaml in the same directory.

        Returns:
            Validated HookSessionEndedContract instance.

        Raises:
            FileNotFoundError: If the contract file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            pydantic.ValidationError: If the contract fails validation.

        Example:
            >>> contract = HookSessionEndedContract.load()
            >>> contract.event_bus.topic_base
            'onex.evt.omniclaude.session-ended.v1'
        """
        if path is None:
            path = Path(__file__).parent / "contract_hook_session_ended.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        # Handle non-mapping YAML (empty file, scalar, etc.)
        if not isinstance(data, dict):
            data = {}

        return cls.model_validate(data)


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Root contract
    "HookSessionEndedContract",
]
