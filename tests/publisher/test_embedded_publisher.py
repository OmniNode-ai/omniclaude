"""Tests for omniclaude.publisher.embedded_publisher."""

from __future__ import annotations

import asyncio
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

        # Check spool directory for events
        spool_files = list(publisher_config.spool_dir.glob("*.json"))
        # Events may have been published by the publisher loop before shutdown,
        # or drained to spool — either way, nothing should be lost
        assert publisher.queue.memory_size() == 0
        # Verify events were either published or spooled (not silently lost)
        assert mock_event_bus.publish.await_count + len(spool_files) >= 3

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

    @pytest.mark.asyncio
    async def test_publisher_loop_retries_then_drops(
        self,
        publisher_config: PublisherConfig,
        mock_event_bus: MagicMock,
    ) -> None:
        """Verify the publisher loop retries failed events and drops after max retries."""
        from datetime import UTC, datetime

        from omniclaude.publisher.event_queue import ModelQueuedEvent

        # Make publish always fail
        mock_event_bus.publish = AsyncMock(side_effect=Exception("Kafka down"))

        publisher = EmbeddedEventPublisher(
            config=publisher_config, event_bus=mock_event_bus
        )

        # Enqueue a single event directly
        event = ModelQueuedEvent(
            event_id="retry-test",
            event_type="test.event",
            topic="test-topic",
            payload={"key": "val"},
            queued_at=datetime.now(UTC),
        )
        await publisher.queue.enqueue(event)
        assert publisher.queue.total_size() == 1

        # Save real sleep before patching — the patch replaces asyncio.sleep
        # on the shared module object, so we need a direct reference to the
        # original function for the test's own event-loop yields.
        real_sleep = asyncio.sleep

        async def mock_sleep(_seconds: float) -> None:
            """Mock that still yields to event loop (zero real delay)."""
            await real_sleep(0)

        with patch(
            "omniclaude.publisher.embedded_publisher.asyncio.sleep",
            side_effect=mock_sleep,
        ):
            publisher._running = True
            publisher._shutdown_event = asyncio.Event()

            loop_task = asyncio.create_task(publisher._publisher_loop())

            # Yield to event loop repeatedly so the publisher loop can run
            # through all retry attempts (max_retry_attempts defaults to 3)
            for _ in range(50):
                await real_sleep(0)

            publisher._running = False
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # Event should have been dropped after max retries
        assert "retry-test" not in publisher._retry_counts
        # Verify publish was actually attempted (at least max_retry_attempts times)
        assert mock_event_bus.publish.await_count >= publisher_config.max_retry_attempts

    @pytest.mark.asyncio
    async def test_oversized_payload_rejected(
        self, publisher: EmbeddedEventPublisher
    ) -> None:
        """Verify that payloads exceeding max_payload_bytes after enrichment are rejected."""
        await publisher.start()
        try:
            # inject_metadata returns a payload that exceeds max_payload_bytes
            oversized = {"data": "x" * (publisher.config.max_payload_bytes + 1)}
            with (
                patch.object(
                    publisher._registry, "resolve_topic", return_value="test-topic"
                ),
                patch.object(publisher._registry, "validate_payload"),
                patch.object(
                    publisher._registry,
                    "inject_metadata",
                    return_value=oversized,
                ),
            ):
                request = (
                    json.dumps(
                        {
                            "event_type": "session.started",
                            "payload": {"session_id": "abc"},
                        }
                    ).encode()
                    + b"\n"
                )
                response_json = await publisher._process_request(request)
                response = json.loads(response_json)

                assert response["status"] == "error"
                assert "maximum size" in response["reason"]
        finally:
            await publisher.stop()

    @pytest.mark.asyncio
    async def test_stale_socket_cleanup_with_dead_pid(
        self, publisher_config: PublisherConfig, mock_event_bus: MagicMock
    ) -> None:
        """Test cleanup when PID file exists but referenced process is dead."""
        # Create stale socket and PID file pointing to a dead process
        publisher_config.socket_path.touch()
        publisher_config.pid_path.parent.mkdir(parents=True, exist_ok=True)
        publisher_config.pid_path.write_text("12345")

        publisher = EmbeddedEventPublisher(
            config=publisher_config, event_bus=mock_event_bus
        )

        # Mock os.kill to simulate dead process (ProcessLookupError)
        with patch(
            "omniclaude.publisher.embedded_publisher.os.kill",
            side_effect=ProcessLookupError("No such process"),
        ):
            # _check_stale_socket should detect dead process via ProcessLookupError
            assert publisher._check_stale_socket() is True

            # Publisher should start successfully after stale cleanup
            await publisher.start()

        assert publisher.config.socket_path.exists()
        await publisher.stop()

    @pytest.mark.asyncio
    async def test_stale_socket_live_process_permission_error(
        self, publisher_config: PublisherConfig, mock_event_bus: MagicMock
    ) -> None:
        """Test that PermissionError (live process, different user) is not treated as stale."""
        publisher_config.pid_path.parent.mkdir(parents=True, exist_ok=True)
        publisher_config.pid_path.write_text("12345")

        publisher = EmbeddedEventPublisher(
            config=publisher_config, event_bus=mock_event_bus
        )

        with patch(
            "omniclaude.publisher.embedded_publisher.os.kill",
            side_effect=PermissionError("Operation not permitted"),
        ):
            # PermissionError means process exists but we can't signal it — not stale
            assert publisher._check_stale_socket() is False
