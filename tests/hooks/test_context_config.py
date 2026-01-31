# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for ContextInjectionConfig.

Tests verify:
1. Default values load correctly
2. Environment variable overrides work
3. Nested cohort config loads via from_contract factory
4. Nested cohort config respects OMNICLAUDE_COHORT_* env vars
5. from_env() properly triggers nested config loading

Part of OMN-1674: INJECT-005 A/B cohort assignment
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from omniclaude.hooks.cohort_assignment import CohortAssignmentConfig
from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.injection_limits import InjectionLimitsConfig

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


class TestContextInjectionConfigDefaults:
    """Test default values for ContextInjectionConfig."""

    def test_default_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test enabled defaults to True."""
        monkeypatch.delenv("OMNICLAUDE_CONTEXT_ENABLED", raising=False)
        config = ContextInjectionConfig()
        assert config.enabled is True

    def test_default_max_patterns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test max_patterns defaults to 5."""
        monkeypatch.delenv("OMNICLAUDE_CONTEXT_MAX_PATTERNS", raising=False)
        config = ContextInjectionConfig()
        assert config.max_patterns == 5

    def test_default_min_confidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test min_confidence defaults to 0.7."""
        monkeypatch.delenv("OMNICLAUDE_CONTEXT_MIN_CONFIDENCE", raising=False)
        config = ContextInjectionConfig()
        assert config.min_confidence == 0.7

    def test_default_db_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test db_enabled defaults to True."""
        monkeypatch.delenv("OMNICLAUDE_CONTEXT_DB_ENABLED", raising=False)
        config = ContextInjectionConfig()
        assert config.db_enabled is True


class TestContextInjectionConfigEnvOverride:
    """Test environment variable overrides for ContextInjectionConfig."""

    def test_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test enabled can be set via environment variable."""
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_ENABLED", "false")
        config = ContextInjectionConfig()
        assert config.enabled is False

    def test_max_patterns_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test max_patterns can be set via environment variable."""
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_MAX_PATTERNS", "10")
        config = ContextInjectionConfig()
        assert config.max_patterns == 10

    def test_min_confidence_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test min_confidence can be set via environment variable."""
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_MIN_CONFIDENCE", "0.85")
        config = ContextInjectionConfig()
        assert config.min_confidence == 0.85


class TestContextInjectionConfigNestedLimits:
    """Test nested InjectionLimitsConfig loading."""

    def test_limits_is_injection_limits_config(self) -> None:
        """Test limits field is InjectionLimitsConfig instance."""
        config = ContextInjectionConfig()
        assert isinstance(config.limits, InjectionLimitsConfig)

    def test_limits_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test limits loads default values."""
        monkeypatch.delenv(
            "OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION", raising=False
        )
        config = ContextInjectionConfig()
        assert config.limits.max_patterns_per_injection == 5
        assert config.limits.max_per_domain == 2

    def test_limits_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test limits respects its own env prefix."""
        monkeypatch.setenv(
            "OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION", "15"
        )
        config = ContextInjectionConfig()
        assert config.limits.max_patterns_per_injection == 15


class TestContextInjectionConfigNestedCohort:
    """Test nested CohortAssignmentConfig loading via from_contract factory."""

    def test_cohort_is_cohort_assignment_config(self) -> None:
        """Test cohort field is CohortAssignmentConfig instance."""
        config = ContextInjectionConfig()
        assert isinstance(config.cohort, CohortAssignmentConfig)

    def test_cohort_loads_contract_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cohort loads defaults from contract YAML."""
        # Clear any env overrides to ensure contract defaults are used
        monkeypatch.delenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", raising=False)
        monkeypatch.delenv("OMNICLAUDE_COHORT_SALT", raising=False)

        config = ContextInjectionConfig()

        # These are the contract defaults from contract_experiment_cohort.yaml
        assert config.cohort.control_percentage == 20
        assert config.cohort.salt == "omniclaude-injection-v1"
        assert config.cohort.treatment_percentage == 80

    def test_cohort_respects_env_override_control_percentage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cohort respects OMNICLAUDE_COHORT_CONTROL_PERCENTAGE env var.

        This verifies that the from_contract factory correctly reads
        OMNICLAUDE_COHORT_* env vars (not OMNICLAUDE_CONTEXT_COHORT_*).
        """
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "35")

        config = ContextInjectionConfig()

        assert config.cohort.control_percentage == 35
        assert config.cohort.treatment_percentage == 65

    def test_cohort_respects_env_override_salt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test cohort respects OMNICLAUDE_COHORT_SALT env var."""
        monkeypatch.setenv("OMNICLAUDE_COHORT_SALT", "custom-experiment-salt")

        config = ContextInjectionConfig()

        assert config.cohort.salt == "custom-experiment-salt"

    def test_cohort_env_override_via_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test from_env() properly triggers cohort env var loading.

        This is the key test for PR #67 - verifying that calling
        ContextInjectionConfig.from_env() correctly invokes the
        CohortAssignmentConfig.from_contract() factory which reads
        OMNICLAUDE_COHORT_* environment variables.
        """
        # Set cohort env overrides (not OMNICLAUDE_CONTEXT_COHORT_*)
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "50")
        monkeypatch.setenv("OMNICLAUDE_COHORT_SALT", "from-env-test-salt")

        # Use from_env() explicitly (the method under test)
        config = ContextInjectionConfig.from_env()

        # Verify cohort config picked up the env overrides
        assert config.cohort.control_percentage == 50
        assert config.cohort.salt == "from-env-test-salt"
        assert config.cohort.treatment_percentage == 50

    def test_from_env_loads_both_nested_configs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test from_env() loads both limits and cohort nested configs."""
        # Set env vars for both nested configs
        monkeypatch.setenv(
            "OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION", "12"
        )
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "25")

        config = ContextInjectionConfig.from_env()

        # Both nested configs should have picked up their env vars
        assert config.limits.max_patterns_per_injection == 12
        assert config.cohort.control_percentage == 25


class TestContextInjectionConfigFromEnv:
    """Test from_env() class method."""

    def test_from_env_returns_config_instance(self) -> None:
        """Test from_env returns ContextInjectionConfig instance."""
        config = ContextInjectionConfig.from_env()
        assert isinstance(config, ContextInjectionConfig)

    def test_from_env_equivalent_to_constructor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test from_env() is equivalent to calling cls()."""
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_MAX_PATTERNS", "8")

        config1 = ContextInjectionConfig.from_env()
        config2 = ContextInjectionConfig()

        assert config1.max_patterns == config2.max_patterns == 8

    def test_from_env_with_all_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() with env overrides at all levels."""
        # Top-level config
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_ENABLED", "true")
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_MAX_PATTERNS", "7")
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_MIN_CONFIDENCE", "0.9")

        # Limits nested config
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_MAX_PER_DOMAIN", "3")

        # Cohort nested config (uses from_contract factory)
        monkeypatch.setenv("OMNICLAUDE_COHORT_CONTROL_PERCENTAGE", "40")

        config = ContextInjectionConfig.from_env()

        # Verify all levels
        assert config.enabled is True
        assert config.max_patterns == 7
        assert config.min_confidence == 0.9
        assert config.limits.max_per_domain == 3
        assert config.cohort.control_percentage == 40


class TestContextInjectionConfigDatabaseDsn:
    """Test get_db_dsn() method."""

    def test_get_db_dsn_format(self) -> None:
        """Test DSN format is correct."""
        config = ContextInjectionConfig(
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
            db_user="testuser",
            db_password=SecretStr("testpass"),
        )
        dsn = config.get_db_dsn()
        assert dsn == "postgresql://testuser:testpass@localhost:5432/testdb"

    def test_get_db_dsn_with_defaults(self) -> None:
        """Test DSN uses default values."""
        config = ContextInjectionConfig(db_password=SecretStr("mypassword"))
        dsn = config.get_db_dsn()

        assert "192.168.86.200" in dsn  # Default host
        assert "5436" in dsn  # Default port
        assert "omninode_bridge" in dsn  # Default db name
        assert "postgres" in dsn  # Default user
        assert "mypassword" in dsn  # Password we set
