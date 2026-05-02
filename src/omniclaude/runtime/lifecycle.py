# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lifecycle modules for PluginClaude — on_start / on_shutdown.

Extracted from PluginClaude (OMN-7659) so that auto-wiring can call
lifecycle hooks without coupling to the plugin adapter class.

Background workers are:
- Named (thread.name is set for diagnostics)
- Stoppable (each has a threading.Event for graceful stop)
- Reflected in health (LifecycleState tracks all workers)
- Idempotent (repeated calls are safe)

This module produces structured failure diagnostics via
ModelLifecycleDiagnostic rather than silently swallowing errors.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from omnibase_core.protocols.event_bus.protocol_event_bus import ProtocolEventBus

    from omniclaude.nodes.node_local_llm_inference_effect.backends import (
        VllmInferenceBackend,
    )

logger = logging.getLogger(__name__)


class _ManagedPublisher(Protocol):
    """Runtime-managed emit daemon surface used by lifecycle hooks."""

    @property
    def event_bus(self) -> ProtocolEventBus | None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class _OmnimarketEmitDaemon:
    """In-process lifecycle wrapper for the omnimarket emit daemon components."""

    def __init__(self, kafka_bootstrap_servers: str) -> None:
        from omnimarket.nodes.node_emit_daemon.event_queue import BoundedEventQueue
        from omnimarket.nodes.node_emit_daemon.event_registry import EventRegistry
        from omnimarket.nodes.node_emit_daemon.models.model_emit_daemon_config import (
            ModelEmitDaemonConfig,
        )
        from omnimarket.nodes.node_emit_daemon.publisher_loop import KafkaPublisherLoop
        from omnimarket.nodes.node_emit_daemon.socket_server import EmitSocketServer

        socket_path = _resolve_path(
            "ONEX_EMIT_SOCKET_PATH",
            "OMNICLAUDE_PUBLISHER_SOCKET_PATH",
            default=str(Path.home() / ".claude" / "emit.sock"),
        )
        pid_path = _resolve_path(
            "ONEX_EMIT_PID_PATH",
            "OMNICLAUDE_PUBLISHER_PID_PATH",
            default=str(Path.home() / ".claude" / "emit.pid"),
        )
        spool_dir = Path(
            _resolve_path(
                "ONEX_EMIT_SPOOL_DIR",
                "OMNICLAUDE_PUBLISHER_SPOOL_DIR",
                default=str(_default_spool_dir()),
            )
        )

        self._config = ModelEmitDaemonConfig(
            socket_path=socket_path,
            pid_path=pid_path,
            spool_dir=spool_dir,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
        )
        self._pid_path = Path(pid_path)
        self._event_bus: ProtocolEventBus | None = None

        registry_path = _default_event_registry_path()
        registry = (
            EventRegistry.from_yaml(registry_path)
            if registry_path.exists()
            else EventRegistry()
        )
        self._queue = BoundedEventQueue(
            max_memory_queue=self._config.max_memory_queue,
            max_spool_messages=self._config.max_spool_messages,
            max_spool_bytes=self._config.max_spool_bytes,
            spool_dir=self._config.spool_dir,
        )
        self._publisher_loop = KafkaPublisherLoop(
            queue=self._queue,
            publish_fn=self._publish_to_kafka,
            max_retry_attempts=self._config.max_retry_attempts,
            backoff_base_seconds=self._config.backoff_base_seconds,
            max_backoff_seconds=self._config.max_backoff_seconds,
            source="omniclaude",
            failure_threshold=self._config.circuit_breaker_failure_threshold,
            recovery_timeout=self._config.circuit_breaker_recovery_timeout,
            half_open_max_probes=self._config.circuit_breaker_half_open_max_probes,
        )
        self._server = EmitSocketServer(
            socket_path=self._config.socket_path,
            queue=self._queue,
            registry=registry,
            socket_timeout_seconds=self._config.socket_timeout_seconds,
            socket_permissions=self._config.socket_permissions,
            max_payload_bytes=self._config.max_payload_bytes,
            publisher_loop=self._publisher_loop,
        )

    @property
    def event_bus(self) -> ProtocolEventBus | None:
        return self._event_bus

    async def start(self) -> None:
        await self._claim_pid_file()

        try:
            from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
            from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig

            environment = os.environ.get("OMNICLAUDE_PUBLISHER_ENVIRONMENT", "")
            config = ModelKafkaEventBusConfig(
                bootstrap_servers=self._config.kafka_bootstrap_servers or "",
                environment=environment,
                timeout_seconds=int(self._config.kafka_timeout_seconds),
            ).apply_environment_overrides()
            event_bus = EventBusKafka(config=config)
            await event_bus.start()
            self._event_bus = event_bus

            await self._queue.load_spool()
            await self._server.start()
            await self._publisher_loop.start()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        errors: list[Exception] = []

        try:
            await self._server.stop()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

        try:
            await self._publisher_loop.stop(
                drain_timeout=self._config.shutdown_drain_seconds
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

        try:
            await self._queue.drain_to_spool()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

        try:
            if self._event_bus is not None and hasattr(self._event_bus, "close"):
                await self._event_bus.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            self._event_bus = None
            self._pid_path.unlink(missing_ok=True)

        if errors:
            raise errors[0]

    async def _publish_to_kafka(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: dict[str, str],
    ) -> None:
        from omnibase_infra.event_bus.models import ModelEventHeaders

        if self._event_bus is None:
            raise RuntimeError("Event bus is not started")

        try:
            correlation_id = UUID(headers["correlation_id"])
        except (KeyError, ValueError):
            correlation_id = uuid4()
        try:
            timestamp = datetime.fromisoformat(headers["timestamp"])
        except (KeyError, ValueError):
            timestamp = datetime.now(UTC)

        event_headers = ModelEventHeaders(
            source=headers.get("source", "omniclaude"),
            event_type=headers.get("event_type", topic),
            timestamp=timestamp,
            correlation_id=correlation_id,
        )
        await self._event_bus.publish(
            topic=topic,
            key=key,
            value=value,
            headers=event_headers,
        )

    async def _claim_pid_file(self) -> None:
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(
                    self._pid_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                try:
                    if self._remove_stale_pid_file():
                        continue
                    pid = self._read_pid_file()
                except FileNotFoundError:
                    continue
                raise RuntimeError(
                    f"Another emit daemon is already running with PID {pid}"
                )

            with os.fdopen(fd, "w") as pid_file:
                pid_file.write(str(os.getpid()))
            return

    def _remove_stale_pid_file(self) -> bool:
        try:
            pid = self._read_pid_file()
            os.kill(pid, 0)
        except FileNotFoundError:
            return True
        except (ProcessLookupError, ValueError):
            self._pid_path.unlink(missing_ok=True)
            return True
        return False

    def _read_pid_file(self) -> int:
        return int(self._pid_path.read_text().strip())


def _resolve_path(primary_env: str, legacy_env: str, *, default: str) -> str:
    return os.environ.get(primary_env) or os.environ.get(legacy_env) or default


def _default_spool_dir() -> Path:
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime) / "onex" / "event-spool"
    return Path(gettempdir()) / "onex-event-spool"


def _default_event_registry_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "onex"
        / "lib"
        / "event_registry"
        / "omniclaude.yaml"  # arch-topic-naming: ignore
    )


# ---------------------------------------------------------------------------
# Diagnostic model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelLifecycleDiagnostic:
    """Structured failure diagnostic from a lifecycle operation."""

    component: str
    operation: str
    success: bool
    message: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Worker descriptor
# ---------------------------------------------------------------------------


@dataclass
class _WorkerDescriptor:
    """Tracks a named background worker thread and its stop signal."""

    name: str
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None

    @property
    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self) -> None:
        """Signal the worker to stop (non-blocking)."""
        if self.stop_event is not None:
            self.stop_event.set()
            self.stop_event = None
        self.thread = None


# ---------------------------------------------------------------------------
# Lifecycle state — holds all resources created during on_start
# ---------------------------------------------------------------------------


@dataclass
class LifecycleState:
    """Mutable bag of resources managed by the lifecycle module.

    PluginClaude owns a single instance and passes it into on_start /
    on_shutdown.  The lifecycle functions mutate this state rather than
    holding their own module-level globals.
    """

    publisher: _ManagedPublisher | None = None
    publisher_config: object | None = None
    vllm_backend: VllmInferenceBackend | None = None
    shutdown_in_progress: bool = False

    # Background workers keyed by name
    workers: dict[str, _WorkerDescriptor] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Health reflection
    # ------------------------------------------------------------------

    def worker_health(self) -> dict[str, bool]:
        """Return {worker_name: is_alive} for all registered workers."""
        return {name: w.is_alive for name, w in self.workers.items()}

    def all_workers_alive(self) -> bool:
        """True when every registered worker is still running."""
        return all(w.is_alive for w in self.workers.values()) if self.workers else True


# ---------------------------------------------------------------------------
# on_start — publisher + vllm backend
# ---------------------------------------------------------------------------


async def on_start(
    state: LifecycleState,
    kafka_bootstrap_servers: str,
) -> list[ModelLifecycleDiagnostic]:
    """Initialise the omnimarket emit daemon and VllmInferenceBackend.

    Populates ``state.publisher`` and ``state.vllm_backend``.
    Returns a list of diagnostics (one per component).
    """
    diagnostics: list[ModelLifecycleDiagnostic] = []

    # ---------------------------------------------------------------
    # Publisher
    # ---------------------------------------------------------------
    try:
        publisher = _OmnimarketEmitDaemon(kafka_bootstrap_servers)
        await publisher.start()

        state.publisher_config = publisher
        state.publisher = publisher

        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="OmnimarketEmitDaemon",
                operation="start",
                success=True,
                message="Emit daemon started",
            )
        )
    except Exception as exc:  # noqa: BLE001 — boundary: lifecycle init
        # Best-effort cleanup
        await _cleanup_publisher(state)
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="OmnimarketEmitDaemon",
                operation="start",
                success=False,
                error=str(exc),
            )
        )
        return diagnostics  # Publisher failure is fatal for on_start

    # ---------------------------------------------------------------
    # VllmInferenceBackend (optional — failure is non-fatal)
    # ---------------------------------------------------------------
    try:
        from omniclaude.config.model_local_llm_config import (
            LocalLlmEndpointRegistry,
        )
        from omniclaude.nodes.node_local_llm_inference_effect.backends import (
            VllmInferenceBackend,
        )

        registry = LocalLlmEndpointRegistry()
        state.vllm_backend = VllmInferenceBackend(registry=registry)
        logger.info("VllmInferenceBackend initialised")
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="VllmInferenceBackend",
                operation="init",
                success=True,
                message="Backend initialised",
            )
        )
    except Exception as exc:  # noqa: BLE001 — boundary: optional backend init
        logger.warning("VllmInferenceBackend init failed: %s", exc)
        state.vllm_backend = None
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="VllmInferenceBackend",
                operation="init",
                success=False,
                error=str(exc),
            )
        )

    return diagnostics


# ---------------------------------------------------------------------------
# start_workers — compliance + decision-record subscriber threads
# ---------------------------------------------------------------------------


async def start_workers(
    state: LifecycleState,
    kafka_bootstrap_servers: str,
) -> list[ModelLifecycleDiagnostic]:
    """Start background Kafka subscriber threads.

    Workers:
    - ``compliance-subscriber``: subscribes to compliance-evaluated events
    - ``decision-record-subscriber``: subscribes to decision-recorded events

    Each worker is named, stoppable via its stop_event, and tracked in
    ``state.workers`` for health reflection.

    Idempotent: skips workers that are already alive.
    """
    diagnostics: list[ModelLifecycleDiagnostic] = []

    if state.shutdown_in_progress:
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="workers",
                operation="start",
                success=False,
                error="shutdown in progress",
            )
        )
        return diagnostics

    # Check idempotency — all workers already alive?
    if state.workers and all(w.is_alive for w in state.workers.values()):
        logger.debug("All workers already running — skipping duplicate start")
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="workers",
                operation="start",
                success=True,
                message="All workers already running (idempotent)",
            )
        )
        return diagnostics

    # ----------------------------------------------------------------
    # Compliance subscriber
    # ----------------------------------------------------------------
    worker_name = "compliance-subscriber"
    existing = state.workers.get(worker_name)
    if existing is None or not existing.is_alive:
        try:
            from omniclaude.hooks.lib.compliance_result_subscriber import (  # noqa: PLC0415
                run_subscriber_background as _compliance_run_bg,
            )

            stop_event = threading.Event()
            thread = _compliance_run_bg(
                kafka_bootstrap_servers=kafka_bootstrap_servers,
                group_id="omniclaude-compliance-subscriber.v1",
                stop_event=stop_event,
            )
            thread.name = worker_name
            state.workers[worker_name] = _WorkerDescriptor(
                name=worker_name,
                thread=thread,
                stop_event=stop_event,
            )
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component=worker_name,
                    operation="start",
                    success=True,
                    message="Thread started",
                )
            )
        except Exception as exc:  # noqa: BLE001 — boundary: subscriber start must degrade
            logger.warning("Failed to start %s: %s", worker_name, exc)
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component=worker_name,
                    operation="start",
                    success=False,
                    error=str(exc),
                )
            )

    # ----------------------------------------------------------------
    # Decision-record subscriber
    # ----------------------------------------------------------------
    worker_name = "decision-record-subscriber"
    existing = state.workers.get(worker_name)
    if existing is None or not existing.is_alive:
        try:
            from omniclaude.hooks.lib.decision_record_subscriber import (  # noqa: PLC0415
                run_subscriber_background as _decision_run_bg,
            )

            stop_event = threading.Event()
            thread = _decision_run_bg(
                kafka_bootstrap_servers=kafka_bootstrap_servers,
                group_id="omniclaude-decision-record-subscriber.v1",
                stop_event=stop_event,
            )
            thread.name = worker_name
            state.workers[worker_name] = _WorkerDescriptor(
                name=worker_name,
                thread=thread,
                stop_event=stop_event,
            )
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component=worker_name,
                    operation="start",
                    success=True,
                    message="Thread started",
                )
            )
        except Exception as exc:  # noqa: BLE001 — boundary: subscriber start must degrade
            logger.warning("Failed to start %s: %s", worker_name, exc)
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component=worker_name,
                    operation="start",
                    success=False,
                    error=str(exc),
                )
            )

    # ----------------------------------------------------------------
    # Skill node introspection (best-effort, non-blocking)
    # ----------------------------------------------------------------
    try:
        from omniclaude.runtime.introspection import (  # noqa: PLC0415
            SkillNodeIntrospectionProxy,
        )

        introspection_proxy = SkillNodeIntrospectionProxy(
            event_bus=state.publisher.event_bus
            if state.publisher is not None
            else None,
        )
        published_count = await introspection_proxy.publish_all(reason="startup")
        if published_count > 0:
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component="skill-node-introspection",
                    operation="publish",
                    success=True,
                    message=f"Published {published_count} introspection events",
                )
            )
    except Exception as exc:  # noqa: BLE001 — boundary: introspection is optional
        logger.warning("Skill node introspection proxy failed to start: %s", exc)
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="skill-node-introspection",
                operation="publish",
                success=False,
                error=str(exc),
            )
        )

    return diagnostics


# ---------------------------------------------------------------------------
# on_shutdown — tear down all resources
# ---------------------------------------------------------------------------


async def on_shutdown(state: LifecycleState) -> list[ModelLifecycleDiagnostic]:
    """Idempotent, exception-safe shutdown of all lifecycle resources.

    Stops all background workers, closes the VllmInferenceBackend,
    and stops the publisher. Clears all references regardless of errors.
    """
    diagnostics: list[ModelLifecycleDiagnostic] = []

    if state.shutdown_in_progress:
        return diagnostics

    state.shutdown_in_progress = True
    try:
        # ---------------------------------------------------------------
        # Stop all background workers
        # ---------------------------------------------------------------
        for name, worker in list(state.workers.items()):
            worker.stop()
            diagnostics.append(
                ModelLifecycleDiagnostic(
                    component=name,
                    operation="stop",
                    success=True,
                    message="Stop signal sent",
                )
            )
        state.workers.clear()

        # ---------------------------------------------------------------
        # Close VllmInferenceBackend
        # ---------------------------------------------------------------
        if state.vllm_backend is not None:
            try:
                await state.vllm_backend.aclose()
                diagnostics.append(
                    ModelLifecycleDiagnostic(
                        component="VllmInferenceBackend",
                        operation="close",
                        success=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — boundary: best-effort cleanup
                logger.debug("VllmInferenceBackend close failed: %s", exc)
                diagnostics.append(
                    ModelLifecycleDiagnostic(
                        component="VllmInferenceBackend",
                        operation="close",
                        success=False,
                        error=str(exc),
                    )
                )
            state.vllm_backend = None

        # ---------------------------------------------------------------
        # Stop publisher
        # ---------------------------------------------------------------
        if state.publisher is not None:
            try:
                await state.publisher.stop()
                diagnostics.append(
                    ModelLifecycleDiagnostic(
                        component="OmnimarketEmitDaemon",
                        operation="stop",
                        success=True,
                        message="Emit daemon stopped",
                    )
                )
            except Exception as exc:  # noqa: BLE001 — boundary: shutdown must not crash
                diagnostics.append(
                    ModelLifecycleDiagnostic(
                        component="OmnimarketEmitDaemon",
                        operation="stop",
                        success=False,
                        error=str(exc),
                    )
                )

        # Clear references regardless of outcome
        state.publisher = None
        state.publisher_config = None

    finally:
        state.shutdown_in_progress = False

    return diagnostics


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _cleanup_publisher(state: LifecycleState) -> None:
    """Best-effort cleanup after a failed initialisation."""
    if state.publisher is not None:
        try:
            await state.publisher.stop()
        except Exception:  # noqa: BLE001 — boundary: best-effort cleanup
            logger.debug("Cleanup: publisher stop failed", exc_info=True)
    state.publisher = None
    state.publisher_config = None
