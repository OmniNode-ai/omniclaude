# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Emission request model - input to the routing emission effect node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniclaude.nodes.node_agent_routing_compute.models.model_confidence_breakdown import (
    ModelConfidenceBreakdown,
)


class ModelEmissionRequest(BaseModel):
    """Request to emit a routing decision event.

    Contains the routing decision data to be emitted to Kafka topics
    for observability and intelligence processing.

    Attributes:
        correlation_id: Correlation ID for request tracing.
        session_id: Claude Code session ID.
        selected_agent: Name of the selected agent.
        confidence: Overall confidence of the selection.
        confidence_breakdown: Detailed score breakdown.
        routing_policy: How the agent was selected.
        routing_path: Infrastructure path used.
        prompt_preview: Sanitized prompt preview (max 100 chars).
        prompt_length: Full prompt length for analytics.
        emitted_at: Explicit emission timestamp (no datetime.now() defaults).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for request tracing",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Claude Code session ID",
    )
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
        description="Detailed score breakdown",
    )
    routing_policy: Literal["trigger_match", "explicit_request", "fallback_default"] = (
        Field(
            ...,
            description="How the agent was selected",
        )
    )
    routing_path: Literal["event", "local", "hybrid"] = Field(
        ...,
        description="Infrastructure path used",
    )
    prompt_preview: str = Field(
        ...,
        max_length=100,
        description="Sanitized prompt preview (max 100 chars)",
    )
    prompt_length: int = Field(
        ...,
        ge=0,
        description="Full prompt length for analytics",
    )
    emitted_at: datetime = Field(
        ...,
        description="Explicit emission timestamp (no datetime.now() defaults)",
    )

    @field_validator("emitted_at")
    @classmethod
    def _require_timezone_aware(cls, v: datetime) -> datetime:
        """Reject naive datetimes to enforce the explicit-timestamp invariant."""
        if v.tzinfo is None:
            raise ValueError("emitted_at must be timezone-aware (got naive datetime)")
        return v


__all__ = ["ModelEmissionRequest"]
