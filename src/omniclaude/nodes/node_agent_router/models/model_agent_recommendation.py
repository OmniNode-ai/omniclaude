# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Agent recommendation model — typed representation of an AgentRouter recommendation.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentRecommendation(BaseModel):
    """A single agent recommendation from the router.

    Mirrors the AgentRecommendation dataclass from lib/core/agent_router.py
    but as a frozen Pydantic model for ONEX contract compliance.

    Attributes:
        agent_name: Internal agent identifier (e.g. "agent-debug").
        agent_title: Human-readable agent title.
        confidence: Overall confidence score (0.0-1.0).
        trigger_score: Trigger matching component of the confidence score.
        context_score: Context relevance component of the confidence score.
        capability_score: Capability match component of the confidence score.
        historical_score: Historical usage component of the confidence score.
        confidence_explanation: Human-readable explanation of the score.
        reason: Primary reason this agent was matched.
        definition_path: Absolute path to the agent definition YAML file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(..., description="Internal agent identifier")
    agent_title: str = Field(..., description="Human-readable agent title")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence score"
    )
    trigger_score: float = Field(
        ..., ge=0.0, le=1.0, description="Trigger matching component"
    )
    context_score: float = Field(
        ..., ge=0.0, le=1.0, description="Context relevance component"
    )
    capability_score: float = Field(
        ..., ge=0.0, le=1.0, description="Capability match component"
    )
    historical_score: float = Field(
        ..., ge=0.0, le=1.0, description="Historical usage component"
    )
    confidence_explanation: str = Field(
        default="",
        max_length=500,
        description="Human-readable explanation of the score",
    )
    reason: str = Field(
        default="",
        max_length=500,
        description="Primary reason this agent was matched",
    )
    definition_path: str = Field(
        default="",
        description="Absolute path to the agent definition YAML file",
    )


__all__ = ["ModelAgentRecommendation"]
