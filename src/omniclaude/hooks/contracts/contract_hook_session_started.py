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

# =============================================================================
# Nested Models - I/O Model References
# =============================================================================


class ModelReference(BaseModel):
    """Reference to a Pydantic model used for input or output.

    Attributes:
        name: Class name of the model.
        module: Python module path where the model is defined.
        description: Human-readable description of the model's purpose.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Class name of the model",
    )
    module: str = Field(
        ...,
        min_length=1,
        description="Python module path where the model is defined",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the model's purpose",
    )


# =============================================================================
# Nested Models - Event Bus Configuration
# =============================================================================


class EventBus(BaseModel):
    """Event bus configuration for Kafka publishing.

    Attributes:
        topic_base: Base topic name without environment prefix.
        partition_key_field: Field name used for partition key.
        partition_strategy: Strategy for partition assignment.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    topic_base: str = Field(
        ...,
        min_length=1,
        description="Base topic name without environment prefix",
    )
    partition_key_field: str = Field(
        ...,
        min_length=1,
        description="Field name used for partition key",
    )
    partition_strategy: Literal["hash", "round_robin", "sticky"] = Field(
        ...,
        description="Strategy for partition assignment",
    )


# =============================================================================
# Nested Models - Runtime Configuration
# =============================================================================


class Runtime(BaseModel):
    """Runtime configuration for the node.

    Attributes:
        supports_direct_call: Whether the node can be called directly.
        supports_event_driven: Whether the node can be triggered by events.
        side_effects: Whether the node has side effects (e.g., Kafka publish).
        timeout_ms: Maximum execution time in milliseconds.
        deterministic: Whether same input produces same output.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    supports_direct_call: bool = Field(
        ...,
        description="Whether the node can be called directly",
    )
    supports_event_driven: bool = Field(
        ...,
        description="Whether the node can be triggered by events",
    )
    side_effects: bool = Field(
        ...,
        description="Whether the node has side effects (e.g., Kafka publish)",
    )
    timeout_ms: int = Field(
        ...,
        gt=0,
        le=60000,
        description="Maximum execution time in milliseconds",
    )
    deterministic: bool = Field(
        ...,
        description="Whether same input produces same output",
    )


# =============================================================================
# Nested Models - Timestamp Policy
# =============================================================================


class TimestampPolicy(BaseModel):
    """ONEX timestamp policy configuration.

    Attributes:
        explicit_injection: Whether timestamps must be explicitly injected.
        timezone_required: Whether timestamps must be timezone-aware.
        rationale: Explanation for the timestamp policy.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    explicit_injection: bool = Field(
        ...,
        description="Whether timestamps must be explicitly injected",
    )
    timezone_required: bool = Field(
        ...,
        description="Whether timestamps must be timezone-aware",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Explanation for the timestamp policy",
    )


# =============================================================================
# Nested Models - Dependencies
# =============================================================================


class Dependency(BaseModel):
    """Dependency definition for the node.

    Attributes:
        name: Dependency identifier.
        type: Type of dependency (service, utility, etc.).
        description: Human-readable description of the dependency.
        class_name: Optional class name if the dependency is a class.
        module: Optional Python module path for the dependency.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Dependency identifier",
    )
    type: Literal["service", "utility", "model", "config"] = Field(
        ...,
        description="Type of dependency",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the dependency",
    )
    class_name: str | None = Field(
        default=None,
        min_length=1,
        description="Optional class name if the dependency is a class",
    )
    module: str | None = Field(
        default=None,
        min_length=1,
        description="Optional Python module path for the dependency",
    )


# =============================================================================
# Nested Models - Capabilities
# =============================================================================


class Capability(BaseModel):
    """Capability provided by the node.

    Attributes:
        name: Capability identifier.
        description: Human-readable description of the capability.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Capability identifier",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the capability",
    )


# =============================================================================
# Nested Models - JSON Schema Definitions
# =============================================================================


class PropertyDefinition(BaseModel):
    """JSON Schema property definition.

    Attributes:
        type: JSON Schema type.
        description: Human-readable description of the property.
        format: Optional format hint (e.g., uuid, date-time).
        nullable: Whether the property can be null.
        minLength: Minimum string length.
        maxLength: Maximum string length.
        minimum: Minimum numeric value.
        enum: List of allowed values.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    type: str = Field(
        ...,
        min_length=1,
        description="JSON Schema type",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the property",
    )
    format: str | None = Field(
        default=None,
        min_length=1,
        description="Optional format hint (e.g., uuid, date-time)",
    )
    nullable: bool | None = Field(
        default=None,
        description="Whether the property can be null",
    )
    minLength: int | None = Field(
        default=None,
        ge=0,
        description="Minimum string length",
    )
    maxLength: int | None = Field(
        default=None,
        ge=0,
        description="Maximum string length",
    )
    minimum: int | None = Field(
        default=None,
        description="Minimum numeric value",
    )
    enum: list[str] | None = Field(
        default=None,
        description="List of allowed values",
    )


class ModelDefinition(BaseModel):
    """JSON Schema model definition.

    Attributes:
        type: JSON Schema type (always 'object' for models).
        description: Human-readable description of the model.
        properties: Dictionary of property definitions.
        required: List of required property names.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    type: Literal["object"] = Field(
        ...,
        description="JSON Schema type (always 'object' for models)",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the model",
    )
    properties: dict[str, PropertyDefinition] = Field(
        ...,
        description="Dictionary of property definitions",
    )
    required: list[str] = Field(
        ...,
        min_length=1,
        description="List of required property names",
    )


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
    definitions: dict[str, ModelDefinition] = Field(
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
    # Nested models
    "Capability",
    "Dependency",
    "EventBus",
    "ModelDefinition",
    "ModelReference",
    "PropertyDefinition",
    "Runtime",
    "TimestampPolicy",
    # Root contract
    "HookSessionStartedContract",
]
