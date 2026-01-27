# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Result model for pattern query operations."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .model_learned_pattern_record import ModelLearnedPatternRecord


class ModelLearnedPatternQueryResult(BaseModel):
    """Result of a pattern query operation.

    This model encapsulates the response from querying learned patterns,
    including the matched records, total count for pagination, and
    operation metadata.

    Attributes:
        success: Whether the query operation succeeded.
        records: Tuple of matched pattern records. Empty tuple on failure.
        total_count: Total number of matching patterns AFTER include_general
            union, BEFORE limit/offset. Used for pagination UI.
        error: Error message if the operation failed (None on success).
        duration_ms: Query execution duration in milliseconds.
        backend_type: Storage backend identifier (e.g., 'postgresql').
        correlation_id: Correlation ID for distributed tracing.

    Example:
        >>> result = ModelLearnedPatternQueryResult(
        ...     success=True,
        ...     records=(pattern1, pattern2),
        ...     total_count=42,
        ...     duration_ms=15.5,
        ...     backend_type="postgresql",
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(
        ...,
        description="Whether the query operation succeeded",
    )
    records: tuple[ModelLearnedPatternRecord, ...] = Field(
        default_factory=tuple,
        description="Tuple of matched pattern records",
    )
    total_count: int = Field(
        default=0,
        ge=0,
        description="Total matches AFTER include_general union, BEFORE limit/offset",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the operation failed",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Query execution duration in milliseconds",
    )
    backend_type: str = Field(
        default="postgresql",
        description="Storage backend identifier",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for distributed tracing",
    )


__all__ = ["ModelLearnedPatternQueryResult"]
