# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enriched payload model — a chain definition with injected correlation_id."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .model_chain_definition import ModelChainAssertion


class ModelEnrichedPayload(BaseModel):
    """Enriched payload ready for Kafka publish + DB poll."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_name: str = Field(..., description="Chain name")
    head_topic: str = Field(..., description="Kafka topic to publish to")
    tail_table: str = Field(..., description="DB table to poll")
    correlation_id: str = Field(
        ..., description="Injected correlation_id with golden-chain- prefix"
    )
    emitted_at: str = Field(..., description="ISO-8601 UTC timestamp")
    fixture: dict[str, Any] = (
        Field(  # ONEX_EXCLUDE: dict_str_any — schemaless fixture payloads
            ..., description="Complete fixture payload with correlation_id injected"
        )
    )
    assertions: tuple[ModelChainAssertion, ...] = Field(
        default=(), description="Assertions to run against projected row"
    )
    timeout_ms: int = Field(
        default=15000, description="Timeout for DB poll in milliseconds"
    )


__all__ = ["ModelEnrichedPayload"]
