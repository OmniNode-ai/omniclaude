# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for TransformationValidator.

Covers:
- Valid self-transformations with sufficient reasoning
- Blocked short-reason self-transformations
- Low-confidence specialized task blocking
- Orchestration keyword passthrough
- Word-boundary matching (no false positives from substrings)
- Non-self-transformations (always valid)
- Fail-closed internal error path
"""

import pytest

from omniclaude.lib.core.transformation_validator import (
    TransformationValidator,
    validate_transformation,
)


class TestNonSelfTransformations:
    """Non-self-transformations should always be valid."""

    def test_different_agents_always_valid(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="agent-api-architect",
            reason="API task detected",
            confidence=0.95,
        )
        assert result.is_valid is True
        assert result.metrics["transformation_type"] == "specialized"

    def test_non_polymorphic_source_always_valid(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="agent-researcher",
            to_agent="agent-api-architect",
            reason="x",
            confidence=0.1,
        )
        assert result.is_valid is True


class TestSelfTransformationReasonLength:
    """Self-transformations require minimum 50-char reasoning."""

    def test_short_reason_blocked(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="too short",
        )
        assert result.is_valid is False
        assert "min 50 chars" in result.error_message

    def test_empty_reason_blocked(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="",
        )
        assert result.is_valid is False

    def test_none_reason_blocked(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason=None,
        )
        assert result.is_valid is False

    def test_sufficient_reason_allowed(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="This is a multi-agent orchestration task that requires coordinating multiple parallel workflows",
            confidence=0.85,
        )
        assert result.is_valid is True

    def test_custom_min_reason_length(self):
        validator = TransformationValidator(min_reason_length=10)
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="short text",
            confidence=0.85,
        )
        assert result.is_valid is True


class TestOrchestrationKeywords:
    """Orchestration keywords indicate legitimate self-transformation."""

    @pytest.mark.parametrize(
        "keyword",
        [
            "orchestrate",
            "coordinate",
            "workflow",
            "multi-agent",
            "parallel",
            "sequential",
            "batch",
            "pipeline",
        ],
    )
    def test_orchestration_keyword_detected(self, keyword):
        validator = TransformationValidator()
        reason = f"This task requires {keyword} execution across multiple components for proper coordination"
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason=reason,
            confidence=0.5,
        )
        # Orchestration with low confidence -> still valid (orchestration overrides)
        assert result.is_valid is True
        assert result.metrics["is_orchestration_task"] is True


class TestSpecializedKeywordBlocking:
    """Specialized tasks with low confidence should be blocked."""

    def test_specialized_low_confidence_blocked(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="This task involves frontend development with React components and styling updates",
            confidence=0.3,
            user_request="Build a frontend dashboard",
        )
        assert result.is_valid is False
        assert "Self-transformation blocked" in result.error_message

    def test_specialized_high_confidence_allowed(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Complex frontend and backend integration requiring full-stack orchestration capabilities",
            confidence=0.85,
            user_request="Build a frontend dashboard",
        )
        assert result.is_valid is True

    def test_specialized_plus_orchestration_overrides(self):
        """Orchestration keyword overrides specialized keyword blocking."""
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Orchestrate frontend and backend deployment pipeline across multiple services",
            confidence=0.3,
            user_request="orchestrate frontend deployment",
        )
        # Has both "frontend" (specialized) and "orchestrate" (orchestration)
        # Orchestration overrides the specialized blocking
        assert result.is_valid is True


class TestWordBoundaryMatching:
    """Short keywords must use word-boundary matching to prevent false positives."""

    def test_capital_does_not_match_api(self):
        """'capital' should NOT trigger 'api' keyword."""
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Analyze the capital expenditure reports and financial data for the quarterly review",
            confidence=0.3,
            user_request="review capital expenditure",
        )
        # Should NOT be detected as specialized (no actual "api" word)
        assert result.metrics.get("is_specialized_task") is False

    def test_therapy_does_not_match_api(self):
        """'therapy' should NOT trigger 'api' keyword."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("therapy session notes") is False

    def test_actual_api_does_match(self):
        """'api' as a standalone word should still match."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("design an api endpoint") is True

    def test_built_does_not_match_ui(self):
        """'built' should NOT trigger 'ui' keyword."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("the system was built yesterday") is False

    def test_actual_ui_does_match(self):
        """'ui' as a standalone word should match."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("fix the ui layout") is True

    def test_sequel_does_not_match_sql(self):
        """'sequel' should NOT trigger 'sql' keyword."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("watch the sequel movie") is False

    def test_actual_sql_does_match(self):
        """'sql' as a standalone word should match."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("optimize the sql query") is True

    def test_discussion_does_not_match_css(self):
        """'discussion' should NOT trigger 'css' keyword."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("join the discussion thread") is False

    def test_linux_does_not_match_ux(self):
        """'linux' should NOT trigger 'ux' keyword."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("deploy to linux server") is False

    def test_longer_keywords_use_substring_matching(self):
        """Keywords >4 chars like 'frontend', 'database' use substring matching."""
        validator = TransformationValidator()
        assert validator._is_specialized_task("the frontend needs work") is True
        assert validator._is_specialized_task("database migration") is True
        assert validator._is_specialized_task("javascript module") is True


class TestLowConfidenceWarning:
    """Low confidence generates warnings."""

    def test_low_confidence_warning(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="General task coordination that requires the polymorphic agent's broad capabilities",
            confidence=0.4,
        )
        assert result.is_valid is True
        assert "Low confidence" in result.warning_message

    def test_high_confidence_no_warning(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Multi-agent orchestration task requiring coordination of parallel workflows",
            confidence=0.9,
        )
        assert result.is_valid is True
        assert result.warning_message == ""

    def test_no_confidence_no_warning(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Multi-agent orchestration task requiring coordination of parallel workflows",
            confidence=None,
        )
        assert result.is_valid is True
        assert result.warning_message == ""


class TestFailClosed:
    """Internal errors should reject the transformation (fail closed)."""

    def test_internal_error_returns_invalid(self):
        validator = TransformationValidator()

        # Monkey-patch _validate_internal to raise
        original = validator._validate_internal

        def raise_error(*args, **kwargs):
            raise RuntimeError("unexpected validator bug")

        validator._validate_internal = raise_error

        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="test",
        )
        assert result.is_valid is False
        assert "internal error" in result.error_message.lower()
        assert result.metrics["internal_error_type"] == "RuntimeError"

        # Restore
        validator._validate_internal = original


class TestConvenienceFunction:
    """Test the module-level validate_transformation() function."""

    def test_convenience_function_works(self):
        result = validate_transformation(
            from_agent="polymorphic-agent",
            to_agent="agent-api-architect",
            reason="API task",
            confidence=0.95,
        )
        assert result.is_valid is True

    def test_convenience_function_blocks_invalid(self):
        result = validate_transformation(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="short",
        )
        assert result.is_valid is False


class TestMetrics:
    """Validate metrics are properly populated."""

    def test_self_transformation_metrics(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Multi-agent orchestration for complex parallel workflow execution across repos",
            confidence=0.8,
            user_request="orchestrate parallel execution",
        )
        assert result.metrics["transformation_type"] == "self"
        assert result.metrics["confidence"] == 0.8
        assert result.metrics["is_orchestration_task"] is True
        assert "reason_length" in result.metrics

    def test_specialized_transformation_metrics(self):
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="agent-frontend-dev",
            reason="Frontend task",
        )
        assert result.metrics["transformation_type"] == "specialized"
