# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for QPM promotion decision engine."""

from __future__ import annotations

import pytest
from merge_planner.classifier import PRContext
from merge_planner.models import (
    EnumPromotionDecision,
    EnumPRQueueClass,
    ModelPRQueueScore,
)
from merge_planner.promoter import PromotionMode, decide_promotion


def _make_score(accel: float) -> ModelPRQueueScore:
    """Create a score with given acceleration_value and zero penalties."""
    return ModelPRQueueScore(
        acceleration_value=max(0.0, min(1.0, accel)),
        dependency_risk=0.0,
        blast_radius=0.0,
        flakiness_penalty=0.0,
        queue_disruption_cost=0.0,
    )


def _make_ctx(labels: list[str] | None = None) -> PRContext:
    return PRContext(
        number=42,
        repo="OmniNode-ai/omnibase_core",
        title="fix(ci): rule",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[".github/workflows/ci.yml"],
        labels=labels or [],
    )


@pytest.mark.unit
class TestDecidePromotion:
    def test_blocked_always_blocks(self) -> None:
        record = decide_promotion(
            _make_ctx(),
            EnumPRQueueClass.BLOCKED,
            _make_score(0.0),
            PromotionMode.AUTO,
        )
        assert record.decision == EnumPromotionDecision.BLOCK

    def test_normal_always_holds(self) -> None:
        record = decide_promotion(
            _make_ctx(),
            EnumPRQueueClass.NORMAL,
            _make_score(0.5),
            PromotionMode.AUTO,
        )
        assert record.decision == EnumPromotionDecision.HOLD

    def test_shadow_mode_holds_even_qualifying(self) -> None:
        record = decide_promotion(
            _make_ctx(),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.SHADOW,
        )
        assert record.decision == EnumPromotionDecision.HOLD
        assert "shadow" in record.reason.lower()
        assert record.would_promote is True

    def test_label_gated_without_label_holds(self) -> None:
        record = decide_promotion(
            _make_ctx(labels=[]),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.LABEL_GATED,
        )
        assert record.decision == EnumPromotionDecision.HOLD
        assert "label" in record.reason.lower()

    def test_label_gated_with_label_promotes(self) -> None:
        record = decide_promotion(
            _make_ctx(labels=["qpm-accelerate"]),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.LABEL_GATED,
        )
        assert record.decision == EnumPromotionDecision.PROMOTE

    def test_below_threshold_holds(self) -> None:
        record = decide_promotion(
            _make_ctx(labels=["qpm-accelerate"]),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.1),
            PromotionMode.LABEL_GATED,
        )
        assert record.decision == EnumPromotionDecision.HOLD
        assert "threshold" in record.reason.lower()

    def test_auto_mode_promotes_without_label(self) -> None:
        record = decide_promotion(
            _make_ctx(labels=[]),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.AUTO,
        )
        assert record.decision == EnumPromotionDecision.PROMOTE

    def test_override_decision(self) -> None:
        record = decide_promotion(
            _make_ctx(),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.AUTO,
            override_decision=EnumPromotionDecision.HOLD,
            override_reason="Max promotions reached",
        )
        assert record.decision == EnumPromotionDecision.HOLD
        assert "Max promotions" in record.reason

    def test_record_fields(self) -> None:
        record = decide_promotion(
            _make_ctx(),
            EnumPRQueueClass.ACCELERATOR,
            _make_score(0.7),
            PromotionMode.AUTO,
        )
        assert record.pr_number == 42
        assert record.repo == "OmniNode-ai/omnibase_core"
        assert record.pr_title == "fix(ci): rule"
        assert record.classification == EnumPRQueueClass.ACCELERATOR
        assert record.decision == EnumPromotionDecision.PROMOTE
