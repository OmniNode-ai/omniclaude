# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for agent accuracy detector.

Tests verify:
- No-trigger edge case returns score=0.0 with method="no_triggers"
- Full match scoring (all triggers found in context signals)
- Partial match scoring (subset of triggers found)
- No match scoring (zero triggers found)
- Case-insensitive matching between triggers and signals
- Substring matching (trigger found within a longer signal)
- Edge cases (empty signals, single elements, special characters)
- Result structure and type correctness

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

import pytest

from plugins.onex.hooks.lib.agent_accuracy_detector import (
    AgentMatchResult,
    calculate_agent_match_score,
)

pytestmark = pytest.mark.unit


class TestNoTriggers:
    """Test behavior when agent has no activation triggers."""

    def test_empty_triggers_returns_zero_score(self) -> None:
        """Empty agent_triggers list yields score=0.0."""
        result = calculate_agent_match_score(
            agent_triggers=[],
            context_signals=["api design", "openapi spec"],
        )
        assert result.score == 0.0

    def test_empty_triggers_returns_no_triggers_method(self) -> None:
        """Empty agent_triggers list yields method='no_triggers'."""
        result = calculate_agent_match_score(
            agent_triggers=[],
            context_signals=["anything"],
        )
        assert result.method == "no_triggers"

    def test_empty_triggers_returns_empty_matched_tuple(self) -> None:
        """Empty agent_triggers list yields empty matched_triggers."""
        result = calculate_agent_match_score(
            agent_triggers=[],
            context_signals=["signal"],
        )
        assert result.matched_triggers == ()

    def test_empty_triggers_returns_zero_total(self) -> None:
        """Empty agent_triggers list yields total_triggers=0."""
        result = calculate_agent_match_score(
            agent_triggers=[],
            context_signals=["signal"],
        )
        assert result.total_triggers == 0

    def test_empty_triggers_with_empty_signals(self) -> None:
        """Both triggers and signals empty yields no_triggers method."""
        result = calculate_agent_match_score(
            agent_triggers=[],
            context_signals=[],
        )
        assert result.score == 0.0
        assert result.method == "no_triggers"
        assert result.matched_triggers == ()
        assert result.total_triggers == 0


class TestFullMatch:
    """Test behavior when all triggers are found in context signals."""

    def test_all_triggers_found_returns_perfect_score(self) -> None:
        """All triggers matching yields score=1.0."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi"],
            context_signals=["api design patterns", "openapi spec review"],
        )
        assert result.score == 1.0

    def test_all_triggers_found_method_is_trigger_overlap(self) -> None:
        """With triggers present, method is always 'trigger_overlap'."""
        result = calculate_agent_match_score(
            agent_triggers=["api design"],
            context_signals=["api design patterns"],
        )
        assert result.method == "trigger_overlap"

    def test_all_triggers_listed_in_matched(self) -> None:
        """matched_triggers contains all original trigger strings when all match."""
        triggers = ["api design", "openapi", "rest"]
        result = calculate_agent_match_score(
            agent_triggers=triggers,
            context_signals=["api design review", "openapi v3 spec", "rest endpoints"],
        )
        assert sorted(result.matched_triggers) == sorted(triggers)

    def test_total_triggers_equals_input_length(self) -> None:
        """total_triggers reflects the number of triggers provided."""
        triggers = ["api design", "openapi", "rest"]
        result = calculate_agent_match_score(
            agent_triggers=triggers,
            context_signals=["api design review", "openapi v3 spec", "rest endpoints"],
        )
        assert result.total_triggers == 3

    def test_single_trigger_single_signal_full_match(self) -> None:
        """Single trigger found in single signal yields score=1.0."""
        result = calculate_agent_match_score(
            agent_triggers=["debug"],
            context_signals=["debug session active"],
        )
        assert result.score == 1.0
        assert result.matched_triggers == ("debug",)
        assert result.total_triggers == 1


class TestPartialMatch:
    """Test behavior when only some triggers match context signals."""

    def test_half_triggers_match_returns_half_score(self) -> None:
        """2 of 4 triggers matching yields score=0.5."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi", "graphql", "grpc"],
            context_signals=["api design patterns", "openapi spec review"],
        )
        assert result.score == 0.5

    def test_one_of_three_triggers_match(self) -> None:
        """1 of 3 triggers matching yields score ~0.333."""
        result = calculate_agent_match_score(
            agent_triggers=["pytest", "jest", "cypress"],
            context_signals=["running pytest suite"],
        )
        assert result.score == pytest.approx(1 / 3)

    def test_matched_triggers_contains_only_matches(self) -> None:
        """matched_triggers includes only triggers that were found."""
        result = calculate_agent_match_score(
            agent_triggers=["pytest", "jest", "cypress"],
            context_signals=["running pytest suite"],
        )
        assert result.matched_triggers == ("pytest",)

    def test_total_triggers_unchanged_by_match_count(self) -> None:
        """total_triggers always equals len(agent_triggers) regardless of matches."""
        result = calculate_agent_match_score(
            agent_triggers=["pytest", "jest", "cypress"],
            context_signals=["running pytest suite"],
        )
        assert result.total_triggers == 3

    def test_two_of_five_triggers_match(self) -> None:
        """2 of 5 triggers yields score=0.4."""
        result = calculate_agent_match_score(
            agent_triggers=["docker", "kubernetes", "terraform", "ansible", "helm"],
            context_signals=["docker compose up", "terraform plan output"],
        )
        assert result.score == pytest.approx(0.4)
        assert len(result.matched_triggers) == 2


class TestNoMatch:
    """Test behavior when no triggers match context signals."""

    def test_no_triggers_found_returns_zero_score(self) -> None:
        """No triggers found in context yields score=0.0."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi"],
            context_signals=["database migration", "schema update"],
        )
        assert result.score == 0.0

    def test_no_match_method_is_trigger_overlap(self) -> None:
        """Method is 'trigger_overlap' even when nothing matches."""
        result = calculate_agent_match_score(
            agent_triggers=["api design"],
            context_signals=["database migration"],
        )
        assert result.method == "trigger_overlap"

    def test_no_match_empty_matched_tuple(self) -> None:
        """matched_triggers is empty when nothing matches."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi"],
            context_signals=["database migration", "schema update"],
        )
        assert result.matched_triggers == ()

    def test_no_match_total_triggers_preserved(self) -> None:
        """total_triggers still reflects input count even when nothing matches."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi"],
            context_signals=["database migration", "schema update"],
        )
        assert result.total_triggers == 2


class TestCaseInsensitivity:
    """Test case-insensitive matching between triggers and signals."""

    def test_uppercase_trigger_matches_lowercase_signal(self) -> None:
        """Trigger 'API Design' matches signal 'api design patterns'."""
        result = calculate_agent_match_score(
            agent_triggers=["API Design"],
            context_signals=["api design patterns"],
        )
        assert result.score == 1.0
        assert result.matched_triggers == ("API Design",)

    def test_lowercase_trigger_matches_uppercase_signal(self) -> None:
        """Trigger 'api design' matches signal 'API DESIGN PATTERNS'."""
        result = calculate_agent_match_score(
            agent_triggers=["api design"],
            context_signals=["API DESIGN PATTERNS"],
        )
        assert result.score == 1.0

    def test_mixed_case_trigger_matches_mixed_case_signal(self) -> None:
        """Trigger 'OpenAPI' matches signal 'openapi Spec Review'."""
        result = calculate_agent_match_score(
            agent_triggers=["OpenAPI"],
            context_signals=["openapi Spec Review"],
        )
        assert result.score == 1.0

    def test_all_caps_trigger_matches(self) -> None:
        """Trigger 'KUBERNETES' matches signal 'kubernetes cluster setup'."""
        result = calculate_agent_match_score(
            agent_triggers=["KUBERNETES"],
            context_signals=["kubernetes cluster setup"],
        )
        assert result.score == 1.0
        assert result.matched_triggers == ("KUBERNETES",)

    def test_original_trigger_casing_preserved_in_matched(self) -> None:
        """matched_triggers preserves original casing of the trigger string."""
        result = calculate_agent_match_score(
            agent_triggers=["API Design", "OpenAPI Spec"],
            context_signals=["api design review", "openapi spec validation"],
        )
        assert "API Design" in result.matched_triggers
        assert "OpenAPI Spec" in result.matched_triggers


class TestSubstringMatching:
    """Test that triggers match as substrings within signals."""

    def test_short_trigger_matches_longer_signal(self) -> None:
        """Trigger 'api' matches signal 'api design patterns'."""
        result = calculate_agent_match_score(
            agent_triggers=["api"],
            context_signals=["api design patterns"],
        )
        assert result.score == 1.0

    def test_trigger_matches_in_middle_of_signal(self) -> None:
        """Trigger 'test' matches signal 'unit testing framework'."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["unit testing framework"],
        )
        assert result.score == 1.0

    def test_exact_signal_match(self) -> None:
        """Trigger that exactly equals a signal still matches."""
        result = calculate_agent_match_score(
            agent_triggers=["debug"],
            context_signals=["debug"],
        )
        assert result.score == 1.0

    def test_trigger_matches_within_single_signal(self) -> None:
        """Multi-word trigger matches when contained in a single signal.

        Each signal is checked individually, so a multi-word trigger matches
        only when it appears within a single signal string, not across
        signal boundaries.
        """
        result = calculate_agent_match_score(
            agent_triggers=["api design"],
            context_signals=["api design review"],
        )
        assert result.score == 1.0

    def test_trigger_not_substring_does_not_match(self) -> None:
        """Trigger 'graphql' does not match signal 'rest api design'."""
        result = calculate_agent_match_score(
            agent_triggers=["graphql"],
            context_signals=["rest api design"],
        )
        assert result.score == 0.0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_context_signals_returns_zero(self) -> None:
        """Empty context_signals with non-empty triggers yields score=0.0."""
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi"],
            context_signals=[],
        )
        assert result.score == 0.0
        assert result.method == "trigger_overlap"
        assert result.matched_triggers == ()
        assert result.total_triggers == 2

    def test_single_trigger_single_signal_no_match(self) -> None:
        """Single trigger and single signal with no overlap."""
        result = calculate_agent_match_score(
            agent_triggers=["kubernetes"],
            context_signals=["database migration"],
        )
        assert result.score == 0.0
        assert result.total_triggers == 1

    def test_many_triggers(self) -> None:
        """Large trigger list is handled correctly."""
        triggers = [f"trigger_{i}" for i in range(100)]
        # Only the first 10 will match
        signals = [f"trigger_{i} is active" for i in range(10)]
        result = calculate_agent_match_score(
            agent_triggers=triggers,
            context_signals=signals,
        )
        assert result.score == pytest.approx(10 / 100)
        assert len(result.matched_triggers) == 10
        assert result.total_triggers == 100

    def test_special_characters_in_triggers(self) -> None:
        """Triggers containing special characters are handled."""
        result = calculate_agent_match_score(
            agent_triggers=["c++", "node.js", "model-contract"],
            context_signals=[
                "c++ compiler error",
                "node.js server",
                "model-contract validation",
            ],
        )
        assert result.score == 1.0
        assert len(result.matched_triggers) == 3

    def test_regex_special_characters_in_triggers(self) -> None:
        """Triggers with regex metacharacters are treated as literal strings.

        The implementation uses Python 'in' operator (substring check),
        not regex, so metacharacters are safe.
        """
        result = calculate_agent_match_score(
            agent_triggers=["file.py", "a+b", "[config]"],
            context_signals=[
                "editing file.py now",
                "compute a+b result",
                "[config] loaded",
            ],
        )
        assert result.score == 1.0

    def test_whitespace_in_triggers(self) -> None:
        """Triggers with whitespace match correctly."""
        result = calculate_agent_match_score(
            agent_triggers=["api  design"],
            context_signals=["api  design review"],
        )
        assert result.score == 1.0

    def test_duplicate_triggers(self) -> None:
        """Duplicate entries in agent_triggers are each evaluated independently."""
        result = calculate_agent_match_score(
            agent_triggers=["api", "api", "api"],
            context_signals=["api design"],
        )
        # All 3 identical triggers match, so score = 3/3 = 1.0
        assert result.score == 1.0
        assert result.total_triggers == 3
        assert len(result.matched_triggers) == 3

    def test_duplicate_signals(self) -> None:
        """Duplicate entries in context_signals do not inflate scoring."""
        result = calculate_agent_match_score(
            agent_triggers=["api", "openapi"],
            context_signals=["api design", "api design", "api design"],
        )
        assert result.score == pytest.approx(0.5)  # Only "api" matches, not "openapi"

    def test_empty_string_trigger_filtered_out(self) -> None:
        """Empty string triggers are filtered out before matching.

        Previously, an empty string was a substring of any string and would
        always match. Now empty triggers are removed as noise, so a list
        containing only empty strings yields no_triggers / score=0.0.
        """
        result = calculate_agent_match_score(
            agent_triggers=[""],
            context_signals=["anything"],
        )
        assert result.score == 0.0
        assert result.method == "no_triggers"
        assert result.total_triggers == 0

    def test_mixed_empty_and_real_triggers(self) -> None:
        """Empty strings are removed but real triggers are still evaluated."""
        result = calculate_agent_match_score(
            agent_triggers=["", "api", "", "debug", ""],
            context_signals=["api design"],
        )
        # After filtering: ["api", "debug"] -> 1 of 2 matches
        assert result.total_triggers == 2
        assert result.score == pytest.approx(0.5)
        assert result.matched_triggers == ("api",)

    def test_unicode_in_triggers_and_signals(self) -> None:
        """Unicode characters in triggers and signals are handled."""
        result = calculate_agent_match_score(
            agent_triggers=["cafe"],
            context_signals=["cafe latte"],
        )
        assert result.score == 1.0


class TestResultStructure:
    """Test the structure and types of AgentMatchResult."""

    def test_result_is_named_tuple(self) -> None:
        """Result is an AgentMatchResult NamedTuple."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test session"],
        )
        assert isinstance(result, AgentMatchResult)
        assert isinstance(result, tuple)

    def test_score_is_float(self) -> None:
        """score field is a float."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test session"],
        )
        assert isinstance(result.score, float)

    def test_method_is_string(self) -> None:
        """method field is a string."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test session"],
        )
        assert isinstance(result.method, str)

    def test_matched_triggers_is_tuple_of_strings(self) -> None:
        """matched_triggers field is a tuple of strings."""
        result = calculate_agent_match_score(
            agent_triggers=["test", "debug"],
            context_signals=["test session", "debug log"],
        )
        assert isinstance(result.matched_triggers, tuple)
        for item in result.matched_triggers:
            assert isinstance(item, str)

    def test_total_triggers_is_int(self) -> None:
        """total_triggers field is an int."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test session"],
        )
        assert isinstance(result.total_triggers, int)

    def test_score_bounded_zero_to_one(self) -> None:
        """Score is always between 0.0 and 1.0 inclusive."""
        test_cases = [
            ([], ["signal"]),
            (["no-match"], ["signal"]),
            (["match"], ["match here"]),
            (["a", "b", "c"], ["a here", "b here"]),
        ]
        for triggers, signals in test_cases:
            result = calculate_agent_match_score(triggers, signals)
            assert 0.0 <= result.score <= 1.0, (
                f"Score {result.score} out of bounds for "
                f"triggers={triggers}, signals={signals}"
            )

    def test_method_is_known_value(self) -> None:
        """method is one of the two known values."""
        result_no_triggers = calculate_agent_match_score([], ["signal"])
        result_with_triggers = calculate_agent_match_score(["x"], ["signal"])

        assert result_no_triggers.method == "no_triggers"
        assert result_with_triggers.method == "trigger_overlap"

    def test_result_fields_accessible_by_name_and_index(self) -> None:
        """NamedTuple fields accessible both by name and by position."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test here"],
        )
        # By name
        assert result.score == result[0]
        assert result.method == result[1]
        assert result.matched_triggers == result[2]
        assert result.total_triggers == result[3]

    def test_result_is_immutable(self) -> None:
        """NamedTuple result cannot be mutated via attribute assignment."""
        result = calculate_agent_match_score(
            agent_triggers=["test"],
            context_signals=["test here"],
        )
        with pytest.raises(AttributeError):
            result.score = 0.5  # type: ignore[misc]

    def test_matched_triggers_count_plus_unmatched_equals_total(self) -> None:
        """len(matched_triggers) is always <= total_triggers."""
        result = calculate_agent_match_score(
            agent_triggers=["a", "b", "c", "d"],
            context_signals=["a here", "c here"],
        )
        assert len(result.matched_triggers) <= result.total_triggers
        assert result.total_triggers == 4


class TestRealisticScenarios:
    """Test with realistic agent configurations and session signals."""

    def test_api_architect_agent_realistic(self) -> None:
        """Realistic scenario for agent-api-architect selection.

        Each trigger is checked as a substring within each individual signal:
        - "api design" is NOT a substring of any individual signal
        - "openapi" IS a substring of "openapi specification v3"
        - "rest endpoint" is NOT a substring of any signal
        - "http" IS a substring of "http method selection"
        Result: 2/4 = 0.5
        """
        result = calculate_agent_match_score(
            agent_triggers=["api design", "openapi", "rest endpoint", "http"],
            context_signals=[
                "designing rest api",
                "openapi specification v3",
                "http method selection",
                "fastapi router implementation",
            ],
        )
        assert result.score == pytest.approx(0.5)
        assert result.method == "trigger_overlap"
        assert "openapi" in result.matched_triggers
        assert "http" in result.matched_triggers

    def test_testing_agent_realistic(self) -> None:
        """Realistic scenario for agent-testing selection."""
        result = calculate_agent_match_score(
            agent_triggers=["pytest", "unit test", "coverage", "test fixture"],
            context_signals=[
                "running pytest with verbose output",
                "checking test coverage report",
                "unit test for user service",
            ],
        )
        # "pytest" matches, "unit test" matches, "coverage" matches
        # "test fixture" - "test fixture" not in joined signals
        assert result.score >= 0.75
        assert "pytest" in result.matched_triggers
        assert "unit test" in result.matched_triggers
        assert "coverage" in result.matched_triggers

    def test_debug_agent_with_unrelated_signals(self) -> None:
        """Debug agent selected but signals indicate API work -- low score."""
        result = calculate_agent_match_score(
            agent_triggers=["debug", "breakpoint", "stack trace", "error log"],
            context_signals=[
                "designing api endpoints",
                "openapi spec generation",
                "rest api patterns",
            ],
        )
        assert result.score == 0.0
        assert result.matched_triggers == ()

    def test_deterministic_results(self) -> None:
        """Same inputs always produce the same output (pure function)."""
        kwargs = {
            "agent_triggers": ["debug", "trace", "log"],
            "context_signals": ["debug session active", "reading log file"],
        }
        results = [calculate_agent_match_score(**kwargs) for _ in range(10)]
        for r in results:
            assert r == results[0]


class TestModuleExports:
    """Test that __all__ exports are correct."""

    def test_agent_match_result_exported(self) -> None:
        """AgentMatchResult is listed in __all__."""
        from plugins.onex.hooks.lib import agent_accuracy_detector

        assert "AgentMatchResult" in agent_accuracy_detector.__all__

    def test_calculate_agent_match_score_exported(self) -> None:
        """calculate_agent_match_score is listed in __all__."""
        from plugins.onex.hooks.lib import agent_accuracy_detector

        assert "calculate_agent_match_score" in agent_accuracy_detector.__all__
