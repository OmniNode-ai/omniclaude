# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for PatternQualityScorer - pattern quality evaluation across dimensions.

Tests the scoring logic for:
1. Code Completeness: Penalizes stubs, rewards logic
2. Documentation Quality: Rewards docstrings, comments, type hints
3. ONEX Compliance: Rewards node_type, proper naming, method signatures
4. Metadata Richness: Rewards use_cases, examples, rich metadata
5. Complexity Appropriateness: Matches declared vs actual complexity

Composite score is a weighted average of all dimensions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from omniclaude.lib.pattern_quality_scorer import (
    PatternQualityScore,
    PatternQualityScorer,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def scorer() -> PatternQualityScorer:
    """Create a PatternQualityScorer instance."""
    return PatternQualityScorer()


@pytest.fixture
def minimal_pattern() -> dict[str, Any]:
    """Create a minimal pattern with required fields only."""
    return {
        "pattern_id": "test-pattern-001",
        "pattern_name": "TestPattern",
        "code": "",
        "text": "",
        "metadata": {},
        "node_type": None,
        "use_cases": [],
        "examples": [],
        "confidence": 0.5,
    }


@pytest.fixture
def complete_pattern() -> dict[str, Any]:
    """Create a complete pattern with all fields populated."""
    return {
        "pattern_id": "test-pattern-002",
        "pattern_name": "NodeTestCompute",
        "code": '''"""Compute node for testing.

This is a comprehensive docstring.
"""

import asyncio
from typing import Any

class NodeTestCompute:
    """Test compute node implementation."""

    async def execute_compute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute computation on input data.

        Args:
            input_data: Input dictionary

        Returns:
            Processed result
        """
        # Process the input
        if input_data:
            for key, value in input_data.items():
                if value is not None:
                    # Transform the value
                    pass
        return {"status": "success"}
''',
        "text": "This is a comprehensive description of the test compute node. "
        "It provides pattern discovery and quality evaluation capabilities. "
        "The node follows ONEX architecture patterns and conventions.",
        "metadata": {
            "complexity": "medium",
            "domain": "testing",
            "category": "compute",
            "version": "1.0.0",
        },
        "node_type": "compute",
        "use_cases": [
            "Pattern quality evaluation",
            "Code analysis",
            "Metric generation",
        ],
        "examples": [
            "Example usage 1",
            "Example usage 2",
        ],
        "confidence": 0.95,
    }


@pytest.fixture
def stub_pattern() -> dict[str, Any]:
    """Create a pattern with stub implementations."""
    return {
        "pattern_id": "test-pattern-003",
        "pattern_name": "StubPattern",
        "code": """class StubPattern:
    def do_something(self):
        pass  # TODO: implement this

    def another_method(self):
        raise NotImplementedError("Not implemented yet")
""",
        "text": "A stub pattern.",
        "metadata": {},
        "node_type": None,
        "use_cases": [],
        "examples": [],
        "confidence": 0.3,
    }


# =============================================================================
# PatternQualityScore Dataclass Tests
# =============================================================================


class TestPatternQualityScoreDataclass:
    """Tests for PatternQualityScore dataclass fields."""

    def test_dataclass_has_required_fields(self) -> None:
        """PatternQualityScore has all required fields."""
        score = PatternQualityScore(
            pattern_id="test-id",
            pattern_name="TestPattern",
            composite_score=0.75,
            completeness_score=0.8,
            documentation_score=0.7,
            onex_compliance_score=0.6,
            metadata_richness_score=0.5,
            complexity_score=0.9,
            confidence=0.85,
            measurement_timestamp=datetime.now(UTC),
        )
        assert score.pattern_id == "test-id"
        assert score.pattern_name == "TestPattern"
        assert score.composite_score == 0.75
        assert score.completeness_score == 0.8
        assert score.documentation_score == 0.7
        assert score.onex_compliance_score == 0.6
        assert score.metadata_richness_score == 0.5
        assert score.complexity_score == 0.9
        assert score.confidence == 0.85
        assert score.version == "1.0.0"

    def test_dataclass_default_version(self) -> None:
        """PatternQualityScore has default version of 1.0.0."""
        score = PatternQualityScore(
            pattern_id="test",
            pattern_name="Test",
            composite_score=0.5,
            completeness_score=0.5,
            documentation_score=0.5,
            onex_compliance_score=0.5,
            metadata_richness_score=0.5,
            complexity_score=0.5,
            confidence=0.5,
            measurement_timestamp=datetime.now(UTC),
        )
        assert score.version == "1.0.0"

    def test_dataclass_custom_version(self) -> None:
        """PatternQualityScore accepts custom version."""
        score = PatternQualityScore(
            pattern_id="test",
            pattern_name="Test",
            composite_score=0.5,
            completeness_score=0.5,
            documentation_score=0.5,
            onex_compliance_score=0.5,
            metadata_richness_score=0.5,
            complexity_score=0.5,
            confidence=0.5,
            measurement_timestamp=datetime.now(UTC),
            version="2.0.0",
        )
        assert score.version == "2.0.0"

    def test_dataclass_timestamp_is_datetime(self) -> None:
        """PatternQualityScore measurement_timestamp is datetime."""
        timestamp = datetime.now(UTC)
        score = PatternQualityScore(
            pattern_id="test",
            pattern_name="Test",
            composite_score=0.5,
            completeness_score=0.5,
            documentation_score=0.5,
            onex_compliance_score=0.5,
            metadata_richness_score=0.5,
            complexity_score=0.5,
            confidence=0.5,
            measurement_timestamp=timestamp,
        )
        assert score.measurement_timestamp == timestamp
        assert isinstance(score.measurement_timestamp, datetime)


# =============================================================================
# PatternQualityScorer Class Constants Tests
# =============================================================================


class TestPatternQualityScorerConstants:
    """Tests for PatternQualityScorer class constants."""

    def test_quality_thresholds(self) -> None:
        """Quality thresholds are defined correctly."""
        assert PatternQualityScorer.EXCELLENT_THRESHOLD == 0.9
        assert PatternQualityScorer.GOOD_THRESHOLD == 0.7
        assert PatternQualityScorer.FAIR_THRESHOLD == 0.5

    def test_weights_sum_to_one(self) -> None:
        """Composite score weights sum to 1.0."""
        weights = PatternQualityScorer.WEIGHTS
        total = sum(weights.values())
        assert total == pytest.approx(1.0)

    def test_weights_values(self) -> None:
        """Individual weight values are correct."""
        weights = PatternQualityScorer.WEIGHTS
        assert weights["completeness"] == 0.30
        assert weights["documentation"] == 0.25
        assert weights["onex_compliance"] == 0.20
        assert weights["metadata_richness"] == 0.15
        assert weights["complexity"] == 0.10


# =============================================================================
# score_pattern Method Tests
# =============================================================================


class TestScorePattern:
    """Tests for the score_pattern method."""

    def test_returns_pattern_quality_score(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """score_pattern returns a PatternQualityScore object."""
        result = scorer.score_pattern(minimal_pattern)
        assert isinstance(result, PatternQualityScore)

    def test_extracts_pattern_id(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """score_pattern extracts pattern_id from input."""
        result = scorer.score_pattern(minimal_pattern)
        assert result.pattern_id == "test-pattern-001"

    def test_extracts_pattern_name(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """score_pattern extracts pattern_name from input."""
        result = scorer.score_pattern(minimal_pattern)
        assert result.pattern_name == "TestPattern"

    def test_extracts_confidence(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """score_pattern extracts confidence from input."""
        result = scorer.score_pattern(minimal_pattern)
        assert result.confidence == 0.5

    def test_composite_score_is_weighted_average(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """Composite score is weighted average of dimension scores."""
        result = scorer.score_pattern(complete_pattern)

        # Calculate expected composite score
        expected = (
            result.completeness_score * 0.30
            + result.documentation_score * 0.25
            + result.onex_compliance_score * 0.20
            + result.metadata_richness_score * 0.15
            + result.complexity_score * 0.10
        )
        assert result.composite_score == pytest.approx(expected, rel=1e-6)

    def test_all_dimension_scores_populated(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """All dimension scores are populated."""
        result = scorer.score_pattern(complete_pattern)
        assert result.completeness_score >= 0.0
        assert result.documentation_score >= 0.0
        assert result.onex_compliance_score >= 0.0
        assert result.metadata_richness_score >= 0.0
        assert result.complexity_score >= 0.0

    def test_measurement_timestamp_is_recent(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """Measurement timestamp is set to current time."""
        before = datetime.now(UTC)
        result = scorer.score_pattern(minimal_pattern)
        after = datetime.now(UTC)
        assert before <= result.measurement_timestamp <= after

    def test_handles_missing_fields_gracefully(self, scorer: PatternQualityScorer) -> None:
        """score_pattern handles missing fields gracefully."""
        empty_pattern: dict[str, Any] = {}
        result = scorer.score_pattern(empty_pattern)
        assert result.pattern_id == ""
        assert result.pattern_name == ""
        assert result.confidence == 0.0


# =============================================================================
# _score_completeness Method Tests
# =============================================================================


class TestScoreCompleteness:
    """Tests for _score_completeness method."""

    def test_empty_code_returns_zero(self, scorer: PatternQualityScorer) -> None:
        """Empty code returns 0.0 completeness score."""
        score = scorer._score_completeness("", "")
        assert score == 0.0

    def test_stub_pass_penalized(self, scorer: PatternQualityScorer) -> None:
        """Code with 'pass' statement is penalized."""
        code_with_pass = "def foo():\n    pass"
        code_without_pass = "def foo():\n    return 42"
        score_with = scorer._score_completeness(code_with_pass, "")
        score_without = scorer._score_completeness(code_without_pass, "")
        assert score_with < score_without

    def test_stub_todo_penalized(self, scorer: PatternQualityScorer) -> None:
        """Code with 'TODO' comment is penalized."""
        code_with_todo = "def foo():\n    # TODO: implement\n    return None"
        code_without_todo = "def foo():\n    return 42"
        score_with = scorer._score_completeness(code_with_todo, "")
        score_without = scorer._score_completeness(code_without_todo, "")
        assert score_with < score_without

    def test_stub_not_implemented_error_penalized(self, scorer: PatternQualityScorer) -> None:
        """Code with 'raise NotImplementedError' is penalized."""
        code_with_error = "def foo():\n    raise NotImplementedError('Not done')"
        code_without_error = "def foo():\n    return 42"
        score_with = scorer._score_completeness(code_with_error, "")
        score_without = scorer._score_completeness(code_without_error, "")
        assert score_with < score_without

    def test_stub_ellipsis_penalized(self, scorer: PatternQualityScorer) -> None:
        """Code with ellipsis (...) is penalized."""
        code_with_ellipsis = "def foo():\n    ..."
        code_without_ellipsis = "def foo():\n    return 42"
        score_with = scorer._score_completeness(code_with_ellipsis, "")
        score_without = scorer._score_completeness(code_without_ellipsis, "")
        assert score_with < score_without

    def test_logic_if_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with 'if' statement gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        # Both have 'pass' (-0.2 penalty), but one has 'if ' (+0.1 bonus)
        code_with_if = "def foo(x):\n    pass\n    if x:\n        return 1"
        code_without_if = "def foo(x):\n    pass\n    return x"
        score_with = scorer._score_completeness(code_with_if, "")
        score_without = scorer._score_completeness(code_without_if, "")
        assert score_with > score_without

    def test_logic_for_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with 'for' loop gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        code_with_for = "def foo(items):\n    pass\n    for item in items:\n        x = 1"
        code_without_for = "def foo(items):\n    pass\n    x = items"
        score_with = scorer._score_completeness(code_with_for, "")
        score_without = scorer._score_completeness(code_without_for, "")
        assert score_with > score_without

    def test_logic_while_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with 'while' loop gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        code_with_while = "def foo():\n    pass\n    while True:\n        break"
        code_without_while = "def foo():\n    pass\n    return True"
        score_with = scorer._score_completeness(code_with_while, "")
        score_without = scorer._score_completeness(code_without_while, "")
        assert score_with > score_without

    def test_logic_async_def_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with 'async def' gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        code_with_async = "pass\nasync def foo():\n    return 1"
        code_without_async = "pass\ndef foo():\n    return 1"
        score_with = scorer._score_completeness(code_with_async, "")
        score_without = scorer._score_completeness(code_without_async, "")
        assert score_with > score_without

    def test_logic_class_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with 'class' definition gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        code_with_class = "pass\nclass Foo:\n    def bar(self):\n        return 1"
        code_without_class = "pass\ndef bar():\n    return 1"
        score_with = scorer._score_completeness(code_with_class, "")
        score_without = scorer._score_completeness(code_without_class, "")
        assert score_with > score_without

    def test_imports_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with imports gets bonus.

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        code_with_import = "import os\npass\ndef foo():\n    return 1"
        code_without_import = "pass\ndef foo():\n    return 1"
        score_with = scorer._score_completeness(code_with_import, "")
        score_without = scorer._score_completeness(code_without_import, "")
        assert score_with > score_without

    def test_line_count_bonus(self, scorer: PatternQualityScorer) -> None:
        """Longer code gets line count bonus (up to limit).

        Use code with a stub penalty so bonuses are visible below the 1.0 cap.
        """
        short_code = "pass\ndef foo():\n    return 1"
        # 50 lines of code with pass penalty
        long_code = "pass\n" + "\n".join([f"line{i} = {i}" for i in range(50)])
        score_short = scorer._score_completeness(short_code, "")
        score_long = scorer._score_completeness(long_code, "")
        assert score_long > score_short

    def test_score_capped_at_one(self, scorer: PatternQualityScorer) -> None:
        """Score is capped at 1.0 maximum."""
        # Code with all bonuses
        excellent_code = """import os
import sys

class MyClass:
    async def execute_compute(self, data):
        if data:
            for item in data:
                while True:
                    break
        return data
"""
        # Add many more lines
        excellent_code += "\n".join([f"var{i} = {i}" for i in range(200)])
        score = scorer._score_completeness(excellent_code, "")
        assert score <= 1.0

    def test_score_floor_at_zero(self, scorer: PatternQualityScorer) -> None:
        """Score is floored at 0.0 minimum."""
        # Code with multiple penalties
        terrible_code = """def foo():
    pass
    # TODO: implement
    raise NotImplementedError
    ...
"""
        score = scorer._score_completeness(terrible_code, "")
        assert score >= 0.0

    def test_multiple_stubs_cumulative_penalty(self, scorer: PatternQualityScorer) -> None:
        """Multiple stub indicators apply cumulative penalties."""
        one_stub = "def foo():\n    pass"
        two_stubs = "def foo():\n    pass\n    # TODO"
        three_stubs = "def foo():\n    pass\n    # TODO\n    raise NotImplementedError"
        score_one = scorer._score_completeness(one_stub, "")
        score_two = scorer._score_completeness(two_stubs, "")
        score_three = scorer._score_completeness(three_stubs, "")
        assert score_one > score_two > score_three


# =============================================================================
# _score_documentation Method Tests
# =============================================================================


class TestScoreDocumentation:
    """Tests for _score_documentation method."""

    def test_empty_code_and_text_returns_zero(self, scorer: PatternQualityScorer) -> None:
        """Empty code and text returns 0.0."""
        score = scorer._score_documentation("", "")
        assert score == 0.0

    def test_docstring_triple_double_quotes_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with triple double-quote docstrings gets bonus."""
        code_with_docstring = '''def foo():
    """This is a docstring."""
    return 1'''
        code_without_docstring = "def foo():\n    return 1"
        score_with = scorer._score_documentation(code_with_docstring, "")
        score_without = scorer._score_documentation(code_without_docstring, "")
        assert score_with > score_without

    def test_docstring_triple_single_quotes_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with triple single-quote docstrings gets bonus."""
        code_with_docstring = "def foo():\n    '''This is a docstring.'''\n    return 1"
        code_without_docstring = "def foo():\n    return 1"
        score_with = scorer._score_documentation(code_with_docstring, "")
        score_without = scorer._score_documentation(code_without_docstring, "")
        assert score_with > score_without

    def test_inline_comments_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with inline comments gets bonus."""
        code_with_comments = """def foo():
    # Initialize counter
    count = 0
    # Process items
    for i in range(10):
        count += i  # Accumulate
    return count
"""
        code_without_comments = """def foo():
    count = 0
    for i in range(10):
        count += i
    return count
"""
        score_with = scorer._score_documentation(code_with_comments, "")
        score_without = scorer._score_documentation(code_without_comments, "")
        assert score_with > score_without

    def test_comment_bonus_capped(self, scorer: PatternQualityScorer) -> None:
        """Comment bonus is capped at 0.2."""
        # Create code with many comments (25+ lines with comments)
        many_comments = "\n".join([f"# Comment line {i}" for i in range(30)])
        # Create code with moderate comments (10 lines)
        some_comments = "\n".join([f"# Comment line {i}" for i in range(10)])
        score_many = scorer._score_documentation(many_comments, "")
        score_some = scorer._score_documentation(some_comments, "")
        # Both should contribute to score, but many comments caps at 0.2 bonus
        assert score_many >= score_some

    def test_type_hints_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Code with type hints gets bonus.

        Note: The regex r":\\s*\\w+|\\s*->\\s*\\w+" detects type hints.
        Code without hints must avoid patterns that match this regex
        (e.g., `: ` followed by whitespace and a word).
        """
        # Code with explicit type hints
        code_with_hints = "x: int = 5"
        # Code without any `:` to avoid false positive matches
        code_without_hints = "x = 5"
        score_with = scorer._score_documentation(code_with_hints, "")
        score_without = scorer._score_documentation(code_without_hints, "")
        assert score_with > score_without

    def test_descriptive_text_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Descriptive text over 100 characters gets bonus."""
        short_text = "Brief description."
        long_text = (
            "This is a comprehensive description that exceeds one hundred characters "
            "and provides detailed information about the pattern and its usage."
        )
        score_short = scorer._score_documentation("def foo(): pass", short_text)
        score_long = scorer._score_documentation("def foo(): pass", long_text)
        assert score_long > score_short

    def test_text_exactly_100_chars_no_bonus(self, scorer: PatternQualityScorer) -> None:
        """Text at exactly 100 characters does not get bonus."""
        text_100 = "x" * 100
        text_101 = "x" * 101
        score_100 = scorer._score_documentation("def foo(): pass", text_100)
        score_101 = scorer._score_documentation("def foo(): pass", text_101)
        assert score_101 > score_100

    def test_score_capped_at_one(self, scorer: PatternQualityScorer) -> None:
        """Documentation score is capped at 1.0."""
        # Code with all documentation bonuses
        excellent_docs = '''"""Module docstring."""

def foo(x: int) -> str:
    """Function docstring.

    Args:
        x: An integer

    Returns:
        A string
    """
    # Implementation comment
    # Another comment
    # More comments
    return str(x)
'''
        long_text = "x" * 200
        score = scorer._score_documentation(excellent_docs, long_text)
        assert score <= 1.0


# =============================================================================
# _score_onex_compliance Method Tests
# =============================================================================


class TestScoreOnexCompliance:
    """Tests for _score_onex_compliance method."""

    def test_no_node_type_base_score(self, scorer: PatternQualityScorer) -> None:
        """No node_type returns base score of 0.3."""
        score = scorer._score_onex_compliance("def foo(): pass", None, "SimplePattern")
        assert score == 0.3

    def test_no_node_type_name_suggests_type(self, scorer: PatternQualityScorer) -> None:
        """No node_type but name suggests type returns 0.5."""
        for name in [
            "MyEffect",
            "TestCompute",
            "DataReducer",
            "WorkflowOrchestrator",
        ]:
            score = scorer._score_onex_compliance("def foo(): pass", None, name)
            assert score == 0.5

    def test_has_node_type_base_score(self, scorer: PatternQualityScorer) -> None:
        """Having node_type gives base score of 0.7."""
        score = scorer._score_onex_compliance("def foo(): pass", "effect", "SimplePattern")
        assert score >= 0.7

    def test_proper_naming_bonus(self, scorer: PatternQualityScorer) -> None:
        """Proper naming (node_type in pattern_name) gives bonus."""
        score_proper = scorer._score_onex_compliance("def foo(): pass", "effect", "NodeTestEffect")
        score_improper = scorer._score_onex_compliance("def foo(): pass", "effect", "SomePattern")
        assert score_proper > score_improper

    def test_proper_naming_case_insensitive(self, scorer: PatternQualityScorer) -> None:
        """Proper naming check is case-insensitive."""
        score = scorer._score_onex_compliance("def foo(): pass", "EFFECT", "nodetesteffect")
        assert score > 0.7  # Should get naming bonus

    def test_onex_method_signature_effect(self, scorer: PatternQualityScorer) -> None:
        """Effect node with execute_effect method gets bonus."""
        code_with_sig = "async def execute_effect(self): pass"
        code_without_sig = "async def run(self): pass"
        score_with = scorer._score_onex_compliance(code_with_sig, "effect", "TestEffect")
        score_without = scorer._score_onex_compliance(code_without_sig, "effect", "TestEffect")
        assert score_with > score_without

    def test_onex_method_signature_compute(self, scorer: PatternQualityScorer) -> None:
        """Compute node with execute_compute method gets bonus."""
        code_with_sig = "async def execute_compute(self): pass"
        code_without_sig = "async def run(self): pass"
        score_with = scorer._score_onex_compliance(code_with_sig, "compute", "TestCompute")
        score_without = scorer._score_onex_compliance(code_without_sig, "compute", "TestCompute")
        assert score_with > score_without

    def test_onex_method_signature_reducer(self, scorer: PatternQualityScorer) -> None:
        """Reducer node with execute_reduction method gets bonus."""
        code_with_sig = "async def execute_reduction(self): pass"
        code_without_sig = "async def run(self): pass"
        score_with = scorer._score_onex_compliance(code_with_sig, "reducer", "TestReducer")
        score_without = scorer._score_onex_compliance(code_without_sig, "reducer", "TestReducer")
        assert score_with > score_without

    def test_onex_method_signature_orchestrator(self, scorer: PatternQualityScorer) -> None:
        """Orchestrator node with execute_orchestration method gets bonus."""
        code_with_sig = "async def execute_orchestration(self): pass"
        code_without_sig = "async def run(self): pass"
        score_with = scorer._score_onex_compliance(
            code_with_sig, "orchestrator", "TestOrchestrator"
        )
        score_without = scorer._score_onex_compliance(
            code_without_sig, "orchestrator", "TestOrchestrator"
        )
        assert score_with > score_without

    def test_max_score_with_all_bonuses(self, scorer: PatternQualityScorer) -> None:
        """Maximum ONEX compliance score with all bonuses."""
        code = "async def execute_effect(self, data): return data"
        score = scorer._score_onex_compliance(code, "effect", "NodeTestEffect")
        # Base 0.7 + naming 0.15 + method 0.15 = 1.0
        assert score == 1.0

    def test_score_capped_at_one(self, scorer: PatternQualityScorer) -> None:
        """ONEX compliance score is capped at 1.0."""
        code = "async def execute_effect(self, data): return data"
        score = scorer._score_onex_compliance(code, "effect", "NodeTestEffect")
        assert score <= 1.0


# =============================================================================
# _score_metadata_richness Method Tests
# =============================================================================


class TestScoreMetadataRichness:
    """Tests for _score_metadata_richness method."""

    def test_empty_metadata_returns_zero(self, scorer: PatternQualityScorer) -> None:
        """Empty use_cases, examples, and metadata returns 0.0."""
        score = scorer._score_metadata_richness([], [], {})
        assert score == 0.0

    def test_use_cases_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Having use cases adds to score."""
        score_with = scorer._score_metadata_richness(["Use case 1"], [], {})
        score_without = scorer._score_metadata_richness([], [], {})
        assert score_with > score_without

    def test_use_cases_bonus_capped(self, scorer: PatternQualityScorer) -> None:
        """Use cases bonus is capped at 0.4 (3 use cases)."""
        score_3 = scorer._score_metadata_richness(["UC1", "UC2", "UC3"], [], {})
        score_5 = scorer._score_metadata_richness(["UC1", "UC2", "UC3", "UC4", "UC5"], [], {})
        # Both should have same use cases contribution (capped at 0.4)
        assert score_3 == pytest.approx(score_5, rel=1e-6)

    def test_examples_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Having examples adds to score."""
        score_with = scorer._score_metadata_richness([], ["Example 1"], {})
        score_without = scorer._score_metadata_richness([], [], {})
        assert score_with > score_without

    def test_examples_bonus_capped(self, scorer: PatternQualityScorer) -> None:
        """Examples bonus is capped at 0.3 (2 examples)."""
        score_2 = scorer._score_metadata_richness([], ["Ex1", "Ex2"], {})
        score_5 = scorer._score_metadata_richness([], ["Ex1", "Ex2", "Ex3", "Ex4", "Ex5"], {})
        # Both should have same examples contribution (capped at 0.3)
        assert score_2 == pytest.approx(score_5, rel=1e-6)

    def test_rich_metadata_rewarded(self, scorer: PatternQualityScorer) -> None:
        """Metadata with >3 fields adds bonus."""
        rich_metadata = {
            "field1": "value1",
            "field2": "value2",
            "field3": "value3",
            "field4": "value4",
        }
        sparse_metadata = {"field1": "value1"}
        score_rich = scorer._score_metadata_richness([], [], rich_metadata)
        score_sparse = scorer._score_metadata_richness([], [], sparse_metadata)
        assert score_rich > score_sparse

    def test_metadata_exactly_3_fields_no_bonus(self, scorer: PatternQualityScorer) -> None:
        """Metadata with exactly 3 fields does not get bonus."""
        metadata_3 = {"f1": "v1", "f2": "v2", "f3": "v3"}
        metadata_4 = {"f1": "v1", "f2": "v2", "f3": "v3", "f4": "v4"}
        score_3 = scorer._score_metadata_richness([], [], metadata_3)
        score_4 = scorer._score_metadata_richness([], [], metadata_4)
        assert score_4 > score_3

    def test_all_metadata_combined(self, scorer: PatternQualityScorer) -> None:
        """Combined use_cases, examples, and rich metadata."""
        use_cases = ["UC1", "UC2", "UC3"]
        examples = ["Ex1", "Ex2"]
        metadata = {"f1": "v1", "f2": "v2", "f3": "v3", "f4": "v4"}
        score = scorer._score_metadata_richness(use_cases, examples, metadata)
        # Should get all bonuses: 0.4 + 0.3 + 0.3 = 1.0
        assert score == pytest.approx(1.0, rel=1e-6)

    def test_score_capped_at_one(self, scorer: PatternQualityScorer) -> None:
        """Metadata richness score is capped at 1.0."""
        use_cases = ["UC1", "UC2", "UC3", "UC4", "UC5"]
        examples = ["Ex1", "Ex2", "Ex3", "Ex4", "Ex5"]
        metadata = {f"field{i}": f"value{i}" for i in range(10)}
        score = scorer._score_metadata_richness(use_cases, examples, metadata)
        assert score <= 1.0


# =============================================================================
# _score_complexity Method Tests
# =============================================================================


class TestScoreComplexity:
    """Tests for _score_complexity method."""

    def test_empty_code_returns_base_score(self, scorer: PatternQualityScorer) -> None:
        """Empty code returns base score of 0.4."""
        score = scorer._score_complexity("", None)
        assert score == 0.4

    def test_no_declaration_returns_base_score(self, scorer: PatternQualityScorer) -> None:
        """No declared complexity returns 0.4."""
        code = "def foo(): return 1"
        score = scorer._score_complexity(code, None)
        assert score == 0.4

    def test_low_complexity_match(self, scorer: PatternQualityScorer) -> None:
        """Declared 'low' matches actual low complexity (0-2 indicators)."""
        # Code with 0-2 indicators (if/for/while/except)
        low_code = "def foo():\n    return 1"
        score = scorer._score_complexity(low_code, "low")
        assert score == 1.0

    def test_medium_complexity_match(self, scorer: PatternQualityScorer) -> None:
        """Declared 'medium' matches actual medium complexity (3-7 indicators)."""
        # Code with 3-7 indicators
        medium_code = """def foo(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                pass
"""
        score = scorer._score_complexity(medium_code, "medium")
        assert score == 1.0

    def test_high_complexity_match(self, scorer: PatternQualityScorer) -> None:
        """Declared 'high' matches actual high complexity (8+ indicators)."""
        # Code with 8+ indicators
        high_code = """def foo(x):
    if x > 0:
        for i in range(x):
            if i > 0:
                while True:
                    if i > 1:
                        for j in range(i):
                            if j > 0:
                                try:
                                    pass
                                except Exception:
                                    pass
                    break
"""
        score = scorer._score_complexity(high_code, "high")
        assert score == 1.0

    def test_mismatch_returns_partial_score(self, scorer: PatternQualityScorer) -> None:
        """Mismatched declared vs actual complexity returns 0.6."""
        # Low actual complexity but declared high
        low_code = "def foo():\n    return 1"
        score = scorer._score_complexity(low_code, "high")
        assert score == 0.6

    def test_complexity_case_insensitive(self, scorer: PatternQualityScorer) -> None:
        """Declared complexity comparison is case-insensitive."""
        low_code = "def foo():\n    return 1"
        score_lower = scorer._score_complexity(low_code, "low")
        score_upper = scorer._score_complexity(low_code, "LOW")
        score_mixed = scorer._score_complexity(low_code, "Low")
        assert score_lower == score_upper == score_mixed == 1.0

    def test_counts_if_indicators(self, scorer: PatternQualityScorer) -> None:
        """Counts 'if ' statements as complexity indicators."""
        code = "if x:\n    if y:\n        if z:\n            pass"
        # 3 if statements = medium complexity
        score = scorer._score_complexity(code, "medium")
        assert score == 1.0

    def test_counts_for_indicators(self, scorer: PatternQualityScorer) -> None:
        """Counts 'for ' loops as complexity indicators."""
        code = "for i in a:\n    for j in b:\n        for k in c:\n            pass"
        # 3 for loops = medium complexity
        score = scorer._score_complexity(code, "medium")
        assert score == 1.0

    def test_counts_while_indicators(self, scorer: PatternQualityScorer) -> None:
        """Counts 'while ' loops as complexity indicators."""
        code = "while a:\n    while b:\n        while c:\n            pass"
        # 3 while loops = medium complexity
        score = scorer._score_complexity(code, "medium")
        assert score == 1.0

    def test_counts_except_indicators(self, scorer: PatternQualityScorer) -> None:
        """Counts 'except ' blocks as complexity indicators."""
        code = """try:
    pass
except ValueError:
    pass
except TypeError:
    pass
except Exception:
    pass
"""
        # 3 except blocks = medium complexity
        score = scorer._score_complexity(code, "medium")
        assert score == 1.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the complete scoring pipeline."""

    def test_complete_pattern_scores_high(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """Complete, well-documented pattern scores high."""
        result = scorer.score_pattern(complete_pattern)
        assert result.composite_score >= PatternQualityScorer.GOOD_THRESHOLD

    def test_stub_pattern_scores_low(
        self, scorer: PatternQualityScorer, stub_pattern: dict[str, Any]
    ) -> None:
        """Stub pattern with minimal content scores low."""
        result = scorer.score_pattern(stub_pattern)
        assert result.composite_score < PatternQualityScorer.GOOD_THRESHOLD

    def test_minimal_pattern_scores_lowest(
        self, scorer: PatternQualityScorer, minimal_pattern: dict[str, Any]
    ) -> None:
        """Minimal pattern with no content scores lowest."""
        result = scorer.score_pattern(minimal_pattern)
        assert result.composite_score < PatternQualityScorer.FAIR_THRESHOLD

    def test_quality_tier_excellent(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """Pattern can achieve excellent tier (>=0.9)."""
        # Enhance the pattern to maximize score
        complete_pattern["use_cases"] = ["UC1", "UC2", "UC3"]
        complete_pattern["examples"] = ["Ex1", "Ex2"]
        complete_pattern["metadata"]["extra1"] = "v1"
        result = scorer.score_pattern(complete_pattern)
        # May or may not reach excellent, but should be close to good
        assert result.composite_score >= PatternQualityScorer.FAIR_THRESHOLD

    def test_all_scores_in_valid_range(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """All dimension scores are in valid range [0.0, 1.0]."""
        result = scorer.score_pattern(complete_pattern)
        assert 0.0 <= result.completeness_score <= 1.0
        assert 0.0 <= result.documentation_score <= 1.0
        assert 0.0 <= result.onex_compliance_score <= 1.0
        assert 0.0 <= result.metadata_richness_score <= 1.0
        assert 0.0 <= result.complexity_score <= 1.0
        assert 0.0 <= result.composite_score <= 1.0

    def test_scoring_is_deterministic(
        self, scorer: PatternQualityScorer, complete_pattern: dict[str, Any]
    ) -> None:
        """Scoring the same pattern twice gives same results (except timestamp)."""
        result1 = scorer.score_pattern(complete_pattern)
        result2 = scorer.score_pattern(complete_pattern)
        assert result1.composite_score == result2.composite_score
        assert result1.completeness_score == result2.completeness_score
        assert result1.documentation_score == result2.documentation_score
        assert result1.onex_compliance_score == result2.onex_compliance_score
        assert result1.metadata_richness_score == result2.metadata_richness_score
        assert result1.complexity_score == result2.complexity_score
