# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Emission result model - output from the routing emission effect node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelEmissionResult(BaseModel):
    """Result of a routing event emission.

    Attributes:
        success: Whether the emission succeeded.
        correlation_id: Correlation ID for request tracing.
        topics_emitted: Topics that received events.
        error: Error message if emission failed.
        duration_ms: Emission duration in milliseconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(
        ...,
        description="Whether the emission succeeded",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for request tracing",
    )
    topics_emitted: tuple[str, ...] = Field(
        default=(),
        description="Topics that received events",
    )
    error: str | None = Field(
        default=None,
        max_length=1000,
        description="Error message if emission failed",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Emission duration in milliseconds",
    )


__all__ = ["ModelEmissionResult"]
