# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for IntelligenceConfig fail-fast behavior.

These tests verify that IntelligenceConfig.from_env() properly enforces
the requirement that KAFKA_BOOTSTRAP_SERVERS must be configured in the
environment, following fail-fast principles.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


class TestIntelligenceConfigFromEnv:
    """Tests for IntelligenceConfig.from_env() factory method."""

    def test_from_env_raises_when_kafka_not_configured(self) -> None:
        """Test that from_env() raises ValueError when KAFKA_BOOTSTRAP_SERVERS is not set.

        The from_env() method follows fail-fast principles: if KAFKA_BOOTSTRAP_SERVERS
        is not configured in the environment, it should raise a clear error rather
        than silently using defaults. This ensures .env is the single source of truth.
        """
        # Mock settings to return empty bootstrap servers
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = ""
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "dev"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            # Import after patching to get the patched version
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            with pytest.raises(ValueError) as exc_info:
                IntelligenceConfig.from_env()

            # Verify the error message is helpful and mentions the config key
            error_message = str(exc_info.value)
            assert "KAFKA_BOOTSTRAP_SERVERS" in error_message
            assert "not configured" in error_message

    def test_from_env_raises_when_kafka_is_none(self) -> None:
        """Test that from_env() raises ValueError when bootstrap servers returns None."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = None
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "dev"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            with pytest.raises(ValueError) as exc_info:
                IntelligenceConfig.from_env()

            assert "KAFKA_BOOTSTRAP_SERVERS" in str(exc_info.value)

    def test_from_env_raises_when_kafka_is_whitespace_only(self) -> None:
        """Test that from_env() raises ValueError when bootstrap servers is whitespace."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = "   "
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "dev"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            # Whitespace-only string is falsy when stripped, but non-empty
            # The from_env checks "if not bootstrap_servers:" which handles empty string
            # But whitespace passes that check, then validator catches it
            with pytest.raises(ValueError):
                IntelligenceConfig.from_env()

    def test_from_env_succeeds_when_kafka_configured(self) -> None:
        """Test that from_env() succeeds when KAFKA_BOOTSTRAP_SERVERS is properly set."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
            "localhost:9092"
        )
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "dev"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            # Should not raise
            config = IntelligenceConfig.from_env()

            # Verify config was created with correct values
            assert config.kafka_bootstrap_servers == "localhost:9092"
            assert config.kafka_enable_intelligence is True
            assert config.kafka_request_timeout_ms == 5000

    def test_from_env_error_message_includes_guidance(self) -> None:
        """Test that the error message includes helpful guidance for the user."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = ""

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            with pytest.raises(ValueError) as exc_info:
                IntelligenceConfig.from_env()

            error_message = str(exc_info.value)
            # Error should mention .env file as the source of truth
            assert ".env" in error_message
            # Error should provide an example value
            assert "Example" in error_message or "localhost:9092" in error_message


class TestIntelligenceConfigValidation:
    """Tests for IntelligenceConfig validation."""

    def test_bootstrap_servers_cannot_be_empty(self) -> None:
        """Test that kafka_bootstrap_servers field rejects empty string."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="")

        assert "cannot be empty" in str(exc_info.value)

    def test_direct_instantiation_error_includes_guidance(self) -> None:
        """Test that direct instantiation without args provides helpful guidance.

        When users call IntelligenceConfig() without arguments, the error message
        should guide them to use from_env() or provide explicit parameters.
        """
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig()

        error_message = str(exc_info.value)
        # Error should mention from_env() as an alternative
        assert "from_env()" in error_message
        # Error should provide an example with explicit parameter
        assert "kafka_bootstrap_servers" in error_message
        assert "Example" in error_message

    def test_bootstrap_servers_requires_host_port_format(self) -> None:
        """Test that kafka_bootstrap_servers validates host:port format."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="invalid-no-port")

        assert "Expected 'host:port'" in str(exc_info.value)

    def test_bootstrap_servers_validates_port_number(self) -> None:
        """Test that kafka_bootstrap_servers validates port is a number."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="localhost:notaport")

        assert "Invalid port" in str(exc_info.value)

    def test_bootstrap_servers_validates_port_range(self) -> None:
        """Test that kafka_bootstrap_servers validates port is in valid range."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="localhost:99999")

        assert "out of valid range" in str(exc_info.value)

    def test_bootstrap_servers_accepts_valid_format(self) -> None:
        """Test that kafka_bootstrap_servers accepts valid host:port."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")
        assert config.kafka_bootstrap_servers == "localhost:9092"

    def test_bootstrap_servers_accepts_multiple_brokers(self) -> None:
        """Test that kafka_bootstrap_servers accepts comma-separated brokers."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="broker1:9092,broker2:9092,broker3:9092"
        )
        assert (
            config.kafka_bootstrap_servers == "broker1:9092,broker2:9092,broker3:9092"
        )

    def test_bootstrap_servers_port_boundary_lower(self) -> None:
        """Test that port 1 is accepted (lowest valid port)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:1")
        assert config.kafka_bootstrap_servers == "localhost:1"

    def test_bootstrap_servers_port_boundary_upper(self) -> None:
        """Test that port 65535 is accepted (highest valid port)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:65535")
        assert config.kafka_bootstrap_servers == "localhost:65535"

    def test_bootstrap_servers_port_zero_rejected(self) -> None:
        """Test that port 0 is rejected as invalid."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="localhost:0")

        assert "out of valid range" in str(exc_info.value)

    def test_bootstrap_servers_port_too_high_rejected(self) -> None:
        """Test that port 65536 is rejected as out of range."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="localhost:65536")

        assert "out of valid range" in str(exc_info.value)

    def test_bootstrap_servers_empty_host_rejected(self) -> None:
        """Test that empty host in host:port format is rejected."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers=":9092")

        assert "Expected 'host:port'" in str(exc_info.value)

    def test_bootstrap_servers_empty_port_rejected(self) -> None:
        """Test that empty port in host:port format is rejected."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="localhost:")

        assert "Invalid port" in str(exc_info.value) or "Expected 'host:port'" in str(
            exc_info.value
        )

    def test_bootstrap_servers_with_spaces_around_brokers(self) -> None:
        """Test that spaces around broker addresses are handled correctly."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        # Spaces around brokers should be trimmed during validation
        config = IntelligenceConfig(
            kafka_bootstrap_servers="  broker1:9092 , broker2:9093  "
        )
        assert config.kafka_bootstrap_servers == "  broker1:9092 , broker2:9093  "

    def test_bootstrap_servers_ipv4_address(self) -> None:
        """Test that IPv4 addresses are accepted."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="192.168.1.100:9092")  # onex-allow-internal-ip
        assert config.kafka_bootstrap_servers == "192.168.1.100:9092"  # onex-allow-internal-ip

    def test_bootstrap_servers_one_invalid_in_list_fails(self) -> None:
        """Test that validation fails if any broker in list is invalid."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="broker1:9092,invalid-no-port,broker3:9092"
            )

        assert "Expected 'host:port'" in str(exc_info.value)


class TestConsumerGroupPrefixValidation:
    """Tests for kafka_consumer_group_prefix validation."""

    def test_consumer_group_prefix_cannot_be_empty(self) -> None:
        """Test that kafka_consumer_group_prefix rejects empty string."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_consumer_group_prefix="",
            )

        assert "cannot be empty" in str(exc_info.value)

    def test_consumer_group_prefix_cannot_be_whitespace(self) -> None:
        """Test that kafka_consumer_group_prefix rejects whitespace-only string."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_consumer_group_prefix="   ",
            )

        assert "cannot be empty" in str(exc_info.value)

    def test_consumer_group_prefix_strips_whitespace(self) -> None:
        """Test that kafka_consumer_group_prefix strips surrounding whitespace."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_consumer_group_prefix="  my-group  ",
        )
        assert config.kafka_consumer_group_prefix == "my-group"

    def test_consumer_group_prefix_accepts_valid_value(self) -> None:
        """Test that kafka_consumer_group_prefix accepts valid values."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_consumer_group_prefix="omniclaude-intelligence",
        )
        assert config.kafka_consumer_group_prefix == "omniclaude-intelligence"

    def test_consumer_group_prefix_accepts_special_characters(self) -> None:
        """Test that kafka_consumer_group_prefix accepts special characters."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_consumer_group_prefix="my_group-v1.0",
        )
        assert config.kafka_consumer_group_prefix == "my_group-v1.0"


class TestCanonicalTopicConstants:
    """GAP-1 regression tests: verify intelligence_config.py topic constants (OMN-2367)."""

    def test_topic_requested_constant_uses_onex_cmd_prefix(self) -> None:
        """TOPIC_CODE_ANALYSIS_REQUESTED must use onex.cmd namespace (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import (
            TOPIC_CODE_ANALYSIS_REQUESTED,
        )

        assert TOPIC_CODE_ANALYSIS_REQUESTED.startswith("onex.cmd.")

    def test_topic_requested_constant_exact_value(self) -> None:
        """TOPIC_CODE_ANALYSIS_REQUESTED must match canonical omniintelligence topic (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import (
            TOPIC_CODE_ANALYSIS_REQUESTED,
        )

        assert (
            TOPIC_CODE_ANALYSIS_REQUESTED
            == "onex.cmd.omniintelligence.code-analysis.v1"
        )

    def test_topic_completed_constant_uses_onex_evt_prefix(self) -> None:
        """TOPIC_CODE_ANALYSIS_COMPLETED must use onex.evt namespace (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import (
            TOPIC_CODE_ANALYSIS_COMPLETED,
        )

        assert TOPIC_CODE_ANALYSIS_COMPLETED.startswith("onex.evt.")

    def test_topic_completed_constant_exact_value(self) -> None:
        """TOPIC_CODE_ANALYSIS_COMPLETED must match canonical omniintelligence topic (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import (
            TOPIC_CODE_ANALYSIS_COMPLETED,
        )

        assert (
            TOPIC_CODE_ANALYSIS_COMPLETED
            == "onex.evt.omniintelligence.code-analysis-completed.v1"
        )

    def test_topic_failed_constant_uses_onex_evt_prefix(self) -> None:
        """TOPIC_CODE_ANALYSIS_FAILED must use onex.evt namespace (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import TOPIC_CODE_ANALYSIS_FAILED

        assert TOPIC_CODE_ANALYSIS_FAILED.startswith("onex.evt.")

    def test_topic_failed_constant_exact_value(self) -> None:
        """TOPIC_CODE_ANALYSIS_FAILED must match canonical omniintelligence topic (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import TOPIC_CODE_ANALYSIS_FAILED

        assert (
            TOPIC_CODE_ANALYSIS_FAILED
            == "onex.evt.omniintelligence.code-analysis-failed.v1"
        )

    def test_config_topic_fields_use_canonical_values(self) -> None:
        """IntelligenceConfig fields must reflect canonical topic constants (OMN-2367)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")

        assert (
            config.topic_code_analysis_requested
            == "onex.cmd.omniintelligence.code-analysis.v1"
        )
        assert (
            config.topic_code_analysis_completed
            == "onex.evt.omniintelligence.code-analysis-completed.v1"
        )
        assert (
            config.topic_code_analysis_failed
            == "onex.evt.omniintelligence.code-analysis-failed.v1"
        )


class TestDynamicTopicNameBuilding:
    """Tests for build_dynamic_topic_names model validator."""

    def test_topic_names_built_without_prefix(self) -> None:
        """Test that topic names are wire-ready without environment prefix (OMN-1972)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")

        # Topics should NOT have any environment prefix (OMN-1972)
        # Request topic uses onex.cmd (no "requested" suffix per OMN-2367)
        assert not config.topic_code_analysis_requested.startswith("dev.")
        assert (
            config.topic_code_analysis_requested
            == "onex.cmd.omniintelligence.code-analysis.v1"
        )
        assert not config.topic_code_analysis_completed.startswith("dev.")
        assert "code-analysis-completed" in config.topic_code_analysis_completed
        assert not config.topic_code_analysis_failed.startswith("dev.")
        assert "code-analysis-failed" in config.topic_code_analysis_failed

    def test_topic_names_ignore_environment(self) -> None:
        """Test that kafka_environment does not affect topic names (OMN-1972)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="staging",
        )

        # Topics should NOT have staging prefix
        assert not config.topic_code_analysis_requested.startswith("staging.")
        assert not config.topic_code_analysis_completed.startswith("staging.")
        assert not config.topic_code_analysis_failed.startswith("staging.")

    def test_topic_names_consistent_across_environments(self) -> None:
        """Test that topic names are the same regardless of environment."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config_dev = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="dev",
        )
        config_prod = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="prod",
        )

        assert (
            config_dev.topic_code_analysis_requested
            == config_prod.topic_code_analysis_requested
        )
        assert (
            config_dev.topic_code_analysis_completed
            == config_prod.topic_code_analysis_completed
        )
        assert (
            config_dev.topic_code_analysis_failed
            == config_prod.topic_code_analysis_failed
        )

    def test_explicit_topic_names_preserved(self) -> None:
        """Test that explicitly provided topic names are not overwritten."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        custom_topic = "custom.my-topic.v1"
        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            topic_code_analysis_requested=custom_topic,
        )

        # Custom topic should be preserved
        assert config.topic_code_analysis_requested == custom_topic
        # Other topics should still be built from constants
        assert "code-analysis-completed" in config.topic_code_analysis_completed

    def test_all_explicit_topics_preserved(self) -> None:
        """Test that all explicitly provided topics are preserved."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            topic_code_analysis_requested="custom.requested.v1",
            topic_code_analysis_completed="custom.completed.v1",
            topic_code_analysis_failed="custom.failed.v1",
        )

        assert config.topic_code_analysis_requested == "custom.requested.v1"
        assert config.topic_code_analysis_completed == "custom.completed.v1"
        assert config.topic_code_analysis_failed == "custom.failed.v1"


class TestValidateConfigMethod:
    """Tests for the validate_config() method."""

    def test_validate_config_succeeds_with_defaults(self) -> None:
        """Test that validate_config() succeeds with valid default configuration."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")

        # Should not raise
        config.validate_config()

    def test_validate_config_fails_when_both_sources_disabled(self) -> None:
        """Test that validate_config() fails if both intelligence sources are disabled."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            enable_event_based_discovery=False,
            enable_filesystem_fallback=False,
        )

        with pytest.raises(ValueError) as exc_info:
            config.validate_config()

        error_msg = str(exc_info.value)
        assert "At least one intelligence source must be enabled" in error_msg

    def test_validate_config_succeeds_with_only_event_discovery(self) -> None:
        """Test that validate_config() succeeds with only event discovery enabled."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            enable_event_based_discovery=True,
            enable_filesystem_fallback=False,
        )

        # Should not raise
        config.validate_config()

    def test_validate_config_succeeds_with_only_filesystem_fallback(self) -> None:
        """Test that validate_config() succeeds with only filesystem fallback enabled."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            enable_event_based_discovery=False,
            enable_filesystem_fallback=True,
        )

        # Should not raise
        config.validate_config()

    def test_validate_config_fails_with_empty_requested_topic(self) -> None:
        """Test that validate_config() fails if topic_code_analysis_requested is empty."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        # Create config and then manually set topic to empty
        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")
        # We need to bypass Pydantic's frozen model - use model_construct for testing
        config_dict = config.model_dump()
        config_dict["topic_code_analysis_requested"] = ""
        # Create new instance with modified data
        test_config = IntelligenceConfig.model_construct(**config_dict)

        with pytest.raises(ValueError) as exc_info:
            test_config.validate_config()

        assert "topic_code_analysis_requested cannot be empty" in str(exc_info.value)

    def test_validate_config_fails_with_whitespace_topic(self) -> None:
        """Test that validate_config() fails if topic names are whitespace-only."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")
        config_dict = config.model_dump()
        config_dict["topic_code_analysis_completed"] = "   "
        test_config = IntelligenceConfig.model_construct(**config_dict)

        with pytest.raises(ValueError) as exc_info:
            test_config.validate_config()

        assert "topic_code_analysis_completed cannot be empty" in str(exc_info.value)


class TestUtilityMethods:
    """Tests for utility methods on IntelligenceConfig."""

    def test_is_event_discovery_enabled_both_true(self) -> None:
        """Test is_event_discovery_enabled returns True when both flags are True."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_enable_intelligence=True,
            enable_event_based_discovery=True,
        )

        assert config.is_event_discovery_enabled() is True

    def test_is_event_discovery_enabled_kafka_disabled(self) -> None:
        """Test is_event_discovery_enabled returns False when kafka is disabled."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_enable_intelligence=False,
            enable_event_based_discovery=True,
        )

        assert config.is_event_discovery_enabled() is False

    def test_is_event_discovery_enabled_discovery_disabled(self) -> None:
        """Test is_event_discovery_enabled returns False when discovery is disabled."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_enable_intelligence=True,
            enable_event_based_discovery=False,
        )

        assert config.is_event_discovery_enabled() is False

    def test_is_event_discovery_enabled_both_false(self) -> None:
        """Test is_event_discovery_enabled returns False when both are False."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_enable_intelligence=False,
            enable_event_based_discovery=False,
        )

        assert config.is_event_discovery_enabled() is False

    def test_get_bootstrap_servers(self) -> None:
        """Test get_bootstrap_servers returns configured value."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="broker1:9092,broker2:9093")

        assert config.get_bootstrap_servers() == "broker1:9092,broker2:9093"

    def test_to_dict_returns_all_fields(self) -> None:
        """Test to_dict returns dictionary with all configuration fields."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_enable_intelligence=True,
            kafka_environment="dev",
        )

        result = config.to_dict()

        assert isinstance(result, dict)
        assert result["kafka_bootstrap_servers"] == "localhost:9092"
        assert result["kafka_enable_intelligence"] is True
        assert result["kafka_environment"] == "dev"
        assert "topic_code_analysis_requested" in result
        assert "topic_code_analysis_completed" in result
        assert "topic_code_analysis_failed" in result

    def test_to_dict_matches_model_dump(self) -> None:
        """Test to_dict returns same result as model_dump."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(kafka_bootstrap_servers="localhost:9092")

        assert config.to_dict() == config.model_dump()


class TestFieldConstraints:
    """Tests for field constraint validation (ge/le bounds)."""

    def test_request_timeout_minimum_bound(self) -> None:
        """Test that kafka_request_timeout_ms enforces minimum of 1000ms."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_request_timeout_ms=999,
            )

        assert "greater than or equal to 1000" in str(exc_info.value)

    def test_request_timeout_maximum_bound(self) -> None:
        """Test that kafka_request_timeout_ms enforces maximum of 60000ms."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_request_timeout_ms=60001,
            )

        assert "less than or equal to 60000" in str(exc_info.value)

    def test_request_timeout_at_minimum(self) -> None:
        """Test that kafka_request_timeout_ms accepts minimum value."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_request_timeout_ms=1000,
        )
        assert config.kafka_request_timeout_ms == 1000

    def test_request_timeout_at_maximum(self) -> None:
        """Test that kafka_request_timeout_ms accepts maximum value."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_request_timeout_ms=60000,
        )
        assert config.kafka_request_timeout_ms == 60000

    def test_pattern_discovery_timeout_minimum_bound(self) -> None:
        """Test that kafka_pattern_discovery_timeout_ms enforces minimum."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_pattern_discovery_timeout_ms=500,
            )

        assert "greater than or equal to 1000" in str(exc_info.value)

    def test_pattern_discovery_timeout_maximum_bound(self) -> None:
        """Test that kafka_pattern_discovery_timeout_ms enforces maximum."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_pattern_discovery_timeout_ms=60001,
            )

        assert "less than or equal to 60000" in str(exc_info.value)

    def test_code_analysis_timeout_minimum_bound(self) -> None:
        """Test that kafka_code_analysis_timeout_ms enforces minimum."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_code_analysis_timeout_ms=500,
            )

        assert "greater than or equal to 1000" in str(exc_info.value)

    def test_code_analysis_timeout_maximum_bound(self) -> None:
        """Test that kafka_code_analysis_timeout_ms enforces maximum of 120000ms."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_code_analysis_timeout_ms=120001,
            )

        assert "less than or equal to 120000" in str(exc_info.value)

    def test_code_analysis_timeout_at_maximum(self) -> None:
        """Test that kafka_code_analysis_timeout_ms accepts maximum value."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_code_analysis_timeout_ms=120000,
        )
        assert config.kafka_code_analysis_timeout_ms == 120000


class TestFromEnvTopicConstruction:
    """Tests for from_env() topic name construction."""

    def test_from_env_builds_topic_names_without_prefix(self) -> None:
        """Test that from_env() builds topic names without environment prefix (OMN-1972)."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
            "localhost:9092"
        )
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "staging"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            config = IntelligenceConfig.from_env()

            # Topics should NOT have environment prefix (OMN-1972)
            # Request topic uses onex.cmd (no "requested" suffix per OMN-2367)
            assert not config.topic_code_analysis_requested.startswith("staging.")
            assert (
                config.topic_code_analysis_requested
                == "onex.cmd.omniintelligence.code-analysis.v1"
            )
            assert "code-analysis-completed" in config.topic_code_analysis_completed
            assert "code-analysis-failed" in config.topic_code_analysis_failed

    def test_from_env_uses_settings_values(self) -> None:
        """Test that from_env() correctly maps all settings values."""
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
            "broker1:9092"
        )
        mock_settings.use_event_routing = False
        mock_settings.request_timeout_ms = 10000
        mock_settings.kafka_group_id = "custom-group"
        mock_settings.kafka_environment = "prod"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            config = IntelligenceConfig.from_env()

            assert config.kafka_bootstrap_servers == "broker1:9092"
            assert config.kafka_enable_intelligence is False
            assert config.kafka_request_timeout_ms == 10000
            assert config.kafka_pattern_discovery_timeout_ms == 10000
            assert config.kafka_code_analysis_timeout_ms == 20000  # 2x timeout
            assert config.kafka_consumer_group_prefix == "custom-group"
            assert config.kafka_environment == "prod"
            assert config.enable_event_based_discovery is False


class TestKafkaEnvironmentValidation:
    """Tests for kafka_environment validation to prevent malformed topic names."""

    def test_from_env_accepts_empty_kafka_environment(self) -> None:
        """Test that from_env() accepts empty KAFKA_ENVIRONMENT (OMN-1972).

        kafka_environment is metadata only — not used for topic prefixing.
        """
        mock_settings = MagicMock()
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
            "localhost:9092"
        )
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = ""

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            config = IntelligenceConfig.from_env()
            # Topics should still be populated from constants (OMN-2367 canonical values)
            assert (
                config.topic_code_analysis_requested
                == "onex.cmd.omniintelligence.code-analysis.v1"
            )

    def test_direct_instantiation_accepts_empty_environment(self) -> None:
        """Test that direct instantiation accepts empty kafka_environment (OMN-1972)."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="",
        )
        # Topics should still be populated (OMN-2367 canonical values)
        assert (
            config.topic_code_analysis_requested
            == "onex.cmd.omniintelligence.code-analysis.v1"
        )

    def test_kafka_environment_normalizes_uppercase(self) -> None:
        """Test that kafka_environment normalizes to lowercase."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        # Uppercase should be normalized to lowercase before validation
        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="DEV",
        )
        # Should be normalized to lowercase
        assert config.kafka_environment == "dev"

    def test_kafka_environment_accepts_valid_values(self) -> None:
        """Test that kafka_environment accepts standard valid values."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        for env in ["dev", "staging", "prod", "test", "local"]:
            config = IntelligenceConfig(
                kafka_bootstrap_servers="localhost:9092",
                kafka_environment=env,
            )
            assert config.kafka_environment == env

    def test_kafka_environment_accepts_hyphenated_values(self) -> None:
        """Test that kafka_environment accepts hyphenated environment names."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="dev-us-east-1",
        )
        assert config.kafka_environment == "dev-us-east-1"

    def test_topic_names_have_no_environment_prefix(self) -> None:
        """Test that topic names have no environment prefix regardless of kafka_environment."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        config = IntelligenceConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_environment="staging",
        )

        # Topics should NOT start with environment prefix
        assert not config.topic_code_analysis_requested.startswith("staging.")
        assert not config.topic_code_analysis_requested.startswith(".")


class TestDualPublishLegacyTopicsSettings:
    """Tests for dual_publish_legacy_topics Settings field env-var binding."""

    def test_dual_publish_legacy_topics_defaults_false(self) -> None:
        """dual_publish_legacy_topics defaults to False when env var is absent."""
        from omniclaude.config.settings import Settings

        with patch.dict("os.environ", {}, clear=False):
            s = Settings(kafka_bootstrap_servers="localhost:9092")
        assert s.dual_publish_legacy_topics is False

    def test_dual_publish_legacy_topics_reads_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dual_publish_legacy_topics is True when DUAL_PUBLISH_LEGACY_TOPICS=1."""
        from omniclaude.config.settings import Settings

        monkeypatch.setenv("DUAL_PUBLISH_LEGACY_TOPICS", "1")
        s = Settings(kafka_bootstrap_servers="localhost:9092")
        assert s.dual_publish_legacy_topics is True

    def test_dual_publish_legacy_topics_accepts_true_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dual_publish_legacy_topics accepts 'true' (Pydantic bool coercion)."""
        from omniclaude.config.settings import Settings

        monkeypatch.setenv("DUAL_PUBLISH_LEGACY_TOPICS", "true")
        s = Settings(kafka_bootstrap_servers="localhost:9092")
        assert s.dual_publish_legacy_topics is True
