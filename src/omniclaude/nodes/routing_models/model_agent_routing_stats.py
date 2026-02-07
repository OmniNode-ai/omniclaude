# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Aggregated routing statistics model.

Contains per-agent statistics entries as evidence for routing decisions.
The reducer node will produce this model from raw routing events.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .model_agent_stats_entry import ModelAgentStatsEntry


class ModelAgentRoutingStats(BaseModel):
    """Aggregated routing statistics across all agents.

    Treat as evidence, not state. The routing compute node uses these
    statistics to inform the historical_score dimension of confidence.

    Attributes:
        entries: Per-agent statistics, keyed by agent name.
        total_decisions: Total routing decisions in the stats window.
        stats_window_seconds: Time window these statistics cover.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[ModelAgentStatsEntry, ...] = Field(
        ...,
        description="Per-agent statistics entries",
    )
    total_decisions: int = Field(
        ...,
        ge=0,
        description="Total routing decisions in the stats window",
    )
    stats_window_seconds: int = Field(
        ...,
        ge=0,
        description="Time window these statistics cover (seconds)",
    )


__all__ = ["ModelAgentRoutingStats"]
