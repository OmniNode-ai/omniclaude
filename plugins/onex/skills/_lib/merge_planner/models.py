# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""QPM Pydantic models — type vocabulary for merge queue priority management.

Types:
    EnumPRQueueClass: PR classification (accelerator / normal / blocked).
    EnumPromotionDecision: Promotion outcome per PR.
    ModelPRQueueScore: 5-dimension frozen score.
    ModelPromotionRecord: Per-PR decision record.
    ModelQPMAuditEntry: Per-run audit with policy knobs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumPRQueueClass(StrEnum):
    """Classification of a PR for merge queue prioritization.

    Not reusing CommentSeverity (review findings) or existing routing enums —
    this is a merge-queue-specific classification vocabulary.
    """

    ACCELERATOR = "accelerator"
    NORMAL = "normal"
    BLOCKED = "blocked"


class EnumAcceleratorTier(StrEnum):
    """Strength tier for accelerator classification.

    Drives the acceleration_value in ModelPRQueueScore.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class EnumPromotionDecision(StrEnum):
    """Outcome of QPM promotion decision for a single PR."""

    PROMOTE = "promote"
    HOLD = "hold"
    SKIP = "skip"
    BLOCK = "block"


class ModelPRQueueScore(BaseModel):
    """5-dimension frozen score for a classified PR.

    Net score = acceleration_value - dependency_risk - blast_radius
                - flakiness_penalty - queue_disruption_cost

    Not reusing ConfidenceScorer (agent routing) — this is merge-queue-specific
    with dimensions meaningful only in the queue promotion context.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    acceleration_value: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Acceleration value based on accelerator tier "
        "(strong=0.8, moderate=0.6, weak=0.3).",
    )
    dependency_risk: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Risk from cross-repo or package dependency changes.",
    )
    blast_radius: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Scope of changes (files touched, repos affected).",
    )
    flakiness_penalty: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Penalty for historically flaky test paths.",
    )
    queue_disruption_cost: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Cost of disrupting existing queue ordering.",
    )

    @property
    def net_score(self) -> float:
        """Compute net priority score."""
        return (
            self.acceleration_value
            - self.dependency_risk
            - self.blast_radius
            - self.flakiness_penalty
            - self.queue_disruption_cost
        )


class ModelPromotionRecord(BaseModel):
    """Per-PR decision record capturing classification, scoring, and decision.

    One record per PR processed in a QPM run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="Repository slug (owner/name).")
    pr_number: int = Field(..., ge=1, description="Pull request number.")
    pr_title: str = Field(..., description="Pull request title.")
    classification: EnumPRQueueClass = Field(
        ..., description="QPM classification result."
    )
    accelerator_tier: EnumAcceleratorTier | None = Field(
        default=None,
        description="Accelerator strength tier (None if not accelerator).",
    )
    score: ModelPRQueueScore = Field(..., description="5-dimension priority score.")
    decision: EnumPromotionDecision = Field(
        ..., description="Promotion decision outcome."
    )
    reason: str = Field(..., description="Human-readable decision explanation.")
    would_promote: bool = Field(
        default=False,
        description="True if PR would have been promoted in auto mode "
        "(set in shadow mode for observability).",
    )


class ModelQPMAuditEntry(BaseModel):
    """Per-run audit entry recording all QPM decisions and policy knobs.

    Written to the audit ledger after each QPM run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Unique QPM run identifier.")
    timestamp: datetime = Field(..., description="UTC timestamp of the QPM run.")
    mode: str = Field(
        ...,
        description="Operating mode: shadow, label_gated, or auto.",
    )
    repos_queried: list[str] = Field(
        default_factory=list,
        description="Repository slugs queried in this run.",
    )
    repo_fetch_errors: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of repo slug to fetch error message "
        "for repos with degraded fetches.",
    )
    promotion_threshold: float = Field(
        ...,
        description="Minimum net_score required for promotion.",
    )
    max_promotions: int = Field(
        default=3,
        ge=1,
        description="Safety cap on promotions per run.",
    )
    records: list[ModelPromotionRecord] = Field(
        default_factory=list,
        description="Per-PR decision records.",
    )
    promotions_executed: int = Field(
        default=0,
        ge=0,
        description="Number of PRs actually promoted (enqueue called).",
    )
    promotions_held: int = Field(
        default=0,
        ge=0,
        description="Number of PRs held (would-promote but capped or shadow).",
    )
