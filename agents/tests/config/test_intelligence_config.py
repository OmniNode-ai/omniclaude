#!/usr/bin/env python3
"""
Test Suite for IntelligenceConfig

Tests configuration management for event-based intelligence gathering:
- Environment variable loading and precedence
- Field validation and error handling
- Default values and feature flags
- Configuration consistency validation
- Serialization and utility methods

Coverage Target: >90%
Reference: EVENT_INTELLIGENCE_INTEGRATION_PLAN.md Section 2.2
"""


import pytest
from pydantic import ValidationError

from agents.lib.config.intelligence_config import IntelligenceConfig

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Clean environment with no intelligence config variables set."""
    env_vars = [
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_ENABLE_INTELLIGENCE",
        "KAFKA_REQUEST_TIMEOUT_MS",
        "KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS",
        "KAFKA_CODE_ANALYSIS_TIMEOUT_MS",
        "KAFKA_CONSUMER_GROUP_PREFIX",
        "ENABLE_EVENT_BASED_DISCOVERY",
        "ENABLE_FILESYSTEM_FALLBACK",
        "PREFER_EVENT_PATTERNS",
        "TOPIC_CODE_ANALYSIS_REQUESTED",
        "TOPIC_CODE_ANALYSIS_COMPLETED",
        "TOPIC_CODE_ANALYSIS_FAILED",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def sample_config():
    """Sample valid configuration."""
    return IntelligenceConfig(
        kafka_bootstrap_servers="kafka:9092",
        kafka_enable_intelligence=True,
        kafka_request_timeout_ms=5000,
        enable_event_based_discovery=True,
        enable_filesystem_fallback=True,
    )


# =============================================================================
# Test: Default Values
# =============================================================================


class TestIntelligenceConfigDefaults:
    """Test default configuration values."""

    def test_default_values(self, clean_env):
        """Test all default configuration values are set correctly."""
        config = IntelligenceConfig()

        # Kafka configuration defaults (loaded from centralized Pydantic Settings)
        # Note: Values come from .env file loaded at module import time
        # The .env file is loaded by settings.py before Settings initialization,
        # so these are the actual runtime defaults
        assert config.kafka_bootstrap_servers == "192.168.86.200:29092"
        assert config.kafka_enable_intelligence is True
        assert config.kafka_request_timeout_ms == 5000
        assert config.kafka_pattern_discovery_timeout_ms == 5000
        assert config.kafka_code_analysis_timeout_ms == 10000
        assert config.kafka_consumer_group_prefix == "omniclaude"

        # Feature flag defaults
        assert config.enable_event_based_discovery is True
        assert config.enable_filesystem_fallback is True
        assert config.prefer_event_patterns is True

        # Topic name defaults
        assert config.topic_code_analysis_requested == (
            "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
        )
        assert config.topic_code_analysis_completed == (
            "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
        )
        assert config.topic_code_analysis_failed == (
            "dev.archon-intelligence.intelligence.code-analysis-failed.v1"
        )

    def test_default_config_is_valid(self):
        """Test default configuration passes validation."""
        config = IntelligenceConfig()
        # Should not raise
        config.validate_config()


# =============================================================================
# Test: Environment Variable Loading
# =============================================================================


class TestEnvironmentVariableLoading:
    """Test configuration loading from environment variables."""

    def test_from_env_loads_bootstrap_servers(self, clean_env):
        """Test loading KAFKA_BOOTSTRAP_SERVERS from environment."""
        clean_env.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        config = IntelligenceConfig.from_env()
        assert config.kafka_bootstrap_servers == "kafka:9092"

    def test_from_env_loads_boolean_flags(self, clean_env):
        """Test loading boolean feature flags from environment."""
        clean_env.setenv("KAFKA_ENABLE_INTELLIGENCE", "false")
        clean_env.setenv("ENABLE_EVENT_BASED_DISCOVERY", "no")
        clean_env.setenv("ENABLE_FILESYSTEM_FALLBACK", "0")
        clean_env.setenv("PREFER_EVENT_PATTERNS", "off")

        config = IntelligenceConfig.from_env()

        assert config.kafka_enable_intelligence is False
        assert config.enable_event_based_discovery is False
        assert config.enable_filesystem_fallback is False
        assert config.prefer_event_patterns is False

    def test_from_env_loads_integer_timeouts(self, clean_env):
        """Test loading integer timeout values from environment."""
        clean_env.setenv("KAFKA_REQUEST_TIMEOUT_MS", "3000")
        clean_env.setenv("KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS", "4000")
        clean_env.setenv("KAFKA_CODE_ANALYSIS_TIMEOUT_MS", "15000")

        config = IntelligenceConfig.from_env()

        assert config.kafka_request_timeout_ms == 3000
        assert config.kafka_pattern_discovery_timeout_ms == 4000
        assert config.kafka_code_analysis_timeout_ms == 15000

    def test_from_env_loads_consumer_group_prefix(self, clean_env):
        """Test loading consumer group prefix from environment."""
        clean_env.setenv("KAFKA_CONSUMER_GROUP_PREFIX", "custom-prefix")
        config = IntelligenceConfig.from_env()
        assert config.kafka_consumer_group_prefix == "custom-prefix"

    def test_from_env_loads_topic_names(self, clean_env):
        """Test loading Kafka topic names from environment."""
        clean_env.setenv("TOPIC_CODE_ANALYSIS_REQUESTED", "custom.requested.v2")
        clean_env.setenv("TOPIC_CODE_ANALYSIS_COMPLETED", "custom.completed.v2")
        clean_env.setenv("TOPIC_CODE_ANALYSIS_FAILED", "custom.failed.v2")

        config = IntelligenceConfig.from_env()

        assert config.topic_code_analysis_requested == "custom.requested.v2"
        assert config.topic_code_analysis_completed == "custom.completed.v2"
        assert config.topic_code_analysis_failed == "custom.failed.v2"

    def test_from_env_uses_defaults_when_not_set(self, clean_env):
        """Test from_env() uses default values when env vars not set."""
        config = IntelligenceConfig.from_env()
        # Note: kafka_bootstrap_servers comes from .env file loaded at module import time
        assert config.kafka_bootstrap_servers == "192.168.86.200:29092"
        assert config.kafka_enable_intelligence is True


# =============================================================================
# Test: Field Validation
# =============================================================================


class TestFieldValidation:
    """Test field validators and error handling."""

    def test_validate_bootstrap_servers_empty_string(self):
        """Test validation rejects empty bootstrap servers."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            IntelligenceConfig(kafka_bootstrap_servers="")

    def test_validate_bootstrap_servers_missing_port(self):
        """Test validation rejects servers without port."""
        with pytest.raises(ValidationError, match="Expected 'host:port'"):
            IntelligenceConfig(kafka_bootstrap_servers="localhost")

    def test_validate_bootstrap_servers_invalid_format(self):
        """Test validation rejects invalid server format."""
        with pytest.raises(ValidationError, match="Invalid server format"):
            IntelligenceConfig(kafka_bootstrap_servers="not_valid_format")

    def test_validate_bootstrap_servers_invalid_port(self):
        """Test validation rejects invalid port numbers."""
        with pytest.raises(ValidationError, match="Port.*out of valid range"):
            IntelligenceConfig(kafka_bootstrap_servers="localhost:99999")

    def test_validate_bootstrap_servers_negative_port(self):
        """Test validation rejects negative port numbers."""
        with pytest.raises(ValidationError, match="Port.*out of valid range"):
            IntelligenceConfig(kafka_bootstrap_servers="localhost:-1")

    def test_validate_bootstrap_servers_multiple_valid(self):
        """Test validation accepts multiple comma-separated servers."""
        config = IntelligenceConfig(
            kafka_bootstrap_servers="kafka1:9092,kafka2:9092,kafka3:9092"
        )
        assert config.kafka_bootstrap_servers == "kafka1:9092,kafka2:9092,kafka3:9092"

    def test_validate_consumer_group_prefix_empty(self):
        """Test validation rejects empty consumer group prefix."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            IntelligenceConfig(kafka_consumer_group_prefix="")

    def test_validate_consumer_group_prefix_whitespace(self):
        """Test validation rejects whitespace-only consumer group prefix."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            IntelligenceConfig(kafka_consumer_group_prefix="   ")

    def test_validate_timeout_below_minimum(self):
        """Test validation rejects timeouts below minimum."""
        with pytest.raises(ValidationError):
            IntelligenceConfig(kafka_request_timeout_ms=500)  # Below 1000ms minimum

    def test_validate_timeout_above_maximum(self):
        """Test validation rejects timeouts above maximum."""
        with pytest.raises(ValidationError):
            IntelligenceConfig(kafka_request_timeout_ms=70000)  # Above 60000ms maximum


# =============================================================================
# Test: Configuration Consistency Validation
# =============================================================================


class TestConfigurationValidation:
    """Test validate() method for configuration consistency."""

    def test_validate_catches_both_sources_disabled(self):
        """Test validation fails when both intelligence sources disabled."""
        config = IntelligenceConfig(
            enable_event_based_discovery=False,
            enable_filesystem_fallback=False,
        )

        with pytest.raises(ValueError, match="At least one intelligence source"):
            config.validate_config()

    def test_validate_accepts_event_only(self):
        """Test validation accepts event-based discovery only."""
        config = IntelligenceConfig(
            enable_event_based_discovery=True,
            enable_filesystem_fallback=False,
        )
        # Should not raise
        config.validate_config()

    def test_validate_accepts_filesystem_only(self):
        """Test validation accepts filesystem fallback only."""
        config = IntelligenceConfig(
            enable_event_based_discovery=False,
            enable_filesystem_fallback=True,
        )
        # Should not raise
        config.validate_config()

    def test_validate_empty_topic_requested(self):
        """Test validation rejects empty request topic name."""
        config = IntelligenceConfig(topic_code_analysis_requested="   ")

        with pytest.raises(
            ValueError, match="topic_code_analysis_requested cannot be empty"
        ):
            config.validate_config()

    def test_validate_empty_topic_completed(self):
        """Test validation rejects empty completed topic name."""
        config = IntelligenceConfig(topic_code_analysis_completed="   ")

        with pytest.raises(
            ValueError, match="topic_code_analysis_completed cannot be empty"
        ):
            config.validate_config()

    def test_validate_empty_topic_failed(self):
        """Test validation rejects empty failed topic name."""
        config = IntelligenceConfig(topic_code_analysis_failed="   ")

        with pytest.raises(
            ValueError, match="topic_code_analysis_failed cannot be empty"
        ):
            config.validate_config()


# =============================================================================
# Test: Utility Methods
# =============================================================================


class TestUtilityMethods:
    """Test utility and helper methods."""

    def test_is_event_discovery_enabled_both_true(self):
        """Test event discovery enabled when both flags true."""
        config = IntelligenceConfig(
            kafka_enable_intelligence=True,
            enable_event_based_discovery=True,
        )
        assert config.is_event_discovery_enabled() is True

    def test_is_event_discovery_enabled_kafka_disabled(self):
        """Test event discovery disabled when kafka disabled."""
        config = IntelligenceConfig(
            kafka_enable_intelligence=False,
            enable_event_based_discovery=True,
        )
        assert config.is_event_discovery_enabled() is False

    def test_is_event_discovery_enabled_discovery_disabled(self):
        """Test event discovery disabled when discovery flag disabled."""
        config = IntelligenceConfig(
            kafka_enable_intelligence=True,
            enable_event_based_discovery=False,
        )
        assert config.is_event_discovery_enabled() is False

    def test_is_event_discovery_enabled_both_false(self):
        """Test event discovery disabled when both flags false."""
        config = IntelligenceConfig(
            kafka_enable_intelligence=False,
            enable_event_based_discovery=False,
        )
        assert config.is_event_discovery_enabled() is False

    def test_get_bootstrap_servers(self, sample_config):
        """Test get_bootstrap_servers returns correct value."""
        servers = sample_config.get_bootstrap_servers()
        assert servers == "kafka:9092"

    def test_to_dict_serialization(self, sample_config):
        """Test configuration serialization to dictionary."""
        data = sample_config.to_dict()

        assert isinstance(data, dict)
        assert "kafka_bootstrap_servers" in data
        assert "kafka_enable_intelligence" in data
        assert "enable_event_based_discovery" in data
        assert data["kafka_bootstrap_servers"] == "kafka:9092"

    def test_to_dict_contains_all_fields(self):
        """Test to_dict includes all configuration fields."""
        config = IntelligenceConfig()
        data = config.to_dict()

        expected_fields = [
            "kafka_bootstrap_servers",
            "kafka_enable_intelligence",
            "kafka_request_timeout_ms",
            "kafka_pattern_discovery_timeout_ms",
            "kafka_code_analysis_timeout_ms",
            "kafka_consumer_group_prefix",
            "enable_event_based_discovery",
            "enable_filesystem_fallback",
            "prefer_event_patterns",
            "topic_code_analysis_requested",
            "topic_code_analysis_completed",
            "topic_code_analysis_failed",
        ]

        for field in expected_fields:
            assert field in data, f"Missing field: {field}"


# =============================================================================
# Test: Edge Cases and Boundary Conditions
# =============================================================================
# Note: Helper function tests (_parse_bool, _parse_int) removed in Phase 2
# Type conversion is now handled automatically by Pydantic Settings framework


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_bootstrap_servers_with_spaces(self):
        """Test bootstrap servers with extra whitespace in list."""
        config = IntelligenceConfig(
            kafka_bootstrap_servers="kafka1:9092, kafka2:9092, kafka3:9092"
        )
        # Should handle spaces gracefully
        assert config.kafka_bootstrap_servers == "kafka1:9092, kafka2:9092, kafka3:9092"

    def test_consumer_group_prefix_with_special_characters(self):
        """Test consumer group prefix with special characters."""
        config = IntelligenceConfig(kafka_consumer_group_prefix="omniclaude-test_2025")
        assert config.kafka_consumer_group_prefix == "omniclaude-test_2025"

    def test_timeout_at_minimum_boundary(self):
        """Test timeout at minimum allowed value."""
        config = IntelligenceConfig(kafka_request_timeout_ms=1000)  # Minimum
        assert config.kafka_request_timeout_ms == 1000

    def test_timeout_at_maximum_boundary(self):
        """Test timeout at maximum allowed value."""
        config = IntelligenceConfig(kafka_request_timeout_ms=60000)  # Maximum
        assert config.kafka_request_timeout_ms == 60000

    def test_code_analysis_timeout_at_maximum(self):
        """Test code analysis timeout at maximum allowed value."""
        config = IntelligenceConfig(kafka_code_analysis_timeout_ms=120000)  # Maximum
        assert config.kafka_code_analysis_timeout_ms == 120000

    def test_ipv6_address_in_bootstrap_servers(self):
        """Test bootstrap servers with IPv6 address."""
        config = IntelligenceConfig(kafka_bootstrap_servers="[::1]:9092")
        assert config.kafka_bootstrap_servers == "[::1]:9092"

    def test_config_immutability_with_pydantic(self, clean_env):
        """Test configuration field access with Pydantic BaseModel."""
        config = IntelligenceConfig()
        # Pydantic BaseModel models are mutable by default (unless frozen=True)
        # Test verifies field access works correctly
        assert hasattr(config, "kafka_bootstrap_servers")
        # Note: kafka_bootstrap_servers comes from .env file loaded at module import time
        assert config.kafka_bootstrap_servers == "192.168.86.200:29092"

        # Verify we can read all key fields
        assert hasattr(config, "kafka_enable_intelligence")
        assert hasattr(config, "kafka_request_timeout_ms")
        assert hasattr(config, "enable_event_based_discovery")


# =============================================================================
# Test: Integration with Real Environment
# =============================================================================


class TestRealEnvironmentIntegration:
    """Test integration with real environment variables."""

    def test_partial_environment_override(self, clean_env):
        """Test partial environment variable override uses defaults for rest."""
        clean_env.setenv("KAFKA_BOOTSTRAP_SERVERS", "prod-kafka:9092")
        clean_env.setenv("KAFKA_ENABLE_INTELLIGENCE", "false")

        config = IntelligenceConfig.from_env()

        # Overridden values
        assert config.kafka_bootstrap_servers == "prod-kafka:9092"
        assert config.kafka_enable_intelligence is False

        # Default values
        assert config.kafka_request_timeout_ms == 5000
        assert config.enable_event_based_discovery is True

    def test_all_environment_variables_override(self, clean_env):
        """Test all environment variables can be overridden."""
        clean_env.setenv("KAFKA_BOOTSTRAP_SERVERS", "custom:9092")
        clean_env.setenv("KAFKA_ENABLE_INTELLIGENCE", "false")
        clean_env.setenv("KAFKA_REQUEST_TIMEOUT_MS", "3000")
        clean_env.setenv("KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS", "4000")
        clean_env.setenv("KAFKA_CODE_ANALYSIS_TIMEOUT_MS", "15000")
        clean_env.setenv("KAFKA_CONSUMER_GROUP_PREFIX", "custom-prefix")
        clean_env.setenv("ENABLE_EVENT_BASED_DISCOVERY", "no")
        clean_env.setenv("ENABLE_FILESYSTEM_FALLBACK", "yes")
        clean_env.setenv("PREFER_EVENT_PATTERNS", "false")

        config = IntelligenceConfig.from_env()

        assert config.kafka_bootstrap_servers == "custom:9092"
        assert config.kafka_enable_intelligence is False
        assert config.kafka_request_timeout_ms == 3000
        assert config.kafka_pattern_discovery_timeout_ms == 4000
        assert config.kafka_code_analysis_timeout_ms == 15000
        assert config.kafka_consumer_group_prefix == "custom-prefix"
        assert config.enable_event_based_discovery is False
        assert config.enable_filesystem_fallback is True
        assert config.prefer_event_patterns is False
