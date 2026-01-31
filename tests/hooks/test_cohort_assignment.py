# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for cohort assignment.

Tests verify:
- Deterministic assignment (same session → same cohort)
- Approximate 20/80 distribution
- Assignment seed in valid range
- Enum values match database constraints

Part of OMN-1673: INJECT-004 injection tracking.
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.cohort_assignment import (
    COHORT_CONTROL_PERCENTAGE,
    COHORT_TREATMENT_PERCENTAGE,
    CohortAssignment,
    EnumCohort,
    assign_cohort,
)

pytestmark = pytest.mark.unit


class TestCohortAssignment:
    """Test cohort assignment function."""

    def test_returns_cohort_assignment(self) -> None:
        """Test returns CohortAssignment namedtuple."""
        result = assign_cohort("test-session-123")
        assert isinstance(result, CohortAssignment)
        assert isinstance(result.cohort, EnumCohort)
        assert isinstance(result.assignment_seed, int)

    def test_deterministic_assignment(self) -> None:
        """Test same session always gets same cohort."""
        session_id = "abc-123-def-456"

        result1 = assign_cohort(session_id)
        result2 = assign_cohort(session_id)
        result3 = assign_cohort(session_id)

        assert result1 == result2 == result3

    def test_different_sessions_can_differ(self) -> None:
        """Test different sessions can get different cohorts."""
        # Generate many sessions to statistically ensure both cohorts are hit
        cohorts_seen = set()
        for i in range(100):
            result = assign_cohort(f"session-{i}")
            cohorts_seen.add(result.cohort)

        # With 100 samples and 20/80 split, extremely likely to see both
        assert EnumCohort.CONTROL in cohorts_seen
        assert EnumCohort.TREATMENT in cohorts_seen

    def test_assignment_seed_in_valid_range(self) -> None:
        """Test assignment_seed is in 0-99 range."""
        for i in range(50):
            result = assign_cohort(f"session-{i}")
            assert 0 <= result.assignment_seed < 100

    def test_control_cohort_threshold(self) -> None:
        """Test control cohort assigned when seed < COHORT_CONTROL_PERCENTAGE."""
        # Find a session that lands in control
        for i in range(1000):
            result = assign_cohort(f"test-{i}")
            if result.assignment_seed < COHORT_CONTROL_PERCENTAGE:
                assert result.cohort == EnumCohort.CONTROL
                return  # Found one, test passes

        pytest.fail("Could not find a session in control cohort in 1000 attempts")

    def test_treatment_cohort_threshold(self) -> None:
        """Test treatment cohort assigned when seed >= COHORT_CONTROL_PERCENTAGE."""
        for i in range(1000):
            result = assign_cohort(f"test-{i}")
            if result.assignment_seed >= COHORT_CONTROL_PERCENTAGE:
                assert result.cohort == EnumCohort.TREATMENT
                return  # Found one, test passes

        pytest.fail("Could not find a session in treatment cohort in 1000 attempts")

    def test_approximate_distribution(self) -> None:
        """Test distribution approximately matches 20/80 split."""
        n_samples = 1000
        control_count = 0

        for i in range(n_samples):
            result = assign_cohort(f"distribution-test-{i}")
            if result.cohort == EnumCohort.CONTROL:
                control_count += 1

        control_rate = control_count / n_samples
        expected_rate = COHORT_CONTROL_PERCENTAGE / 100

        # Allow 5% tolerance (15% to 25% control)
        assert abs(control_rate - expected_rate) < 0.05, (
            f"Control rate {control_rate:.2%} not within 5% of expected {expected_rate:.2%}"
        )


class TestCohortEnums:
    """Test cohort enum values match database constraints."""

    def test_control_value(self) -> None:
        """Test control enum value matches database CHECK constraint."""
        assert EnumCohort.CONTROL.value == "control"

    def test_treatment_value(self) -> None:
        """Test treatment enum value matches database CHECK constraint."""
        assert EnumCohort.TREATMENT.value == "treatment"


class TestCohortConstants:
    """Test cohort constants."""

    def test_percentages_sum_to_100(self) -> None:
        """Test control + treatment = 100%."""
        assert COHORT_CONTROL_PERCENTAGE + COHORT_TREATMENT_PERCENTAGE == 100

    def test_control_percentage(self) -> None:
        """Test control percentage matches spec (20%)."""
        assert COHORT_CONTROL_PERCENTAGE == 20

    def test_treatment_percentage(self) -> None:
        """Test treatment percentage matches spec (80%)."""
        assert COHORT_TREATMENT_PERCENTAGE == 80
