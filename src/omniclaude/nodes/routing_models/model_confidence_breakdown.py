# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Confidence breakdown model for routing decisions.

Replaces the legacy ``ConfidenceScore`` dataclass in ``agent_router.py``
with a frozen Pydantic model. Each dimension score is bounded [0.0, 1.0].

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelConfidenceBreakdown(BaseModel):
    """Detailed confidence scoring breakdown for a routing decision.

    Each score represents a dimension of the routing confidence calculation.
    The ``total`` is the weighted aggregate; individual scores explain
    which dimensions contributed most.

    Attributes:
        total: Weighted aggregate confidence (0.0-1.0).
        trigger_score: Trigger matching quality (0.0-1.0).
        context_score: Context alignment quality (0.0-1.0).
        capability_score: Capability relevance (0.0-1.0).
        historical_score: Historical performance (0.0-1.0).
        explanation: Human-readable explanation of the scoring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Weighted aggregate confidence (0.0-1.0)",
    )
    trigger_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Trigger matching quality (0.0-1.0)",
    )
    context_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Context alignment quality (0.0-1.0)",
    )
    capability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Capability relevance (0.0-1.0)",
    )
    historical_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Historical performance (0.0-1.0)",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable explanation of the scoring",
    )


__all__ = ["ModelConfidenceBreakdown"]
