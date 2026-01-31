# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""A/B cohort assignment for pattern injection experiments.

Implements deterministic hash-based cohort assignment per session.
Algorithm: SHA-256(session_id + salt) → first 8 bytes → mod 100

- 0-19: control (20%)
- 20-99: treatment (80%)
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import NamedTuple

# Match omniintelligence constants
COHORT_CONTROL_PERCENTAGE: int = 20
COHORT_TREATMENT_PERCENTAGE: int = 80
COHORT_SALT: str = "omniclaude-injection-v1"


class EnumCohort(str, Enum):
    """A/B experiment cohort."""

    CONTROL = "control"
    TREATMENT = "treatment"


class CohortAssignment(NamedTuple):
    """Result of cohort assignment."""

    cohort: EnumCohort
    assignment_seed: int  # 0-99, deterministic from hash


def assign_cohort(session_id: str) -> CohortAssignment:
    """Assign session to A/B cohort.

    Algorithm: SHA-256(session_id + salt) → first 8 bytes → mod 100
    - 0-19: control (20%)
    - 20-99: treatment (80%)

    Args:
        session_id: Session identifier (any string, including UUIDs).

    Returns:
        CohortAssignment with cohort and seed.
    """
    seed_input = f"{session_id}:{COHORT_SALT}"
    hash_bytes = hashlib.sha256(seed_input.encode("utf-8")).digest()
    assignment_seed = int.from_bytes(hash_bytes[:8], byteorder="big") % 100

    cohort = (
        EnumCohort.CONTROL
        if assignment_seed < COHORT_CONTROL_PERCENTAGE
        else EnumCohort.TREATMENT
    )
    return CohortAssignment(cohort=cohort, assignment_seed=assignment_seed)


__all__ = [
    "COHORT_CONTROL_PERCENTAGE",
    "COHORT_TREATMENT_PERCENTAGE",
    "COHORT_SALT",
    "EnumCohort",
    "CohortAssignment",
    "assign_cohort",
]
