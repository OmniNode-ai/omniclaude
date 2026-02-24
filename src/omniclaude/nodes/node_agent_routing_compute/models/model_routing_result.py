# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Routing result model - output from the agent routing compute node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_agent_routing_compute.models.model_confidence_breakdown import (
    ModelConfidenceBreakdown,
)


class ModelRoutingCandidate(BaseModel):
    """A single routing candidate with confidence breakdown.

    Attributes:
        agent_name: Name of the candidate agent.
        confidence: Overall confidence score.
        confidence_breakdown: Detailed score breakdown.
        match_reason: Why this agent was matched.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(..., description="Name of the candidate agent")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence score"
    )
    confidence_breakdown: ModelConfidenceBreakdown = Field(
        ..., description="Detailed score breakdown"
    )
    match_reason: str = Field(
        default="", max_length=500, description="Why this agent was matched"
    )


class ModelRoutingResult(BaseModel):
    """Output from the agent routing compute node.

    Attributes:
        selected_agent: Name of the selected agent.
        confidence: Overall confidence of the selection (0.0-1.0).
        confidence_breakdown: Detailed score breakdown for the selected agent.
        routing_policy: How the agent was selected.
        routing_path: Infrastructure path used for routing.
        candidates: All evaluated candidates, sorted by confidence descending.
        fallback_reason: Reason if fallback agent was selected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_agent: str = Field(
        ...,
        description="Name of the selected agent",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence of the selection",
    )
    confidence_breakdown: ModelConfidenceBreakdown = Field(
        ...,
        description="Detailed score breakdown for the selected agent",
    )
    routing_policy: Literal["trigger_match", "explicit_request", "fallback_default"] = (
        Field(
            ...,
            description="How the agent was selected",
        )
    )
    routing_path: Literal["event", "local", "hybrid"] = Field(
        ...,
        description="Infrastructure path used for routing",
    )
    candidates: tuple[ModelRoutingCandidate, ...] = Field(
        default=(),
        description="All evaluated candidates, sorted by confidence descending",
    )
    fallback_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Reason if fallback agent was selected",
    )


__all__ = ["ModelRoutingResult", "ModelRoutingCandidate"]
