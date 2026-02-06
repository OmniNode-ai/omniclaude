"""Tests for omniclaude.publisher.config."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.publisher.publisher_config import PublisherConfig


class TestPublisherConfig:
    def test_minimal_valid_config(self) -> None:
        config = PublisherConfig(kafka_bootstrap_servers="localhost:9092")
        assert config.kafka_bootstrap_servers == "localhost:9092"
        assert config.kafka_client_id == "omniclaude-publisher"
        assert config.environment == "dev"
        assert config.max_memory_queue == 100

    def test_spool_dir_default(self) -> None:
        config = PublisherConfig(kafka_bootstrap_servers="localhost:9092")
        assert config.spool_dir == Path.home() / ".claude" / "event-spool"

    def test_socket_path_default(self) -> None:
        import tempfile

        config = PublisherConfig(kafka_bootstrap_servers="localhost:9092")
        assert (
            config.socket_path == Path(tempfile.gettempdir()) / "omniclaude-emit.sock"
        )

    def test_custom_values(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        config = PublisherConfig(
            kafka_bootstrap_servers="kafka1:9092,kafka2:9092",
            kafka_client_id="test-client",
            environment="staging",
            max_memory_queue=50,
            max_spool_messages=500,
            spool_dir=spool,
        )
        assert config.kafka_client_id == "test-client"
        assert config.environment == "staging"
        assert config.max_memory_queue == 50

    def test_bootstrap_servers_validation(self) -> None:
        # Missing port
        with pytest.raises(ValidationError):
            PublisherConfig(kafka_bootstrap_servers="localhost")

        # Invalid port
        with pytest.raises(ValidationError):
            PublisherConfig(kafka_bootstrap_servers="localhost:99999")

        # Empty
        with pytest.raises(ValidationError):
            PublisherConfig(kafka_bootstrap_servers="")

    def test_multi_broker_servers(self) -> None:
        config = PublisherConfig(
            kafka_bootstrap_servers="kafka1:9092,kafka2:9092,kafka3:9092"
        )
        assert "kafka1:9092" in config.kafka_bootstrap_servers

    def test_spool_limits_consistency(self) -> None:
        # max_spool_messages=0 but max_spool_bytes>0 -> error
        with pytest.raises(ValidationError):
            PublisherConfig(
                kafka_bootstrap_servers="localhost:9092",
                max_spool_messages=0,
                max_spool_bytes=1000,
            )

    def test_spooling_disabled(self) -> None:
        config = PublisherConfig(
            kafka_bootstrap_servers="localhost:9092",
            max_spool_messages=0,
            max_spool_bytes=0,
        )
        assert not config.spooling_enabled

    def test_spooling_enabled(self) -> None:
        config = PublisherConfig(kafka_bootstrap_servers="localhost:9092")
        assert config.spooling_enabled

    def test_frozen_config(self) -> None:
        config = PublisherConfig(kafka_bootstrap_servers="localhost:9092")
        with pytest.raises(ValidationError):
            config.kafka_bootstrap_servers = "new:9092"  # type: ignore[misc]

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OMNICLAUDE_PUBLISHER_KAFKA_BOOTSTRAP_SERVERS", "env-kafka:9092"
        )
        config = PublisherConfig()  # type: ignore[call-arg]
        assert config.kafka_bootstrap_servers == "env-kafka:9092"

    def test_environment_pattern_validation(self) -> None:
        # Valid
        PublisherConfig(kafka_bootstrap_servers="localhost:9092", environment="dev")
        PublisherConfig(kafka_bootstrap_servers="localhost:9092", environment="staging")
        # Invalid (uppercase)
        with pytest.raises(ValidationError):
            PublisherConfig(kafka_bootstrap_servers="localhost:9092", environment="DEV")
