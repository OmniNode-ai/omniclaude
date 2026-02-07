# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for pipeline Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.lib.pipeline.models import (
    IssueFingerprint,
    IterationRecord,
    PhaseResult,
    PipelinePolicy,
)

pytestmark = pytest.mark.unit


class TestPipelinePolicy:
    """Tests for PipelinePolicy model."""

    def test_defaults(self) -> None:
        policy = PipelinePolicy()
        assert policy.policy_version == "1.0"
        assert policy.auto_advance is True
        assert policy.auto_commit is True
        assert policy.auto_push is True
        assert policy.auto_pr_create is True
        assert policy.max_review_iterations == 3
        assert policy.stop_on_major is True
        assert policy.stop_on_repeat is True
        assert policy.stop_on_cross_repo is True
        assert policy.stop_on_invariant is True

    def test_frozen_immutability(self) -> None:
        policy = PipelinePolicy()
        with pytest.raises(ValidationError):
            policy.auto_advance = False

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            PipelinePolicy(unknown_field="value")

    def test_custom_values(self) -> None:
        policy = PipelinePolicy(
            auto_advance=False,
            max_review_iterations=5,
            stop_on_major=False,
        )
        assert policy.auto_advance is False
        assert policy.max_review_iterations == 5
        assert policy.stop_on_major is False

    def test_max_review_iterations_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            PipelinePolicy(max_review_iterations=0)

    def test_max_review_iterations_rejects_above_ten(self) -> None:
        with pytest.raises(ValidationError):
            PipelinePolicy(max_review_iterations=11)


class TestIssueFingerprint:
    """Tests for IssueFingerprint model."""

    def test_creation(self) -> None:
        fp = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        assert fp.file == "src/foo.py"
        assert fp.rule_id == "unused-import"
        assert fp.severity == "minor"

    def test_frozen_immutability(self) -> None:
        fp = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        with pytest.raises(ValidationError):
            fp.file = "other.py"

    def test_as_tuple(self) -> None:
        fp = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        assert fp.as_tuple() == ("src/foo.py", "unused-import", "minor")

    def test_hashable(self) -> None:
        fp1 = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        fp2 = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        assert hash(fp1) == hash(fp2)
        assert fp1 == fp2

    def test_different_fingerprints_not_equal(self) -> None:
        fp1 = IssueFingerprint(
            file="src/foo.py", rule_id="unused-import", severity="minor"
        )
        fp2 = IssueFingerprint(
            file="src/bar.py", rule_id="unused-import", severity="minor"
        )
        assert fp1 != fp2

    def test_can_be_used_in_set(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp3 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        s = {fp1, fp2, fp3}
        assert len(s) == 2

    def test_rejects_invalid_severity(self) -> None:
        with pytest.raises(ValidationError):
            IssueFingerprint(file="a.py", rule_id="r1", severity="invalid")

    def test_accepts_all_valid_severities(self) -> None:
        for sev in ("critical", "major", "minor", "nit"):
            fp = IssueFingerprint(file="a.py", rule_id="r1", severity=sev)
            assert fp.severity == sev


class TestPhaseResult:
    """Tests for PhaseResult model."""

    def test_completed_result(self) -> None:
        r = PhaseResult(status="completed")
        assert r.status == "completed"
        assert r.blocking_issues == 0
        assert r.nit_count == 0
        assert r.reason is None
        assert r.block_kind is None

    def test_blocked_result(self) -> None:
        r = PhaseResult(
            status="blocked",
            blocking_issues=3,
            reason="Review limit reached",
            block_kind="blocked_review_limit",
        )
        assert r.status == "blocked"
        assert r.blocking_issues == 3

    def test_failed_result(self) -> None:
        r = PhaseResult(
            status="failed",
            reason="Exception occurred",
            block_kind="failed_exception",
        )
        assert r.status == "failed"

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            PhaseResult(status="unknown")

    def test_rejects_invalid_block_kind(self) -> None:
        with pytest.raises(ValidationError):
            PhaseResult(status="blocked", block_kind="invalid_kind")

    def test_frozen_immutability(self) -> None:
        r = PhaseResult(status="completed")
        with pytest.raises(ValidationError):
            r.status = "failed"


class TestIterationRecord:
    """Tests for IterationRecord model."""

    def test_creation(self) -> None:
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        record = IterationRecord(
            iteration=1,
            fingerprints=frozenset([fp]),
            blocking_count=1,
            nit_count=0,
            has_major=False,
        )
        assert record.iteration == 1
        assert len(record.fingerprints) == 1
        assert record.blocking_count == 1

    def test_defaults(self) -> None:
        record = IterationRecord(iteration=1)
        assert record.fingerprints == frozenset()
        assert record.blocking_count == 0
        assert record.nit_count == 0
        assert record.has_major is False

    def test_rejects_zero_iteration(self) -> None:
        with pytest.raises(ValidationError):
            IterationRecord(iteration=0)

    def test_frozen_immutability(self) -> None:
        record = IterationRecord(iteration=1)
        with pytest.raises(ValidationError):
            record.iteration = 2
