# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for CodeRabbit auto-triage handler."""

from __future__ import annotations

import pytest

from omniclaude.hooks.handlers.coderabbit_triage import (
    EnumTriageAction,
    EnumTriageSeverity,
    classify_severity,
    is_auto_triageable,
)


@pytest.mark.unit
class TestClassifySeverity:
    """Tests for severity classification of CodeRabbit comments."""

    def test_critical_keyword(self) -> None:
        assert (
            classify_severity("This is a critical security issue")
            == EnumTriageSeverity.CRITICAL
        )

    def test_critical_emoji(self) -> None:
        assert (
            classify_severity("🔴 Buffer overflow in parser")
            == EnumTriageSeverity.CRITICAL
        )

    def test_critical_bracket(self) -> None:
        assert (
            classify_severity("[critical] Missing auth check")
            == EnumTriageSeverity.CRITICAL
        )

    def test_major_keyword(self) -> None:
        assert (
            classify_severity("This is a major performance regression")
            == EnumTriageSeverity.MAJOR
        )

    def test_major_emoji(self) -> None:
        assert (
            classify_severity("🟠 Missing error handling") == EnumTriageSeverity.MAJOR
        )

    def test_major_important(self) -> None:
        assert (
            classify_severity("This is an important issue to fix")
            == EnumTriageSeverity.MAJOR
        )

    def test_minor_keyword(self) -> None:
        assert (
            classify_severity("Minor: consider using a list comprehension")
            == EnumTriageSeverity.MINOR
        )

    def test_minor_emoji(self) -> None:
        assert (
            classify_severity("🟡 Could improve readability")
            == EnumTriageSeverity.MINOR
        )

    def test_minor_suggestion(self) -> None:
        assert (
            classify_severity("Suggestion: rename this variable")
            == EnumTriageSeverity.MINOR
        )

    def test_nitpick_keyword(self) -> None:
        assert (
            classify_severity("Nitpick: trailing whitespace")
            == EnumTriageSeverity.NITPICK
        )

    def test_nitpick_nit(self) -> None:
        assert classify_severity("Nit: extra blank line") == EnumTriageSeverity.NITPICK

    def test_nitpick_emoji(self) -> None:
        assert classify_severity("🟢 Style preference") == EnumTriageSeverity.NITPICK

    def test_nitpick_style(self) -> None:
        assert (
            classify_severity("Style: prefer single quotes")
            == EnumTriageSeverity.NITPICK
        )

    def test_nitpick_naming(self) -> None:
        assert (
            classify_severity("Naming convention: use snake_case")
            == EnumTriageSeverity.NITPICK
        )

    def test_unknown_no_markers(self) -> None:
        assert (
            classify_severity("Consider refactoring this function")
            == EnumTriageSeverity.UNKNOWN
        )

    def test_empty_body(self) -> None:
        assert classify_severity("") == EnumTriageSeverity.UNKNOWN

    def test_highest_severity_wins(self) -> None:
        """When multiple severity markers are present, highest wins."""
        assert (
            classify_severity("Critical issue, also a minor nit")
            == EnumTriageSeverity.CRITICAL
        )

    def test_case_insensitive(self) -> None:
        assert classify_severity("CRITICAL: fix this") == EnumTriageSeverity.CRITICAL
        assert classify_severity("MINOR suggestion") == EnumTriageSeverity.MINOR

    def test_severity_in_coderabbit_format(self) -> None:
        """CodeRabbit uses 'severity: minor' format in structured output."""
        assert (
            classify_severity("severity: minor\nConsider using...")
            == EnumTriageSeverity.MINOR
        )
        assert (
            classify_severity("severity: critical\nSQL injection")
            == EnumTriageSeverity.CRITICAL
        )


@pytest.mark.unit
class TestIsAutoTriageable:
    """Tests for auto-triage eligibility."""

    def test_minor_is_triageable(self) -> None:
        assert is_auto_triageable(EnumTriageSeverity.MINOR) is True

    def test_nitpick_is_triageable(self) -> None:
        assert is_auto_triageable(EnumTriageSeverity.NITPICK) is True

    def test_critical_not_triageable(self) -> None:
        assert is_auto_triageable(EnumTriageSeverity.CRITICAL) is False

    def test_major_not_triageable(self) -> None:
        assert is_auto_triageable(EnumTriageSeverity.MAJOR) is False

    def test_unknown_not_triageable(self) -> None:
        assert is_auto_triageable(EnumTriageSeverity.UNKNOWN) is False


@pytest.mark.unit
class TestEnumValues:
    """Tests for enum value integrity."""

    def test_severity_values(self) -> None:
        assert EnumTriageSeverity.CRITICAL.value == "critical"
        assert EnumTriageSeverity.MAJOR.value == "major"
        assert EnumTriageSeverity.MINOR.value == "minor"
        assert EnumTriageSeverity.NITPICK.value == "nitpick"
        assert EnumTriageSeverity.UNKNOWN.value == "unknown"

    def test_action_values(self) -> None:
        assert EnumTriageAction.AUTO_REPLIED.value == "auto_replied"
        assert EnumTriageAction.SKIPPED_REQUIRES_FIX.value == "skipped_requires_fix"
        assert (
            EnumTriageAction.SKIPPED_ALREADY_RESOLVED.value
            == "skipped_already_resolved"
        )
        assert EnumTriageAction.SKIPPED_NOT_CODERABBIT.value == "skipped_not_coderabbit"
        assert EnumTriageAction.ERROR.value == "error"
