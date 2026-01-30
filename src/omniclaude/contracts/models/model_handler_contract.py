# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pydantic models for handler contract YAML validation.

This module provides ONEX-compatible Pydantic models for validating handler
contract YAML files. These contracts define the interface, configuration,
and metadata for handler implementations in the omniclaude ecosystem.

Handler contracts are distinct from node contracts - they define handlers
that implement specific protocols and can be registered with the runtime
container for dependency injection.

Contract Location:
    Handler contracts are stored in `contracts/handlers/<handler_name>/contract.yaml`

Constructor Signature:
    All handlers registered via these contracts MUST accept a single
    `container` argument in their constructor:
    ```python
    def __init__(self, container: Container) -> None:
        ...
    ```

Validation Strictness:
    The models use `extra="forbid"` to fail fast on invalid contracts,
    catching typos and schema drift early.

Example Contract Structure:
    ```yaml
    handler_id: effect.learned_pattern.storage.postgres
    name: Learned Pattern Storage Handler (PostgreSQL)
    contract_version:
      major: 1
      minor: 0
      patch: 0
    descriptor:
      handler_kind: effect
      purity: side_effecting
      ...
    metadata:
      author: OmniNode Team
      license: MIT
      ticket: OMN-1403
      tags:
        - postgresql
        - storage
    ```

See Also:
    - contracts/handlers/pattern_storage_postgres/contract.yaml for reference
    - OMN-1605 for contract-driven handler registration loader

Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# =============================================================================
# Enums for Type-Safe Validation
# =============================================================================


class HandlerKind(StrEnum):
    """Kind of handler in the ONEX type system.

    Handlers are categorized by their computational characteristics.

    Values:
        EFFECT: Performs external I/O operations (database, API, file system).
        COMPUTE: Pure computational transformations with no side effects.
        REDUCER: Aggregates data from multiple sources into a single result.
        ORCHESTRATOR: Coordinates workflows across multiple handlers/nodes.
    """

    EFFECT = "effect"
    COMPUTE = "compute"
    REDUCER = "reducer"
    ORCHESTRATOR = "orchestrator"


class HandlerPurity(StrEnum):
    """Purity classification for handlers.

    Indicates whether a handler has side effects.

    Values:
        PURE: No side effects, deterministic output for same input.
        SIDE_EFFECTING: Has side effects (I/O, state mutation, etc.).
    """

    PURE = "pure"
    SIDE_EFFECTING = "side_effecting"


class BackoffStrategy(StrEnum):
    """Retry backoff strategy for handler failures.

    Values:
        EXPONENTIAL: Exponentially increasing delay between retries.
        LINEAR: Linearly increasing delay between retries.
        CONSTANT: Fixed delay between retries (also known as 'fixed').
    """

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    CONSTANT = "constant"


class ConcurrencyPolicy(StrEnum):
    """Concurrency policy for handler execution.

    Values:
        PARALLEL: Handler can execute in parallel with other handlers.
        SEQUENTIAL: Handler must execute sequentially (no concurrent executions).
    """

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class IsolationPolicy(StrEnum):
    """Isolation policy for handler execution context.

    Values:
        NONE: No isolation, shares context with other handlers.
        READ_COMMITTED: Read committed transaction isolation level.
        SERIALIZABLE: Serializable transaction isolation level.
    """

    NONE = "none"
    READ_COMMITTED = "read_committed"
    SERIALIZABLE = "serializable"


class ObservabilityLevel(StrEnum):
    """Observability level for handler instrumentation.

    Values:
        MINIMAL: Minimal logging and metrics (errors only).
        STANDARD: Standard logging and metrics (input/output, timing).
        DETAILED: Detailed/verbose logging with full tracing information.
    """

    MINIMAL = "minimal"
    STANDARD = "standard"
    DETAILED = "detailed"


class ModelRetryPolicy(BaseModel):
    """Retry policy configuration for handler failures.

    Defines how the runtime should handle transient failures by retrying
    the handler execution with configurable backoff.

    Attributes:
        enabled: Whether retry is enabled for this handler.
        max_retries: Maximum number of retry attempts (0-10).
        backoff_strategy: Strategy for calculating delay between retries.
        base_delay_ms: Initial delay in milliseconds before first retry.
        max_delay_ms: Maximum delay in milliseconds between retries.

    Example:
        >>> policy = ModelRetryPolicy(
        ...     enabled=True,
        ...     max_retries=3,
        ...     backoff_strategy=BackoffStrategy.EXPONENTIAL,
        ...     base_delay_ms=500,
        ...     max_delay_ms=10000,
        ... )
    """

    enabled: bool = Field(default=False, description="Whether retry is enabled")
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts (0-10)",
    )
    backoff_strategy: BackoffStrategy = Field(
        default=BackoffStrategy.EXPONENTIAL,
        description="Backoff strategy: exponential, linear, constant",
    )
    base_delay_ms: int = Field(
        default=500,
        ge=0,
        le=60000,
        description="Base delay in ms (max 60s)",
    )
    max_delay_ms: int = Field(
        default=10000,
        ge=0,
        le=300000,
        description="Maximum delay in ms (max 5min)",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelCircuitBreaker(BaseModel):
    """Circuit breaker configuration for handler fault tolerance.

    Implements the circuit breaker pattern to prevent cascading failures.
    When the failure threshold is reached, the circuit opens and subsequent
    calls fail fast without executing the handler.

    Attributes:
        enabled: Whether circuit breaker is enabled for this handler.
        failure_threshold: Number of failures before circuit opens.
        timeout_ms: Time in milliseconds before circuit half-opens for retry.

    Example:
        >>> breaker = ModelCircuitBreaker(
        ...     enabled=True,
        ...     failure_threshold=5,
        ...     timeout_ms=60000,
        ... )
    """

    enabled: bool = Field(
        default=False, description="Whether circuit breaker is enabled"
    )
    failure_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of failures before opening circuit (1-100)",
    )
    timeout_ms: int = Field(
        default=60000,
        ge=1000,
        le=600000,
        description="Timeout before attempting to close circuit (1s-10min)",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelHandlerDescriptor(BaseModel):
    """Handler behavior descriptor defining runtime semantics.

    The descriptor contains all operational characteristics of a handler
    including its type, purity, timeout, retry, and observability settings.

    Attributes:
        handler_kind: Kind of handler (effect, compute, reducer, orchestrator).
        purity: Whether handler is pure or has side effects.
        idempotent: Whether handler is idempotent (safe to retry).
        timeout_ms: Maximum execution time in milliseconds.
        retry_policy: Retry configuration for transient failures.
        circuit_breaker: Circuit breaker configuration for fault tolerance.
        concurrency_policy: How handler handles concurrent executions.
        isolation_policy: Isolation context for handler execution.
        observability_level: Level of logging and metrics instrumentation.

    Example:
        >>> descriptor = ModelHandlerDescriptor(
        ...     handler_kind=HandlerKind.EFFECT,
        ...     purity=HandlerPurity.SIDE_EFFECTING,
        ...     idempotent=True,
        ...     timeout_ms=30000,
        ... )
    """

    handler_kind: HandlerKind = Field(
        ...,
        description="Handler archetype: compute, effect, reducer, orchestrator",
    )
    purity: HandlerPurity = Field(
        default=HandlerPurity.PURE,
        description="Handler purity: pure, side_effecting",
    )
    idempotent: bool = Field(
        default=False,
        description="Whether the handler is idempotent (safe to retry)",
    )
    timeout_ms: int = Field(
        default=30000,
        ge=100,
        le=600000,
        description="Execution timeout in milliseconds (100ms-10min)",
    )
    retry_policy: ModelRetryPolicy | None = Field(
        default=None,
        description="Retry policy configuration",
    )
    circuit_breaker: ModelCircuitBreaker | None = Field(
        default=None,
        description="Circuit breaker configuration",
    )
    concurrency_policy: ConcurrencyPolicy = Field(
        default=ConcurrencyPolicy.SEQUENTIAL,
        description="Concurrency policy: sequential, parallel",
    )
    isolation_policy: IsolationPolicy = Field(
        default=IsolationPolicy.NONE,
        description="Isolation policy: none, read_committed, serializable",
    )
    observability_level: ObservabilityLevel = Field(
        default=ObservabilityLevel.STANDARD,
        description="Observability level: minimal, standard, detailed",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelContractVersion(BaseModel):
    """Semantic version for handler contracts.

    Follows semantic versioning (SemVer) for contract evolution.
    Major version changes indicate breaking changes, minor versions
    add backwards-compatible features, and patch versions are for
    bug fixes only.

    Attributes:
        major: Major version number (breaking changes).
        minor: Minor version number (new features, backwards-compatible).
        patch: Patch version number (bug fixes only).

    Example:
        >>> version = ModelContractVersion(major=1, minor=0, patch=0)
        >>> str(version)
        '1.0.0'
    """

    major: int = Field(..., ge=0, description="Major version (breaking changes)")
    minor: int = Field(
        ..., ge=0, description="Minor version (backwards-compatible features)"
    )
    patch: int = Field(..., ge=0, description="Patch version (bug fixes)")

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __str__(self) -> str:
        """Return version string in SemVer format."""
        return f"{self.major}.{self.minor}.{self.patch}"


class ModelContractMetadata(BaseModel):
    """Metadata for handler contracts.

    Contains authorship, licensing, and categorization information
    for the handler contract. This model matches the nested `metadata`
    structure in the contract YAML.

    Attributes:
        author: Author or team responsible for the handler.
        license: Software license identifier (e.g., MIT, Apache-2.0).
        ticket: Issue/ticket reference for traceability (e.g., OMN-1403).
        tags: List of tags for categorization and discovery.

    Example:
        >>> metadata = ModelContractMetadata(
        ...     author="OmniNode Team",
        ...     license="MIT",
        ...     ticket="OMN-1403",
        ...     tags=["postgresql", "storage", "effect"],
        ... )
    """

    author: str | None = Field(
        default=None,
        description="Author or team responsible for the handler",
    )
    license: str | None = Field(
        default=None,
        description="Software license identifier (e.g., MIT, Apache-2.0)",
    )
    ticket: str | None = Field(
        default=None,
        description="Issue/ticket reference for traceability (e.g., OMN-1403)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="List of tags for categorization and discovery",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelHandlerContract(BaseModel):
    """Complete handler contract schema for YAML validation.

    This is the top-level model for parsing and validating handler contract
    YAML files. It defines the full interface specification for a handler
    including its identity, capabilities, input/output models, and metadata.

    Constructor Signature:
        All handlers registered via this contract MUST accept a single
        `container` argument in their constructor:
        ```python
        def __init__(self, container: Container) -> None:
            ...
        ```

    OmniClaude-Specific Fields:
        - handler_class: Fully qualified Python class for the handler
        - handler_key: Key used for handler routing/lookup
        - protocol: Protocol interface the handler implements

    Validation:
        - Fails fast on invalid contracts (strict validation mode)
        - Extra fields are forbidden to catch typos and schema drift

    Example:
        >>> import yaml
        >>> contract_yaml = '''
        ... handler_id: effect.learned_pattern.storage.postgres
        ... name: Learned Pattern Storage Handler
        ... contract_version:
        ...   major: 1
        ...   minor: 0
        ...   patch: 0
        ... descriptor:
        ...   handler_kind: effect
        ...   purity: side_effecting
        ...   idempotent: true
        ...   timeout_ms: 30000
        ... capability_outputs:
        ...   - learned_pattern.storage.query
        ... input_model: myapp.models.ModelInput
        ... output_model: myapp.models.ModelOutput
        ... handler_class: myapp.handlers.MyHandler
        ... handler_key: postgresql
        ... protocol: myapp.protocols.MyProtocol
        ... '''
        >>> data = yaml.safe_load(contract_yaml)
        >>> contract = ModelHandlerContract(**data)
        >>> contract.handler_id
        'effect.learned_pattern.storage.postgres'

    See Also:
        - contracts/handlers/pattern_storage_postgres/contract.yaml
        - OMN-1605 for contract-driven handler registration loader
    """

    # ==========================================================================
    # Identity
    # ==========================================================================

    handler_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique identifier for registry lookup (e.g., 'effect.pattern.storage.postgres')",
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable display name",
    )

    contract_version: ModelContractVersion = Field(
        ...,
        description="Semantic version of this handler contract",
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional detailed description of the handler",
    )

    # ==========================================================================
    # Behavior Descriptor
    # ==========================================================================

    descriptor: ModelHandlerDescriptor = Field(
        ...,
        description="Handler behavior configuration defining runtime semantics",
    )

    # ==========================================================================
    # Capabilities
    # ==========================================================================

    capability_inputs: list[str] = Field(
        default_factory=list,
        description="Required input capabilities",
    )

    capability_outputs: list[str] = Field(
        default_factory=list,
        description="Provided output capabilities",
    )

    # ==========================================================================
    # Execution
    # ==========================================================================

    input_model: str = Field(
        ...,
        min_length=1,
        description="Fully qualified input model reference",
    )

    output_model: str = Field(
        ...,
        min_length=1,
        description="Fully qualified output model reference",
    )

    # ==========================================================================
    # OmniClaude-Specific: Handler Binding
    # ==========================================================================

    handler_class: str = Field(
        ...,
        min_length=1,
        description="Fully qualified Python class for the handler implementation",
    )

    handler_key: str = Field(
        ...,
        min_length=1,
        description="Key used for handler routing and lookup",
    )

    protocol: str = Field(
        ...,
        min_length=1,
        description="Fully qualified protocol interface the handler implements",
    )

    # ==========================================================================
    # Lifecycle
    # ==========================================================================

    supports_lifecycle: bool = Field(
        default=False,
        description="Handler implements lifecycle hooks (init/shutdown)",
    )

    supports_health_check: bool = Field(
        default=False,
        description="Handler implements health checking",
    )

    supports_provisioning: bool = Field(
        default=False,
        description="Handler can be provisioned/deprovisioned dynamically",
    )

    lazy_load: bool = Field(
        default=False,
        description=(
            "Whether to defer handler instantiation until first use. "
            "NOTE: Not yet implemented - will log warning if True."
        ),
    )

    # ==========================================================================
    # Metadata
    # ==========================================================================

    metadata: ModelContractMetadata = Field(
        default_factory=ModelContractMetadata,
        description="Authorship and categorization metadata",
    )

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    @field_validator("handler_id")
    @classmethod
    def validate_handler_id_format(cls, v: str) -> str:
        """Validate handler_id uses dot-notation with valid segments.

        Args:
            v: The handler_id string.

        Returns:
            The validated handler_id.

        Raises:
            ValueError: If format is invalid.
        """
        if not v or not v.strip():
            raise ValueError("handler_id cannot be empty")

        segments = v.split(".")
        if len(segments) < 2:
            raise ValueError(
                f"handler_id '{v}' must have at least 2 segments (e.g., 'node.name')"
            )

        for segment in segments:
            if not segment:
                raise ValueError(f"handler_id '{v}' contains empty segment")
            if not segment[0].isalpha() and segment[0] != "_":
                raise ValueError(
                    f"handler_id segment '{segment}' must start with letter or underscore"
                )

        return v

    @model_validator(mode="after")
    def warn_lazy_load_not_implemented(self) -> ModelHandlerContract:
        """Log warning if lazy_load is True since it's not yet implemented.

        Returns:
            Self after validation.
        """
        if self.lazy_load:
            logger.warning(
                "lazy_load=True for handler '%s' but lazy loading is not yet implemented. "
                "Handler will be instantiated at registration time.",
                self.handler_id,
            )
        return self


__all__ = [
    # Enums
    "BackoffStrategy",
    "ConcurrencyPolicy",
    "HandlerKind",
    "HandlerPurity",
    "IsolationPolicy",
    "ObservabilityLevel",
    # Models
    "ModelCircuitBreaker",
    "ModelContractMetadata",
    "ModelContractVersion",
    "ModelHandlerContract",
    "ModelHandlerDescriptor",
    "ModelRetryPolicy",
]
