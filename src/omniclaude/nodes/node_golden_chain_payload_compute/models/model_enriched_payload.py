# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enriched payload model — a chain definition with injected correlation_id."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .model_chain_definition import JsonScalar, ModelChainAssertion


class ModelEnrichedPayload(BaseModel):
    """Enriched payload ready for Kafka publish + DB poll."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_name: str = Field(..., description="Chain name")
    head_topic: str = Field(..., description="Kafka topic to publish to")
    tail_table: str = Field(..., description="DB table to poll")
    correlation_id: str = Field(
        ...,
        description="Correlation ID for the event envelope (UUID or prefixed string)",
    )
    emitted_at: str = Field(..., description="ISO-8601 UTC timestamp")
    fixture: dict[str, JsonScalar] = Field(
        ..., description="Complete fixture payload with correlation_id injected"
    )
    assertions: tuple[ModelChainAssertion, ...] = Field(
        default=(), description="Assertions to run against projected row"
    )
    timeout_ms: int = Field(
        default=15000, description="Timeout for DB poll in milliseconds"
    )
    lookup_column: str = Field(
        default="correlation_id",
        description="DB column used to locate the projected row",
    )
    lookup_value: str = Field(
        default="",
        description="Value to match against lookup_column when polling DB",
    )


__all__ = ["ModelEnrichedPayload"]
