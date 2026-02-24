# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Typed Intent Object — the system-of-record output of Stage 1→2.

NL input is the *entry point*; the structured Intent object is the *authority*.
Downstream stages (Plan DAG, Ambiguity Gate, Ticket Compiler) consume this
model exclusively — they never re-parse raw NL.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_intent_type import (
    EnumIntentType,
)
from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_resolution_path import (
    EnumResolutionPath,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_extracted_entity import (
    ModelExtractedEntity,
)

# Confidence threshold below which an intent is considered low-confidence.
# Flagged (not rejected) — rejection happens at the Ambiguity Gate (OMN-2504).
LOW_CONFIDENCE_THRESHOLD = 0.5


class ModelIntentObject(BaseModel):
    """Typed, structured representation of a classified user intent.

    This is the single source of record produced by the NL Intent Pipeline and
    consumed by every subsequent stage of the compiler.

    Attributes:
        intent_id: Stable UUID-like string identifier for this intent.
        nl_input_hash: SHA-256 hex digest of the original NL input (for
            traceability back to source without re-storing raw text).
        intent_type: Classified intent type (see EnumIntentType).
        confidence: Overall classification confidence in [0.0, 1.0].
        is_low_confidence: True when confidence < LOW_CONFIDENCE_THRESHOLD.
            Flagged here; rejected at the Ambiguity Gate (OMN-2504).
        entities: Named entities extracted from the NL input.
        summary: One-sentence human-readable summary of the detected intent.
        resolution_path: How any detected ambiguity was resolved.
        raw_nl_length: Character length of the original NL input (for
            diagnostics; raw text is not stored in the object).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this intent object",
    )
    nl_input_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hex digest of the original NL input",
    )
    intent_type: EnumIntentType = Field(
        ...,
        description="Classified intent type",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall classification confidence in [0.0, 1.0]",
    )
    is_low_confidence: bool = Field(
        default=False,
        description="True when confidence < LOW_CONFIDENCE_THRESHOLD",
    )
    entities: tuple[ModelExtractedEntity, ...] = Field(
        default=(),
        description="Named entities extracted from the NL input",
    )
    summary: str = Field(
        default="",
        max_length=500,
        description="One-sentence summary of the detected intent",
    )
    resolution_path: EnumResolutionPath = Field(
        default=EnumResolutionPath.NONE,
        description="How any detected ambiguity was resolved",
    )
    raw_nl_length: int = Field(
        default=0,
        ge=0,
        description="Character length of the original NL input",
    )

    @model_validator(mode="after")
    def _sync_low_confidence_flag(self) -> ModelIntentObject:
        """Ensure is_low_confidence is consistent with confidence value."""
        expected = self.confidence < LOW_CONFIDENCE_THRESHOLD
        if self.is_low_confidence != expected:
            # Pydantic frozen models raise ValidationError on assignment;
            # re-raise as ValueError so the validator surfaces it clearly.
            raise ValueError(
                f"is_low_confidence={self.is_low_confidence!r} is inconsistent "
                f"with confidence={self.confidence} "
                f"(threshold={LOW_CONFIDENCE_THRESHOLD})"
            )
        return self

    @staticmethod
    def hash_nl_input(nl_input: str) -> str:
        """Compute SHA-256 hex digest of a raw NL input string.

        Args:
            nl_input: Raw natural language string to hash.

        Returns:
            64-character lowercase hex string.
        """
        return hashlib.sha256(nl_input.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        *,
        intent_id: str,
        nl_input: str,
        intent_type: EnumIntentType,
        confidence: float,
        entities: tuple[ModelExtractedEntity, ...] = (),
        summary: str = "",
        resolution_path: EnumResolutionPath = EnumResolutionPath.NONE,
    ) -> ModelIntentObject:
        """Convenience factory that auto-computes derived fields.

        Args:
            intent_id: Stable identifier for this intent.
            nl_input: Raw NL text — used only to derive nl_input_hash and
                raw_nl_length; never stored on the model.
            intent_type: Classified intent type.
            confidence: Classification confidence in [0.0, 1.0].
            entities: Extracted entities (default empty).
            summary: Human-readable intent summary (default empty).
            resolution_path: Ambiguity resolution path (default NONE).

        Returns:
            Immutable ModelIntentObject with all fields populated.
        """
        return cls(
            intent_id=intent_id,
            nl_input_hash=cls.hash_nl_input(nl_input),
            intent_type=intent_type,
            confidence=confidence,
            is_low_confidence=confidence < LOW_CONFIDENCE_THRESHOLD,
            entities=entities,
            summary=summary,
            resolution_path=resolution_path,
            raw_nl_length=len(nl_input),
        )


__all__ = ["ModelIntentObject", "LOW_CONFIDENCE_THRESHOLD"]
