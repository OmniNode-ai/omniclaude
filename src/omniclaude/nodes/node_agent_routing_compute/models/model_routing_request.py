# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Routing request model - input to the agent routing compute node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_agent_routing_compute.models.model_agent_definition import (
    ModelAgentDefinition,
)
from omniclaude.nodes.node_routing_history_reducer.models.model_agent_routing_stats import (
    ModelAgentRoutingStats,
)


class ModelRoutingRequest(BaseModel):
    """Input to the agent routing compute node.

    Contains the user prompt, available agent registry, and optional
    historical statistics for informed routing decisions.

    Attributes:
        prompt: User's input text to route.
        correlation_id: Correlation ID for request tracing.
        agent_registry: Tuple of available agent definitions.
        historical_stats: Optional historical routing statistics.
        confidence_threshold: Minimum confidence to accept a match (0.0-1.0).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(
        ...,
        min_length=1,
        description="User's input text to route",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for request tracing",
    )
    agent_registry: tuple[ModelAgentDefinition, ...] = Field(
        ...,
        description="Available agent definitions for routing",
    )
    historical_stats: ModelAgentRoutingStats | None = Field(
        default=None,
        description="Optional historical routing statistics",
    )
    confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept a match",
    )


__all__ = ["ModelRoutingRequest"]
