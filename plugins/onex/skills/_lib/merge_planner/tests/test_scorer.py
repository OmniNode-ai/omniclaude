"""Tests for QPM Priority Scorer."""

import pytest
from merge_planner.classifier import PRContext
from merge_planner.models import EnumPRQueueClass
from merge_planner.scorer import PROMOTION_THRESHOLD, score_pr


def test_strong_accelerator_ci_fix_high_score():
    """Strong accelerator (CI workflow) + CI-fix title keyword = 0.8 + 0.1 = 0.9."""
    ctx = PRContext(
        number=42,
        repo="r",
        title="fix(ci): add lint rule",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[".github/workflows/ci.yml"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=0)
    assert score.acceleration_value == pytest.approx(0.9)
    assert score.net_score >= PROMOTION_THRESHOLD


def test_moderate_accelerator_test_only():
    """Moderate accelerator (test files) without CI keyword = 0.6."""
    ctx = PRContext(
        number=43,
        repo="r",
        title="test: add scorer tests",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=["tests/test_scorer.py"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=0)
    assert score.acceleration_value == pytest.approx(0.6)
    assert score.net_score >= PROMOTION_THRESHOLD


def test_weak_accelerator_docs_only_low_acceleration():
    """Weak accelerator (docs) scores below strong/moderate but still classifies."""
    ctx = PRContext(
        number=47,
        repo="r",
        title="docs: update README",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=["docs/architecture/overview.md"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=0)
    assert score.acceleration_value == pytest.approx(0.3)


def test_normal_pr_low_score():
    ctx = PRContext(
        number=44,
        repo="r",
        title="feat: new feature",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=["src/feature.py"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.NORMAL, queue_depth=0)
    assert score.acceleration_value == pytest.approx(0.2)
    assert score.net_score < PROMOTION_THRESHOLD


def test_blocked_pr_negative_score():
    ctx = PRContext(
        number=45,
        repo="r",
        title="wip",
        is_draft=True,
        ci_status="pending",
        review_state="none",
        changed_files=["src/wip.py"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.BLOCKED, queue_depth=0)
    assert score.acceleration_value == pytest.approx(0.0)
    assert score.net_score < 0


def test_blast_radius_scales_with_file_count():
    ctx = PRContext(
        number=50,
        repo="r",
        title="refactor: big change",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[f"src/file_{i}.py" for i in range(50)],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.NORMAL, queue_depth=0)
    assert score.blast_radius == pytest.approx(1.0)


def test_queue_disruption_scales_with_depth():
    ctx = PRContext(
        number=51,
        repo="r",
        title="fix(ci): rule",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[".github/workflows/ci.yml"],
        labels=[],
    )
    score_empty = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=0)
    score_deep = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=5)
    assert score_deep.queue_disruption_cost > score_empty.queue_disruption_cost
    assert score_deep.net_score < score_empty.net_score


def test_dependency_risk_pyproject():
    """pyproject.toml changes add dependency risk."""
    ctx = PRContext(
        number=52,
        repo="r",
        title="chore: update deps",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=["pyproject.toml"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.NORMAL, queue_depth=0)
    assert score.dependency_risk == pytest.approx(0.3)


def test_dependency_risk_workflow():
    """Workflow changes add dependency risk (0.2) even for accelerators."""
    ctx = PRContext(
        number=53,
        repo="r",
        title="fix(ci): rule",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[".github/workflows/ci.yml"],
        labels=[],
    )
    score = score_pr(ctx, EnumPRQueueClass.ACCELERATOR, queue_depth=0)
    assert score.dependency_risk == pytest.approx(0.2)
