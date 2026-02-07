# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Routing request model for the compute node.

Captures all inputs needed to make a routing decision: the user prompt,
available agents, optional historical statistics, and the confidence
threshold for accepting a match.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .model_agent_definition import ModelAgentDefinition
from .model_agent_routing_stats import ModelAgentRoutingStats


class ModelRoutingRequest(BaseModel):
    """Input to the routing compute node.

    Attributes:
        prompt: The user prompt to route.
        correlation_id: Unique identifier for tracing this routing decision.
        agent_registry: Available agents for routing consideration.
        historical_stats: Optional historical routing statistics as evidence.
        confidence_threshold: Minimum confidence to accept a match (0.0-1.0).

    Example:
        >>> from uuid import uuid4
        >>> req = ModelRoutingRequest(
        ...     prompt="help me debug this error",
        ...     correlation_id=uuid4(),
        ...     agent_registry=(
        ...         ModelAgentDefinition(
        ...             name="agent-debug",
        ...             agent_type="debug",
        ...             description="Debug agent",
        ...             explicit_triggers=("debug", "error"),
        ...         ),
        ...     ),
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(
        ...,
        min_length=1,
        description="The user prompt to route",
    )
    correlation_id: UUID = Field(
        ...,
        description="Unique identifier for tracing this routing decision",
    )
    agent_registry: tuple[ModelAgentDefinition, ...] = Field(
        ...,
        description="Available agents for routing consideration",
    )
    historical_stats: ModelAgentRoutingStats | None = Field(
        default=None,
        description="Optional historical routing statistics as evidence",
    )
    confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept a match (0.0-1.0)",
    )


__all__ = ["ModelRoutingRequest"]
