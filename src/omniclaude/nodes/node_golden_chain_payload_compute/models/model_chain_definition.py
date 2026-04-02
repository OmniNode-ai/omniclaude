# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Chain definition model — describes one Kafka-to-DB validation chain."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelChainAssertion(BaseModel):
    """Single field-level assertion for a chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(..., description="Dot-separated field path in the projected row")
    op: str = Field(..., description="Assertion operator: eq, neq, gte, lte, in, contains")
    expected: Any = Field(..., description="Expected value")


class ModelChainDefinition(BaseModel):
    """Defines one golden chain: topic -> table with fixture and assertions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Chain name (e.g. 'registration')")
    head_topic: str = Field(..., description="Kafka topic to publish synthetic event to")
    tail_table: str = Field(..., description="DB table to poll for projected row")
    fixture_template: dict[str, Any] = Field(
        ..., description="Template payload for the synthetic event"
    )
    assertions: tuple[ModelChainAssertion, ...] = Field(
        default=(), description="Field-level assertions to run against projected row"
    )


__all__ = ["ModelChainAssertion", "ModelChainDefinition"]
