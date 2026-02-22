# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Promotion criteria for OmniMemory pattern eligibility.

Criteria are loaded from configuration (Pydantic Settings / .env) rather
than hardcoded — no magic numbers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelPromotionCriteria(BaseModel):
    """Configurable criteria that a pattern must satisfy for promotion.

    Attributes:
        min_evidence_count: Minimum number of successful evidence bundles
            required before a pattern is eligible for promotion.
            Defaults to 3; override via OMNIMEMORY_MIN_EVIDENCE_COUNT env var.
        require_all_acs_passing: If True, all ACs in the evidence bundles
            must have PASS verdicts for the pattern to be eligible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    min_evidence_count: int = Field(
        default=3,
        ge=1,
        description=(
            "Minimum successful evidence bundles before promotion. "
            "Override via OMNIMEMORY_MIN_EVIDENCE_COUNT env var."
        ),
    )
    require_all_acs_passing: bool = Field(
        default=True,
        description="If True, all ACs must have PASS verdicts for eligibility",
    )


__all__ = ["ModelPromotionCriteria"]
