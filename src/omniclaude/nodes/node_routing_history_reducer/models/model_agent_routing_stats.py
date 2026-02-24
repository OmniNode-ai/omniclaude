# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("snapshot_at")
    @classmethod
    def _require_timezone_aware(cls, v: datetime | None) -> datetime | None:
        """Reject naive datetimes to enforce the explicit-timestamp invariant."""
        if v is not None and v.tzinfo is None:
            raise ValueError("snapshot_at must be timezone-aware (got naive datetime)")
        return v


__all__ = ["ModelAgentRoutingStats"]
