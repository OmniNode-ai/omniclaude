# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Chain result model — outcome of a single chain publish+poll+assert cycle."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_golden_chain_payload_compute.models.model_chain_definition import (
    JsonScalar,
)

#: Per-field assertion outcome — keys: field, op, expected, actual, passed, error.
AssertionOutcome = dict[str, JsonScalar | bool]


class ModelChainResult(BaseModel):
    """Result of validating one golden chain (publish -> poll -> assert)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_name: str = Field(..., description="Chain name")
    correlation_id: str = Field(..., description="Correlation ID used for this chain")
    publish_status: str = Field(..., description="Kafka publish result: ok | error")
    publish_latency_ms: float = Field(default=-1, description="Time to Kafka ack in ms")
    projection_status: str = Field(
        ..., description="DB projection result: pass | fail | timeout | error"
    )
    projection_latency_ms: float = Field(
        default=-1, description="Time from publish to DB row appearance in ms"
    )
    assertion_results: list[AssertionOutcome] = Field(
        default_factory=list, description="Per-field assertion outcomes"
    )
    raw_row_preview: str = Field(
        default="", description="First 500 chars of projected row JSON"
    )
    error_reason: str | None = Field(
        default=None, description="Error details if publish or projection failed"
    )


__all__ = ["ModelChainResult"]
