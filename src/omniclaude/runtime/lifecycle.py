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
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.nodes.node_local_llm_inference_effect.backends import (
        VllmInferenceBackend,
    )
    from omniclaude.publisher.embedded_publisher import EmbeddedEventPublisher

logger = logging.getLogger(__name__)


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

    publisher: EmbeddedEventPublisher | None = None
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
    """Initialise the EmbeddedEventPublisher and VllmInferenceBackend.

    Populates ``state.publisher`` and ``state.vllm_backend``.
    Returns a list of diagnostics (one per component).
    """
    diagnostics: list[ModelLifecycleDiagnostic] = []

    # ---------------------------------------------------------------
    # Publisher
    # ---------------------------------------------------------------
    try:
        from omniclaude.publisher.embedded_publisher import (
            EmbeddedEventPublisher,
        )
        from omniclaude.publisher.publisher_config import PublisherConfig

        publisher_config = PublisherConfig(
            kafka_bootstrap_servers=kafka_bootstrap_servers,
        )
        publisher = EmbeddedEventPublisher(config=publisher_config)
        await publisher.start()

        state.publisher_config = publisher_config
        state.publisher = publisher

        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="EmbeddedEventPublisher",
                operation="start",
                success=True,
                message="Publisher started",
            )
        )
    except Exception as exc:  # noqa: BLE001 — boundary: lifecycle init
        # Best-effort cleanup
        await _cleanup_publisher(state)
        diagnostics.append(
            ModelLifecycleDiagnostic(
                component="EmbeddedEventPublisher",
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
                        component="EmbeddedEventPublisher",
                        operation="stop",
                        success=True,
                        message="Publisher stopped",
                    )
                )
            except Exception as exc:  # noqa: BLE001 — boundary: shutdown must not crash
                diagnostics.append(
                    ModelLifecycleDiagnostic(
                        component="EmbeddedEventPublisher",
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
