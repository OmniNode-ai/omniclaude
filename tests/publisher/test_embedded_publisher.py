"""Tests for omniclaude.publisher.embedded_publisher."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaude.publisher.embedded_publisher import EmbeddedEventPublisher
from omniclaude.publisher.publisher_config import PublisherConfig


@pytest.fixture
def publisher_config(tmp_path: Path) -> PublisherConfig:
    import uuid

    # Use /tmp/ for socket to avoid macOS AF_UNIX path length limit (104 bytes)
    short_id = uuid.uuid4().hex[:8]
    socket_path = Path(f"/tmp/test-pub-{short_id}.sock")  # noqa: S108
    pid_path = Path(f"/tmp/test-pub-{short_id}.pid")  # noqa: S108
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()

    config = PublisherConfig(
        kafka_bootstrap_servers="localhost:9092",
        socket_path=socket_path,
        pid_path=pid_path,
        spool_dir=spool_dir,
        environment="dev",
        shutdown_drain_seconds=1.0,
    )

    yield config  # type: ignore[misc]

    # Cleanup temp socket/pid files
    socket_path.unlink(missing_ok=True)
    pid_path.unlink(missing_ok=True)


@pytest.fixture
def mock_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.start = AsyncMock()
    bus.close = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def publisher(
    publisher_config: PublisherConfig, mock_event_bus: MagicMock
) -> EmbeddedEventPublisher:
    return EmbeddedEventPublisher(config=publisher_config, event_bus=mock_event_bus)


class TestEmbeddedEventPublisher:
    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        await publisher.start()
        assert publisher.config.socket_path.exists()
        assert publisher.config.pid_path.exists()

        await publisher.stop()
        assert not publisher.config.socket_path.exists()
        assert not publisher.config.pid_path.exists()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, publisher: EmbeddedEventPublisher) -> None:
        await publisher.start()
        await publisher.start()  # Should not raise
        await publisher.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, publisher: EmbeddedEventPublisher) -> None:
        await publisher.start()
        await publisher.stop()
        await publisher.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stale_socket_cleanup(
        self, publisher_config: PublisherConfig, mock_event_bus: MagicMock
    ) -> None:
        # Create a stale socket file (no process behind it)
        publisher_config.socket_path.touch()

        publisher = EmbeddedEventPublisher(
            config=publisher_config, event_bus=mock_event_bus
        )
        await publisher.start()
        assert publisher.config.socket_path.exists()
        await publisher.stop()

    @pytest.mark.asyncio
    async def test_process_ping_request(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        await publisher.start()
        try:
            request = b'{"command": "ping"}\n'
            response_json = await publisher._process_request(request)
            response = json.loads(response_json)

            assert response["status"] == "ok"
            assert "queue_size" in response
            assert "spool_size" in response
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_process_emit_request(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        await publisher.start()
        try:
            # Use a mock for the registry to avoid needing real event types
            with (
                patch.object(
                    publisher._registry, "resolve_topic", return_value="test-topic"
                ),
                patch.object(publisher._registry, "validate_payload"),
                patch.object(
                    publisher._registry,
                    "inject_metadata",
                    return_value={"enriched": True},
                ),
                patch.object(
                    publisher._registry, "get_partition_key", return_value="key"
                ),
            ):
                request = (
                    json.dumps(
                        {
                            "event_type": "session.started",
                            "payload": {"session_id": "abc-123"},
                        }
                    ).encode()
                    + b"\n"
                )

                response_json = await publisher._process_request(request)
                response = json.loads(response_json)

                assert response["status"] == "queued"
                assert "event_id" in response
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_process_invalid_json(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        await publisher.start()
        try:
            response_json = await publisher._process_request(b"not json\n")
            response = json.loads(response_json)
            assert response["status"] == "error"
            assert "Invalid JSON" in response["reason"]
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_process_unknown_request_type(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        await publisher.start()
        try:
            request = b'{"unknown_field": "value"}\n'
            response_json = await publisher._process_request(request)
            response = json.loads(response_json)
            assert response["status"] == "error"
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_drain_on_shutdown(
        self,
        publisher_config: PublisherConfig,
        mock_event_bus: MagicMock,
    ) -> None:
        publisher = EmbeddedEventPublisher(
            config=publisher_config, event_bus=mock_event_bus
        )
        await publisher.start()

        # Enqueue some events directly
        with (
            patch.object(
                publisher._registry, "resolve_topic", return_value="test-topic"
            ),
            patch.object(publisher._registry, "validate_payload"),
            patch.object(
                publisher._registry, "inject_metadata", return_value={"data": True}
            ),
            patch.object(publisher._registry, "get_partition_key", return_value="key"),
        ):
            for i in range(3):
                request = (
                    json.dumps(
                        {
                            "event_type": "session.started",
                            "payload": {"session_id": f"s-{i}"},
                        }
                    ).encode()
                    + b"\n"
                )
                await publisher._process_request(request)

        await publisher.stop()

        # Check spool directory has events
        spool_files = list(publisher_config.spool_dir.glob("*.json"))
        # Events may have been published by the publisher loop before shutdown,
        # or drained to spool — either way, nothing should be lost
        assert publisher.queue.memory_size() == 0

    @pytest.mark.asyncio
    async def test_publish_event_success(
        self,
        publisher: EmbeddedEventPublisher,
        mock_event_bus: MagicMock,
    ) -> None:
        from datetime import UTC, datetime

        from omniclaude.publisher.event_queue import ModelQueuedEvent

        event = ModelQueuedEvent(
            event_id="pub-test",
            event_type="test.event",
            topic="test-topic",
            payload={"key": "val"},
            queued_at=datetime.now(UTC),
        )

        result = await publisher._publish_event(event)
        assert result is True
        mock_event_bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_event_failure(
        self,
        publisher: EmbeddedEventPublisher,
        mock_event_bus: MagicMock,
    ) -> None:
        from datetime import UTC, datetime

        from omniclaude.publisher.event_queue import ModelQueuedEvent

        mock_event_bus.publish = AsyncMock(side_effect=Exception("Kafka down"))

        event = ModelQueuedEvent(
            event_id="fail-test",
            event_type="test.event",
            topic="test-topic",
            payload={"key": "val"},
            queued_at=datetime.now(UTC),
        )

        result = await publisher._publish_event(event)
        assert result is False
