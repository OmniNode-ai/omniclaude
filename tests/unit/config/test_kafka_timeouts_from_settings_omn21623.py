# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Kafka publish and request timeouts come from Settings, not from literals (OMN-21623).

The contracts_and_di check refused ``KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0`` (three
copies) and ``request_timeout_ms=5000`` in the publishers and event clients. The values
are declared once on ``Settings`` and each caller reads them from there.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from omniclaude.config.settings import Settings
from omniclaude.lib import kafka_producer_utils, kafka_publisher_base
from omniclaude.lib.core import (
    action_event_publisher,
    intelligence_event_client,
    routing_event_client,
)

_ENV_KEY = "KAFKA_PUBLISH_TIMEOUT_SECONDS"


@pytest.mark.unit
class TestPublishTimeoutSetting:
    def test_default_is_declared_once_on_settings(self, monkeypatch) -> None:
        monkeypatch.delenv(_ENV_KEY, raising=False)
        assert Settings(_env_file=None).kafka_publish_timeout_seconds == 10.0

    def test_environment_overrides_default(self, monkeypatch) -> None:
        monkeypatch.setenv(_ENV_KEY, "25")
        assert Settings(_env_file=None).kafka_publish_timeout_seconds == 25.0

    @pytest.mark.parametrize("value", ["0.5", "301"])
    def test_out_of_range_value_is_refused(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(_ENV_KEY, value)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    @pytest.mark.parametrize(
        "module", [kafka_publisher_base, kafka_producer_utils, action_event_publisher]
    )
    def test_no_module_keeps_its_own_copy(self, module) -> None:
        assert not hasattr(module, "KAFKA_PUBLISH_TIMEOUT_SECONDS")

    @pytest.mark.asyncio
    async def test_publish_waits_for_the_settings_value(self) -> None:
        fake = MagicMock()
        fake.kafka_publish_timeout_seconds = 17.5
        producer = MagicMock()
        producer.send_and_wait = MagicMock(return_value=object())
        waited: dict[str, float] = {}

        async def fake_wait_for(awaitable, timeout):
            waited["timeout"] = timeout

        with (
            patch.object(kafka_publisher_base, "settings", fake),
            patch.object(
                kafka_publisher_base,
                "get_shared_producer",
                AsyncMock(return_value=producer),
            ),
            patch.object(kafka_publisher_base.asyncio, "wait_for", fake_wait_for),
        ):
            assert await kafka_publisher_base.publish_to_kafka("t", {}, "k") is True
        assert waited["timeout"] == 17.5


@pytest.mark.unit
class TestEventClientDefaultTimeout:
    @pytest.mark.parametrize(
        ("module", "client_cls"),
        [
            (routing_event_client, routing_event_client.RoutingEventClient),
            (
                intelligence_event_client,
                intelligence_event_client.IntelligenceEventClient,
            ),
        ],
    )
    def test_default_follows_settings_and_explicit_wins(
        self, module, client_cls
    ) -> None:
        fake = MagicMock()
        fake.get_effective_kafka_bootstrap_servers.return_value = "broker:9092"
        fake.request_timeout_ms = 7000
        with patch.object(module, "settings", fake):
            assert client_cls().request_timeout_ms == 7000
            assert client_cls(request_timeout_ms=1234).request_timeout_ms == 1234


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shared_producer_request_timeout_comes_from_settings() -> None:
    producer = MagicMock()
    producer.start = AsyncMock()
    aiokafka = MagicMock()
    aiokafka.AIOKafkaProducer.return_value = producer
    fake = MagicMock()
    fake.request_timeout_ms = 4321
    with (
        patch.dict(sys.modules, {"aiokafka": aiokafka}),
        patch.object(kafka_publisher_base, "settings", fake),
        patch.object(kafka_publisher_base, "_kafka_producer", None),
        patch.object(
            kafka_publisher_base, "get_kafka_bootstrap_servers", return_value="b:9092"
        ),
    ):
        await kafka_publisher_base.get_shared_producer()
    assert aiokafka.AIOKafkaProducer.call_args.kwargs["request_timeout_ms"] == 4321
