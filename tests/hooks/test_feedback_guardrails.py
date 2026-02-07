# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for feedback guardrails.

Tests verify:
- Gate 1: No injection skips reinforcement
- Gate 2: Unclear outcomes skip reinforcement
- Gate 3: Low utilization/accuracy skips reinforcement
- All gates passing allows reinforcement
- Gate evaluation order (short-circuit semantics)
- Result structure invariants

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

import pytest

from plugins.onex.hooks.lib.feedback_guardrails import (
    CLEAR_OUTCOMES,
    MIN_ACCURACY_THRESHOLD,
    MIN_UTILIZATION_THRESHOLD,
    SKIP_BELOW_SCORE_THRESHOLD,
    SKIP_NO_INJECTION,
    SKIP_UNCLEAR_OUTCOME,
    GuardrailResult,
    should_reinforce_routing,
)

pytestmark = pytest.mark.unit


class TestGate1NoInjection:
    """Gate 1: Context injection must have occurred."""

    def test_no_injection_returns_false(self) -> None:
        """No injection means no feedback signal regardless of other inputs."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.9,
            agent_match_score=0.9,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_NO_INJECTION

    def test_no_injection_with_perfect_scores(self) -> None:
        """Even perfect utilization and accuracy cannot override missing injection."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=1.0,
            agent_match_score=1.0,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_NO_INJECTION

    def test_no_injection_with_failed_outcome(self) -> None:
        """No injection skips regardless of outcome type."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="failed",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_NO_INJECTION


class TestGate2UnclearOutcome:
    """Gate 2: Session outcome must be clear (success or failed)."""

    def test_abandoned_outcome_returns_false(self) -> None:
        """Abandoned sessions provide no useful signal."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.8,
            agent_match_score=0.9,
            session_outcome="abandoned",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME

    def test_unknown_outcome_returns_false(self) -> None:
        """Unknown outcomes provide no useful signal."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.8,
            agent_match_score=0.9,
            session_outcome="unknown",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME

    def test_success_passes_gate_2(self) -> None:
        """Success outcome passes gate 2 (may still fail gate 3)."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        # Should not fail on gate 2
        assert result.skip_reason != SKIP_UNCLEAR_OUTCOME

    def test_failed_passes_gate_2(self) -> None:
        """Failed outcome passes gate 2 (may still fail gate 3)."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="failed",
        )
        # Should not fail on gate 2
        assert result.skip_reason != SKIP_UNCLEAR_OUTCOME

    def test_empty_string_outcome_returns_false(self) -> None:
        """Empty string is not a clear outcome."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.8,
            agent_match_score=0.9,
            session_outcome="",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME

    def test_arbitrary_string_outcome_returns_false(self) -> None:
        """Arbitrary strings that are not 'success' or 'failed' are unclear."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.8,
            agent_match_score=0.9,
            session_outcome="partial",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME


class TestGate3LowUtilizationAndAccuracy:
    """Gate 3: Utilization and accuracy must meet minimum thresholds."""

    def test_low_utilization_returns_false(self) -> None:
        """Utilization below threshold skips reinforcement."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.1,
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_low_accuracy_returns_false(self) -> None:
        """Accuracy below threshold skips reinforcement."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.3,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_both_below_thresholds_returns_false(self) -> None:
        """Both scores below thresholds skips reinforcement."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.05,
            agent_match_score=0.1,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_zero_utilization_returns_false(self) -> None:
        """Zero utilization score skips reinforcement."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.0,
            agent_match_score=0.9,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_zero_accuracy_returns_false(self) -> None:
        """Zero accuracy score skips reinforcement."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.0,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_utilization_just_below_threshold_returns_false(self) -> None:
        """Utilization just below the threshold (0.2) fails gate 3."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=MIN_UTILIZATION_THRESHOLD - 0.001,
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD

    def test_accuracy_just_below_threshold_returns_false(self) -> None:
        """Accuracy just below the threshold (0.5) fails gate 3."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=MIN_ACCURACY_THRESHOLD - 0.001,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD


class TestBoundaryValues:
    """Test exact threshold boundary behavior."""

    def test_utilization_exactly_at_threshold_passes(self) -> None:
        """Utilization exactly at 0.2 passes gate 3 (>= semantics)."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=MIN_UTILIZATION_THRESHOLD,
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_accuracy_exactly_at_threshold_passes(self) -> None:
        """Accuracy exactly at 0.5 passes gate 3 (>= semantics)."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=MIN_ACCURACY_THRESHOLD,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_both_exactly_at_thresholds_passes(self) -> None:
        """Both scores exactly at their thresholds passes all gates."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=MIN_UTILIZATION_THRESHOLD,
            agent_match_score=MIN_ACCURACY_THRESHOLD,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None


class TestAllGatesPass:
    """Test scenarios where all gates pass and reinforcement occurs."""

    def test_success_with_good_scores_reinforces(self) -> None:
        """Successful session with good utilization and accuracy reinforces."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_failed_with_good_scores_reinforces(self) -> None:
        """Failed session with good utilization and accuracy reinforces.

        Failures are valid feedback signals: they teach the router what
        not to do.
        """
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.3,
            agent_match_score=0.6,
            session_outcome="failed",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_perfect_scores_reinforces(self) -> None:
        """Perfect scores across the board reinforce."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=1.0,
            agent_match_score=1.0,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_scores_just_above_thresholds_reinforce(self) -> None:
        """Scores just above thresholds still reinforce."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=MIN_UTILIZATION_THRESHOLD + 0.001,
            agent_match_score=MIN_ACCURACY_THRESHOLD + 0.001,
            session_outcome="failed",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None


class TestGatePriority:
    """Test that gates short-circuit in order: gate 1 -> gate 2 -> gate 3."""

    def test_gate_1_fails_before_gate_2(self) -> None:
        """When both gate 1 and gate 2 would fail, gate 1 reason wins.

        injection_occurred=False (gate 1 fail) + unclear outcome (gate 2 fail)
        should report NO_INJECTION, not UNCLEAR_OUTCOME.
        """
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.0,
            agent_match_score=0.0,
            session_outcome="abandoned",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_NO_INJECTION

    def test_gate_2_fails_before_gate_3(self) -> None:
        """When both gate 2 and gate 3 would fail, gate 2 reason wins.

        unclear outcome (gate 2 fail) + low scores (gate 3 fail)
        should report UNCLEAR_OUTCOME, not BELOW_SCORE_THRESHOLD.
        """
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.0,
            agent_match_score=0.0,
            session_outcome="unknown",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME

    def test_all_three_gates_would_fail_reports_gate_1(self) -> None:
        """When all three gates would fail, gate 1 reason wins."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.0,
            agent_match_score=0.0,
            session_outcome="unknown",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_NO_INJECTION

    def test_gate_1_passes_gate_2_fails(self) -> None:
        """Gate 1 passes but gate 2 fails, so gate 2 reason is reported."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.0,
            agent_match_score=0.0,
            session_outcome="abandoned",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_UNCLEAR_OUTCOME

    def test_gates_1_2_pass_gate_3_fails(self) -> None:
        """Gates 1 and 2 pass but gate 3 fails, so gate 3 reason is reported."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.0,
            agent_match_score=0.0,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD


class TestResultStructure:
    """Test GuardrailResult structure and invariants."""

    def test_result_is_namedtuple(self) -> None:
        """GuardrailResult is a NamedTuple with expected fields."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert isinstance(result, GuardrailResult)
        assert isinstance(result, tuple)
        assert hasattr(result, "should_reinforce")
        assert hasattr(result, "skip_reason")
        assert hasattr(result, "details")

    def test_should_reinforce_is_bool(self) -> None:
        """should_reinforce is always a bool."""
        result_pass = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        result_fail = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert isinstance(result_pass.should_reinforce, bool)
        assert isinstance(result_fail.should_reinforce, bool)

    def test_skip_reason_is_str_when_skipped(self) -> None:
        """skip_reason is a non-empty string when should_reinforce is False."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert isinstance(result.skip_reason, str)
        assert len(result.skip_reason) > 0

    def test_skip_reason_is_none_when_reinforcing(self) -> None:
        """skip_reason is None when should_reinforce is True."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.skip_reason is None

    def test_details_contains_all_input_parameters(self) -> None:
        """details dict contains all input parameters (raw and clamped)."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.42,
            agent_match_score=0.73,
            session_outcome="failed",
        )
        assert isinstance(result.details, dict)
        assert result.details["injection_occurred"] is True
        assert result.details["utilization_score_raw"] == 0.42
        assert result.details["agent_match_score_raw"] == 0.73
        assert result.details["utilization_score"] == 0.42
        assert result.details["agent_match_score"] == 0.73
        assert result.details["session_outcome"] == "failed"

    def test_details_present_on_skip(self) -> None:
        """details dict is populated even when reinforcement is skipped."""
        result = should_reinforce_routing(
            injection_occurred=False,
            utilization_score=0.1,
            agent_match_score=0.2,
            session_outcome="abandoned",
        )
        assert result.should_reinforce is False
        assert isinstance(result.details, dict)
        assert result.details["injection_occurred"] is False
        assert result.details["utilization_score_raw"] == 0.1
        assert result.details["agent_match_score_raw"] == 0.2
        assert result.details["utilization_score"] == 0.1
        assert result.details["agent_match_score"] == 0.2
        assert result.details["session_outcome"] == "abandoned"

    def test_result_unpacks_as_tuple(self) -> None:
        """GuardrailResult can be unpacked like a tuple."""
        should_reinforce, skip_reason, details = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        assert should_reinforce is True
        assert skip_reason is None
        assert isinstance(details, dict)


class TestConstants:
    """Test module-level constants."""

    def test_min_utilization_threshold_value(self) -> None:
        """MIN_UTILIZATION_THRESHOLD is 0.2."""
        assert MIN_UTILIZATION_THRESHOLD == 0.2

    def test_min_accuracy_threshold_value(self) -> None:
        """MIN_ACCURACY_THRESHOLD is 0.5."""
        assert MIN_ACCURACY_THRESHOLD == 0.5

    def test_skip_reason_constants_are_strings(self) -> None:
        """Skip reason constants are non-empty strings."""
        for constant in [
            SKIP_NO_INJECTION,
            SKIP_UNCLEAR_OUTCOME,
            SKIP_BELOW_SCORE_THRESHOLD,
        ]:
            assert isinstance(constant, str)
            assert len(constant) > 0

    def test_clear_outcomes_is_frozenset(self) -> None:
        """CLEAR_OUTCOMES is a frozenset containing success and failed."""
        assert isinstance(CLEAR_OUTCOMES, frozenset)
        assert "success" in CLEAR_OUTCOMES
        assert "failed" in CLEAR_OUTCOMES
        assert len(CLEAR_OUTCOMES) == 2

    def test_unclear_outcomes_not_in_clear_outcomes(self) -> None:
        """Unclear outcomes are not in the CLEAR_OUTCOMES set."""
        assert "abandoned" not in CLEAR_OUTCOMES
        assert "unknown" not in CLEAR_OUTCOMES
        assert "" not in CLEAR_OUTCOMES


class TestInputValidation:
    """Test input clamping and NaN/inf handling."""

    def test_nan_utilization_score_treated_as_zero(self) -> None:
        """NaN utilization_score is treated as 0.0, should fail Gate 3."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=float("nan"),
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["utilization_score"] == 0.0

    def test_nan_agent_match_score_treated_as_zero(self) -> None:
        """NaN agent_match_score is treated as 0.0, should fail Gate 3."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=float("nan"),
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["agent_match_score"] == 0.0

    def test_negative_utilization_score_clamped_to_zero(self) -> None:
        """Negative utilization_score is clamped to 0.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=-0.5,
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["utilization_score"] == 0.0

    def test_negative_agent_match_score_clamped_to_zero(self) -> None:
        """Negative agent_match_score is clamped to 0.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=-1.0,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["agent_match_score"] == 0.0

    def test_utilization_score_above_one_clamped(self) -> None:
        """Utilization score > 1.0 is clamped to 1.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=5.0,
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.details["utilization_score"] == 1.0

    def test_agent_match_score_above_one_clamped(self) -> None:
        """Agent match score > 1.0 is clamped to 1.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=99.0,
            session_outcome="success",
        )
        assert result.should_reinforce is True
        assert result.details["agent_match_score"] == 1.0

    def test_positive_inf_utilization_treated_as_zero(self) -> None:
        """Positive inf utilization_score is treated as 0.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=float("inf"),
            agent_match_score=0.8,
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["utilization_score"] == 0.0

    def test_negative_inf_agent_match_treated_as_zero(self) -> None:
        """Negative inf agent_match_score is treated as 0.0."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=float("-inf"),
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["agent_match_score"] == 0.0

    def test_both_nan_scores_treated_as_zero(self) -> None:
        """Both scores as NaN are treated as 0.0, fails Gate 3."""
        result = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=float("nan"),
            agent_match_score=float("nan"),
            session_outcome="success",
        )
        assert result.should_reinforce is False
        assert result.skip_reason == SKIP_BELOW_SCORE_THRESHOLD
        assert result.details["utilization_score"] == 0.0
        assert result.details["agent_match_score"] == 0.0


class TestPureFunctionProperties:
    """Test that should_reinforce_routing is a pure function."""

    def test_deterministic_output(self) -> None:
        """Same inputs always produce same outputs."""
        kwargs = {
            "injection_occurred": True,
            "utilization_score": 0.5,
            "agent_match_score": 0.7,
            "session_outcome": "success",
        }
        results = [should_reinforce_routing(**kwargs) for _ in range(10)]
        for result in results:
            assert result.should_reinforce == results[0].should_reinforce
            assert result.skip_reason == results[0].skip_reason
            assert result.details == results[0].details

    def test_no_shared_mutable_state(self) -> None:
        """Mutating the details dict of one result does not affect others."""
        result_a = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        result_b = should_reinforce_routing(
            injection_occurred=True,
            utilization_score=0.5,
            agent_match_score=0.7,
            session_outcome="success",
        )
        # Mutate result_a's details
        result_a.details["extra_key"] = "mutation"
        # result_b should be unaffected
        assert "extra_key" not in result_b.details
