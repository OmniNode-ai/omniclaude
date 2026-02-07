# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Emission result model from the effect node.

Captures the outcome of emitting a routing decision event: whether
it succeeded and any error details.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelEmissionResult(BaseModel):
    """Output from the emission effect node.

    Attributes:
        correlation_id: Trace identifier matching the request.
        emitted: Whether the event was successfully emitted.
        topic_name: Full topic name the event was emitted to.
        error: Error message if emission failed, None on success.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID = Field(
        ...,
        description="Trace identifier matching the request",
    )
    emitted: bool = Field(
        ...,
        description="Whether the event was successfully emitted",
    )
    topic_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Full topic name the event was emitted to",
    )
    error: str | None = Field(
        default=None,
        max_length=500,
        description="Error message if emission failed, None on success",
    )


__all__ = ["ModelEmissionResult"]
