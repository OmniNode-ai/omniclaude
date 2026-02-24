# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for cohort assignment.

Tests verify:
- Deterministic assignment (same session → same cohort)
- Approximate 20/80 distribution (default)
- Assignment seed in valid range
- Enum values match database constraints
- Configuration defaults and environment variable loading
- Validation of configuration values (0-100 range, non-empty salt)
- Custom percentage and salt configurations
- Distribution accuracy with custom percentages

Part of OMN-1673: INJECT-004 injection tracking.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from omniclaude.hooks.cohort_assignment import (
    COHORT_CONTROL_PERCENTAGE,
    COHORT_TREATMENT_PERCENTAGE,
    CohortAssignment,
    CohortAssignmentConfig,
    EnumCohort,
    IdentityType,
    assign_cohort,
)
from omniclaude.hooks.contracts.contract_experiment_cohort import (
    ExperimentCohortContract,
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

    def test_control_percentage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test control percentage matches spec (20%).

        Note: COHORT_CONTROL_PERCENTAGE is loaded at module import time from
        the contract YAML. Clearing env vars here ensures the test documents
        the expected default value, though the constant is already set.
        """
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)
        assert COHORT_CONTROL_PERCENTAGE == 20

    def test_treatment_percentage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test treatment percentage matches spec (80%).

        Note: COHORT_TREATMENT_PERCENTAGE is loaded at module import time from
        the contract YAML. Clearing env vars here ensures the test documents
        the expected default value, though the constant is already set.
        """
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)
        assert COHORT_TREATMENT_PERCENTAGE == 80


class TestCohortAssignmentConfig:
    """Test CohortAssignmentConfig configuration class."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config loads defaults correctly."""
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)
        config = CohortAssignmentConfig()
        assert config.control_percentage == 20
        assert config.salt == "omniclaude-injection-v1"
        assert config.treatment_percentage == 80

    def test_custom_control_percentage(self) -> None:
        """Test config accepts custom control percentage."""
        config = CohortAssignmentConfig(control_percentage=30)
        assert config.control_percentage == 30
        assert config.treatment_percentage == 70

    def test_custom_salt(self) -> None:
        """Test config accepts custom salt."""
        config = CohortAssignmentConfig(salt="my-custom-salt")
        assert config.salt == "my-custom-salt"

    def test_treatment_percentage_property(self) -> None:
        """Test treatment_percentage computed as 100 - control."""
        test_cases = [
            (0, 100),
            (20, 80),
            (50, 50),
            (75, 25),
            (100, 0),
        ]
        for control, expected_treatment in test_cases:
            config = CohortAssignmentConfig(control_percentage=control)
            assert config.treatment_percentage == expected_treatment, (
                f"For control={control}, expected treatment={expected_treatment}, "
                f"got {config.treatment_percentage}"
            )

    def test_validation_rejects_negative_percentage(self) -> None:
        """Test validation rejects control_percentage < 0."""
        with pytest.raises(ValidationError) as exc_info:
            CohortAssignmentConfig(control_percentage=-1)
        assert "control_percentage" in str(exc_info.value)

    def test_validation_rejects_over_100_percentage(self) -> None:
        """Test validation rejects control_percentage > 100."""
        with pytest.raises(ValidationError) as exc_info:
            CohortAssignmentConfig(control_percentage=101)
        assert "control_percentage" in str(exc_info.value)

    def test_validation_accepts_boundary_values(self) -> None:
        """Test validation accepts 0 and 100 as valid percentages."""
        config_0 = CohortAssignmentConfig(control_percentage=0)
        assert config_0.control_percentage == 0

        config_100 = CohortAssignmentConfig(control_percentage=100)
        assert config_100.control_percentage == 100

    def test_validation_rejects_empty_salt(self) -> None:
        """Test validation rejects empty salt string."""
        with pytest.raises(ValidationError) as exc_info:
            CohortAssignmentConfig(salt="")
        assert "salt" in str(exc_info.value)

    def test_from_env_returns_config(self) -> None:
        """Test from_env returns a CohortAssignmentConfig instance."""
        config = CohortAssignmentConfig.from_env()
        assert isinstance(config, CohortAssignmentConfig)

    def test_from_contract_returns_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test from_contract returns a CohortAssignmentConfig instance."""
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)
        config = CohortAssignmentConfig.from_contract()
        assert isinstance(config, CohortAssignmentConfig)
        # Should have contract defaults
        assert config.control_percentage == 20
        assert config.salt == "omniclaude-injection-v1"

    def test_from_contract_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test env override takes precedence over contract defaults."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "35")
        monkeypatch.setenv("OMNICLAUDE_COHORT_SALT", "override-salt")
        config = CohortAssignmentConfig.from_contract()
        assert config.control_percentage == 35
        assert config.salt == "override-salt"

    def test_from_contract_malformed_yaml_falls_back_to_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that contract load failure falls back gracefully to defaults."""
        # Clear any env overrides to ensure we test contract fallback
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        # Patch the contract model's load method to raise an error
        with patch.object(
            ExperimentCohortContract,
            "load",
            side_effect=Exception("Simulated contract load failure"),
        ):
            # Should fall back to defaults without raising
            with caplog.at_level(logging.WARNING):
                config = CohortAssignmentConfig.from_contract()

        # Verify fallback to hardcoded defaults
        assert config.control_percentage == 20
        assert config.salt == "omniclaude-injection-v1"

        # Verify warning was logged
        assert any(
            "Failed to load cohort contract" in record.message
            for record in caplog.records
        )

    def test_respects_environment_variable_control_percentage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test config respects OMNICLAUDE_COHORT_CONTROL_PERCENTAGE env var."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "45")
        config = CohortAssignmentConfig()
        assert config.control_percentage == 45
        assert config.treatment_percentage == 55

    def test_respects_environment_variable_salt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test config respects OMNICLAUDE_COHORT_SALT env var."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_SALT", "env-salt-value")
        config = CohortAssignmentConfig()
        assert config.salt == "env-salt-value"

    def test_from_contract_invalid_env_percentage_uses_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test invalid env percentage (non-numeric) falls back to contract default."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "abc")
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        with caplog.at_level(logging.WARNING):
            config = CohortAssignmentConfig.from_contract()

        # Should use contract default
        assert config.control_percentage == 20

        # Should log warning mentioning the env var
        assert any(
            "OMNICLAUDE_COHORT_CONTROL_PERCENTAGE" in record.message
            for record in caplog.records
        )

    def test_from_contract_float_env_percentage_uses_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test float env percentage falls back to contract default."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "35.5")
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        with caplog.at_level(logging.WARNING):
            config = CohortAssignmentConfig.from_contract()

        # Should use contract default (int("35.5") raises ValueError)
        assert config.control_percentage == 20

        # Should log warning mentioning the env var
        assert any(
            "OMNICLAUDE_COHORT_CONTROL_PERCENTAGE" in record.message
            for record in caplog.records
        )

    def test_from_contract_empty_env_percentage_uses_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test empty string env percentage falls back to contract default."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "")
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        with caplog.at_level(logging.WARNING):
            config = CohortAssignmentConfig.from_contract()

        # Should use contract default (int("") raises ValueError)
        assert config.control_percentage == 20

        # Should log warning mentioning the env var
        assert any(
            "OMNICLAUDE_COHORT_CONTROL_PERCENTAGE" in record.message
            for record in caplog.records
        )

    def test_contract_file_exists_and_is_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure the shipped contract file exists and contains expected values.

        Clear env vars to ensure we're testing the actual contract file values,
        not any environment overrides that might be set in the test environment.
        """
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)
        # Load contract using Pydantic model - validates structure and types
        contract = ExperimentCohortContract.load()

        assert contract.experiment.cohort.control_percentage == 20
        assert contract.experiment.cohort.salt == "omniclaude-injection-v1"


class TestCohortAssignmentWithCustomConfig:
    """Test assign_cohort with custom configuration."""

    def test_zero_percent_control_all_treatment(self) -> None:
        """Test 0% control assigns all sessions to treatment."""
        config = CohortAssignmentConfig(control_percentage=0)

        for i in range(100):
            result = assign_cohort(f"session-{i}", config=config)
            assert result.cohort == EnumCohort.TREATMENT, (
                f"Session {i} with seed {result.assignment_seed} "
                f"should be treatment with 0% control"
            )

    def test_100_percent_control_all_control(self) -> None:
        """Test 100% control assigns all sessions to control."""
        config = CohortAssignmentConfig(control_percentage=100)

        for i in range(100):
            result = assign_cohort(f"session-{i}", config=config)
            assert result.cohort == EnumCohort.CONTROL, (
                f"Session {i} with seed {result.assignment_seed} "
                f"should be control with 100% control"
            )

    def test_50_50_split_sees_both_cohorts(self) -> None:
        """Test 50/50 split produces both cohorts."""
        config = CohortAssignmentConfig(control_percentage=50)
        cohorts_seen = set()

        for i in range(100):
            result = assign_cohort(f"session-{i}", config=config)
            cohorts_seen.add(result.cohort)

        assert EnumCohort.CONTROL in cohorts_seen
        assert EnumCohort.TREATMENT in cohorts_seen

    def test_custom_salt_changes_assignment(self) -> None:
        """Test different salt produces different assignment for same session."""
        session_id = "test-session-for-salt"
        config1 = CohortAssignmentConfig(salt="salt-one")
        config2 = CohortAssignmentConfig(salt="salt-two")

        result1 = assign_cohort(session_id, config=config1)
        result2 = assign_cohort(session_id, config=config2)

        # Seeds should differ with different salts
        assert result1.assignment_seed != result2.assignment_seed, (
            "Different salts should produce different assignment seeds"
        )

    def test_custom_config_preserves_determinism(self) -> None:
        """Test same session+config always produces same result."""
        config = CohortAssignmentConfig(control_percentage=35, salt="custom-salt")
        session_id = "determinism-test-session"

        result1 = assign_cohort(session_id, config=config)
        result2 = assign_cohort(session_id, config=config)
        result3 = assign_cohort(session_id, config=config)

        assert result1 == result2 == result3

    def test_threshold_boundary_control(self) -> None:
        """Test control cohort assigned when seed < control_percentage."""
        config = CohortAssignmentConfig(control_percentage=50)

        # Find a session in control
        for i in range(1000):
            result = assign_cohort(f"boundary-test-{i}", config=config)
            if result.assignment_seed < 50:
                assert result.cohort == EnumCohort.CONTROL
                return

        pytest.fail("Could not find a session in control with 50% threshold")

    def test_threshold_boundary_treatment(self) -> None:
        """Test treatment cohort assigned when seed >= control_percentage."""
        config = CohortAssignmentConfig(control_percentage=50)

        # Find a session in treatment
        for i in range(1000):
            result = assign_cohort(f"boundary-test-{i}", config=config)
            if result.assignment_seed >= 50:
                assert result.cohort == EnumCohort.TREATMENT
                return

        pytest.fail("Could not find a session in treatment with 50% threshold")


class TestCohortDistributionWithCustomPercentage:
    """Test distribution matches custom percentages."""

    def test_10_percent_control_distribution(self) -> None:
        """Test 10% control gives approximately 10% in control cohort."""
        config = CohortAssignmentConfig(control_percentage=10)
        n_samples = 2000
        control_count = 0

        for i in range(n_samples):
            result = assign_cohort(f"dist-10-{i}", config=config)
            if result.cohort == EnumCohort.CONTROL:
                control_count += 1

        control_rate = control_count / n_samples
        expected_rate = 0.10

        # Allow 3% tolerance (7% to 13%)
        assert abs(control_rate - expected_rate) < 0.03, (
            f"Control rate {control_rate:.2%} not within 3% of expected {expected_rate:.2%}"
        )

    def test_50_percent_control_distribution(self) -> None:
        """Test 50% control gives approximately 50% in control cohort."""
        config = CohortAssignmentConfig(control_percentage=50)
        n_samples = 2000
        control_count = 0

        for i in range(n_samples):
            result = assign_cohort(f"dist-50-{i}", config=config)
            if result.cohort == EnumCohort.CONTROL:
                control_count += 1

        control_rate = control_count / n_samples
        expected_rate = 0.50

        # Allow 5% tolerance (45% to 55%)
        assert abs(control_rate - expected_rate) < 0.05, (
            f"Control rate {control_rate:.2%} not within 5% of expected {expected_rate:.2%}"
        )

    def test_90_percent_control_distribution(self) -> None:
        """Test 90% control gives approximately 90% in control cohort."""
        config = CohortAssignmentConfig(control_percentage=90)
        n_samples = 2000
        control_count = 0

        for i in range(n_samples):
            result = assign_cohort(f"dist-90-{i}", config=config)
            if result.cohort == EnumCohort.CONTROL:
                control_count += 1

        control_rate = control_count / n_samples
        expected_rate = 0.90

        # Allow 3% tolerance (87% to 93%)
        assert abs(control_rate - expected_rate) < 0.03, (
            f"Control rate {control_rate:.2%} not within 3% of expected {expected_rate:.2%}"
        )


class TestStickyIdentityAssignment:
    """Test sticky identity functionality for cohort assignment."""

    def test_user_id_takes_priority_over_repo_path(self) -> None:
        """Test user_id is used when both user_id and repo_path are provided."""
        result = assign_cohort(
            "session-123", user_id="user-456", repo_path="/workspace/repo"
        )
        assert result.identity_type == IdentityType.USER_ID

    def test_user_id_takes_priority_over_session_id(self) -> None:
        """Test user_id is used when only session_id and user_id provided."""
        result = assign_cohort("session-123", user_id="user-456")
        assert result.identity_type == IdentityType.USER_ID

    def test_repo_path_takes_priority_over_session_id(self) -> None:
        """Test repo_path is used when user_id not provided."""
        result = assign_cohort("session-123", repo_path="/workspace/repo")
        assert result.identity_type == IdentityType.REPO_PATH

    def test_session_id_used_as_fallback(self) -> None:
        """Test session_id used when no user_id or repo_path provided."""
        result = assign_cohort("session-123")
        assert result.identity_type == IdentityType.SESSION_ID

    def test_empty_user_id_falls_back_to_repo_path(self) -> None:
        """Test empty string user_id falls back to repo_path."""
        result = assign_cohort("session-123", user_id="", repo_path="/workspace/repo")
        assert result.identity_type == IdentityType.REPO_PATH

    def test_whitespace_user_id_falls_back_to_repo_path(self) -> None:
        """Test whitespace-only user_id falls back to repo_path."""
        result = assign_cohort(
            "session-123", user_id="   ", repo_path="/workspace/repo"
        )
        assert result.identity_type == IdentityType.REPO_PATH

    def test_empty_repo_path_falls_back_to_session_id(self) -> None:
        """Test empty string repo_path falls back to session_id."""
        result = assign_cohort("session-123", repo_path="")
        assert result.identity_type == IdentityType.SESSION_ID

    def test_whitespace_repo_path_falls_back_to_session_id(self) -> None:
        """Test whitespace-only repo_path falls back to session_id."""
        result = assign_cohort("session-123", repo_path="   ")
        assert result.identity_type == IdentityType.SESSION_ID

    def test_none_user_id_falls_back_to_repo_path(self) -> None:
        """Test None user_id falls back to repo_path."""
        result = assign_cohort("session-123", user_id=None, repo_path="/workspace/repo")
        assert result.identity_type == IdentityType.REPO_PATH

    def test_same_user_id_deterministic_across_sessions(self) -> None:
        """Test same user gets same cohort across different sessions."""
        result1 = assign_cohort("session-111", user_id="user-stable")
        result2 = assign_cohort("session-222", user_id="user-stable")
        result3 = assign_cohort("session-333", user_id="user-stable")

        assert result1.cohort == result2.cohort == result3.cohort
        assert (
            result1.assignment_seed
            == result2.assignment_seed
            == result3.assignment_seed
        )

    def test_same_repo_path_deterministic_across_sessions(self) -> None:
        """Test same repo gets same cohort across different sessions."""
        result1 = assign_cohort("session-111", repo_path="/workspace/myrepo")
        result2 = assign_cohort("session-222", repo_path="/workspace/myrepo")
        result3 = assign_cohort("session-333", repo_path="/workspace/myrepo")

        assert result1.cohort == result2.cohort == result3.cohort
        assert (
            result1.assignment_seed
            == result2.assignment_seed
            == result3.assignment_seed
        )

    def test_different_user_ids_can_have_different_cohorts(self) -> None:
        """Test different users can be assigned to different cohorts."""
        cohorts_seen = set()
        for i in range(100):
            result = assign_cohort(f"session-{i}", user_id=f"user-{i}")
            cohorts_seen.add(result.cohort)

        # With 100 samples, statistically likely to see both cohorts
        assert EnumCohort.CONTROL in cohorts_seen
        assert EnumCohort.TREATMENT in cohorts_seen

    def test_identity_type_in_cohort_assignment_result(self) -> None:
        """Test CohortAssignment includes identity_type field."""
        result = assign_cohort("session-123", user_id="user-456")

        # Verify all expected fields are present
        assert hasattr(result, "cohort")
        assert hasattr(result, "assignment_seed")
        assert hasattr(result, "identity_type")
        assert isinstance(result.identity_type, IdentityType)


class TestCohortAssignmentHashAlgorithm:
    """Verify hash algorithm correctness and boundary behavior.

    These tests document the cohort assignment algorithm:
    - SHA-256(identity + ":" + salt) -> first 8 bytes -> mod 100

    This ensures the algorithm is deterministic and produces expected seeds.
    """

    def test_hash_algorithm_produces_expected_seed(self) -> None:
        """Verify hash algorithm produces expected seed for known input.

        Algorithm: SHA-256(identity:salt) -> first 8 bytes -> mod 100
        This test documents the exact algorithm for ONEX compliance.
        """
        import hashlib

        # Test with known values
        identity = "test-session"
        salt = "test-salt"
        config = CohortAssignmentConfig(salt=salt, control_percentage=50)

        # Compute expected seed manually
        seed_input = f"{identity}:{salt}"
        hash_bytes = hashlib.sha256(seed_input.encode("utf-8")).digest()
        expected_seed = int.from_bytes(hash_bytes[:8], byteorder="big") % 100

        # Verify assign_cohort produces the same seed
        result = assign_cohort(identity, config=config)
        assert result.assignment_seed == expected_seed, (
            f"Expected seed {expected_seed}, got {result.assignment_seed}. "
            f"Algorithm: SHA-256('{seed_input}') first 8 bytes mod 100"
        )

    def test_seed_zero_is_possible(self) -> None:
        """Verify seed=0 is a valid assignment result.

        This tests the boundary condition at seed=0 (should be CONTROL
        when control_percentage > 0).
        """
        # Search for a session that produces seed=0
        # Note: Finding seed=0 may take many iterations
        for i in range(100000):
            result = assign_cohort(f"seed-zero-search-{i}")
            if result.assignment_seed == 0:
                # Found seed=0, verify it's in control (default 20% control)
                assert result.cohort == EnumCohort.CONTROL
                return

        # Skip if not found - this is probabilistic
        pytest.skip("Could not find seed=0 in 100000 iterations (probabilistic)")

    def test_seed_99_is_possible(self) -> None:
        """Verify seed=99 is a valid assignment result.

        This tests the upper boundary (should be TREATMENT when
        control_percentage < 100).
        """
        for i in range(100000):
            result = assign_cohort(f"seed-99-search-{i}")
            if result.assignment_seed == 99:
                # Found seed=99, verify it's in treatment (default 20% control)
                assert result.cohort == EnumCohort.TREATMENT
                return

        pytest.skip("Could not find seed=99 in 100000 iterations (probabilistic)")

    def test_boundary_at_control_percentage_minus_one(self) -> None:
        """Test seed exactly at control_percentage-1 is CONTROL."""
        config = CohortAssignmentConfig(control_percentage=50)

        # Find a session with seed=49 (last control seed for 50% control)
        for i in range(100000):
            result = assign_cohort(f"boundary-49-{i}", config=config)
            if result.assignment_seed == 49:
                assert result.cohort == EnumCohort.CONTROL, (
                    "Seed 49 should be CONTROL with control_percentage=50"
                )
                return

        pytest.skip("Could not find seed=49 in 100000 iterations")

    def test_boundary_at_control_percentage(self) -> None:
        """Test seed exactly at control_percentage is TREATMENT."""
        config = CohortAssignmentConfig(control_percentage=50)

        # Find a session with seed=50 (first treatment seed for 50% control)
        for i in range(100000):
            result = assign_cohort(f"boundary-50-{i}", config=config)
            if result.assignment_seed == 50:
                assert result.cohort == EnumCohort.TREATMENT, (
                    "Seed 50 should be TREATMENT with control_percentage=50"
                )
                return

        pytest.skip("Could not find seed=50 in 100000 iterations")

    def test_all_seeds_in_valid_range(self) -> None:
        """Verify all seeds are in valid range 0-99 across many samples."""
        seeds_seen = set()
        for i in range(10000):
            result = assign_cohort(f"range-test-{i}")
            assert 0 <= result.assignment_seed < 100, (
                f"Seed {result.assignment_seed} out of valid range [0, 100)"
            )
            seeds_seen.add(result.assignment_seed)

        # With 10000 samples, should see most of the 100 possible seeds
        # (birthday paradox: very high probability of seeing all 100)
        assert len(seeds_seen) > 80, (
            f"Expected to see most seeds in 10000 samples, only saw {len(seeds_seen)}"
        )

    def test_uniform_distribution_chi_squared(self) -> None:
        """Verify seed distribution is approximately uniform using chi-squared.

        This statistical test verifies the hash function produces a uniform
        distribution across [0, 100) which is essential for correct cohort splits.
        """

        n_samples = 10000
        expected_per_bucket = n_samples / 100  # 100 expected per seed value

        # Count occurrences of each seed
        seed_counts = [0] * 100
        for i in range(n_samples):
            result = assign_cohort(f"uniform-test-{i}")
            seed_counts[result.assignment_seed] += 1

        # Calculate chi-squared statistic
        chi_squared = sum(
            (observed - expected_per_bucket) ** 2 / expected_per_bucket
            for observed in seed_counts
        )

        # Critical value for df=99, alpha=0.01 is approximately 134.6
        # If chi-squared < critical, distribution is uniform (fail to reject H0)
        critical_value = 134.6
        assert chi_squared < critical_value, (
            f"Chi-squared {chi_squared:.2f} exceeds critical value {critical_value}. "
            f"Distribution may not be uniform. "
            f"Min bucket: {min(seed_counts)}, Max bucket: {max(seed_counts)}"
        )


class TestCohortAssignmentImmutability:
    """Test that CohortAssignment is immutable (NamedTuple guarantee)."""

    def test_cohort_assignment_is_immutable(self) -> None:
        """Test CohortAssignment attributes cannot be modified."""
        result = assign_cohort("test-session")

        with pytest.raises(AttributeError):
            result.cohort = EnumCohort.CONTROL  # type: ignore[misc]

        with pytest.raises(AttributeError):
            result.assignment_seed = 50  # type: ignore[misc]

    def test_cohort_assignment_is_hashable(self) -> None:
        """Test CohortAssignment can be used in sets and as dict keys."""
        result1 = assign_cohort("session-1")
        result2 = assign_cohort("session-2")

        # Should be usable in a set (requires hashability)
        result_set = {result1, result2}
        assert len(result_set) >= 1  # At least one unique result

        # Should be usable as dict key
        result_dict = {result1: "value1"}
        assert result_dict[result1] == "value1"

    def test_cohort_assignment_equality(self) -> None:
        """Test CohortAssignment equality is value-based."""
        # Same session should produce identical results
        result1 = assign_cohort("same-session")
        result2 = assign_cohort("same-session")

        assert result1 == result2
        assert hash(result1) == hash(result2)


class TestCohortAssignmentRegressionValues:
    """Regression tests with known input/output values.

    These tests document the exact behavior of the cohort assignment algorithm
    by asserting specific seeds for specific inputs. If the algorithm changes,
    these tests will fail, alerting developers that existing cohort assignments
    may be affected.

    Algorithm: SHA-256(identity:salt) -> first 8 bytes -> mod 100
    Default salt: "omniclaude-injection-v1"
    """

    def test_known_session_produces_known_seed(self) -> None:
        """Regression test: known session ID produces known seed.

        This documents the exact algorithm behavior. If this test fails,
        it means the cohort assignment algorithm has changed, which would
        affect all existing users' cohort assignments.
        """
        # Use default config (20% control, salt="omniclaude-injection-v1")
        result = assign_cohort("test-regression-session-12345")

        # Document the expected seed for this input
        # SHA-256("test-regression-session-12345:omniclaude-injection-v1")
        # First 8 bytes as int, mod 100 = 83
        # This seed was computed from the known algorithm and serves as a regression guard
        assert result.assignment_seed == 83, (
            f"Regression failure: expected seed 83 for session 'test-regression-session-12345', "
            f"got {result.assignment_seed}. The cohort assignment algorithm may have changed."
        )

    def test_known_config_produces_expected_cohort(self) -> None:
        """Regression test: known config determines correct cohort from seed.

        With 20% control (default), seed 83 should be TREATMENT (>=20).
        This verifies the threshold logic works correctly.
        """
        result = assign_cohort("test-regression-session-12345")

        # seed=83, control_percentage=20, so 83 >= 20 -> TREATMENT
        assert result.cohort == EnumCohort.TREATMENT, (
            f"Regression failure: expected TREATMENT for seed {result.assignment_seed} "
            f"with 20% control threshold, got {result.cohort}"
        )

    def test_custom_salt_changes_seed_predictably(self) -> None:
        """Regression test: different salt produces different known seed.

        Documents that changing the salt changes cohort assignments.
        """
        config = CohortAssignmentConfig(salt="custom-regression-salt")
        result = assign_cohort("test-regression-session-12345", config=config)

        # This seed was computed for the custom salt
        # SHA-256("test-regression-session-12345:custom-regression-salt") = 49
        # If this fails, the salt handling in the algorithm may have changed
        assert result.assignment_seed == 49, (
            f"Regression failure: expected seed 49 for custom salt, "
            f"got {result.assignment_seed}. Salt handling may have changed."
        )
