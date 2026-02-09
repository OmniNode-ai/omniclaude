# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for fingerprint engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.lib.pipeline.fingerprint_engine import (
    classify_severity,
    compute_fingerprint_set,
    detect_new_major,
    detect_repeat_issues,
    normalize_finding,
)
from omniclaude.lib.pipeline.models import IssueFingerprint

pytestmark = pytest.mark.unit


class TestNormalizeFinding:
    """Tests for normalize_finding function."""

    def test_basic_normalization(self) -> None:
        fp = normalize_finding("src/foo.py", "unused-import", "minor")
        assert fp.file == "src/foo.py"
        assert fp.rule_id == "unused-import"
        assert fp.severity == "minor"

    def test_strips_leading_dot_slash(self) -> None:
        fp = normalize_finding("./src/foo.py", "rule", "minor")
        assert fp.file == "src/foo.py"

    def test_lowercases_rule_id(self) -> None:
        fp = normalize_finding("a.py", "UNUSED-IMPORT", "minor")
        assert fp.rule_id == "unused-import"

    def test_strips_whitespace(self) -> None:
        fp = normalize_finding("  a.py  ", "  rule  ", "minor")
        assert fp.file == "a.py"
        assert fp.rule_id == "rule"

    def test_lowercases_severity(self) -> None:
        fp = normalize_finding("a.py", "rule", "MAJOR")
        assert fp.severity == "major"

    def test_returns_issue_fingerprint(self) -> None:
        fp = normalize_finding("a.py", "rule", "critical")
        assert isinstance(fp, IssueFingerprint)

    def test_rejects_invalid_severity(self) -> None:
        """normalize_finding passes through severity without alias mapping — invalid values raise."""
        with pytest.raises(ValidationError):
            normalize_finding("a.py", "rule", "warning")


class TestComputeFingerprintSet:
    """Tests for compute_fingerprint_set function."""

    def test_empty_list(self) -> None:
        result = compute_fingerprint_set([])
        assert result == frozenset()

    def test_deduplicates(self) -> None:
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        result = compute_fingerprint_set([fp, fp])
        assert len(result) == 1

    def test_preserves_different_fingerprints(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        result = compute_fingerprint_set([fp1, fp2])
        assert len(result) == 2

    def test_returns_frozenset(self) -> None:
        result = compute_fingerprint_set([])
        assert isinstance(result, frozenset)


class TestDetectRepeatIssues:
    """Tests for detect_repeat_issues function."""

    def test_empty_current_returns_false(self) -> None:
        fp = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        assert detect_repeat_issues(frozenset([fp]), frozenset()) is False

    def test_subset_returns_true(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        prev = frozenset([fp1, fp2])
        current = frozenset([fp1])  # subset
        assert detect_repeat_issues(prev, current) is True

    def test_exact_match_returns_true(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        prev = frozenset([fp1, fp2])
        current = frozenset([fp1, fp2])
        assert detect_repeat_issues(prev, current) is True

    def test_new_issues_returns_false(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        fp3 = IssueFingerprint(file="c.py", rule_id="r3", severity="minor")
        prev = frozenset([fp1, fp2])
        current = frozenset([fp1, fp3])  # fp3 is new
        assert detect_repeat_issues(prev, current) is False

    def test_both_empty_returns_false(self) -> None:
        assert detect_repeat_issues(frozenset(), frozenset()) is False


class TestDetectNewMajor:
    """Tests for detect_new_major function."""

    def test_no_majors_returns_false(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        assert detect_new_major([fp1], [fp1]) is False

    def test_same_major_returns_false(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="major")
        assert detect_new_major([fp1], [fp1]) is False

    def test_new_major_returns_true(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="major")
        assert detect_new_major([fp1], [fp1, fp2]) is True

    def test_new_critical_returns_true(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="minor")
        fp2 = IssueFingerprint(file="b.py", rule_id="r2", severity="critical")
        assert detect_new_major([fp1], [fp1, fp2]) is True

    def test_empty_current_returns_false(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="major")
        assert detect_new_major([fp1], []) is False

    def test_empty_prev_with_major_returns_true(self) -> None:
        fp1 = IssueFingerprint(file="a.py", rule_id="r1", severity="major")
        assert detect_new_major([], [fp1]) is True


class TestClassifySeverity:
    """Tests for classify_severity function."""

    def test_critical_keyword(self) -> None:
        assert classify_severity("critical: something wrong") == "critical"

    def test_error_maps_to_critical(self) -> None:
        assert classify_severity("error: in code") == "critical"

    def test_major_keyword(self) -> None:
        assert classify_severity("major: issue found") == "major"

    def test_warning_maps_to_major(self) -> None:
        assert classify_severity("warning: deprecated API") == "major"

    def test_minor_keyword(self) -> None:
        assert classify_severity("minor: style issue") == "minor"

    def test_nit_keyword(self) -> None:
        assert classify_severity("nit: prefer single quotes") == "nit"

    def test_style_maps_to_nit(self) -> None:
        assert classify_severity("style: inconsistent formatting") == "nit"

    def test_unknown_defaults_to_minor(self) -> None:
        assert classify_severity("something happened") == "minor"

    def test_empty_string_defaults_to_minor(self) -> None:
        assert classify_severity("") == "minor"

    def test_multiple_keywords_uses_first_delimiter_match(self) -> None:
        """When multiple severity keywords appear, first one with a delimiter wins."""
        # "minor:" has delimiter so should match as minor, not the "error" word later
        result = classify_severity("minor: fix error handling")
        assert result == "minor"

    def test_keyword_without_delimiter_no_match(self) -> None:
        """Keywords embedded in phrases without delimiters should not match."""
        # "error" appears but without a colon/bracket delimiter
        result = classify_severity("fix error handling")
        assert result == "minor"  # Falls through to default
