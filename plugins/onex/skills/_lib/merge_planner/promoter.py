# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""QPM Promotion Decision Engine.

Determines whether a classified+scored PR should be promoted (jump ahead)
in the GitHub merge queue, held at its current position, or blocked.
"""

from __future__ import annotations

from enum import StrEnum

from merge_planner.classifier import (
    PRContext,  # noqa: TC002 — runtime access to ctx attrs
)
from merge_planner.models import (
    EnumAcceleratorTier,
    EnumPromotionDecision,
    EnumPRQueueClass,
    ModelPromotionRecord,
    ModelPRQueueScore,
)
from merge_planner.scorer import PROMOTION_THRESHOLD

QPM_ACCELERATE_LABEL = "qpm-accelerate"


class PromotionMode(StrEnum):
    SHADOW = "shadow"
    LABEL_GATED = "label_gated"
    AUTO = "auto"


def decide_promotion(
    ctx: PRContext,
    queue_class: EnumPRQueueClass,
    score: ModelPRQueueScore,
    mode: PromotionMode,
    *,
    accelerator_tier: EnumAcceleratorTier | None = None,
    override_decision: EnumPromotionDecision | None = None,
    override_reason: str | None = None,
) -> ModelPromotionRecord:
    """Decide whether to promote a PR. Pure function, no I/O.

    Optional override_decision/override_reason allow callers (e.g., max-promotions cap)
    to force a decision without reconstructing the frozen model after the fact.
    """
    decision: EnumPromotionDecision
    reason: str
    would_promote = False

    if override_decision is not None:
        decision = override_decision
        reason = override_reason or f"Override: {override_decision.value}"
    elif queue_class == EnumPRQueueClass.BLOCKED:
        decision = EnumPromotionDecision.BLOCK
        reason = "PR is blocked (draft, failing CI, or changes requested)"
    elif queue_class == EnumPRQueueClass.NORMAL:
        decision = EnumPromotionDecision.HOLD
        reason = "Only accelerator PRs are eligible for promotion"
    elif score.net_score < PROMOTION_THRESHOLD:
        decision = EnumPromotionDecision.HOLD
        reason = f"Score {score.net_score:.2f} below threshold {PROMOTION_THRESHOLD}"
    elif mode == PromotionMode.SHADOW:
        decision = EnumPromotionDecision.HOLD
        reason = f"Shadow mode — would promote (score {score.net_score:.2f})"
        would_promote = True
    elif mode == PromotionMode.LABEL_GATED and QPM_ACCELERATE_LABEL not in ctx.labels:
        decision = EnumPromotionDecision.HOLD
        reason = f"Missing '{QPM_ACCELERATE_LABEL}' label (label-gated mode)"
    else:
        decision = EnumPromotionDecision.PROMOTE
        reason = f"Accelerator with net_score {score.net_score:.2f} above threshold {PROMOTION_THRESHOLD}"

    return ModelPromotionRecord(
        repo=ctx.repo,
        pr_number=ctx.number,
        pr_title=ctx.title,
        classification=queue_class,
        accelerator_tier=accelerator_tier,
        score=score,
        decision=decision,
        reason=reason,
        would_promote=would_promote,
    )
