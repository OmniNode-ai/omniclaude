# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Local LLM inference request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelLocalLlmInferenceRequest(BaseModel):
    """Input model for local LLM inference requests.

    Attributes:
        prompt: The prompt to submit to the local LLM.
        model: Model name/identifier to use (backend-specific).
            If None, the backend uses its configured default.
        max_tokens: Maximum tokens to generate. If None, uses backend default.
        temperature: Sampling temperature (0.0-2.0). If None, uses backend default.
        skill_name: Human-readable skill name for the ModelSkillResult envelope.
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(
        ...,
        min_length=1,
        description="The prompt to submit to the local LLM",
    )
    model: str | None = Field(
        default=None,
        description="Model name/identifier (backend-specific, uses default if None)",
    )
    max_tokens: int | None = Field(  # noqa: secrets
        default=None,
        ge=1,
        description="Maximum tokens to generate",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0-2.0)",
    )
    skill_name: str = Field(
        default="local_llm.inference",
        min_length=1,
        description="Human-readable skill name for the ModelSkillResult envelope",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["ModelLocalLlmInferenceRequest"]
