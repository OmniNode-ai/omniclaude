# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""A/B cohort assignment for pattern injection experiments.

Implements deterministic hash-based cohort assignment per session.
Algorithm: SHA-256(session_id + salt) → first 8 bytes → mod 100

Configuration hierarchy (contract-first with env override):
1. Contract defaults: contracts/contract_experiment_cohort.yaml
2. Environment overrides: OMNICLAUDE_COHORT_* (optional, for ops flexibility)

Default configuration:
- 0-19: control (20%)
- 20-99: treatment (80%)

Environment variables (override contract defaults):
    OMNICLAUDE_COHORT_CONTROL_PERCENTAGE: Control group percentage (0-100)
    OMNICLAUDE_COHORT_SALT: Hash salt for cohort assignment

Part of OMN-1674: INJECT-005 A/B cohort assignment
"""

from __future__ import annotations

import hashlib
import logging
import os
from enum import Enum
from typing import NamedTuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from omniclaude.hooks.contracts.contract_experiment_cohort import (
    ExperimentCohortContract,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Hardcoded Fallbacks (SINGLE SOURCE for when contract is unavailable)
# =============================================================================
# These values are ONLY used if the contract YAML cannot be loaded.
# The contract file is the true source of truth.
_FALLBACK_CONTROL_PERCENTAGE: int = 20
_FALLBACK_SALT: str = "omniclaude-injection-v1"


class _ContractDefaults(NamedTuple):
    """Typed container for contract defaults."""

    control_percentage: int
    salt: str


def _load_contract_defaults() -> _ContractDefaults:
    """Load default values from contract YAML using Pydantic model.

    Returns:
        _ContractDefaults with 'control_percentage' and 'salt' from contract.
        Falls back to module-level fallbacks if contract unavailable.
    """
    try:
        contract = ExperimentCohortContract.load()
        return _ContractDefaults(
            control_percentage=contract.experiment.cohort.control_percentage,
            salt=contract.experiment.cohort.salt,
        )
    except Exception as e:
        logger.warning(f"Failed to load cohort contract, using fallbacks: {e}")
        return _ContractDefaults(
            control_percentage=_FALLBACK_CONTROL_PERCENTAGE,
            salt=_FALLBACK_SALT,
        )


# =============================================================================
# Module-Level Constants (loaded from contract at import time)
# =============================================================================
# These are the canonical defaults derived from the contract YAML.
# Use these constants for Field defaults and anywhere defaults are needed.

_CONTRACT_DEFAULTS = _load_contract_defaults()

#: Default control percentage from contract (or fallback if unavailable)
CONTRACT_DEFAULT_CONTROL_PERCENTAGE: int = _CONTRACT_DEFAULTS.control_percentage

#: Default salt from contract (or fallback if unavailable)
CONTRACT_DEFAULT_SALT: str = _CONTRACT_DEFAULTS.salt


# =============================================================================
# Legacy Constants (Deprecated)
# =============================================================================
# DEPRECATED: These constants are kept for backward compatibility only.
# Use CohortAssignmentConfig for new code. These will be removed in a future version.
# Now derived from contract-loaded values for consistency.

COHORT_CONTROL_PERCENTAGE: int = CONTRACT_DEFAULT_CONTROL_PERCENTAGE
COHORT_TREATMENT_PERCENTAGE: int = 100 - CONTRACT_DEFAULT_CONTROL_PERCENTAGE
COHORT_SALT: str = CONTRACT_DEFAULT_SALT


# =============================================================================
# Configuration
# =============================================================================


class CohortAssignmentConfig(BaseSettings):
    """Configuration for A/B cohort assignment.

    Configuration hierarchy (contract-first with env override):
    1. Contract defaults: contracts/contract_experiment_cohort.yaml
    2. Environment overrides: OMNICLAUDE_COHORT_* (optional)

    The contract is the source of truth for behavioral parameters.
    Environment variables are the escape hatch for ops flexibility.

    Environment variables use the OMNICLAUDE_COHORT_ prefix:
        OMNICLAUDE_COHORT_CONTROL_PERCENTAGE
        OMNICLAUDE_COHORT_SALT

    Attributes:
        control_percentage: Percentage of sessions assigned to control group (0-100).
        salt: Salt string used in hash computation for deterministic assignment.

    Example:
        >>> config = CohortAssignmentConfig.from_contract()
        >>> config.control_percentage
        20
        >>> config.treatment_percentage
        80

        # Override via environment (optional):
        # OMNICLAUDE_COHORT_CONTROL_PERCENTAGE=50
        >>> config = CohortAssignmentConfig.from_contract()
        >>> config.control_percentage
        50
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_COHORT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    control_percentage: int = Field(
        default=CONTRACT_DEFAULT_CONTROL_PERCENTAGE,
        ge=0,
        le=100,
        description="Percentage of sessions assigned to control group (0-100)",
    )

    salt: str = Field(
        default=CONTRACT_DEFAULT_SALT,
        min_length=1,
        description="Salt string for deterministic hash-based assignment",
    )

    @property
    def treatment_percentage(self) -> int:
        """Calculate treatment percentage as complement of control.

        Returns:
            Treatment group percentage (100 - control_percentage).
        """
        return 100 - self.control_percentage

    @classmethod
    def from_contract(cls) -> CohortAssignmentConfig:
        """Load configuration from contract with env override.

        Priority order:
        1. Environment variables (if set) - highest priority
        2. Contract YAML values - source of truth
        3. Hardcoded defaults - fallback

        Returns:
            Configuration instance with contract defaults and env overrides.
        """
        # Load contract defaults
        contract_defaults = _load_contract_defaults()

        # Check for env overrides
        env_control = os.environ.get("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE")
        env_salt = os.environ.get("OMNICLAUDE_COHORT_SALT")

        # Build config with contract defaults, env overrides win
        control_pct: int = contract_defaults.control_percentage
        if env_control is not None:
            try:
                parsed = float(env_control)
                if parsed != int(parsed):
                    # Value is a float like "35.5" - must be an integer
                    logger.warning(
                        f"OMNICLAUDE_COHORT_CONTROL_PERCENTAGE must be an integer, "
                        f"got float '{env_control}', using contract default {control_pct}"
                    )
                else:
                    control_pct = int(parsed)
            except ValueError:
                # Value is not a valid number at all
                logger.warning(
                    f"OMNICLAUDE_COHORT_CONTROL_PERCENTAGE is not a valid number: "
                    f"'{env_control}', using contract default {control_pct}"
                )

        salt: str = env_salt if env_salt is not None else contract_defaults.salt

        return cls(control_percentage=control_pct, salt=salt)

    @classmethod
    def from_env(cls) -> CohortAssignmentConfig:
        """Load configuration from environment variables.

        DEPRECATED: Use from_contract() for contract-first loading.

        Returns:
            Configuration instance populated from environment.
        """
        return cls.from_contract()


class EnumCohort(str, Enum):
    """A/B experiment cohort."""

    CONTROL = "control"
    TREATMENT = "treatment"


class CohortAssignment(NamedTuple):
    """Result of cohort assignment."""

    cohort: EnumCohort
    assignment_seed: int  # 0-99, deterministic from hash


def assign_cohort(
    session_id: str,
    config: CohortAssignmentConfig | None = None,
) -> CohortAssignment:
    """Assign session to A/B cohort.

    Algorithm: SHA-256(session_id + salt) → first 8 bytes → mod 100

    The control/treatment split is determined by the configuration:
    - 0 to (control_percentage - 1): control
    - control_percentage to 99: treatment

    Args:
        session_id: Session identifier (any string, including UUIDs).
        config: Optional configuration. If None, loads from environment
            or uses defaults.

    Returns:
        CohortAssignment with cohort and seed.

    Example:
        >>> # Using defaults
        >>> assignment = assign_cohort("session-123")

        >>> # Using custom config
        >>> config = CohortAssignmentConfig(control_percentage=50)
        >>> assignment = assign_cohort("session-123", config=config)
    """
    if config is None:
        config = CohortAssignmentConfig.from_contract()

    seed_input = f"{session_id}:{config.salt}"
    hash_bytes = hashlib.sha256(seed_input.encode("utf-8")).digest()
    assignment_seed = int.from_bytes(hash_bytes[:8], byteorder="big") % 100

    cohort = (
        EnumCohort.CONTROL
        if assignment_seed < config.control_percentage
        else EnumCohort.TREATMENT
    )
    return CohortAssignment(cohort=cohort, assignment_seed=assignment_seed)


__all__ = [
    # Configuration
    "CohortAssignmentConfig",
    # Functions
    "assign_cohort",
    # Types
    "EnumCohort",
    "CohortAssignment",
    # Contract-derived constants (canonical defaults)
    "CONTRACT_DEFAULT_CONTROL_PERCENTAGE",
    "CONTRACT_DEFAULT_SALT",
    # Legacy constants (deprecated - use CohortAssignmentConfig instead)
    "COHORT_CONTROL_PERCENTAGE",
    "COHORT_TREATMENT_PERCENTAGE",
    "COHORT_SALT",
]
