#!/usr/bin/env python3
"""
Tests for PR review models and collate_issues module.

This module provides comprehensive test coverage for:
- models.py: Pydantic models (ModelPRIssue, ModelCollatedIssues, CommentSeverity, CommentStatus)
- collate_issues.py: Issue collation logic

Run with: pytest test_models.py -v
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest
from models import (
    BotType,
    ModelCollatedIssues,
    CommentSeverity,
    CommentStatus,
    ModelFileReference,
    ModelPRComment,
    ModelPRCommentSource,
    ModelPRIssue,
    detect_bot_type,
)


# =============================================================================
# CommentSeverity Enum Tests
# =============================================================================


class TestCommentSeverity:
    """Tests for CommentSeverity enum."""

    def test_all_severity_values_exist(self) -> None:
        """Verify all expected severity values are defined."""
        expected = {"CRITICAL", "MAJOR", "MINOR", "NITPICK", "UNCLASSIFIED"}
        actual = {s.name for s in CommentSeverity}
        assert actual == expected

    def test_severity_string_values(self) -> None:
        """Verify severity string values are lowercase."""
        assert CommentSeverity.CRITICAL.value == "critical"
        assert CommentSeverity.MAJOR.value == "major"
        assert CommentSeverity.MINOR.value == "minor"
        assert CommentSeverity.NITPICK.value == "nitpick"
        assert CommentSeverity.UNCLASSIFIED.value == "unclassified"

    def test_is_blocking_critical(self) -> None:
        """CRITICAL severity should be blocking."""
        assert CommentSeverity.CRITICAL.is_blocking is True

    def test_is_blocking_major(self) -> None:
        """MAJOR severity should be blocking."""
        assert CommentSeverity.MAJOR.is_blocking is True

    def test_is_blocking_minor(self) -> None:
        """MINOR severity should NOT be blocking."""
        assert CommentSeverity.MINOR.is_blocking is False

    def test_is_blocking_nitpick(self) -> None:
        """NITPICK severity should NOT be blocking."""
        assert CommentSeverity.NITPICK.is_blocking is False

    def test_is_blocking_unclassified(self) -> None:
        """UNCLASSIFIED severity should NOT be blocking."""
        assert CommentSeverity.UNCLASSIFIED.is_blocking is False

    def test_priority_order_critical(self) -> None:
        """CRITICAL should have highest priority (lowest number)."""
        assert CommentSeverity.CRITICAL.priority_order == 0

    def test_priority_order_major(self) -> None:
        """MAJOR should have second highest priority."""
        assert CommentSeverity.MAJOR.priority_order == 1

    def test_priority_order_minor(self) -> None:
        """MINOR should have third priority."""
        assert CommentSeverity.MINOR.priority_order == 2

    def test_priority_order_nitpick(self) -> None:
        """NITPICK should have fourth priority."""
        assert CommentSeverity.NITPICK.priority_order == 3

    def test_priority_order_unclassified(self) -> None:
        """UNCLASSIFIED should have lowest priority."""
        assert CommentSeverity.UNCLASSIFIED.priority_order == 4

    def test_priority_order_is_sortable(self) -> None:
        """Priority order should enable correct sorting."""
        severities = [
            CommentSeverity.MINOR,
            CommentSeverity.CRITICAL,
            CommentSeverity.NITPICK,
            CommentSeverity.MAJOR,
        ]
        sorted_severities = sorted(severities, key=lambda s: s.priority_order)
        assert sorted_severities == [
            CommentSeverity.CRITICAL,
            CommentSeverity.MAJOR,
            CommentSeverity.MINOR,
            CommentSeverity.NITPICK,
        ]

    def test_str_representation(self) -> None:
        """String representation should return the value."""
        assert str(CommentSeverity.CRITICAL) == "critical"
        assert str(CommentSeverity.MAJOR) == "major"


# =============================================================================
# CommentStatus Enum Tests
# =============================================================================


class TestCommentStatus:
    """Tests for CommentStatus enum."""

    def test_all_status_values_exist(self) -> None:
        """Verify all expected status values are defined."""
        expected = {
            "UNADDRESSED",
            "POTENTIALLY_ADDRESSED",
            "RESOLVED",
            "OUTDATED",
            "WONT_FIX",
        }
        actual = {s.name for s in CommentStatus}
        assert actual == expected

    def test_status_string_values(self) -> None:
        """Verify status string values are lowercase with underscores."""
        assert CommentStatus.UNADDRESSED.value == "unaddressed"
        assert CommentStatus.POTENTIALLY_ADDRESSED.value == "potentially_addressed"
        assert CommentStatus.RESOLVED.value == "resolved"
        assert CommentStatus.OUTDATED.value == "outdated"
        assert CommentStatus.WONT_FIX.value == "wont_fix"

    def test_needs_attention_unaddressed(self) -> None:
        """UNADDRESSED status should need attention."""
        assert CommentStatus.UNADDRESSED.needs_attention is True

    def test_needs_attention_potentially_addressed(self) -> None:
        """POTENTIALLY_ADDRESSED status should need attention."""
        assert CommentStatus.POTENTIALLY_ADDRESSED.needs_attention is True

    def test_needs_attention_resolved(self) -> None:
        """RESOLVED status should NOT need attention."""
        assert CommentStatus.RESOLVED.needs_attention is False

    def test_needs_attention_outdated(self) -> None:
        """OUTDATED status should NOT need attention."""
        assert CommentStatus.OUTDATED.needs_attention is False

    def test_needs_attention_wont_fix(self) -> None:
        """WONT_FIX status should NOT need attention."""
        assert CommentStatus.WONT_FIX.needs_attention is False

    def test_is_resolved_resolved(self) -> None:
        """RESOLVED status should be considered resolved."""
        assert CommentStatus.RESOLVED.is_resolved is True

    def test_is_resolved_outdated(self) -> None:
        """OUTDATED status should be considered resolved."""
        assert CommentStatus.OUTDATED.is_resolved is True

    def test_is_resolved_wont_fix(self) -> None:
        """WONT_FIX status should be considered resolved."""
        assert CommentStatus.WONT_FIX.is_resolved is True

    def test_is_resolved_unaddressed(self) -> None:
        """UNADDRESSED status should NOT be considered resolved."""
        assert CommentStatus.UNADDRESSED.is_resolved is False

    def test_is_resolved_potentially_addressed(self) -> None:
        """POTENTIALLY_ADDRESSED status should NOT be considered resolved."""
        assert CommentStatus.POTENTIALLY_ADDRESSED.is_resolved is False

    def test_str_representation(self) -> None:
        """String representation should return the value."""
        assert str(CommentStatus.RESOLVED) == "resolved"
        assert str(CommentStatus.UNADDRESSED) == "unaddressed"


# =============================================================================
# ModelPRIssue Model Tests
# =============================================================================


class TestModelPRIssue:
    """Tests for ModelPRIssue model."""

    def test_creation_with_valid_data(self) -> None:
        """Test creating ModelPRIssue with all required fields."""
        issue = ModelPRIssue(
            file_path="src/main.py",
            line_number=42,
            severity=CommentSeverity.CRITICAL,
            description="Missing null check",
        )
        assert issue.file_path == "src/main.py"
        assert issue.line_number == 42
        assert issue.severity == CommentSeverity.CRITICAL
        assert issue.description == "Missing null check"
        assert issue.status == CommentStatus.UNADDRESSED  # default

    def test_creation_minimal(self) -> None:
        """Test creating ModelPRIssue with only required fields."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MINOR,
            description="Consider refactoring",
        )
        assert issue.file_path == ""
        assert issue.line_number is None
        assert issue.severity == CommentSeverity.MINOR
        assert issue.description == "Consider refactoring"

    def test_creation_with_status(self) -> None:
        """Test creating ModelPRIssue with explicit status."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Bug fix needed",
            status=CommentStatus.RESOLVED,
        )
        assert issue.status == CommentStatus.RESOLVED

    def test_location_property_with_path_and_line(self) -> None:
        """Test location property with both path and line number."""
        issue = ModelPRIssue(
            file_path="src/utils.py",
            line_number=100,
            severity=CommentSeverity.MINOR,
            description="Test",
        )
        assert issue.location == "[src/utils.py:100]"

    def test_location_property_with_path_only(self) -> None:
        """Test location property with path but no line number."""
        issue = ModelPRIssue(
            file_path="src/utils.py",
            severity=CommentSeverity.MINOR,
            description="Test",
        )
        assert issue.location == "[src/utils.py]"

    def test_location_property_empty(self) -> None:
        """Test location property with no path."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MINOR,
            description="Test",
        )
        assert issue.location == ""

    def test_severity_emoji_critical(self) -> None:
        """Test severity emoji for CRITICAL."""
        issue = ModelPRIssue(
            severity=CommentSeverity.CRITICAL,
            description="Test",
        )
        assert issue.severity_emoji == "🔴"

    def test_severity_emoji_major(self) -> None:
        """Test severity emoji for MAJOR."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
        )
        assert issue.severity_emoji == "🟠"

    def test_severity_emoji_minor(self) -> None:
        """Test severity emoji for MINOR."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MINOR,
            description="Test",
        )
        assert issue.severity_emoji == "🟡"

    def test_severity_emoji_nitpick(self) -> None:
        """Test severity emoji for NITPICK."""
        issue = ModelPRIssue(
            severity=CommentSeverity.NITPICK,
            description="Test",
        )
        assert issue.severity_emoji == "⚪"

    def test_severity_emoji_unclassified(self) -> None:
        """Test severity emoji for UNCLASSIFIED."""
        issue = ModelPRIssue(
            severity=CommentSeverity.UNCLASSIFIED,
            description="Test",
        )
        assert issue.severity_emoji == "❓"

    def test_status_indicator_resolved(self) -> None:
        """Test status indicator for RESOLVED status."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.RESOLVED,
        )
        assert issue.status_indicator == "[RESOLVED]"

    def test_status_indicator_outdated(self) -> None:
        """Test status indicator for OUTDATED status."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.OUTDATED,
        )
        assert issue.status_indicator == "[OUTDATED]"

    def test_status_indicator_outdated_via_flag(self) -> None:
        """Test status indicator when is_outdated flag is True."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.UNADDRESSED,
            is_outdated=True,
        )
        assert issue.status_indicator == "[OUTDATED]"

    def test_status_indicator_wont_fix(self) -> None:
        """Test status indicator for WONT_FIX status."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.WONT_FIX,
        )
        assert issue.status_indicator == "[WONT_FIX]"

    def test_status_indicator_unaddressed(self) -> None:
        """Test status indicator for UNADDRESSED status (empty)."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.UNADDRESSED,
        )
        assert issue.status_indicator == ""

    def test_is_resolved_property_true(self) -> None:
        """Test is_resolved property when status is resolved."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.RESOLVED,
        )
        assert issue.is_resolved is True

    def test_is_resolved_property_false(self) -> None:
        """Test is_resolved property when status is not resolved."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.UNADDRESSED,
        )
        assert issue.is_resolved is False

    def test_is_open_property(self) -> None:
        """Test is_open property."""
        open_issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.UNADDRESSED,
        )
        assert open_issue.is_open is True

        resolved_issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Test",
            status=CommentStatus.RESOLVED,
        )
        assert resolved_issue.is_open is False

    def test_format_display_basic(self) -> None:
        """Test format_display with basic issue."""
        issue = ModelPRIssue(
            file_path="src/main.py",
            line_number=42,
            severity=CommentSeverity.CRITICAL,
            description="Missing null check",
        )
        display = issue.format_display(show_status=False)
        assert "🔴" in display
        assert "[src/main.py:42]" in display
        assert "Missing null check" in display

    def test_format_display_with_status(self) -> None:
        """Test format_display with status indicator."""
        issue = ModelPRIssue(
            severity=CommentSeverity.MAJOR,
            description="Fixed bug",
            status=CommentStatus.RESOLVED,
        )
        display = issue.format_display(show_status=True)
        assert "[RESOLVED]" in display

    def test_from_pr_comment_with_numeric_id(self) -> None:
        """Test from_pr_comment with numeric comment ID."""
        comment = ModelPRComment(
            id="12345",  # Numeric ID (REST API style)
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="This needs fixing",
            created_at=datetime.now(),
        )
        comment.file_ref = ModelFileReference(path="src/test.py", line=10)

        issue = ModelPRIssue.from_pr_comment(comment)

        assert issue.comment_id == 12345  # Should be converted to int
        assert issue.file_path == "src/test.py"
        assert issue.line_number == 10
        assert "This needs fixing" in issue.description

    def test_from_pr_comment_with_non_numeric_id(self) -> None:
        """Test from_pr_comment with non-numeric ID (GraphQL style)."""
        comment = ModelPRComment(
            id="IC_kwDOABC123",  # GraphQL node ID
            source=ModelPRCommentSource.ISSUE_COMMENT,
            author="claude[bot]",
            body="Security vulnerability detected",
            created_at=datetime.now(),
        )

        issue = ModelPRIssue.from_pr_comment(comment)

        assert issue.comment_id is None  # Should be None for non-numeric IDs
        assert "Security vulnerability detected" in issue.description

    def test_from_pr_comment_with_resolved_status(self) -> None:
        """Test from_pr_comment preserves resolution info."""
        resolved_time = datetime.now()
        comment = ModelPRComment(
            id="999",
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="Minor issue",
            created_at=datetime.now(),
            resolved_at=resolved_time,
            resolved_by="author",
        )

        issue = ModelPRIssue.from_pr_comment(comment)

        assert issue.status == CommentStatus.RESOLVED
        assert issue.resolved_at == resolved_time
        assert issue.resolved_by == "author"

    def test_from_pr_comment_with_outdated_flag(self) -> None:
        """Test from_pr_comment handles outdated flag."""
        comment = ModelPRComment(
            id="888",
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="Old comment",
            created_at=datetime.now(),
            is_outdated=True,
        )

        issue = ModelPRIssue.from_pr_comment(comment)

        assert issue.status == CommentStatus.OUTDATED
        assert issue.is_outdated is True

    def test_from_pr_comment_extracts_description(self) -> None:
        """Test from_pr_comment extracts meaningful description."""
        comment = ModelPRComment(
            id="777",
            source=ModelPRCommentSource.PR_COMMENT,
            author="reviewer",
            body="# Header\n\nThis is the actual issue content\n\nMore details",
            created_at=datetime.now(),
        )

        issue = ModelPRIssue.from_pr_comment(comment)

        # Should skip the header and get the meaningful line
        assert "This is the actual issue content" in issue.description

    def test_from_pr_comment_with_severity_override(self) -> None:
        """Test from_pr_comment with severity override."""
        comment = ModelPRComment(
            id="666",
            source=ModelPRCommentSource.REVIEW,
            author="reviewer",
            body="Minor style issue",
            created_at=datetime.now(),
            severity=CommentSeverity.NITPICK,
        )

        issue = ModelPRIssue.from_pr_comment(comment, severity=CommentSeverity.CRITICAL)

        assert issue.severity == CommentSeverity.CRITICAL

    def test_from_pr_comment_with_empty_string_id(self) -> None:
        """Test from_pr_comment with empty string ID (edge case from PR #40)."""
        comment = ModelPRComment(
            id="",  # Empty string ID
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="Some issue to fix",
            created_at=datetime.now(),
        )

        issue = ModelPRIssue.from_pr_comment(comment)

        # Empty string should be converted to None (not raise TypeError)
        assert issue.comment_id is None
        assert "Some issue to fix" in issue.description

    def test_from_pr_comment_with_none_like_values(self) -> None:
        """Test from_pr_comment handles edge cases for comment ID gracefully."""
        # Test with whitespace-only ID
        comment = ModelPRComment(
            id="   ",  # Whitespace - isdigit() returns False
            source=ModelPRCommentSource.PR_COMMENT,
            author="reviewer",
            body="Issue description",
            created_at=datetime.now(),
        )

        issue = ModelPRIssue.from_pr_comment(comment)
        # Whitespace string has isdigit() = False, so should be None
        assert issue.comment_id is None


# =============================================================================
# ModelCollatedIssues Model Tests
# =============================================================================


class TestModelCollatedIssues:
    """Tests for ModelCollatedIssues model."""

    @pytest.fixture
    def sample_issues(self) -> ModelCollatedIssues:
        """Create a sample ModelCollatedIssues for testing."""
        return ModelCollatedIssues(
            pr_number=42,
            repository="owner/repo",
            critical=[
                ModelPRIssue(
                    severity=CommentSeverity.CRITICAL,
                    description="Security flaw",
                    status=CommentStatus.UNADDRESSED,
                ),
                ModelPRIssue(
                    severity=CommentSeverity.CRITICAL,
                    description="Data loss risk",
                    status=CommentStatus.RESOLVED,
                ),
            ],
            major=[
                ModelPRIssue(
                    severity=CommentSeverity.MAJOR,
                    description="Bug in logic",
                    status=CommentStatus.UNADDRESSED,
                ),
                ModelPRIssue(
                    severity=CommentSeverity.MAJOR,
                    description="Missing test",
                    status=CommentStatus.OUTDATED,
                ),
            ],
            minor=[
                ModelPRIssue(
                    severity=CommentSeverity.MINOR,
                    description="Docs update needed",
                    status=CommentStatus.UNADDRESSED,
                ),
            ],
            nitpick=[
                ModelPRIssue(
                    severity=CommentSeverity.NITPICK,
                    description="Naming convention",
                    status=CommentStatus.WONT_FIX,
                ),
            ],
            unclassified=[
                ModelPRIssue(
                    severity=CommentSeverity.UNCLASSIFIED,
                    description="Unknown issue",
                    status=CommentStatus.UNADDRESSED,
                ),
            ],
        )

    def test_all_issues_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test all_issues returns all issues across severities."""
        all_issues = sample_issues.all_issues
        assert len(all_issues) == 7
        descriptions = {i.description for i in all_issues}
        assert "Security flaw" in descriptions
        assert "Bug in logic" in descriptions
        assert "Docs update needed" in descriptions
        assert "Naming convention" in descriptions
        assert "Unknown issue" in descriptions

    def test_open_issues_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test open_issues excludes resolved issues."""
        open_issues = sample_issues.open_issues
        # Should exclude: "Data loss risk" (resolved), "Missing test" (outdated), "Naming convention" (wont_fix)
        assert len(open_issues) == 4
        descriptions = {i.description for i in open_issues}
        assert "Security flaw" in descriptions  # unaddressed
        assert "Bug in logic" in descriptions  # unaddressed
        assert "Docs update needed" in descriptions  # unaddressed
        assert "Unknown issue" in descriptions  # unaddressed
        # These should NOT be in open_issues
        assert "Data loss risk" not in descriptions
        assert "Missing test" not in descriptions
        assert "Naming convention" not in descriptions

    def test_resolved_issues_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test resolved_issues includes only resolved issues."""
        resolved = sample_issues.resolved_issues
        assert len(resolved) == 3
        descriptions = {i.description for i in resolved}
        assert "Data loss risk" in descriptions  # resolved
        assert "Missing test" in descriptions  # outdated (counts as resolved)
        assert "Naming convention" in descriptions  # wont_fix (counts as resolved)

    def test_total_count_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test total_count returns correct count."""
        assert sample_issues.total_count == 7

    def test_open_count_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test open_count returns correct count."""
        assert sample_issues.open_count == 4

    def test_resolved_count_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test resolved_count returns correct count."""
        assert sample_issues.resolved_count == 3

    def test_blocking_count_property(self, sample_issues: ModelCollatedIssues) -> None:
        """Test blocking_count returns open critical + major count."""
        # Open critical: "Security flaw"
        # Open major: "Bug in logic"
        # NOT: "Data loss risk" (resolved), "Missing test" (outdated)
        assert sample_issues.blocking_count == 2

    def test_filter_by_status_hide_resolved(
        self, sample_issues: ModelCollatedIssues
    ) -> None:
        """Test filter_by_status with hide_resolved=True."""
        filtered = sample_issues.filter_by_status(hide_resolved=True)

        assert filtered.total_count == 4
        assert filtered.pr_number == 42  # Preserved
        assert filtered.repository == "owner/repo"  # Preserved

        # Check each category was filtered
        assert len(filtered.critical) == 1
        assert filtered.critical[0].description == "Security flaw"

        assert len(filtered.major) == 1
        assert filtered.major[0].description == "Bug in logic"

        assert len(filtered.minor) == 1
        assert len(filtered.nitpick) == 0  # wont_fix was removed

    def test_filter_by_status_show_resolved_only(
        self, sample_issues: ModelCollatedIssues
    ) -> None:
        """Test filter_by_status with show_resolved_only=True."""
        filtered = sample_issues.filter_by_status(show_resolved_only=True)

        assert filtered.total_count == 3
        # Only resolved issues remain
        assert len(filtered.critical) == 1
        assert filtered.critical[0].description == "Data loss risk"

        assert len(filtered.major) == 1
        assert filtered.major[0].description == "Missing test"

        assert len(filtered.nitpick) == 1
        assert filtered.nitpick[0].description == "Naming convention"

    def test_filter_by_status_conflicting_options(
        self, sample_issues: ModelCollatedIssues
    ) -> None:
        """Test filter_by_status raises error with conflicting options."""
        with pytest.raises(ValueError, match="Cannot use both"):
            sample_issues.filter_by_status(hide_resolved=True, show_resolved_only=True)

    def test_filter_by_status_no_filter(self, sample_issues: ModelCollatedIssues) -> None:
        """Test filter_by_status with no filters returns all issues."""
        filtered = sample_issues.filter_by_status()
        assert filtered.total_count == sample_issues.total_count

    def test_get_summary_basic(self) -> None:
        """Test get_summary with basic issues."""
        issues = ModelCollatedIssues(
            pr_number=1,
            critical=[
                ModelPRIssue(severity=CommentSeverity.CRITICAL, description="c1"),
                ModelPRIssue(severity=CommentSeverity.CRITICAL, description="c2"),
            ],
            major=[
                ModelPRIssue(severity=CommentSeverity.MAJOR, description="m1"),
            ],
            minor=[],
            nitpick=[],
        )

        summary = issues.get_summary()
        assert "2 critical" in summary
        assert "1 major" in summary
        assert "3 actionable" in summary

    def test_get_summary_with_nitpicks(self) -> None:
        """Test get_summary including nitpicks."""
        issues = ModelCollatedIssues(
            pr_number=1,
            critical=[],
            major=[
                ModelPRIssue(severity=CommentSeverity.MAJOR, description="m1"),
            ],
            minor=[],
            nitpick=[
                ModelPRIssue(severity=CommentSeverity.NITPICK, description="n1"),
                ModelPRIssue(severity=CommentSeverity.NITPICK, description="n2"),
            ],
        )

        summary = issues.get_summary(include_nitpicks=True)
        assert "1 major" in summary
        assert "2 nitpick" in summary
        assert "3 actionable" in summary

    def test_get_summary_no_issues(self) -> None:
        """Test get_summary with no issues."""
        issues = ModelCollatedIssues(pr_number=1)
        summary = issues.get_summary()
        assert summary == "No issues found"

    def test_get_summary_excludes_nitpicks_by_default(self) -> None:
        """Test get_summary excludes nitpicks by default."""
        issues = ModelCollatedIssues(
            pr_number=1,
            major=[
                ModelPRIssue(severity=CommentSeverity.MAJOR, description="m1"),
            ],
            nitpick=[
                ModelPRIssue(severity=CommentSeverity.NITPICK, description="n1"),
            ],
        )

        summary = issues.get_summary()
        assert "nitpick" not in summary
        assert "1 actionable" in summary

    def test_empty_collated_issues(self) -> None:
        """Test empty ModelCollatedIssues works correctly."""
        issues = ModelCollatedIssues(pr_number=99)

        assert issues.total_count == 0
        assert issues.open_count == 0
        assert issues.resolved_count == 0
        assert issues.blocking_count == 0
        assert issues.all_issues == []
        assert issues.open_issues == []
        assert issues.resolved_issues == []


# =============================================================================
# BotType Detection Tests
# =============================================================================


class TestBotTypeDetection:
    """Tests for bot type detection functionality."""

    def test_detect_claude_bot(self) -> None:
        """Test detection of Claude bot authors."""
        claude_authors = [
            "claude[bot]",
            "Claude",
            "claude-code",
            "anthropic",
            "claude-bot",
            "CLAUDE",
        ]
        for author in claude_authors:
            assert (
                detect_bot_type(author) == BotType.CLAUDE_CODE
            ), f"Failed for {author}"

    def test_detect_coderabbit(self) -> None:
        """Test detection of CodeRabbit bot."""
        assert detect_bot_type("coderabbitai[bot]") == BotType.CODERABBIT
        assert detect_bot_type("coderabbit") == BotType.CODERABBIT

    def test_detect_github_actions(self) -> None:
        """Test detection of GitHub Actions bot."""
        assert detect_bot_type("github-actions[bot]") == BotType.GITHUB_ACTIONS
        assert detect_bot_type("github-actions") == BotType.GITHUB_ACTIONS

    def test_detect_other_bot(self) -> None:
        """Test detection of generic bots."""
        assert detect_bot_type("some-bot") == BotType.OTHER_BOT
        assert detect_bot_type("dependabot[bot]") == BotType.OTHER_BOT

    def test_detect_human(self) -> None:
        """Test detection of human authors."""
        assert detect_bot_type("octocat") == BotType.HUMAN
        assert detect_bot_type("johndoe") == BotType.HUMAN
        assert detect_bot_type("") == BotType.HUMAN

    def test_bot_type_is_bot_property(self) -> None:
        """Test BotType.is_bot property."""
        assert BotType.CLAUDE_CODE.is_bot is True
        assert BotType.CODERABBIT.is_bot is True
        assert BotType.OTHER_BOT.is_bot is True
        assert BotType.HUMAN.is_bot is False

    def test_bot_type_is_ai_reviewer(self) -> None:
        """Test BotType.is_ai_reviewer property."""
        assert BotType.CLAUDE_CODE.is_ai_reviewer is True
        assert BotType.CODERABBIT.is_ai_reviewer is True
        assert BotType.GITHUB_ACTIONS.is_ai_reviewer is False
        assert BotType.HUMAN.is_ai_reviewer is False


# =============================================================================
# Collate Issues Module Tests
# =============================================================================


class TestCollateIssuesClassifySeverity:
    """Tests for classify_severity function in collate_issues module."""

    def test_classify_critical_patterns(self) -> None:
        """Test classification of critical severity patterns."""
        # Import here to avoid issues with module loading
        from collate_issues import classify_severity

        critical_texts = [
            "## 🔴 Critical Issue",
            "### Must Fix",
            "This is a security vulnerability",
            "May cause data loss",
            "This will crash the app",
            "blocker for release",
        ]
        for text in critical_texts:
            assert (
                classify_severity(text) == CommentSeverity.CRITICAL
            ), f"Failed for: {text}"

    def test_classify_major_patterns(self) -> None:
        """Test classification of major severity patterns."""
        from collate_issues import classify_severity

        major_texts = [
            "## ⚠️ Moderate issue",
            "### Should Fix",
            "This is a bug",
            "Performance problem here",
            "Missing test coverage",
        ]
        for text in major_texts:
            assert (
                classify_severity(text) == CommentSeverity.MAJOR
            ), f"Failed for: {text}"

    def test_classify_minor_patterns(self) -> None:
        """Test classification of minor severity patterns."""
        from collate_issues import classify_severity

        minor_texts = [
            "### 💡 Suggestion",
            "Consider using a different approach",
            "Documentation could be improved",
            "This might be cleaner",
        ]
        for text in minor_texts:
            assert (
                classify_severity(text) == CommentSeverity.MINOR
            ), f"Failed for: {text}"

    def test_classify_nitpick_patterns(self) -> None:
        """Test classification of nitpick severity patterns."""
        from collate_issues import classify_severity

        nitpick_texts = [
            "nit: extra whitespace",
            "nitpick about naming",
            "Style issue only",  # "Style suggestion" would match "suggestion" (minor) first
            "formatting issue",
            "optional: rename this",
        ]
        for text in nitpick_texts:
            assert (
                classify_severity(text) == CommentSeverity.NITPICK
            ), f"Failed for: {text}"

    def test_classify_unclassified(self) -> None:
        """Test unclassified when no patterns match."""
        from collate_issues import classify_severity

        assert classify_severity("") == CommentSeverity.UNCLASSIFIED
        assert (
            classify_severity("Generic comment without keywords")
            == CommentSeverity.UNCLASSIFIED
        )


class TestCollateIssuesBotDetection:
    """Tests for bot detection functions in collate_issues module."""

    def test_is_claude_bot_function(self) -> None:
        """Test is_claude_bot function."""
        from collate_issues import is_claude_bot

        assert is_claude_bot("claude[bot]") is True
        assert is_claude_bot("Claude") is True
        assert is_claude_bot("anthropic") is True
        assert is_claude_bot("") is False
        assert is_claude_bot("johndoe") is False

    def test_is_coderabbit_function(self) -> None:
        """Test is_coderabbit function."""
        from collate_issues import is_coderabbit

        assert is_coderabbit("coderabbitai[bot]") is True
        assert is_coderabbit("coderabbit") is True
        assert is_coderabbit("") is False
        assert is_coderabbit("johndoe") is False


class TestCollateIssuesExtraction:
    """Tests for issue extraction from comment bodies."""

    def test_extract_numbered_bold_issues(self) -> None:
        """Test extraction of ### N. **Title** pattern."""
        from collate_issues import extract_issues_from_body

        body = """
        ### 1. **Security vulnerability**
        Description here
        ### 2. **Missing validation**
        More details
        """
        issues = extract_issues_from_body(body)

        assert len(issues) >= 2
        descriptions = [i["summary"] for i in issues]
        assert "Security vulnerability" in descriptions
        assert "Missing validation" in descriptions

    def test_extract_unchecked_items(self) -> None:
        """Test extraction of unchecked checklist items."""
        from collate_issues import extract_issues_from_body

        body = """
        ## Test Plan
        - [x] Unit tests pass
        - [ ] Integration tests needed
        - [ ] E2E tests pending
        """
        issues = extract_issues_from_body(body)

        assert len(issues) >= 2
        # Unchecked items should be extracted
        summaries = [i["summary"] for i in issues]
        assert any("Integration tests needed" in s for s in summaries)
        assert any("E2E tests pending" in s for s in summaries)

    def test_extract_priority_items(self) -> None:
        """Test extraction of **N. Title (Priority)** pattern."""
        from collate_issues import extract_issues_from_body

        body = """
        **1. Add error handling (High Priority)**
        **2. Update documentation (Low Priority)**
        """
        issues = extract_issues_from_body(body)

        assert len(issues) >= 2
        # High priority should be critical
        high_priority_issue = next(
            (i for i in issues if "Add error handling" in i["summary"]), None
        )
        assert high_priority_issue is not None
        assert high_priority_issue["severity"] == CommentSeverity.CRITICAL


class TestCollateIssuesDeduplication:
    """Tests for issue deduplication logic in collate_issues module."""

    def test_extract_issues_deduplicates_by_summary(self) -> None:
        """Test that extract_issues_from_body deduplicates by normalized summary."""
        from collate_issues import extract_issues_from_body

        # Body with duplicate issues (same title in different patterns)
        body = """
        ### 1. **Add error handling**
        Description here

        **1. Add Error Handling (High Priority)**
        Same issue, different pattern
        """
        issues = extract_issues_from_body(body)

        # Should only have one issue (case-insensitive dedup)
        summaries = [i["summary"].lower() for i in issues]
        assert summaries.count("add error handling") == 1

    def test_extract_issues_preserves_unique_issues(self) -> None:
        """Test that extract_issues_from_body preserves unique issues."""
        from collate_issues import extract_issues_from_body

        body = """
        ### 1. **Add error handling**
        ### 2. **Improve logging**
        ### 3. **Update documentation**
        """
        issues = extract_issues_from_body(body)

        assert len(issues) == 3
        summaries = [i["summary"] for i in issues]
        assert "Add error handling" in summaries
        assert "Improve logging" in summaries
        assert "Update documentation" in summaries

    def test_extract_issues_handles_empty_body(self) -> None:
        """Test that extract_issues_from_body handles empty body gracefully."""
        from collate_issues import extract_issues_from_body

        assert extract_issues_from_body("") == []
        assert extract_issues_from_body(None) == []  # type: ignore[arg-type]


class TestCollateIssuesResolutionMap:
    """Tests for resolution map building and status determination."""

    def test_build_resolution_map(self) -> None:
        """Test building resolution map from resolved threads."""
        from collate_issues import build_resolution_map

        threads = [
            {
                "is_resolved": True,
                "is_outdated": False,
                "resolved_by": "reviewer",
                "comment_ids": [123, 456],
                "path": "src/main.py",
                "line": 42,
            },
            {
                "is_resolved": False,
                "is_outdated": True,
                "comment_ids": [789],
                "path": "src/utils.py",
            },
        ]

        resolution_map = build_resolution_map(threads)

        assert 123 in resolution_map
        assert resolution_map[123]["is_resolved"] is True
        assert resolution_map[123]["resolved_by"] == "reviewer"

        assert 789 in resolution_map
        assert resolution_map[789]["is_outdated"] is True

    def test_determine_comment_status_resolved(self) -> None:
        """Test status determination for resolved comment."""
        from collate_issues import determine_comment_status

        resolution_map = {
            100: {"is_resolved": True, "is_outdated": False, "resolved_by": "user"}
        }

        status, is_outdated, resolved_by = determine_comment_status(100, resolution_map)

        assert status == CommentStatus.RESOLVED
        assert is_outdated is False
        assert resolved_by == "user"

    def test_determine_comment_status_outdated(self) -> None:
        """Test status determination for outdated comment."""
        from collate_issues import determine_comment_status

        resolution_map = {
            200: {"is_resolved": False, "is_outdated": True, "resolved_by": None}
        }

        status, is_outdated, resolved_by = determine_comment_status(200, resolution_map)

        assert status == CommentStatus.OUTDATED
        assert is_outdated is True

    def test_determine_comment_status_not_in_map(self) -> None:
        """Test status determination when comment not in map."""
        from collate_issues import determine_comment_status

        status, is_outdated, resolved_by = determine_comment_status(999, {})

        assert status == CommentStatus.UNADDRESSED
        assert is_outdated is False
        assert resolved_by is None


# =============================================================================
# ModelFileReference Tests
# =============================================================================


class TestModelFileReference:
    """Tests for ModelFileReference model."""

    def test_create_with_path_only(self) -> None:
        """Test creating ModelFileReference with path only."""
        ref = ModelFileReference(path="src/main.py")
        assert ref.path == "src/main.py"
        assert ref.line is None
        assert ref.end_line is None

    def test_create_with_line(self) -> None:
        """Test creating ModelFileReference with path and line."""
        ref = ModelFileReference(path="src/main.py", line=42)
        assert ref.path == "src/main.py"
        assert ref.line == 42

    def test_create_with_line_range(self) -> None:
        """Test creating ModelFileReference with line range."""
        ref = ModelFileReference(path="src/main.py", line=10, end_line=20)
        assert ref.line == 10
        assert ref.end_line == 20

    def test_invalid_line_range(self) -> None:
        """Test that end_line < line raises error."""
        with pytest.raises(ValueError, match="end_line.*must be >= line"):
            ModelFileReference(path="src/main.py", line=20, end_line=10)

    def test_repr_with_line(self) -> None:
        """Test repr with single line."""
        ref = ModelFileReference(path="src/main.py", line=42)
        assert "src/main.py:42" in repr(ref)

    def test_repr_with_range(self) -> None:
        """Test repr with line range."""
        ref = ModelFileReference(path="src/main.py", line=10, end_line=20)
        assert "src/main.py:10-20" in repr(ref)

    def test_from_github_response(self) -> None:
        """Test creating from GitHub API response."""
        data = {
            "path": "src/utils.py",
            "line": 50,
            "end_line": 55,
            "diff_hunk": "@@ -48,10 +48,10 @@",
        }
        ref = ModelFileReference.from_github_response(data)

        assert ref is not None
        assert ref.path == "src/utils.py"
        assert ref.line == 50
        assert ref.end_line == 55
        assert ref.diff_hunk == "@@ -48,10 +48,10 @@"

    def test_from_github_response_no_path(self) -> None:
        """Test from_github_response returns None when no path."""
        data = {"line": 50}
        ref = ModelFileReference.from_github_response(data)
        assert ref is None


# =============================================================================
# ModelPRComment Tests
# =============================================================================


class TestModelPRComment:
    """Tests for ModelPRComment model."""

    def test_create_basic_comment(self) -> None:
        """Test creating a basic PR comment."""
        comment = ModelPRComment(
            id="123",
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="This needs attention",
            created_at=datetime.now(),
        )
        assert comment.id == "123"
        assert comment.source == ModelPRCommentSource.INLINE
        assert comment.author == "reviewer"
        assert comment.author_type == BotType.HUMAN

    def test_auto_detect_claude_bot(self) -> None:
        """Test auto-detection of Claude bot author."""
        comment = ModelPRComment(
            id="456",
            source=ModelPRCommentSource.ISSUE_COMMENT,
            author="claude[bot]",
            body="Code review",
            created_at=datetime.now(),
        )
        assert comment.author_type == BotType.CLAUDE_CODE
        assert comment.is_claude_bot() is True

    def test_is_bot_method(self) -> None:
        """Test is_bot method."""
        bot_comment = ModelPRComment(
            id="1",
            source=ModelPRCommentSource.PR_COMMENT,
            author="some-bot",
            body="Auto message",
            created_at=datetime.now(),
        )
        assert bot_comment.is_bot() is True

        human_comment = ModelPRComment(
            id="2",
            source=ModelPRCommentSource.PR_COMMENT,
            author="johndoe",
            body="My review",
            created_at=datetime.now(),
        )
        assert human_comment.is_bot() is False

    def test_is_blocking(self) -> None:
        """Test is_blocking method."""
        blocking_comment = ModelPRComment(
            id="1",
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="Critical security issue",
            created_at=datetime.now(),
            severity=CommentSeverity.CRITICAL,
            status=CommentStatus.UNADDRESSED,
        )
        assert blocking_comment.is_blocking() is True

        resolved_critical = ModelPRComment(
            id="2",
            source=ModelPRCommentSource.INLINE,
            author="reviewer",
            body="Critical security issue",
            created_at=datetime.now(),
            severity=CommentSeverity.CRITICAL,
            status=CommentStatus.RESOLVED,
        )
        assert resolved_critical.is_blocking() is False

    def test_severity_auto_classification(self) -> None:
        """Test auto-classification of severity from content."""
        comment = ModelPRComment(
            id="1",
            source=ModelPRCommentSource.REVIEW,
            author="reviewer",
            body="This is a security vulnerability that could cause data loss",
            created_at=datetime.now(),
        )
        # Should auto-classify as critical due to "security" and "data loss"
        assert comment.severity == CommentSeverity.CRITICAL


# =============================================================================
# Error Handling Tests (PR #40 fixes)
# =============================================================================


class TestFetchPRDataErrorHandling:
    """Tests for fetch_pr_data error handling."""

    def test_fetch_pr_data_empty_output_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that empty subprocess output raises OnexError."""
        import subprocess as sp
        from unittest.mock import MagicMock

        from collate_issues import OnexError, fetch_pr_data

        # Mock subprocess.run to return empty stdout
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        def mock_run(*args, **kwargs):
            return mock_result

        monkeypatch.setattr(sp, "run", mock_run)

        with pytest.raises(OnexError, match="empty output"):
            fetch_pr_data(123)

    def test_fetch_pr_data_whitespace_only_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that whitespace-only output raises OnexError."""
        import subprocess as sp
        from unittest.mock import MagicMock

        from collate_issues import OnexError, fetch_pr_data

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n\t  "
        mock_result.stderr = ""

        def mock_run(*args, **kwargs):
            return mock_result

        monkeypatch.setattr(sp, "run", mock_run)

        with pytest.raises(OnexError, match="empty output"):
            fetch_pr_data(123)

    def test_fetch_pr_data_invalid_json_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that invalid JSON raises OnexError."""
        import subprocess as sp
        from unittest.mock import MagicMock

        from collate_issues import OnexError, fetch_pr_data

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json {"
        mock_result.stderr = ""

        def mock_run(*args, **kwargs):
            return mock_result

        monkeypatch.setattr(sp, "run", mock_run)

        with pytest.raises(OnexError, match="Failed to parse"):
            fetch_pr_data(123)

    def test_fetch_pr_data_nonzero_exit_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that non-zero exit code raises OnexError."""
        import subprocess as sp
        from unittest.mock import MagicMock

        from collate_issues import OnexError, fetch_pr_data

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Permission denied"

        def mock_run(*args, **kwargs):
            return mock_result

        monkeypatch.setattr(sp, "run", mock_run)

        with pytest.raises(OnexError, match="fetch-pr-data failed"):
            fetch_pr_data(123)

    def test_fetch_pr_data_timeout_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that subprocess timeout raises OnexError."""
        import subprocess as sp

        from collate_issues import OnexError, fetch_pr_data

        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd=["fetch-pr-data"], timeout=120)

        monkeypatch.setattr(sp, "run", mock_run)

        with pytest.raises(OnexError, match="timed out"):
            fetch_pr_data(123)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
