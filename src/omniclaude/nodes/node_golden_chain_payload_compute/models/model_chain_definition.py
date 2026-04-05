# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Chain definition model — describes one Kafka-to-DB validation chain."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Scalar JSON types used in assertion expected values and fixture payloads.
JsonScalar = str | int | float | bool | None


class ModelChainAssertion(BaseModel):
    """Single field-level assertion for a chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(..., description="Dot-separated field path in the projected row")
    op: str = Field(
        ..., description="Assertion operator: eq, neq, gte, lte, in, contains"
    )
    expected: JsonScalar | list[JsonScalar] = Field(
        ..., description="Expected value (scalar or list for 'in' operator)"
    )


class ModelChainDefinition(BaseModel):
    """Defines one golden chain: topic -> table with fixture and assertions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Chain name (e.g. 'registration')")
    head_topic: str = Field(
        ..., description="Kafka topic to publish synthetic event to"
    )
    tail_table: str = Field(..., description="DB table to poll for projected row")
    fixture_template: dict[str, JsonScalar] = Field(
        ..., description="Template payload for the synthetic event"
    )
    assertions: tuple[ModelChainAssertion, ...] = Field(
        default=(), description="Field-level assertions to run against projected row"
    )
    lookup_column: str = Field(
        default="correlation_id",
        description="DB column used to locate the projected row (tables without "
        "correlation_id use an alternate key like pattern_name or session_id)",
    )
    lookup_fixture_key: str = Field(
        default="correlation_id",
        description="Key in fixture_template whose value is used for DB lookup",
    )
    correlation_id_is_uuid: bool = Field(
        default=False,
        description="When True, generate a proper UUID for correlation_id "
        "instead of a prefixed string (required for UUID-typed DB columns)",
    )


__all__ = ["ModelChainAssertion", "ModelChainDefinition"]
