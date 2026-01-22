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
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = "192.168.86.200:29092"
        mock_settings.use_event_routing = True
        mock_settings.request_timeout_ms = 5000
        mock_settings.kafka_group_id = "test-group"
        mock_settings.kafka_environment = "dev"

        with patch("omniclaude.lib.config.intelligence_config.settings", mock_settings):
            from omniclaude.lib.config.intelligence_config import IntelligenceConfig

            # Should not raise
            config = IntelligenceConfig.from_env()

            # Verify config was created with correct values
            assert config.kafka_bootstrap_servers == "192.168.86.200:29092"
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
            assert "Example" in error_message or "192.168.86.200:29092" in error_message


class TestIntelligenceConfigValidation:
    """Tests for IntelligenceConfig validation."""

    def test_bootstrap_servers_cannot_be_empty(self) -> None:
        """Test that kafka_bootstrap_servers field rejects empty string."""
        from omniclaude.lib.config.intelligence_config import IntelligenceConfig

        with pytest.raises(ValueError) as exc_info:
            IntelligenceConfig(kafka_bootstrap_servers="")

        assert "cannot be empty" in str(exc_info.value)

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
        assert config.kafka_bootstrap_servers == "broker1:9092,broker2:9092,broker3:9092"
