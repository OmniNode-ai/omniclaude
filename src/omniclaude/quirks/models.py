# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic v2 data models for the Quirks Detector system.

Two top-level models:

* ``QuirkSignal`` — a raw detection event emitted by a detector tier.
  Persisted to the ``quirk_signals`` table in ``omninode_bridge``.

* ``QuirkFinding`` — a policy recommendation derived from one or more
  signals.  Persisted to the ``quirk_findings`` table.

Both models are immutable (``frozen=True``) after construction.

Related:
    - OMN-2533: Foundation ticket
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniclaude.quirks.enums import QuirkStage, QuirkType


class QuirkSignal(BaseModel):
    """A single detection event produced by a Quirks Detector tier.

    Attributes:
        quirk_id: Stable unique identifier for this signal instance.
        quirk_type: Which anti-pattern was detected.
        session_id: The Claude Code session that triggered this signal.
        confidence: Detection confidence in the range [0.0, 1.0].
        evidence: Ordered list of human-readable evidence strings that
            justify the detection.
        stage: Policy enforcement tier assigned at detection time.
        detected_at: Wall-clock timestamp of detection (UTC).
        extraction_method: Technique used to extract the signal.
        diff_hunk: Optional unified-diff fragment where the quirk was found.
        file_path: Optional source file path (relative to repo root).
        ast_span: Optional ``(start_line, end_line)`` tuple identifying the
            AST node range associated with the quirk.
    """

    model_config = ConfigDict(frozen=True)

    quirk_id: UUID = Field(default_factory=uuid4)
    quirk_type: QuirkType
    session_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    stage: QuirkStage
    detected_at: datetime
    extraction_method: Literal["regex", "AST", "heuristic", "model"]
    diff_hunk: str | None = None
    file_path: str | None = None
    ast_span: tuple[int, int] | None = None

    @field_validator("evidence")
    @classmethod
    def evidence_must_not_be_empty(cls, v: list[str]) -> list[str]:
        """Require at least one evidence string for a valid signal."""
        if not v:
            msg = "evidence must contain at least one entry"
            raise ValueError(msg)
        return v

    @field_validator("ast_span")
    @classmethod
    def ast_span_ordering(cls, v: tuple[int, int] | None) -> tuple[int, int] | None:
        """Require start_line <= end_line when ast_span is provided."""
        if v is not None and v[0] > v[1]:
            msg = f"ast_span start ({v[0]}) must be <= end ({v[1]})"
            raise ValueError(msg)
        return v


class QuirkFinding(BaseModel):
    """A policy recommendation derived from a ``QuirkSignal``.

    Attributes:
        finding_id: Stable unique identifier for this finding instance.
        quirk_type: Anti-pattern type mirrored from the originating signal.
        signal_id: Foreign-key reference to the originating ``QuirkSignal``.
        policy_recommendation: Recommended enforcement action.
        validator_blueprint_id: ID of the validator blueprint that should
            be applied to remediate this finding (if any).
        suggested_exemptions: List of exemption strings that the operator
            may apply to suppress this finding in the future.
        fix_guidance: Human-readable guidance for remediating the quirk.
        confidence: Policy confidence in the range [0.0, 1.0]; may differ
            from the originating signal confidence after aggregation.
    """

    model_config = ConfigDict(frozen=True)

    finding_id: UUID = Field(default_factory=uuid4)
    quirk_type: QuirkType
    signal_id: UUID
    policy_recommendation: Literal["observe", "warn", "block"]
    validator_blueprint_id: str | None = None
    suggested_exemptions: list[str] = Field(default_factory=list)
    fix_guidance: str
    confidence: float = Field(..., ge=0.0, le=1.0)
