# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Routing result model — output from the NodeAgentRouter node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_agent_router.models.model_agent_recommendation import (
    ModelAgentRecommendation,
)


class ModelAgentRouterResult(BaseModel):
    """Output from the NodeAgentRouter compute node.

    Wraps the list of AgentRecommendation objects returned by AgentRouter.route().

    Attributes:
        recommendations: Ranked list of agent recommendations (highest confidence first).
        routed: True when at least one recommendation was returned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    recommendations: tuple[ModelAgentRecommendation, ...] = Field(
        default=(),
        description="Ranked agent recommendations, highest confidence first",
    )
    routed: bool = Field(
        ...,
        description="True when at least one recommendation was returned",
    )


__all__ = ["ModelAgentRouterResult"]
