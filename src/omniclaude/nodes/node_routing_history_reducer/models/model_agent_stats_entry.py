# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Per-agent stats entry model for the routing history reducer.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentStatsEntry(BaseModel):
    """Historical statistics for a single agent.

    Tracks routing success rates and usage patterns for
    informed routing decisions via the historical_score component.

    Attributes:
        agent_name: Name of the agent.
        total_routings: Total number of times this agent was selected.
        successful_routings: Number of successful completions.
        success_rate: Computed success rate (0.0-1.0).
        avg_confidence: Average confidence when selected.
        last_routed_at: When this agent was last selected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(
        ...,
        min_length=1,
        description="Name of the agent",
    )
    total_routings: int = Field(
        default=0,
        ge=0,
        description="Total number of times this agent was selected",
    )
    successful_routings: int = Field(
        default=0,
        ge=0,
        description="Number of successful completions",
    )
    success_rate: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Computed success rate (0.0-1.0)",
    )
    avg_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Average confidence when selected",
    )
    last_routed_at: datetime | None = Field(
        default=None,
        description="When this agent was last selected",
    )


__all__ = ["ModelAgentStatsEntry"]
