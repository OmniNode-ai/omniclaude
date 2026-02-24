# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Input model for the NL Intent Pipeline parse operation."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_intent_type import (
    EnumIntentType,
)


class ModelNlParseRequest(BaseModel):
    """Request object for the NL→Intent parsing stage.

    Attributes:
        raw_nl: Raw natural language string to parse.  Must be non-empty.
        correlation_id: Correlation UUID for distributed tracing.
        session_id: Optional session identifier for context threading.
        force_intent_type: Optional override to skip classification and force
            a specific intent type (e.g. for tests or explicit routing).
            Accepts any string that maps to EnumIntentType; invalid values
            fall back to UNKNOWN.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    raw_nl: str = Field(
        ...,
        min_length=1,
        max_length=32_000,
        description="Raw natural language input to parse",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )
    session_id: str = Field(
        default="",
        max_length=256,
        description="Optional session identifier for context threading",
    )
    force_intent_type: EnumIntentType | None = Field(
        default=None,
        description="Optional override to force a specific intent type",
    )

    @field_validator("force_intent_type", mode="before")
    @classmethod
    def coerce_intent_type(cls, v: object) -> EnumIntentType | None:
        """Coerce raw strings to EnumIntentType; invalid values fall back to UNKNOWN."""
        if v is None:
            return None
        if isinstance(v, EnumIntentType):
            return v
        try:
            return EnumIntentType(str(v))
        except ValueError:
            return EnumIntentType.UNKNOWN


__all__ = ["ModelNlParseRequest"]
