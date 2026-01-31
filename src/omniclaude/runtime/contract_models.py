# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for contract publishing configuration and results.

This module provides typed models for the contract publisher:

- ContractPublisherConfig: Pydantic model for explicit source configuration
- ContractError: Dataclass for contract-level errors (non-fatal, degraded mode)
- InfraError: Dataclass for infrastructure errors (fatal by default)
- PublishResult: Dataclass for publish operation results with separated error types

Design Principles:
    1. Explicit configuration - no magic path resolution
    2. Separated error taxonomy - contract vs infrastructure errors
    3. Immutable types - all dataclasses are frozen
    4. Validation at construction - catch errors early

Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class ContractPublisherConfig(BaseModel):
    """Configuration for contract publishing.

    Enforces explicit source configuration - no magic paths allowed.
    The publisher requires at least one concrete source to be configured
    based on the selected mode.

    Attributes:
        mode: Publishing mode determining which sources are used.
            - "filesystem": Read contracts from filesystem_root directory
            - "package": Read contracts from package_module using importlib.resources
            - "composite": Use both filesystem and package sources
        filesystem_root: Root directory for filesystem mode. Must be set
            when mode is "filesystem" or optionally for "composite".
        package_module: Fully qualified module name for package mode (e.g.,
            "mypackage.contracts"). Must be set when mode is "package" or
            optionally for "composite".
        fail_fast: If True (default), infrastructure errors raise immediately.
            If False, infrastructure errors are collected in PublishResult.infra_errors.
        allow_zero_contracts: If False (default), finding zero contracts is an error.
            If True, empty publish results are allowed.

    Example:
        >>> # Filesystem mode - read from local directory
        >>> config = ContractPublisherConfig(
        ...     mode="filesystem",
        ...     filesystem_root=Path("/app/contracts/handlers"),
        ... )

        >>> # Package mode - read from installed package
        >>> config = ContractPublisherConfig(
        ...     mode="package",
        ...     package_module="omniclaude.contracts.handlers",
        ... )

        >>> # Composite mode - read from both sources
        >>> config = ContractPublisherConfig(
        ...     mode="composite",
        ...     filesystem_root=Path("/app/contracts/handlers"),
        ...     package_module="omniclaude.contracts.handlers",
        ... )

    Raises:
        ValueError: If the required source for the mode is not configured.
    """

    mode: Literal["filesystem", "package", "composite"]
    filesystem_root: Path | None = None
    package_module: str | None = None
    fail_fast: bool = True  # Infra errors are fatal by default
    allow_zero_contracts: bool = False  # Empty publish is error by default

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_source_configured(self) -> Self:
        """Ensure at least one concrete source is configured for the mode."""
        match self.mode:
            case "filesystem":
                if not self.filesystem_root:
                    raise ValueError("filesystem mode requires filesystem_root")
            case "package":
                if not self.package_module:
                    raise ValueError("package mode requires package_module")
            case "composite":
                if not self.filesystem_root and not self.package_module:
                    raise ValueError("composite mode requires at least one source")
        return self


@dataclass(frozen=True)
class ContractError:
    """Error from contract parsing/validation (non-fatal, degraded mode).

    Contract errors represent issues with individual contract files. These
    errors are non-fatal - the publisher will skip the problematic contract
    and continue processing others.

    Attributes:
        contract_path: Path or identifier of the contract that failed.
        error_type: Category of the error for programmatic handling.
            - "yaml_parse": YAML syntax error in contract file
            - "schema_validation": Contract doesn't match expected schema
            - "missing_field": Required field (e.g., handler_id) is missing
            - "invalid_handler_class": handler_class is not fully qualified
        message: Human-readable error description with details.

    Example:
        >>> error = ContractError(
        ...     contract_path="handlers/my_handler/contract.yaml",
        ...     error_type="missing_field",
        ...     message="Contract missing required field: handler_id",
        ... )
    """

    contract_path: str
    error_type: Literal[
        "yaml_parse", "schema_validation", "missing_field", "invalid_handler_class"
    ]
    message: str


@dataclass(frozen=True)
class InfraError:
    """Error from infrastructure (Kafka, network - fatal by default).

    Infrastructure errors represent systemic issues that typically prevent
    the entire publish operation from succeeding. By default (fail_fast=True),
    these errors raise immediately. When fail_fast=False, they are collected
    in PublishResult.infra_errors.

    Attributes:
        error_type: Category of the infrastructure error.
            - "publisher_unavailable": Event bus publisher not in container
            - "kafka_timeout": Kafka operation timed out
            - "broker_down": Kafka broker is unreachable
            - "publish_failed": Generic publish failure
        message: Human-readable error description with details.
        retriable: Whether the operation might succeed on retry. Default False.

    Example:
        >>> error = InfraError(
        ...     error_type="kafka_timeout",
        ...     message="Kafka publish timed out after 30s",
        ...     retriable=True,
        ... )
    """

    error_type: Literal[
        "publisher_unavailable", "kafka_timeout", "broker_down", "publish_failed"
    ]
    message: str
    retriable: bool = False


@dataclass(frozen=True)
class PublishResult:
    """Result of contract publishing with separated error types.

    This dataclass captures the complete outcome of a publish operation,
    including successful publishes and categorized errors.

    Attributes:
        published: List of handler IDs that were successfully published.
        contract_errors: List of contract-level errors (non-fatal).
            These represent issues with individual contracts.
        infra_errors: List of infrastructure errors (fatal by default).
            These represent systemic issues. Only populated when fail_fast=False.
        duration_ms: Total duration of the publish operation in milliseconds.

    Example:
        >>> result = PublishResult(
        ...     published=["handler.persistence.qdrant", "handler.cache.redis"],
        ...     contract_errors=[
        ...         ContractError(
        ...             contract_path="handlers/broken/contract.yaml",
        ...             error_type="yaml_parse",
        ...             message="Invalid YAML: expected ':' at line 5",
        ...         )
        ...     ],
        ...     infra_errors=[],
        ...     duration_ms=245.7,
        ... )
        >>> print(f"Published {len(result.published)} contracts in {result.duration_ms}ms")
        Published 2 contracts in 245.7ms
    """

    published: list[str]
    contract_errors: list[ContractError]
    infra_errors: list[InfraError]
    duration_ms: float
