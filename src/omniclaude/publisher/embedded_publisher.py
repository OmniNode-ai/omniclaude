"""Embedded Event Publisher - Unix socket server with async Kafka publishing.

Ported from omnibase_infra.runtime.emit_daemon.daemon (OMN-1944).

Key differences from the original EmitDaemon:
    - Lives in omniclaude (not omnibase_infra)
    - No CLI entry point — started/stopped programmatically from hook scripts
    - Uses PublisherConfig (pydantic-settings) instead of ModelEmitDaemonConfig
    - Auto-managed lifecycle tied to Claude Code sessions

Architecture:
    Hook Script -> emit_via_daemon() -> Unix Socket -> EmbeddedEventPublisher -> Kafka
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from omnibase_core.errors import OnexError
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models import ModelEventHeaders
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
from omnibase_infra.runtime.emit_daemon.event_registry import EventRegistry
from pydantic import ValidationError

if TYPE_CHECKING:
    from omnibase_infra.protocols import ProtocolEventBusLike

from omniclaude.publisher.event_queue import BoundedEventQueue, ModelQueuedEvent
from omniclaude.publisher.publisher_config import PublisherConfig
from omniclaude.publisher.publisher_models import (
    ModelDaemonEmitRequest,
    ModelDaemonErrorResponse,
    ModelDaemonPingRequest,
    ModelDaemonPingResponse,
    ModelDaemonQueuedResponse,
    parse_daemon_request,
)

logger = logging.getLogger(__name__)

PUBLISHER_POLL_INTERVAL_SECONDS: float = 0.1


class EmbeddedEventPublisher:
    """Unix socket server for persistent Kafka event emission.

    Accepts events via Unix socket, queues them, and publishes to Kafka
    with fire-and-forget semantics from the caller's perspective.
    """

    def __init__(
        self,
        config: PublisherConfig,
        event_bus: ProtocolEventBusLike | None = None,
    ) -> None:
        self._config = config
        self._event_bus: ProtocolEventBusLike | None = event_bus
        self._registry = EventRegistry(environment=config.environment)
        self._queue = BoundedEventQueue(
            max_memory_queue=config.max_memory_queue,
            max_spool_messages=config.max_spool_messages,
            max_spool_bytes=config.max_spool_bytes,
            spool_dir=config.spool_dir,
        )

        self._server: asyncio.Server | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._retry_counts: dict[str, int] = {}  # event_id -> retry count

        logger.debug(
            "EmbeddedEventPublisher initialized",
            extra={
                "socket_path": str(config.socket_path),
                "kafka_servers": config.kafka_bootstrap_servers,
            },
        )

    @property
    def config(self) -> PublisherConfig:
        return self._config

    @property
    def queue(self) -> BoundedEventQueue:
        return self._queue

    async def start(self) -> None:
        """Start the publisher.

        1. Check for stale socket/PID and clean up
        2. Create PID file
        3. Load spooled events from disk
        4. Initialize Kafka event bus
        5. Start Unix socket server
        6. Start publisher loop (background task)
        7. Setup signal handlers
        """
        async with self._lock:
            if self._running:
                logger.debug("EmbeddedEventPublisher already running")
                return

            if self._check_stale_socket():
                self._cleanup_stale()
            elif self._config.pid_path.exists():
                pid = self._config.pid_path.read_text().strip()
                raise OnexError(f"Another publisher is already running with PID {pid}")

            self._write_pid_file()

            try:
                spool_count = await self._queue.load_spool()
                if spool_count > 0:
                    logger.info(f"Loaded {spool_count} events from spool")

                if self._event_bus is None:
                    kafka_config = ModelKafkaEventBusConfig(
                        bootstrap_servers=self._config.kafka_bootstrap_servers,
                        environment=self._config.environment,
                        timeout_seconds=int(self._config.kafka_timeout_seconds),
                    )
                    self._event_bus = EventBusKafka(config=kafka_config)

                if hasattr(self._event_bus, "start"):
                    await self._event_bus.start()

                self._config.socket_path.parent.mkdir(parents=True, exist_ok=True)
                if self._config.socket_path.exists():
                    self._config.socket_path.unlink()

                # Set readline buffer limit to match max_payload_bytes + overhead
                # (default 64KB is too small for large event payloads)
                stream_limit = self._config.max_payload_bytes + 4096
                self._server = await asyncio.start_unix_server(
                    self._handle_client,
                    path=str(self._config.socket_path),
                    limit=stream_limit,
                )
                self._config.socket_path.chmod(self._config.socket_permissions)

                self._publisher_task = asyncio.create_task(self._publisher_loop())

                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, self._signal_handler)

                self._running = True
                self._shutdown_event.clear()
            except Exception:
                self._remove_pid_file()
                raise

            logger.info(
                "EmbeddedEventPublisher started",
                extra={
                    "socket_path": str(self._config.socket_path),
                    "pid": os.getpid(),
                },
            )

    async def stop(self) -> None:
        """Stop the publisher gracefully."""
        async with self._lock:
            if not self._running:
                return

            self._running = False
            self._shutdown_event.set()
            logger.info("EmbeddedEventPublisher stopping...")

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)

            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None

            if self._publisher_task is not None:
                # Give the publisher loop time to finish its current in-flight publish
                # before force-cancelling. _running is already False, so the loop will
                # exit after its current iteration.
                try:
                    async with asyncio.timeout(self._config.shutdown_drain_seconds):
                        await self._publisher_task
                except TimeoutError:
                    self._publisher_task.cancel()
                    try:
                        await self._publisher_task
                    except asyncio.CancelledError:
                        pass
                except asyncio.CancelledError:
                    pass
                self._publisher_task = None

            if self._config.shutdown_drain_seconds > 0:
                try:
                    async with asyncio.timeout(self._config.shutdown_drain_seconds):
                        drained = await self._queue.drain_to_spool()
                        if drained > 0:
                            logger.info(f"Drained {drained} events to spool")
                except TimeoutError:
                    logger.warning(
                        "Shutdown drain timeout exceeded, some events may be lost"
                    )

            if self._event_bus is not None and hasattr(self._event_bus, "close"):
                await self._event_bus.close()

            if self._config.socket_path.exists():
                try:
                    self._config.socket_path.unlink()
                except OSError as e:
                    logger.warning(f"Failed to remove socket file: {e}")

            self._remove_pid_file()
            logger.info("EmbeddedEventPublisher stopped")

    async def run_until_shutdown(self) -> None:
        """Block until shutdown signal is received."""
        await self._shutdown_event.wait()
        await self.stop()

    def _signal_handler(self) -> None:
        logger.info("Received shutdown signal")
        self._shutdown_event.set()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (newline-delimited JSON protocol)."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    line = await asyncio.wait_for(
                        reader.readline(),
                        timeout=self._config.socket_timeout_seconds,
                    )
                except TimeoutError:
                    break

                if not line:
                    break

                response = await self._process_request(line)
                writer.write(response.encode("utf-8") + b"\n")
                await writer.drain()

        except ConnectionResetError:
            pass
        except Exception as e:
            logger.exception(f"Error handling client: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: S110 – best-effort socket cleanup
                logger.debug("Error closing client writer", exc_info=True)

    async def _process_request(self, line: bytes) -> str:
        try:
            raw_request = json.loads(line.decode("utf-8").strip())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return ModelDaemonErrorResponse(
                reason=f"Invalid JSON: {e}"
            ).model_dump_json()

        if not isinstance(raw_request, dict):
            return ModelDaemonErrorResponse(
                reason="Request must be a JSON object"
            ).model_dump_json()

        try:
            request = parse_daemon_request(raw_request)
        except (ValueError, ValidationError) as e:
            return ModelDaemonErrorResponse(reason=str(e)).model_dump_json()

        if isinstance(request, ModelDaemonPingRequest):
            return await self._handle_ping()
        # parse_daemon_request return type is PingRequest | EmitRequest,
        # so this branch is guaranteed to be EmitRequest.
        return await self._handle_emit(request)

    async def _handle_ping(self) -> str:
        return ModelDaemonPingResponse(
            queue_size=self._queue.memory_size(),
            spool_size=self._queue.spool_size(),
        ).model_dump_json()

    async def _handle_emit(self, request: ModelDaemonEmitRequest) -> str:
        event_type = request.event_type

        raw_payload = request.payload
        if raw_payload is None:
            raw_payload = {}
        if not isinstance(raw_payload, dict):
            return ModelDaemonErrorResponse(
                reason="'payload' must be a JSON object"
            ).model_dump_json()

        payload: dict[str, object] = cast("dict[str, object]", raw_payload)

        try:
            topic = self._registry.resolve_topic(event_type)
        except OnexError as e:
            return ModelDaemonErrorResponse(reason=str(e)).model_dump_json()

        try:
            self._registry.validate_payload(event_type, payload)
        except OnexError as e:
            return ModelDaemonErrorResponse(reason=str(e)).model_dump_json()

        correlation_id = payload.get("correlation_id")
        if not isinstance(correlation_id, str):
            correlation_id = None

        try:
            enriched_payload = self._registry.inject_metadata(
                event_type,
                payload,
                correlation_id=correlation_id,
            )
        except Exception as e:
            return ModelDaemonErrorResponse(
                reason=f"Metadata enrichment failed: {e}"
            ).model_dump_json()

        try:
            enriched_json = json.dumps(enriched_payload)
        except (TypeError, ValueError) as e:
            return ModelDaemonErrorResponse(
                reason=f"Payload serialization failed: {e}"
            ).model_dump_json()

        if len(enriched_json.encode("utf-8")) > self._config.max_payload_bytes:
            return ModelDaemonErrorResponse(
                reason=f"Payload exceeds maximum size of {self._config.max_payload_bytes} bytes"
            ).model_dump_json()

        try:
            partition_key = self._registry.get_partition_key(
                event_type, enriched_payload
            )
        except Exception as e:
            return ModelDaemonErrorResponse(
                reason=f"Partition key resolution failed: {e}"
            ).model_dump_json()

        event_id = str(uuid4())
        queued_event = ModelQueuedEvent(
            event_id=event_id,
            event_type=event_type,
            topic=topic,
            payload=enriched_payload,
            partition_key=partition_key,
            queued_at=datetime.now(UTC),
        )

        success = await self._queue.enqueue(queued_event)
        if success:
            logger.debug(
                f"Event queued: {event_id}",
                extra={"event_type": event_type, "topic": topic},
            )
            return ModelDaemonQueuedResponse(event_id=event_id).model_dump_json()
        else:
            return ModelDaemonErrorResponse(
                reason="Failed to queue event (queue may be full)"
            ).model_dump_json()

    async def _publisher_loop(self) -> None:
        """Background task: dequeue events and publish to Kafka."""
        logger.info("Publisher loop started")

        # Note: stop() sets _running=False and waits for this loop to exit gracefully,
        # then drains remaining events via drain_to_spool().
        while self._running:
            try:
                event = await self._queue.dequeue()

                if event is None:
                    await asyncio.sleep(PUBLISHER_POLL_INTERVAL_SECONDS)
                    continue

                success = await self._publish_event(event)

                if success:
                    self._retry_counts.pop(event.event_id, None)
                else:
                    retries = self._retry_counts.get(event.event_id, 0) + 1
                    self._retry_counts[event.event_id] = retries

                    if retries >= self._config.max_retry_attempts:
                        logger.error(
                            f"Dropping event {event.event_id} after {retries} retries",
                            extra={
                                "event_type": event.event_type,
                                "topic": event.topic,
                            },
                        )
                        self._retry_counts.pop(event.event_id, None)
                    else:
                        uncapped_backoff = self._config.backoff_base_seconds * (
                            2 ** (retries - 1)
                        )
                        backoff = min(
                            uncapped_backoff, self._config.max_backoff_seconds
                        )
                        logger.warning(
                            f"Publish failed for {event.event_id}, "
                            f"retry {retries}/{self._config.max_retry_attempts} "
                            f"in {backoff}s",
                        )
                        await asyncio.sleep(backoff)

                        requeue_success = await self._queue.enqueue(event)
                        if not requeue_success:
                            logger.error(
                                f"Failed to re-enqueue event {event.event_id}, event lost"
                            )
                            self._retry_counts.pop(event.event_id, None)

            except asyncio.CancelledError:
                logger.info("Publisher loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Unexpected error in publisher loop: {e}")
                await asyncio.sleep(1.0)

        logger.info("Publisher loop stopped")

    async def _publish_event(self, event: ModelQueuedEvent) -> bool:
        if self._event_bus is None:
            logger.error("Event bus not initialized")
            return False

        try:
            key = event.partition_key.encode("utf-8") if event.partition_key else None
            value = json.dumps(event.payload).encode("utf-8")

            payload_correlation_id = (
                event.payload.get("correlation_id")
                if isinstance(event.payload, dict)
                else None
            )
            if isinstance(payload_correlation_id, str):
                try:
                    correlation_id = UUID(payload_correlation_id)
                except ValueError:
                    correlation_id = uuid4()
            else:
                correlation_id = uuid4()

            headers = ModelEventHeaders(
                source="omniclaude-publisher",
                event_type=event.event_type,
                timestamp=event.queued_at,
                correlation_id=correlation_id,
            )

            await self._event_bus.publish(
                topic=event.topic,
                key=key,
                value=value,
                headers=headers,
            )

            logger.debug(
                f"Published event {event.event_id}",
                extra={"event_type": event.event_type, "topic": event.topic},
            )
            return True

        except Exception as e:
            logger.warning(
                f"Failed to publish event {event.event_id}: {e}",
                extra={
                    "event_type": event.event_type,
                    "topic": event.topic,
                },
            )
            return False

    def _write_pid_file(self) -> None:
        try:
            self._config.pid_path.parent.mkdir(parents=True, exist_ok=True)
            self._config.pid_path.write_text(str(os.getpid()))
        except OSError as e:
            logger.warning(f"Failed to write PID file: {e}")

    def _remove_pid_file(self) -> None:
        try:
            if self._config.pid_path.exists():
                self._config.pid_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to remove PID file: {e}")

    def _check_stale_socket(self) -> bool:
        if not self._config.pid_path.exists():
            return self._config.socket_path.exists()

        try:
            pid_str = self._config.pid_path.read_text().strip()
            pid = int(pid_str)
        except (OSError, ValueError):
            return True

        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

    def _cleanup_stale(self) -> None:
        if self._config.socket_path.exists():
            try:
                self._config.socket_path.unlink()
                logger.info(f"Removed stale socket: {self._config.socket_path}")
            except OSError as e:
                logger.warning(f"Failed to remove stale socket: {e}")

        if self._config.pid_path.exists():
            try:
                self._config.pid_path.unlink()
                logger.info(f"Removed stale PID file: {self._config.pid_path}")
            except OSError as e:
                logger.warning(f"Failed to remove stale PID file: {e}")


__all__: list[str] = ["EmbeddedEventPublisher"]
