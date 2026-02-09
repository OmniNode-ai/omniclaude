# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Confidence breakdown model - strongly typed replacement for ConfidenceScore dataclass.

Replaces the legacy `ConfidenceScore` dataclass from `confidence_scorer.py`
with a frozen Pydantic model. No dict soup.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelConfidenceBreakdown(BaseModel):
    """Breakdown of confidence score across weighted dimensions.

    Weights (defined in scoring logic, not here):
        - Trigger: 40%
        - Context: 30%
        - Capability: 20%
        - Historical: 10%

    Attributes:
        total: Weighted total confidence (0.0-1.0).
        trigger_score: Trigger matching score (0.0-1.0).
        context_score: Context alignment score (0.0-1.0).
        capability_score: Capability match score (0.0-1.0).
        historical_score: Historical success score (0.0-1.0).
        explanation: Human-readable explanation of the scoring decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Weighted total confidence (0.0-1.0)",
    )
    trigger_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Trigger matching score (0.0-1.0)",
    )
    context_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Context alignment score (0.0-1.0)",
    )
    capability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Capability match score (0.0-1.0)",
    )
    historical_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Historical success score (0.0-1.0)",
    )
    explanation: str = Field(
        ...,
        max_length=1000,
        description="Human-readable explanation of scoring decision",
    )


__all__ = ["ModelConfidenceBreakdown"]
