# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from omnibase_core.errors import OnexError
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models import ModelEventHeaders
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
from pydantic import ValidationError

from omniclaude.hooks.event_registry import (
    get_partition_key as registry_get_partition_key,
)
from omniclaude.hooks.event_registry import (
    get_registration,
)
from omniclaude.hooks.event_registry import (
    validate_payload as registry_validate_payload,
)

if TYPE_CHECKING:
    from omnibase_core.types.type_json import JsonType
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
        secondary_event_bus: EventBusKafka | None = None,
    ) -> None:
        self._config = config
        self._event_bus: ProtocolEventBusLike | None = event_bus
        # Secondary event bus typed as EventBusKafka (not ProtocolEventBusLike) to get
        # start()/stop() lifecycle without hasattr checks.
        self._secondary_event_bus: EventBusKafka | None = secondary_event_bus
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

    @property
    def event_bus(self) -> ProtocolEventBusLike | None:
        """Return the underlying event bus, or ``None`` if not yet started.

        Callers that require a ``ProtocolEventBus``-compatible object for
        introspection or publishing should use this property rather than
        passing the ``EmbeddedEventPublisher`` instance itself, which does
        not implement ``ProtocolEventBus``.
        """
        return self._event_bus

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
                    ).apply_environment_overrides()
                    self._event_bus = EventBusKafka(config=kafka_config)

                if hasattr(self._event_bus, "start"):
                    await self._event_bus.start()

                # Initialize secondary Kafka cluster (cloud Redpanda) if configured.
                # Failures are non-fatal: secondary start failure must not prevent
                # the primary from publishing.
                if (
                    self._secondary_event_bus is None
                    and self._config.kafka_secondary_bootstrap_servers is not None
                ):
                    secondary_kafka_config = ModelKafkaEventBusConfig(
                        bootstrap_servers=self._config.kafka_secondary_bootstrap_servers,
                        environment=self._config.environment,
                        timeout_seconds=int(self._config.kafka_secondary_timeout_seconds),
                        security_protocol=self._config.kafka_secondary_security_protocol,
                        sasl_mechanism=self._config.kafka_secondary_sasl_mechanism,
                        sasl_oauthbearer_token_endpoint_url=self._config.kafka_secondary_sasl_oauthbearer_token_endpoint_url,
                        sasl_oauthbearer_client_id=self._config.kafka_secondary_sasl_oauthbearer_client_id,
                        sasl_oauthbearer_client_secret=self._config.kafka_secondary_sasl_oauthbearer_client_secret,
                        ssl_ca_file=self._config.kafka_secondary_ssl_ca_file,
                        # Do NOT call apply_environment_overrides() — those env vars
                        # (KAFKA_*) belong to the primary cluster.
                    )
                    self._secondary_event_bus = EventBusKafka(config=secondary_kafka_config)
                    try:
                        await self._secondary_event_bus.start()
                        logger.info(
                            "Secondary event bus started",
                            extra={"secondary_servers": self._config.kafka_secondary_bootstrap_servers},
                        )
                    except Exception as e:
                        logger.warning(
                            f"Secondary event bus failed to start (non-fatal): {e}",
                            extra={"secondary_servers": self._config.kafka_secondary_bootstrap_servers},
                        )
                        self._secondary_event_bus = None

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
        """Stop the publisher gracefully.

        The total time for draining (publisher loop exit + spool flush) is
        bounded by ``shutdown_drain_seconds`` so callers can rely on a
        predictable upper bound.
        """
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

            # Single timeout wraps both the publisher-loop exit and the spool
            # drain so that the *total* graceful-shutdown time never exceeds
            # shutdown_drain_seconds.
            try:
                async with asyncio.timeout(self._config.shutdown_drain_seconds):
                    if self._publisher_task is not None:
                        # Give the publisher loop time to finish its current
                        # in-flight publish. _running is already False and
                        # _shutdown_event is set, so the loop will exit after
                        # its current iteration. We never cancel the task to
                        # avoid interrupting an in-flight Kafka publish.
                        try:
                            await self._publisher_task
                        except asyncio.CancelledError:
                            pass
                        self._publisher_task = None

                    drained = await self._queue.drain_to_spool()
                    if drained > 0:
                        logger.info(f"Drained {drained} events to spool")
            except TimeoutError:
                logger.warning(
                    "Shutdown drain timeout exceeded, some events may be lost"
                )
                if self._publisher_task is not None:
                    self._publisher_task = None

            # Stop secondary bus first (non-fatal) so primary stops last.
            if self._secondary_event_bus is not None:
                try:
                    await self._secondary_event_bus.stop()
                except Exception as e:
                    logger.warning(f"Secondary event bus stop failed (non-fatal): {e}")
                self._secondary_event_bus = None

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
        except Exception:
            logger.exception("Error handling client")
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

    def _inject_metadata(
        self,
        payload: dict[str, object],
        correlation_id: str | None,
    ) -> dict[str, object]:
        """Add standard metadata fields to payload."""
        result = dict(payload)
        if "correlation_id" not in result or result["correlation_id"] is None:
            result["correlation_id"] = correlation_id or str(uuid4())
        if "causation_id" not in result:
            result["causation_id"] = None
        if "emitted_at" not in result:
            result["emitted_at"] = datetime.now(UTC).isoformat()
        result["schema_version"] = "1.0.0"
        return result

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

        # --- Look up registration from local ONEX-native registry ---
        registration = get_registration(event_type)
        if registration is None:
            return ModelDaemonErrorResponse(
                reason=f"Unknown event type: {event_type}"
            ).model_dump_json()

        # --- Validate required fields ---
        try:
            missing = registry_validate_payload(event_type, payload)
            if missing:
                return ModelDaemonErrorResponse(
                    reason=f"Missing required fields for {event_type}: {missing}"
                ).model_dump_json()
        except KeyError as e:
            return ModelDaemonErrorResponse(reason=str(e)).model_dump_json()

        # --- Inject metadata ---
        correlation_id = payload.get("correlation_id")
        if not isinstance(correlation_id, str):
            correlation_id = None

        enriched_payload = self._inject_metadata(payload, correlation_id)

        # --- Fan-out: enqueue one event per fan-out rule ---
        last_event_id: str | None = None

        for rule in registration.fan_out:
            # Apply transform (e.g., sanitize prompt for observability topic)
            transformed = rule.apply_transform(enriched_payload)

            # Topic = bare ONEX suffix (realm-agnostic, per OMN-1972 TopicResolver)
            # TopicBase is a StrEnum whose value IS the wire topic.
            topic = str(rule.topic_base)

            # Serialize and check size
            try:
                transformed_json = json.dumps(transformed)
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Payload serialization failed for {event_type} -> {topic}: {e}"
                )
                continue

            if len(transformed_json.encode("utf-8")) > self._config.max_payload_bytes:
                logger.warning(
                    f"Payload exceeds max size for {event_type} -> {topic}, skipping"
                )
                continue

            # Get partition key from transformed payload
            try:
                partition_key = registry_get_partition_key(event_type, transformed)
            except KeyError:
                partition_key = None

            event_id = str(uuid4())
            queued_event = ModelQueuedEvent(
                event_id=event_id,
                event_type=event_type,
                topic=topic,
                payload=cast("JsonType", transformed),
                partition_key=partition_key,
                queued_at=datetime.now(UTC),
            )

            success = await self._queue.enqueue(queued_event)
            if success:
                logger.debug(
                    f"Event queued: {event_id}",
                    extra={"event_type": event_type, "topic": topic},
                )
                last_event_id = event_id
            else:
                logger.warning(f"Failed to queue event for {event_type} -> {topic}")

        if last_event_id is None:
            return ModelDaemonErrorResponse(
                reason=f"Failed to queue any events for {event_type}"
            ).model_dump_json()

        return ModelDaemonQueuedResponse(event_id=last_event_id).model_dump_json()

    async def _publisher_loop(self) -> None:
        """Background task: dequeue events and publish to Kafka."""
        logger.info("Publisher loop started")

        # Note: stop() sets _running=False and waits for this loop to exit gracefully,
        # then drains remaining events via drain_to_spool().
        while self._running:
            try:
                event = await self._queue.dequeue()

                if event is None:
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=PUBLISHER_POLL_INTERVAL_SECONDS,
                        )
                        break  # Shutdown requested
                    except TimeoutError:
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
                        try:
                            await asyncio.wait_for(
                                self._shutdown_event.wait(), timeout=backoff
                            )
                            # Shutdown requested during backoff — re-enqueue event and exit
                            requeue_success = await self._queue.enqueue(event)
                            if not requeue_success:
                                logger.error(
                                    f"Failed to re-enqueue event {event.event_id}, event lost"
                                )
                                self._retry_counts.pop(event.event_id, None)
                            break
                        except TimeoutError:
                            pass  # Normal backoff completed, continue with re-enqueue

                        requeue_success = await self._queue.enqueue(event)
                        if not requeue_success:
                            logger.error(
                                f"Failed to re-enqueue event {event.event_id}, event lost"
                            )
                            self._retry_counts.pop(event.event_id, None)

            except asyncio.CancelledError:
                logger.info("Publisher loop cancelled")
                break
            except Exception:
                logger.exception("Unexpected error in publisher loop")
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
                source="omniclaude",
                event_type=event.event_type,
                timestamp=event.queued_at,
                correlation_id=correlation_id,
            )

            # Build publish coroutines: primary always present; secondary added when configured.
            # asyncio.wait_for bounds secondary publish so a cloud stall cannot delay primary.
            publish_coros: list[Awaitable[None]] = [
                self._event_bus.publish(
                    topic=event.topic,
                    key=key,
                    value=value,
                    headers=headers,
                )
            ]
            if self._secondary_event_bus is not None:
                publish_coros.append(
                    asyncio.wait_for(
                        self._secondary_event_bus.publish(
                            topic=event.topic,
                            key=key,
                            value=value,
                            headers=headers,
                        ),
                        timeout=self._config.kafka_secondary_timeout_seconds,
                    )
                )

            results = await asyncio.gather(*publish_coros, return_exceptions=True)

            # Primary (index 0) is authoritative.
            if isinstance(results[0], BaseException):
                logger.warning(
                    f"Primary publish failed for event {event.event_id}: {results[0]}",
                    extra={"event_type": event.event_type, "topic": event.topic, "cluster": "primary"},
                )
                return False

            # Secondary (index 1) is non-fatal.
            if len(results) > 1 and isinstance(results[1], BaseException):
                logger.warning(
                    f"Secondary publish failed (non-fatal) for event {event.event_id}: {results[1]}",
                    extra={"event_type": event.event_type, "topic": event.topic, "cluster": "secondary"},
                )

            logger.debug(
                f"Published event {event.event_id}",
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "topic": event.topic,
                    "cluster": "primary",
                    "success": True,
                },
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
