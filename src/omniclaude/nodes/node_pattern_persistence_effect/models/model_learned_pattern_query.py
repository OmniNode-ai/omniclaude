# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Query parameters for learned pattern retrieval.

Query Execution Order (EXPLICIT):
    1. Apply filters (domain, min_confidence)
    2. Apply include_general union (if domain set and include_general=True)
    3. Sort by confidence DESC, usage_count DESC
    4. Apply offset
    5. Apply limit

Pagination Semantics:
    - total_count: Count of filtered set AFTER include_general union, BEFORE limit/offset
    - include_general: When True AND domain is specified, adds WHERE (domain = X OR domain = 'general')
    - General patterns count toward limit (not added after)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelLearnedPatternQuery(BaseModel):
    """Query parameters for learned pattern retrieval.

    This model encapsulates all filtering and pagination options for querying
    learned patterns from the persistence layer.

    Query Execution Order:
        1. Apply filters (domain, min_confidence)
        2. Apply include_general union (if domain set and include_general=True)
        3. Sort by confidence DESC, usage_count DESC
        4. Apply offset
        5. Apply limit

    Attributes:
        domain: Optional domain filter. When set with include_general=True,
            queries both the specified domain AND 'general' domain.
        min_confidence: Minimum confidence threshold for returned patterns.
        include_general: Whether to include domain='general' patterns when
            a specific domain is filtered. General patterns count toward limit.
        limit: Maximum number of patterns to return (1-500).
        offset: Number of patterns to skip for pagination.

    Example:
        >>> # Query testing patterns with general patterns included
        >>> query = ModelLearnedPatternQuery(
        ...     domain="testing",
        ...     min_confidence=0.7,
        ...     include_general=True,
        ...     limit=20,
        ...     offset=0,
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str | None = Field(
        default=None,
        description="Filter by domain (e.g., 'testing', 'api')",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for returned patterns",
    )
    # REMOVED: project_scope - add when schema supports it
    include_general: bool = Field(
        default=True,
        description="Include domain='general' patterns when domain is specified (counts toward limit)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of patterns to return",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of patterns to skip for pagination",
    )


__all__ = ["ModelLearnedPatternQuery"]
