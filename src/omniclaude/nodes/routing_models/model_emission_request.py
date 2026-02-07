# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Emission request model for the effect node.

Captures the data needed to emit a routing decision event to the
event bus (Kafka). The effect node translates this into the
appropriate topic and schema.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .model_confidence_breakdown import ModelConfidenceBreakdown


class ModelEmissionRequest(BaseModel):
    """Input to the emission effect node.

    Attributes:
        correlation_id: Trace identifier for the routing decision.
        session_id: Claude Code session identifier.
        selected_agent: Name of the agent that was selected.
        confidence: Overall confidence in the selection (0.0-1.0).
        confidence_breakdown: Detailed per-dimension scoring.
        routing_policy: Why this routing path was chosen.
        routing_path: What canonical routing outcome was used.
        topic: Target Kafka topic kind for emission.
        prompt_preview: Sanitized preview of the prompt (max 100 chars).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID = Field(
        ...,
        description="Trace identifier for the routing decision",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Claude Code session identifier",
    )
    selected_agent: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the agent that was selected",
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
    topic: Literal["evt", "cmd"] = Field(
        ...,
        description="Target Kafka topic kind for emission",
    )
    prompt_preview: str = Field(
        ...,
        max_length=100,
        description="Sanitized preview of the prompt (max 100 chars)",
    )


__all__ = ["ModelEmissionRequest"]
