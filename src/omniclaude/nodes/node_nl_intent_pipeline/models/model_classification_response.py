# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Typed response model for the OMN-2348 intent classification service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelClassificationResponse(BaseModel):
    """Response from the OMN-2348 intent classification HTTP service.

    Attributes:
        success: True when the service successfully classified the prompt.
        intent_id: UUID returned by the service for this classification.
        intent_class: Classified intent class string (e.g. "SECURITY").
        confidence: Classification confidence in [0.0, 1.0].
        elapsed_ms: Service-reported elapsed time in milliseconds.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    success: bool = Field(
        default=False, description="True when classification succeeded"
    )
    intent_id: str = Field(default="", description="UUID for this classification")
    intent_class: str = Field(
        default="GENERAL", description="Classified intent class string"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Classification confidence"
    )
    elapsed_ms: int = Field(default=0, ge=0, description="Elapsed time in milliseconds")


__all__ = ["ModelClassificationResponse"]
