# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Per-agent statistics entry for routing decisions.

Captures historical performance metrics for a single agent. Used as
evidence in routing decisions, not mutable state.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentStatsEntry(BaseModel):
    """Historical performance statistics for a single agent.

    Treat as evidence, not state. These values inform routing confidence
    but do not drive routing logic directly.

    Attributes:
        agent_name: Internal agent identifier.
        total_routes: Total number of times this agent was selected.
        success_count: Number of successful routing outcomes.
        success_rate: Historical success rate (0.0-1.0).
        avg_confidence: Average confidence when selected (0.0-1.0).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Internal agent identifier",
    )
    total_routes: int = Field(
        ...,
        ge=0,
        description="Total number of times this agent was selected",
    )
    success_count: int = Field(
        ...,
        ge=0,
        description="Number of successful routing outcomes",
    )
    success_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Historical success rate (0.0-1.0)",
    )
    avg_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Average confidence when selected (0.0-1.0)",
    )


__all__ = ["ModelAgentStatsEntry"]
