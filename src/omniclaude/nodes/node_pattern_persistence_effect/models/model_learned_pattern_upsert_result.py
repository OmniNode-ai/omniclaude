# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Result model for pattern upsert operations."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelLearnedPatternUpsertResult(BaseModel):
    """Result of a pattern upsert operation.

    This model encapsulates the response from inserting or updating a
    learned pattern, including whether it was an insert or update
    operation and relevant metadata.

    Attributes:
        success: Whether the upsert operation succeeded.
        pattern_id: The pattern_id that was upserted (None on failure).
        operation: Whether this was an 'insert' (new pattern) or 'update'
            (existing pattern modified). None on failure.
        error: Error message if the operation failed (None on success).
        duration_ms: Upsert execution duration in milliseconds.
        correlation_id: Correlation ID for distributed tracing.

    Example:
        >>> result = ModelLearnedPatternUpsertResult(
        ...     success=True,
        ...     pattern_id="testing.pytest_fixtures",
        ...     operation="insert",
        ...     duration_ms=5.2,
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(
        ...,
        description="Whether the upsert operation succeeded",
    )
    pattern_id: str | None = Field(
        default=None,
        description="The pattern_id that was upserted",
    )
    operation: Literal["insert", "update"] | None = Field(
        default=None,
        description="Whether this was an insert or update operation",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the operation failed",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Upsert execution duration in milliseconds",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for distributed tracing",
    )


__all__ = ["ModelLearnedPatternUpsertResult"]
