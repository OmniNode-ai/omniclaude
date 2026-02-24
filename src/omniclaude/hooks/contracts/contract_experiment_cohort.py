# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Pydantic backing model for the experiment cohort contract.

This module provides type-safe access to the experiment cohort configuration
defined in contract_experiment_cohort.yaml. It replaces manual yaml.safe_load +
isinstance checks with validated Pydantic models.

The contract defines A/B experiment parameters for pattern injection, including:
- Cohort split configuration (control percentage, salt)
- Environment variable overrides for ops flexibility
- Invariants enforced at load time via Pydantic validators

Usage:
    >>> from omniclaude.hooks.contracts.contract_experiment_cohort import (
    ...     ExperimentCohortContract,
    ... )
    >>> contract = ExperimentCohortContract.load()
    >>> print(contract.experiment.cohort.control_percentage)
    20
    >>> print(contract.experiment.cohort.salt)
    'omniclaude-injection-v1'

See Also:
    - contract_experiment_cohort.yaml for the source YAML contract
    - OMN-1674: INJECT-005 A/B cohort assignment
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Nested Models
# =============================================================================


class Version(BaseModel):
    """Semantic version model for contract versioning.

    Attributes:
        major: Major version number (breaking changes).
        minor: Minor version number (backwards-compatible additions).
        patch: Patch version number (backwards-compatible bug fixes).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    major: int = Field(
        ...,
        ge=0,
        description="Major version number (breaking changes)",
    )
    minor: int = Field(
        ...,
        ge=0,
        description="Minor version number (backwards-compatible additions)",
    )
    patch: int = Field(
        ...,
        ge=0,
        description="Patch version number (backwards-compatible bug fixes)",
    )

    def __str__(self) -> str:
        """Return version as semver string."""
        return f"{self.major}.{self.minor}.{self.patch}"


class Cohort(BaseModel):
    """Cohort split configuration for A/B experiment.

    Invariants (enforced by Pydantic validators):
        - control_percentage must be 0-100 inclusive
        - salt must be non-empty for deterministic hashing

    Attributes:
        control_percentage: Percentage of sessions assigned to control (no injection).
            Valid range: 0-100. Default: 20 (20% control, 80% treatment).
        salt: Salt for deterministic hash-based assignment. Change this value to
            reset the experiment and re-randomize assignments.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    control_percentage: int = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "Percentage of sessions assigned to control (no injection). "
            "Valid range: 0-100. Default: 20 (20% control, 80% treatment)."
        ),
    )
    salt: str = Field(
        ...,
        min_length=1,
        description=(
            "Salt for deterministic hash-based assignment. "
            "Change this value to reset the experiment and re-randomize assignments."
        ),
    )


class EnvOverrides(BaseModel):
    """Environment variable overrides for runtime configuration.

    These environment variables can override contract defaults at runtime,
    providing ops flexibility without contract changes.

    Attributes:
        control_percentage: Environment variable name for control percentage override.
        salt: Environment variable name for salt override.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    control_percentage: str = Field(
        ...,
        min_length=1,
        description="Environment variable name for control percentage override",
    )
    salt: str = Field(
        ...,
        min_length=1,
        description="Environment variable name for salt override",
    )


class Experiment(BaseModel):
    """Experiment configuration containing identity, randomization, and cohort settings.

    Attributes:
        name: Experiment identity (e.g., 'pattern_injection_v1').
        randomization_unit: Unit for randomization (e.g., 'session_id').
        assignment_method: Method for cohort assignment (e.g., 'hash_mod').
        cohort: Cohort split configuration.
        env_overrides: Environment variable overrides for runtime configuration.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Experiment identity (e.g., 'pattern_injection_v1')",
    )
    randomization_unit: str = Field(
        ...,
        min_length=1,
        description="Unit for randomization (e.g., 'session_id')",
    )
    assignment_method: str = Field(
        ...,
        min_length=1,
        description="Method for cohort assignment (e.g., 'hash_mod')",
    )
    cohort: Cohort = Field(
        ...,
        description="Cohort split configuration",
    )
    env_overrides: EnvOverrides = Field(
        ...,
        description="Environment variable overrides for runtime configuration",
    )


class Invariant(BaseModel):
    """Invariant definition for contract validation rules.

    Invariants are enforced at load time. The rules are expressed as
    human-readable pseudo-code and enforced via Pydantic Field constraints.

    Attributes:
        name: Invariant identifier (e.g., 'control_percentage_range').
        description: Human-readable description of the invariant.
        rule: Pseudo-code rule expression for documentation.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Invariant identifier (e.g., 'control_percentage_range')",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the invariant",
    )
    rule: str = Field(
        ...,
        min_length=1,
        description="Pseudo-code rule expression for documentation",
    )


class Auditability(BaseModel):
    """Auditability requirements for experiment tracking.

    Defines what values must be stamped into records for replay and debugging.

    Attributes:
        stamp_into_record: List of field names to stamp into every injection record.
        rationale: Explanation of why these fields are required for auditability.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    stamp_into_record: list[str] = Field(
        ...,
        min_length=1,
        description="List of field names to stamp into every injection record",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Explanation of why these fields are required for auditability",
    )


class Metadata(BaseModel):
    """Contract metadata for documentation and tracking.

    Attributes:
        author: Author or team responsible for the contract.
        license: License under which the contract is released.
        created: Creation date in ISO format (YYYY-MM-DD).
        ticket: Associated ticket or issue number (e.g., 'OMN-1674').
        tags: List of tags for categorization and search.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    author: str = Field(
        ...,
        min_length=1,
        description="Author or team responsible for the contract",
    )
    license: str = Field(
        ...,
        min_length=1,
        description="License under which the contract is released",
    )
    created: str = Field(
        ...,
        min_length=1,
        description="Creation date in ISO format (YYYY-MM-DD)",
    )
    ticket: str = Field(
        ...,
        min_length=1,
        description="Associated ticket or issue number (e.g., 'OMN-1674')",
    )
    tags: list[str] = Field(
        ...,
        min_length=1,
        description="List of tags for categorization and search",
    )


# =============================================================================
# Root Contract Model
# =============================================================================


class ExperimentCohortContract(BaseModel):
    """Root model for the experiment cohort contract.

    This model validates the entire contract_experiment_cohort.yaml structure
    and provides type-safe access to all configuration values.

    Invariants (enforced by nested Pydantic models):
        - control_percentage_range: 0 <= cohort.control_percentage <= 100
        - salt_non_empty: len(cohort.salt) > 0

    Attributes:
        name: Contract name identifier.
        contract_name: Contract name (typically same as name).
        node_name: Node name for ONEX compatibility.
        version: Semantic version of the contract.
        contract_version: Contract semantic version (optional, typically same as version).
        description: Human-readable description of the contract purpose.
        experiment: Experiment configuration with cohort settings.
        invariants: List of invariants enforced by the contract.
        auditability: Auditability requirements for replay/debugging.
        metadata: Contract metadata for documentation and tracking.

    Example:
        >>> contract = ExperimentCohortContract.load()
        >>> contract.experiment.cohort.control_percentage
        20
        >>> contract.experiment.cohort.salt
        'omniclaude-injection-v1'
        >>> contract.experiment.env_overrides.control_percentage
        'OMNICLAUDE_COHORT_CONTROL_PERCENTAGE'
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
    contract_version: Version | None = Field(
        default=None,
        description="Contract semantic version (typically same as version, optional)",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the contract purpose",
    )
    experiment: Experiment = Field(
        ...,
        description="Experiment configuration with cohort settings",
    )
    invariants: list[Invariant] = Field(
        ...,
        min_length=1,
        description="List of invariants enforced by the contract",
    )
    auditability: Auditability = Field(
        ...,
        description="Auditability requirements for replay/debugging",
    )
    metadata: Metadata = Field(
        ...,
        description="Contract metadata for documentation and tracking",
    )

    @classmethod
    def load(cls, path: Path | None = None) -> Self:
        """Load and validate the experiment cohort contract from YAML.

        Args:
            path: Optional path to the YAML contract file. If not provided,
                defaults to contract_experiment_cohort.yaml in the same directory.

        Returns:
            Validated ExperimentCohortContract instance.

        Raises:
            FileNotFoundError: If the contract file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            pydantic.ValidationError: If the contract fails validation.

        Example:
            >>> contract = ExperimentCohortContract.load()
            >>> contract.experiment.cohort.control_percentage
            20
        """
        if path is None:
            path = Path(__file__).parent / "contract_experiment_cohort.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.model_validate(data)


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Nested models
    "Version",
    "Cohort",
    "EnvOverrides",
    "Experiment",
    "Invariant",
    "Auditability",
    "Metadata",
    # Root contract
    "ExperimentCohortContract",
]
