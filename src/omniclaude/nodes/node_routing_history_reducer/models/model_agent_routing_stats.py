# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Aggregate routing statistics model for the routing history reducer.

Model ownership: PRIVATE to omniclaude.

Invariant: This model is EVIDENCE, not STATE. It is a read-only snapshot
of historical routing performance used as input to confidence scoring.
No mutation methods allowed.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_routing_history_reducer.models.model_agent_stats_entry import (
    ModelAgentStatsEntry,
)


class ModelAgentRoutingStats(BaseModel):
    """Aggregate routing statistics across all agents.

    Provides historical performance data as input to the
    historical_score component (10% weight) of confidence scoring.

    Attributes:
        entries: Per-agent statistics entries.
        total_routing_decisions: Total routing decisions recorded.
        snapshot_at: When this statistics snapshot was taken.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[ModelAgentStatsEntry, ...] = Field(
        default=(),
        description="Per-agent statistics entries",
    )
    total_routing_decisions: int = Field(
        default=0,
        ge=0,
        description="Total routing decisions recorded",
    )
    snapshot_at: datetime | None = Field(
        default=None,
        description="When this statistics snapshot was taken",
    )


__all__ = ["ModelAgentRoutingStats"]
