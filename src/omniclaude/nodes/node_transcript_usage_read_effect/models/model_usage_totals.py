# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tokens one model used across the messages one transcript read found (OMN-18946).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelUsageTotals(BaseModel):
    """Distinct API messages of one model, and their summed token counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1, description="The model id the API ran.")
    message_count: int = Field(ge=0, description="Distinct API messages counted.")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(ge=0)
