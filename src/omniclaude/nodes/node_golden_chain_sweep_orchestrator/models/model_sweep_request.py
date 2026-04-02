# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Sweep request model — trigger for the orchestrator."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSweepRequest(BaseModel):
    """Request to trigger a golden chain validation sweep."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_filter: list[str] | None = Field(
        default=None, description="Optional list of chain names to run. None = all."
    )
    timeout_ms: int = Field(
        default=15000, description="Per-chain DB poll timeout in milliseconds"
    )


__all__ = ["ModelSweepRequest"]
