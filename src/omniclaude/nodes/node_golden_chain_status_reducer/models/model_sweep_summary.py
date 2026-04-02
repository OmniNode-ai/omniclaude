# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Sweep summary model — aggregated results from all chains."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelChainSummary(BaseModel):
    """Per-chain summary within a sweep."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Chain name")
    status: str = Field(..., description="Chain status: pass | fail | timeout | error")
    publish_latency_ms: float = Field(default=-1)
    projection_latency_ms: float = Field(default=-1)


class ModelSweepSummary(BaseModel):
    """Aggregated sweep summary across all chains."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sweep_id: str = Field(..., description="Unique sweep identifier")
    sweep_started_at: str = Field(..., description="ISO-8601 when sweep started")
    sweep_completed_at: str = Field(..., description="ISO-8601 when sweep completed")
    overall_status: str = Field(
        ..., description="pass (all pass) | partial (some fail) | fail (all fail)"
    )
    chains: tuple[ModelChainSummary, ...] = Field(
        default=(), description="Per-chain summaries"
    )
    pass_count: int = Field(default=0)
    fail_count: int = Field(default=0)
    timeout_count: int = Field(default=0)
    error_count: int = Field(default=0)


__all__ = ["ModelChainSummary", "ModelSweepSummary"]
