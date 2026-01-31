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
import os
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# Legacy Constants (Deprecated)
# =============================================================================
# DEPRECATED: These constants are kept for backward compatibility only.
# Use CohortAssignmentConfig for new code. These will be removed in a future version.

# Match omniintelligence constants
COHORT_CONTROL_PERCENTAGE: int = 20
COHORT_TREATMENT_PERCENTAGE: int = 80
COHORT_SALT: str = "omniclaude-injection-v1"


# =============================================================================
# Configuration
# =============================================================================


# Contract file path (relative to this module)
_CONTRACT_PATH = Path(__file__).parent / "contracts" / "contract_experiment_cohort.yaml"


def _load_contract_defaults() -> dict[str, int | str]:
    """Load default values from contract YAML.

    Returns:
        Dict with 'control_percentage' and 'salt' from contract.
        Falls back to hardcoded defaults if contract unavailable.
    """
    defaults = {"control_percentage": 20, "salt": "omniclaude-injection-v1"}

    if not _CONTRACT_PATH.exists():
        return defaults

    try:
        with open(_CONTRACT_PATH) as f:
            contract = yaml.safe_load(f)
        experiment = contract.get("experiment", {})
        cohort = experiment.get("cohort", {})

        if "control_percentage" in cohort:
            defaults["control_percentage"] = cohort["control_percentage"]
        if "salt" in cohort:
            defaults["salt"] = cohort["salt"]
    except (OSError, yaml.YAMLError):
        # Contract unavailable or malformed - use hardcoded defaults
        pass

    return defaults


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
        default=20,
        ge=0,
        le=100,
        description="Percentage of sessions assigned to control group (0-100)",
    )

    salt: str = Field(
        default="omniclaude-injection-v1",
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
        control_pct = (
            int(env_control)
            if env_control is not None
            else contract_defaults["control_percentage"]
        )
        salt = env_salt if env_salt is not None else contract_defaults["salt"]

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
        config = CohortAssignmentConfig()

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
    # Legacy constants (deprecated - use CohortAssignmentConfig instead)
    "COHORT_CONTROL_PERCENTAGE",
    "COHORT_TREATMENT_PERCENTAGE",
    "COHORT_SALT",
]
