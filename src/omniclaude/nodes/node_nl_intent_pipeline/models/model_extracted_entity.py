# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Named entity extracted from raw NL input during intent classification."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelExtractedEntity(BaseModel):
    """A single named entity extracted from raw NL input.

    Entities carry structured information about objects, actors, targets,
    or constraints mentioned in the NL text.  They are used by the Plan DAG
    generator to populate work-unit context without re-parsing the original
    text.

    Attributes:
        entity_type: High-level category (e.g. "REPOSITORY", "TICKET", "USER").
        value: Canonical string representation of the entity.
        raw_span: The exact substring from the original NL input.
        confidence: Extraction confidence in [0.0, 1.0].
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="High-level entity category (e.g. REPOSITORY, TICKET, USER)",
    )
    value: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Canonical string representation of the entity",
    )
    raw_span: str = Field(
        default="",
        max_length=1000,
        description="Exact substring from the original NL input",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence in [0.0, 1.0]",
    )


__all__ = ["ModelExtractedEntity"]
