# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Routing result model from the compute node.

Captures the routing decision: which agent was selected, how confident
the system is, and the routing path taken.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .model_confidence_breakdown import ModelConfidenceBreakdown


class ModelRoutingResult(BaseModel):
    """Output from the routing compute node.

    Attributes:
        selected_agent: Name of the selected agent.
        confidence: Overall confidence in the selection (0.0-1.0).
        confidence_breakdown: Detailed per-dimension scoring.
        routing_policy: Why this routing path was chosen.
        routing_path: What canonical routing outcome was used.

    Example:
        >>> result = ModelRoutingResult(
        ...     selected_agent="agent-debug",
        ...     confidence=0.85,
        ...     confidence_breakdown=ModelConfidenceBreakdown(
        ...         total=0.85,
        ...         trigger_score=0.9,
        ...         context_score=0.8,
        ...         capability_score=0.7,
        ...         historical_score=0.6,
        ...         explanation="Strong trigger match on 'debug'",
        ...     ),
        ...     routing_policy="trigger_match",
        ...     routing_path="local",
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_agent: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the selected agent",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in the selection (0.0-1.0)",
    )
    confidence_breakdown: ModelConfidenceBreakdown = Field(
        ...,
        description="Detailed per-dimension scoring",
    )
    routing_policy: Literal["trigger_match", "explicit_request", "fallback_default"] = (
        Field(
            ...,
            description="Why this routing path was chosen",
        )
    )
    routing_path: Literal["event", "local", "hybrid"] = Field(
        ...,
        description="What canonical routing outcome was used",
    )


__all__ = ["ModelRoutingResult"]
