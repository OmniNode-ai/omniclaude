# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pydantic backing model for the hook tool executed contract.

This module provides type-safe access to the hook tool executed configuration
defined in contract_hook_tool_executed.yaml. It replaces manual yaml.safe_load +
isinstance checks with validated Pydantic models.

The contract defines the interface for the tool executed hook effect node,
which emits events to Kafka after a tool completes in Claude Code. Key sections:
- Event bus configuration (topic, partition key, strategy)
- Runtime configuration (timeout, side effects, deterministic)
- Tool matching configuration (regex pattern, sampling)
- Timestamp policy (explicit injection, timezone requirements)

Usage:
    >>> from omniclaude.hooks.contracts.contract_hook_tool_executed import (
    ...     HookToolExecutedContract,
    ... )
    >>> contract = HookToolExecutedContract.load()
    >>> print(contract.tool_matching.pattern)
    '^(Read|Write|Edit|Bash|...)$'
    >>> print(contract.runtime.timeout_ms)
    100

See Also:
    - contract_hook_tool_executed.yaml for the source YAML contract
    - OMN-1399: Define Claude Code hooks schema for ONEX event emission
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.contracts.contract_experiment_cohort import (
    Metadata,
    Version,
)

# =============================================================================
# Nested Models
# =============================================================================


class ModelReference(BaseModel):
    """Reference to a Pydantic model for I/O type definitions.

    Attributes:
        name: The model class name (e.g., 'ModelHookToolExecutedPayload').
        module: The module path where the model is defined.
        description: Human-readable description of the model's purpose.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="The model class name (e.g., 'ModelHookToolExecutedPayload')",
    )
    module: str = Field(
        ...,
        min_length=1,
        description="The module path where the model is defined",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the model's purpose",
    )


class EventBus(BaseModel):
    """Event bus configuration for Kafka topic publishing.

    Attributes:
        topic_base: Base topic name without environment prefix
            (e.g., 'onex.evt.omniclaude.tool-executed.v1').
        partition_key_field: Field name used as partition key for ordering
            (typically 'entity_id' for session-based ordering).
        partition_strategy: Partitioning strategy (e.g., 'hash').
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
        description="Field name used as partition key for ordering",
    )
    partition_strategy: Literal["hash", "round_robin", "sticky"] = Field(
        ...,
        description="Strategy for partition assignment",
    )


class Runtime(BaseModel):
    """Runtime configuration for node execution behavior.

    Attributes:
        supports_direct_call: Whether the node can be invoked directly
            (not just via orchestrator).
        supports_event_driven: Whether the node can be triggered by events.
        side_effects: Whether the node has side effects (e.g., publishes to Kafka).
        timeout_ms: Maximum execution time in milliseconds.
        deterministic: Whether the same input always produces the same output.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    supports_direct_call: bool = Field(
        ...,
        description="Whether the node can be invoked directly",
    )
    supports_event_driven: bool = Field(
        ...,
        description="Whether the node can be triggered by events",
    )
    side_effects: bool = Field(
        ...,
        description="Whether the node has side effects (e.g., publishes to Kafka)",
    )
    timeout_ms: int = Field(
        ...,
        ge=1,
        description="Maximum execution time in milliseconds",
    )
    deterministic: bool = Field(
        ...,
        description="Whether the same input always produces the same output",
    )


class TimestampPolicy(BaseModel):
    """ONEX timestamp policy for event emission.

    Defines how timestamps should be handled per ONEX architecture.
    Explicit injection ensures deterministic testing and consistent ordering.

    Attributes:
        explicit_injection: Whether producers must explicitly inject timestamps.
        timezone_required: Whether timestamps must be timezone-aware.
        rationale: Explanation of why this policy exists.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    explicit_injection: bool = Field(
        ...,
        description="Whether producers must explicitly inject timestamps",
    )
    timezone_required: bool = Field(
        ...,
        description="Whether timestamps must be timezone-aware",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Explanation of why this policy exists",
    )


class ToolMatching(BaseModel):
    """Tool matching configuration for the PostToolUse hook.

    Defines which tools trigger this hook and optional sampling configuration
    for high-frequency tools.

    Attributes:
        pattern: Regex pattern to match tool names (e.g., '^(Read|Write|Edit|...)$').
        sampling_enabled: Whether sampling is enabled for high-frequency tools.
        sampling_rate: Sampling rate when enabled (0.0 to 1.0, where 1.0 = 100%).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    pattern: str = Field(
        ...,
        min_length=1,
        description="Regex pattern to match tool names",
    )
    sampling_enabled: bool = Field(
        ...,
        description="Whether sampling is enabled for high-frequency tools",
    )
    sampling_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Sampling rate when enabled (0.0 to 1.0, where 1.0 = 100%)",
    )


class Dependency(BaseModel):
    """Dependency declaration for a node.

    Describes external services or utilities required by the node.

    Attributes:
        name: Dependency identifier.
        type: Dependency type (e.g., 'service', 'utility').
        description: Human-readable description of the dependency's purpose.
        class_name: Optional class/function name for utilities.
        module: Optional module path for utilities.
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
    type: str = Field(
        ...,
        min_length=1,
        description="Dependency type (e.g., 'service', 'utility')",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the dependency's purpose",
    )
    class_name: str | None = Field(
        default=None,
        min_length=1,
        description="Optional class/function name for utilities",
    )
    module: str | None = Field(
        default=None,
        min_length=1,
        description="Optional module path for utilities",
    )


class Capability(BaseModel):
    """Capability declaration for a node.

    Describes what the node can do or provide.

    Attributes:
        name: Capability identifier (e.g., 'tool_event_emission').
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
# Root Contract Model
# =============================================================================


class HookToolExecutedContract(BaseModel):
    """Root model for the hook tool executed contract.

    This model validates the entire contract_hook_tool_executed.yaml structure
    and provides type-safe access to all configuration values.

    The contract defines the interface for the tool executed hook effect node,
    which emits events to Kafka after a tool completes in Claude Code.

    Attributes:
        name: Contract name identifier.
        contract_name: Contract name (typically same as name).
        node_name: Node name for ONEX compatibility.
        version: Semantic version of the contract.
        node_version: Node implementation version.
        node_type: Node type (e.g., 'EFFECT').
        description: Human-readable description of the contract purpose.
        input_model: Reference to the input Pydantic model.
        output_model: Reference to the output Pydantic model.
        event_bus: Event bus configuration for Kafka publishing.
        runtime: Runtime configuration for node execution.
        timestamp_policy: ONEX timestamp policy for event emission.
        tool_matching: Tool matching configuration for PostToolUse hook.
        dependencies: List of dependencies required by the node.
        capabilities: List of capabilities provided by the node.
        definitions: JSON schema-like definitions for documentation.
        metadata: Contract metadata for documentation and tracking.

    Example:
        >>> contract = HookToolExecutedContract.load()
        >>> contract.tool_matching.pattern
        '^(Read|Write|Edit|Bash|...)$'
        >>> contract.runtime.timeout_ms
        100
        >>> contract.event_bus.topic_base
        'onex.evt.omniclaude.tool-executed.v1'
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
    node_type: str = Field(
        ...,
        min_length=1,
        description="Node type (e.g., 'EFFECT')",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the contract purpose",
    )
    input_model: ModelReference = Field(
        ...,
        description="Reference to the input Pydantic model",
    )
    output_model: ModelReference = Field(
        ...,
        description="Reference to the output Pydantic model",
    )
    event_bus: EventBus = Field(
        ...,
        description="Event bus configuration for Kafka publishing",
    )
    runtime: Runtime = Field(
        ...,
        description="Runtime configuration for node execution",
    )
    timestamp_policy: TimestampPolicy = Field(
        ...,
        description="ONEX timestamp policy for event emission",
    )
    tool_matching: ToolMatching = Field(
        ...,
        description="Tool matching configuration for PostToolUse hook",
    )
    dependencies: list[Dependency] = Field(
        ...,
        min_length=1,
        description="List of dependencies required by the node",
    )
    capabilities: list[Capability] = Field(
        ...,
        min_length=1,
        description="List of capabilities provided by the node",
    )
    definitions: dict[str, object] = Field(
        ...,
        description="JSON schema-like definitions for documentation",
    )
    metadata: Metadata = Field(
        ...,
        description="Contract metadata for documentation and tracking",
    )

    @classmethod
    def load(cls, path: Path | None = None) -> Self:
        """Load and validate the hook tool executed contract from YAML.

        Args:
            path: Optional path to the YAML contract file. If not provided,
                defaults to contract_hook_tool_executed.yaml in the same directory.

        Returns:
            Validated HookToolExecutedContract instance.

        Raises:
            FileNotFoundError: If the contract file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            pydantic.ValidationError: If the contract fails validation.

        Example:
            >>> contract = HookToolExecutedContract.load()
            >>> contract.tool_matching.pattern
            '^(Read|Write|Edit|Bash|...)$'
        """
        if path is None:
            path = Path(__file__).parent / "contract_hook_tool_executed.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.model_validate(data)


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Nested models
    "ModelReference",
    "EventBus",
    "Runtime",
    "TimestampPolicy",
    "ToolMatching",
    "Dependency",
    "Capability",
    # Root contract
    "HookToolExecutedContract",
]
