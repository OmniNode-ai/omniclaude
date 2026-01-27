# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Learned pattern record for persistence (NOT extraction).

Model ownership: PRIVATE to omniclaude.

Promotion trigger: If any external repo (dashboard, intelligence, memory, infra)
imports these models, that is the signal to move them to omnibase_core.models.learned.
Do not allow cross-repo imports without promotion.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Pattern ID validation regex:
# - Must start with lowercase alphanumeric
# - Followed by 2-199 chars of: lowercase alphanumeric, dots, underscores, hyphens
# - Total length: 3-200 characters
_PATTERN_ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9._-]{2,199}$")


class ModelLearnedPatternRecord(BaseModel):
    """A learned pattern record for storage and retrieval.

    This model represents a single learned pattern that can be stored in
    the persistence layer and retrieved for context injection.

    Attributes:
        pattern_id: Semantic identifier for the pattern (e.g., 'testing.pytest_fixtures').
            Must match regex: ^[a-z0-9][a-z0-9._-]{2,199}$
        domain: Pattern domain classification (e.g., 'testing', 'api', 'database').
        title: Human-readable title for the pattern.
        description: Detailed description of the pattern and its application.
        confidence: Confidence score for the pattern (0.0-1.0).
        usage_count: Number of times this pattern has been applied.
        success_rate: Historical success rate when this pattern is applied (0.0-1.0).
        example_reference: Optional reference to an example implementation.

    Example:
        >>> pattern = ModelLearnedPatternRecord(
        ...     pattern_id="testing.pytest_fixtures",
        ...     domain="testing",
        ...     title="Pytest Fixture Patterns",
        ...     description="Use pytest fixtures for test setup and teardown...",
        ...     confidence=0.9,
        ...     usage_count=15,
        ...     success_rate=0.95,
        ... )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Semantic identifier (e.g., 'testing.pytest_fixtures')",
    )
    domain: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Pattern domain classification",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable title for the pattern",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Detailed description of the pattern and its application",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the pattern (0.0-1.0)",
    )
    usage_count: int = Field(
        default=0,
        ge=0,
        description="Number of times this pattern has been applied",
    )
    success_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Historical success rate when pattern is applied (0.0-1.0)",
    )
    example_reference: str | None = Field(
        default=None,
        max_length=500,
        description="Optional reference to an example implementation",
    )
    # REMOVED: project_scope - not in schema, add when schema supports it

    @field_validator("pattern_id")
    @classmethod
    def validate_pattern_id(cls, v: str) -> str:
        """Validate pattern_id matches required format.

        Args:
            v: The pattern_id value to validate.

        Returns:
            The validated pattern_id.

        Raises:
            ValueError: If pattern_id does not match the required regex.
        """
        if not _PATTERN_ID_REGEX.match(v):
            msg = (
                f"pattern_id must match {_PATTERN_ID_REGEX.pattern}: "
                "lowercase alphanumeric, dots, underscores, hyphens; "
                "3-200 chars; must start with alphanumeric"
            )
            raise ValueError(msg)
        return v


__all__ = ["ModelLearnedPatternRecord"]
