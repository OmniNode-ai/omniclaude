# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end test: full QPM pipeline in shadow mode.

Tests the full classify -> score -> decide pipeline without subprocess/gh CLI.
The orchestrator shell entrypoint is tested separately via integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from merge_planner.audit import write_audit
from merge_planner.classifier import PRContext, classify_pr
from merge_planner.models import (
    EnumPromotionDecision,
    EnumPRQueueClass,
    ModelQPMAuditEntry,
)
from merge_planner.promoter import PromotionMode, decide_promotion
from merge_planner.scorer import PROMOTION_THRESHOLD, score_pr


def _make_pr_contexts() -> list[PRContext]:
    """Create a representative set of PRs for E2E testing."""
    return [
        PRContext(
            number=1,
            repo="OmniNode-ai/test-repo",
            title="fix(ci): add new lint rule",
            is_draft=False,
            ci_status="success",
            review_state="approved",
            changed_files=[".github/workflows/ci.yml"],
            labels=["qpm-accelerate"],
        ),
        PRContext(
            number=2,
            repo="OmniNode-ai/test-repo",
            title="test: add unit tests for scorer",
            is_draft=False,
            ci_status="success",
            review_state="none",
            changed_files=["tests/test_scorer.py", "tests/conftest.py"],
            labels=[],
        ),
        PRContext(
            number=3,
            repo="OmniNode-ai/test-repo",
            title="feat: add dashboard page",
            is_draft=False,
            ci_status="success",
            review_state="approved",
            changed_files=["src/dashboard.py", "src/routes.py"],
            labels=[],
        ),
        PRContext(
            number=4,
            repo="OmniNode-ai/test-repo",
            title="wip: experiment",
            is_draft=True,
            ci_status="pending",
            review_state="none",
            changed_files=["src/experiment.py"],
            labels=[],
        ),
    ]


@pytest.mark.unit
class TestE2EShadowMode:
    def test_full_pipeline_shadow_mode(self, tmp_path: Path) -> None:
        """Full classify -> score -> decide pipeline in shadow mode."""
        prs = _make_pr_contexts()
        queue_depth = 0
        records = []

        for ctx in prs:
            queue_class = classify_pr(ctx)
            score = score_pr(ctx, queue_class, queue_depth)
            record = decide_promotion(ctx, queue_class, score, PromotionMode.SHADOW)
            records.append(record)

        # Check classifications
        classes = {r.pr_number: r.classification for r in records}
        assert classes[1] == EnumPRQueueClass.ACCELERATOR  # CI fix
        assert classes[2] == EnumPRQueueClass.ACCELERATOR  # Test only
        assert classes[3] == EnumPRQueueClass.NORMAL  # Feature
        assert classes[4] == EnumPRQueueClass.BLOCKED  # Draft

        # All decisions should be HOLD or BLOCK in shadow mode
        for r in records:
            assert r.decision in (
                EnumPromotionDecision.HOLD,
                EnumPromotionDecision.BLOCK,
            )

        # Shadow mode sets would_promote for qualifying accelerators
        would_promote_prs = [r for r in records if r.would_promote]
        assert len(would_promote_prs) >= 1  # At least CI fix qualifies

        # Verify scores are in expected ranges
        ci_fix_record = next(r for r in records if r.pr_number == 1)
        assert ci_fix_record.score.acceleration_value >= 0.8  # Strong + title bonus
        assert ci_fix_record.score.net_score >= PROMOTION_THRESHOLD

        draft_record = next(r for r in records if r.pr_number == 4)
        assert draft_record.score.acceleration_value == 0.0  # Blocked
        assert draft_record.score.net_score < 0

    def test_full_pipeline_label_gated_mode(self) -> None:
        """Label-gated mode: only labeled accelerators get promoted."""
        prs = _make_pr_contexts()
        records = []

        for ctx in prs:
            queue_class = classify_pr(ctx)
            score = score_pr(ctx, queue_class, 0)
            record = decide_promotion(
                ctx, queue_class, score, PromotionMode.LABEL_GATED
            )
            records.append(record)

        # Only PR #1 (CI fix with qpm-accelerate label) should be PROMOTE
        decisions = {r.pr_number: r.decision for r in records}
        assert decisions[1] == EnumPromotionDecision.PROMOTE
        assert decisions[2] == EnumPromotionDecision.HOLD  # No label
        assert decisions[3] == EnumPromotionDecision.HOLD  # Normal PR
        assert decisions[4] == EnumPromotionDecision.BLOCK  # Draft

    def test_full_pipeline_auto_mode(self) -> None:
        """Auto mode: all qualifying accelerators get promoted."""
        prs = _make_pr_contexts()
        records = []

        for ctx in prs:
            queue_class = classify_pr(ctx)
            score = score_pr(ctx, queue_class, 0)
            record = decide_promotion(ctx, queue_class, score, PromotionMode.AUTO)
            records.append(record)

        # PR #1 and #2 (accelerators above threshold) should be PROMOTE
        decisions = {r.pr_number: r.decision for r in records}
        assert decisions[1] == EnumPromotionDecision.PROMOTE
        assert decisions[2] == EnumPromotionDecision.PROMOTE
        assert decisions[3] == EnumPromotionDecision.HOLD  # Normal
        assert decisions[4] == EnumPromotionDecision.BLOCK  # Draft

    def test_audit_round_trip_after_pipeline(self, tmp_path: Path) -> None:
        """Verify audit entry can be written and read after a full pipeline run."""
        from datetime import UTC, datetime

        prs = _make_pr_contexts()
        records = []
        promote_count = 0

        for ctx in prs:
            queue_class = classify_pr(ctx)
            score = score_pr(ctx, queue_class, 0)
            record = decide_promotion(ctx, queue_class, score, PromotionMode.SHADOW)
            records.append(record)

        audit = ModelQPMAuditEntry(
            run_id="qpm-e2e-test",
            timestamp=datetime.now(UTC),
            mode="shadow",
            repos_queried=["OmniNode-ai/test-repo"],
            repo_fetch_errors={},
            promotion_threshold=PROMOTION_THRESHOLD,
            max_promotions=3,
            records=records,
            promotions_executed=promote_count,
            promotions_held=sum(1 for r in records if r.would_promote),
        )

        path = write_audit(audit, root=tmp_path)
        assert path.exists()

        from merge_planner.audit import read_audit

        restored = read_audit("qpm-e2e-test", root=tmp_path)
        assert restored is not None
        assert len(restored.records) == 4
        assert restored.mode == "shadow"

    def test_queue_depth_affects_scores(self) -> None:
        """Deeper queue increases disruption cost and lowers net scores."""
        ctx = PRContext(
            number=10,
            repo="OmniNode-ai/test-repo",
            title="fix(ci): adjust ruff config",
            is_draft=False,
            ci_status="success",
            review_state="approved",
            changed_files=[".github/workflows/ci.yml"],
            labels=[],
        )
        queue_class = classify_pr(ctx)
        assert queue_class == EnumPRQueueClass.ACCELERATOR

        score_empty = score_pr(ctx, queue_class, 0)
        score_deep = score_pr(ctx, queue_class, 5)

        assert score_deep.queue_disruption_cost > score_empty.queue_disruption_cost
        assert score_deep.net_score < score_empty.net_score
