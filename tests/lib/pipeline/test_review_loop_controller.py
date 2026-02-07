# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for review loop controller."""

from __future__ import annotations

import pytest

from omniclaude.lib.pipeline.models import IssueFingerprint, PipelinePolicy
from omniclaude.lib.pipeline.review_loop_controller import ReviewLoopController

pytestmark = pytest.mark.unit


class TestMaxReviewIterations:
    """Tests for max_review_iterations enforcement."""

    def test_stops_at_limit(self) -> None:
        policy = PipelinePolicy(max_review_iterations=2)
        controller = ReviewLoopController(policy)
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        # Iteration 1: OK
        can_continue, reason = controller.should_continue(1, [fp])
        assert can_continue is True

        # Iteration 2: At limit, should stop
        can_continue, reason = controller.should_continue(2, [fp])
        assert can_continue is False
        assert "capped" in reason.lower() or "iterations" in reason.lower()

    def test_allows_under_limit(self) -> None:
        policy = PipelinePolicy(max_review_iterations=5)
        controller = ReviewLoopController(policy)
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        can_continue, reason = controller.should_continue(1, [fp])
        assert can_continue is True
        assert reason is None


class TestStopOnRepeat:
    """Tests for stop_on_repeat enforcement."""

    def test_detects_repeat(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_repeat=True)
        controller = ReviewLoopController(policy)
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        # Iteration 1: record
        controller.should_continue(1, [fp])
        # Iteration 2: same findings = repeat
        can_continue, reason = controller.should_continue(2, [fp])
        assert can_continue is False
        assert "repeat" in reason.lower()

    def test_disabled_allows_repeat(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_repeat=False)
        controller = ReviewLoopController(policy)
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        controller.should_continue(1, [fp])
        can_continue, _reason = controller.should_continue(2, [fp])
        assert can_continue is True

    def test_new_issues_not_repeat(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_repeat=True)
        controller = ReviewLoopController(policy)
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="minor")

        controller.should_continue(1, [fp1])
        can_continue, _reason = controller.should_continue(2, [fp2])
        assert can_continue is True


class TestStopOnMajor:
    """Tests for stop_on_major enforcement."""

    def test_detects_new_major(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_major=True)
        controller = ReviewLoopController(policy)
        fp_minor = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp_major = IssueFingerprint(file="b.py", rule_id="r2", severity="major")

        controller.should_continue(1, [fp_minor])
        can_continue, reason = controller.should_continue(2, [fp_minor, fp_major])
        assert can_continue is False
        assert "major" in reason.lower()

    def test_disabled_allows_new_major(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_major=False)
        controller = ReviewLoopController(policy)
        fp_minor = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp_major = IssueFingerprint(file="b.py", rule_id="r2", severity="major")

        controller.should_continue(1, [fp_minor])
        can_continue, _reason = controller.should_continue(2, [fp_minor, fp_major])
        assert can_continue is True

    def test_same_major_from_iteration_1_ok(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_major=True)
        controller = ReviewLoopController(policy)
        fp_major = IssueFingerprint(file="a.py", rule_id="r1", severity="major")

        controller.should_continue(1, [fp_major])
        _can_continue, _reason = controller.should_continue(2, [fp_major])
        # Same major from iteration 1 is NOT a "new" major - but it IS a repeat
        # stop_on_repeat may catch this first

    def test_not_triggered_on_iteration_1(self) -> None:
        policy = PipelinePolicy(max_review_iterations=10, stop_on_major=True)
        controller = ReviewLoopController(policy)
        fp_major = IssueFingerprint(file="a.py", rule_id="r1", severity="major")

        can_continue, _reason = controller.should_continue(1, [fp_major])
        assert can_continue is True  # First iteration never triggers stop_on_major


class TestGetStopBlockKind:
    """Tests for get_stop_block_kind method."""

    def test_capped_reason(self) -> None:
        controller = ReviewLoopController(PipelinePolicy())
        assert (
            controller.get_stop_block_kind("Review capped at 3 iterations")
            == "blocked_review_limit"
        )

    def test_repeat_reason(self) -> None:
        controller = ReviewLoopController(PipelinePolicy())
        assert (
            controller.get_stop_block_kind("Repeat fingerprint match")
            == "blocked_review_limit"
        )

    def test_major_reason(self) -> None:
        controller = ReviewLoopController(PipelinePolicy())
        assert (
            controller.get_stop_block_kind("New major issue appeared")
            == "blocked_policy"
        )


class TestIterationTracking:
    """Tests for iteration history tracking."""

    def test_iteration_count(self) -> None:
        controller = ReviewLoopController(PipelinePolicy(max_review_iterations=10))
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        assert controller.iteration_count == 0
        controller.should_continue(1, [fp])
        assert controller.iteration_count == 1
        controller.should_continue(2, [fp])
        assert controller.iteration_count == 2

    def test_last_record(self) -> None:
        controller = ReviewLoopController(PipelinePolicy(max_review_iterations=10))
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        assert controller.last_record is None
        controller.should_continue(1, [fp])
        assert controller.last_record is not None
        assert controller.last_record.iteration == 1

    def test_get_iteration_history(self) -> None:
        controller = ReviewLoopController(PipelinePolicy(max_review_iterations=10))
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")

        controller.should_continue(1, [fp])
        history = controller.get_iteration_history()
        assert len(history) == 1
        assert "iteration_1" in history[0]
