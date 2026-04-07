# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PluginClaude — transitional bootstrap adapter for Claude Code kernel integration.

Implements ProtocolDomainPlugin so that omniclaude's lifecycle can be
managed by the kernel's generic plugin loader (OMN-2002).

Non-wiring lifecycle logic (publisher init, backend init, consumer threads,
shutdown) is delegated to ``lifecycle.py`` (OMN-7659).  PluginClaude is now
a thin adapter that translates protocol calls into lifecycle operations.

Deletion criteria
-----------------
Remove this entire module when the runtime supports dependency factories
and dispatcher wiring from contracts.

Required environment surface
----------------------------
- ``KAFKA_BOOTSTRAP_SERVERS``          — required (gate: should_activate)
- ``OMNICLAUDE_PUBLISHER_SOCKET_PATH`` — optional (default: ~/.claude/emit.sock)
- ``OMNICLAUDE_PUBLISHER_ENVIRONMENT`` — optional (default: dev)
- ``OMNICLAUDE_CONTRACTS_ROOT``        — optional (gate: wire_handlers)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from omniclaude.runtime.lifecycle import (
    LifecycleState,
    on_shutdown,
    on_start,
    start_workers,
)

if TYPE_CHECKING:
    from omnibase_infra.runtime.protocol_domain_plugin import (
        ModelDomainPluginConfig,
        ModelDomainPluginResult,
    )

logger = logging.getLogger(__name__)

_PLUGIN_ID = "claude"
_DISPLAY_NAME = "Claude Code Integration"


class PluginClaude:
    """Transitional bootstrap adapter for Claude Code kernel integration.

    Delegates lifecycle operations to ``lifecycle.on_start`` /
    ``lifecycle.on_shutdown`` (OMN-7659).  Retains protocol wiring
    (``wire_handlers``, ``wire_dispatchers``) which are routing-manifest
    concerns, not lifecycle.

    The constructor is deliberately side-effect-free (no env parsing,
    no network calls) so that module-level protocol checks are safe.

    Deletion criteria: remove when the runtime supports dependency factories
    + dispatcher wiring from contracts.
    """

    # ------------------------------------------------------------------
    # Construction — must be safe for module-level protocol check
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._state = LifecycleState()

    # ------------------------------------------------------------------
    # Protocol properties
    # ------------------------------------------------------------------

    @property
    def plugin_id(self) -> str:
        """Return unique identifier for this plugin."""
        return _PLUGIN_ID

    @property
    def display_name(self) -> str:
        """Return human-readable name for this plugin."""
        return _DISPLAY_NAME

    # ------------------------------------------------------------------
    # Lifecycle — ProtocolDomainPlugin
    # ------------------------------------------------------------------

    def should_activate(self, config: ModelDomainPluginConfig) -> bool:
        """Activate only when Kafka is configured.

        The publisher requires ``KAFKA_BOOTSTRAP_SERVERS`` to function.
        Without it the entire plugin is skipped — nothing useful can run.
        """
        return bool(os.getenv("KAFKA_BOOTSTRAP_SERVERS"))

    async def initialize(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Start the EmbeddedEventPublisher via lifecycle.on_start().

        Creates a ``PublisherConfig`` (reads ``OMNICLAUDE_PUBLISHER_*`` from
        env) and starts the publisher.  On failure the half-initialised
        resources are cleaned up and a ``.failed()`` result is returned.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        if not kafka_servers:
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="KAFKA_BOOTSTRAP_SERVERS not set",
            )

        diagnostics = await on_start(self._state, kafka_servers)

        # Check if publisher start failed (first diagnostic is always publisher)
        publisher_diag = diagnostics[0] if diagnostics else None
        if publisher_diag and not publisher_diag.success:
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message=publisher_diag.error or "Publisher start failed",
            )

        return ModelDomainPluginResult(
            plugin_id=_PLUGIN_ID,
            success=True,
            message="EmbeddedEventPublisher started",
            resources_created=[
                "embedded-event-publisher",
                "kafka-connection",
            ],
        )

    async def wire_handlers(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Delegate to ``wire_omniclaude_services`` if contracts root is set."""
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        contracts_root = os.getenv("OMNICLAUDE_CONTRACTS_ROOT")
        if not contracts_root:
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="OMNICLAUDE_CONTRACTS_ROOT not set; handler wiring skipped",
            )

        try:
            from omniclaude.runtime.wiring import wire_omniclaude_services

            await wire_omniclaude_services(config.container)

            return ModelDomainPluginResult(
                plugin_id=_PLUGIN_ID,
                success=True,
                message=(
                    "Contract publisher ran against "
                    f"OMNICLAUDE_CONTRACTS_ROOT={contracts_root}"
                ),
                services_registered=["wire_omniclaude_services"],
            )
        except Exception as exc:  # noqa: BLE001 — boundary: plugin wire must not crash kernel
            logger.exception(
                "Plugin '%s' wire_handlers failed (contracts_root=%s)",
                _PLUGIN_ID,
                contracts_root,
            )
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message=str(exc),
            )

    async def wire_dispatchers(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Wire skill command dispatchers from contracts (OMN-2802).

        Loads all skill node contracts, builds a multiplexed
        ``SkillCommandDispatcher``, and registers one dispatcher + one route
        on the ``MessageDispatchEngine``.

        Skips gracefully when the dispatch engine or service registry is not
        available (non-runtime contexts like dry-run or tests).
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        if config.dispatch_engine is None:
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="dispatch_engine not available",
            )

        try:
            from omniclaude.runtime.wiring_dispatchers import (
                wire_quirk_finding_subscription,
                wire_skill_dispatchers,
            )

            summary = await wire_skill_dispatchers(
                config.container,
                config.dispatch_engine,
                config.correlation_id,
                vllm_backend=self._state.vllm_backend,
            )

            # Wire quirk-finding-produced.v1 subscription (OMN-2908)
            quirk_summary = wire_quirk_finding_subscription(
                config.container,
                config.dispatch_engine,
            )

            all_dispatchers = summary["dispatchers"] + quirk_summary["dispatchers"]
            all_routes = summary["routes"] + quirk_summary["routes"]

            if not summary["dispatchers"]:
                return ModelDomainPluginResult.skipped(
                    plugin_id=_PLUGIN_ID,
                    reason="no skill dispatchers wired (OMNICLAUDE_CONTRACTS_ROOT not set?)",
                )

            return ModelDomainPluginResult(
                plugin_id=_PLUGIN_ID,
                success=True,
                message=(
                    f"Skill dispatchers wired: "
                    f"{summary['contracts_loaded']}/{summary['contracts_total']} contracts, "
                    f"backends={list(summary['backends'].keys())}"
                ),
                resources_created=all_dispatchers,
                services_registered=all_routes,
            )
        except Exception as exc:
            logger.exception("wire_dispatchers failed (plugin_id=%s)", _PLUGIN_ID)
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message=str(exc),
            )

    async def start_consumers(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Start background Kafka subscriber threads via lifecycle.start_workers().

        Starts two daemon subscriber threads:
        - compliance-evaluated subscriber: subscribes to
          ``onex.evt.omniintelligence.compliance-evaluated.v1`` and transforms
          violations into PatternAdvisory entries for context injection.
        - decision-record subscriber (OMN-2720): subscribes to
          ``onex.cmd.omniintelligence.decision-recorded.v1`` and appends full
          DecisionRecord payloads to the local audit log
          ``$ONEX_STATE_DIR/decision_audit.jsonl``.

        Skips gracefully when ``KAFKA_BOOTSTRAP_SERVERS`` is not set.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        if not bootstrap_servers:
            logger.debug("KAFKA_BOOTSTRAP_SERVERS not set — subscribers not started")
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="KAFKA_BOOTSTRAP_SERVERS not set; subscribers skipped",
            )

        diagnostics = await start_workers(self._state, bootstrap_servers)

        # Check for shutdown-in-progress or idempotent skip
        if diagnostics and diagnostics[0].component == "workers":
            if diagnostics[0].error == "shutdown in progress":
                return ModelDomainPluginResult.skipped(
                    plugin_id=_PLUGIN_ID,
                    reason="shutdown in progress; subscribers not started",
                )
            if "already running" in diagnostics[0].message.lower():
                return ModelDomainPluginResult(
                    plugin_id=_PLUGIN_ID,
                    success=True,
                    message="Subscribers already running (idempotent)",
                    resources_created=[],
                )

        # Collect resources from successful worker starts
        resources_created = [
            d.component
            for d in diagnostics
            if d.success and d.operation == "start" and d.component != "workers"
        ]
        # Include introspection if it succeeded
        for d in diagnostics:
            if d.component == "skill-node-introspection" and d.success:
                resources_created.append("skill-node-introspection")

        if not resources_created:
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message="All subscriber starts failed",
            )

        return ModelDomainPluginResult(
            plugin_id=_PLUGIN_ID,
            success=True,
            message=f"Subscriber daemon threads started: {', '.join(resources_created)}",
            resources_created=resources_created,
        )

    async def shutdown(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Idempotent, exception-safe shutdown via lifecycle.on_shutdown().

        Stops the publisher and clears all references regardless of
        whether stop() raises.  Also signals the compliance subscriber
        daemon thread to stop gracefully.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        if self._state.shutdown_in_progress:
            return ModelDomainPluginResult.succeeded(plugin_id=_PLUGIN_ID)

        diagnostics = await on_shutdown(self._state)

        # Check for publisher stop failure
        errors = [d.error for d in diagnostics if not d.success and d.error]
        if errors:
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message="; ".join(errors),
            )

        # Determine message based on whether publisher was stopped
        publisher_diags = [
            d for d in diagnostics if d.component == "EmbeddedEventPublisher"
        ]
        if publisher_diags:
            return ModelDomainPluginResult.succeeded(
                plugin_id=_PLUGIN_ID,
                message="Publisher stopped",
            )

        return ModelDomainPluginResult.succeeded(
            plugin_id=_PLUGIN_ID,
            message="No publisher to shut down",
        )

    # ------------------------------------------------------------------
    # Extra: status line (not part of protocol)
    # ------------------------------------------------------------------

    def get_status_line(self) -> str:
        """Return human-readable status for diagnostics."""
        if self._state.publisher is None:
            return "disabled"
        return "enabled (Publisher + Kafka)"

    # ------------------------------------------------------------------
    # Backward-compat accessors for tests that inspect internal state
    # ------------------------------------------------------------------

    @property
    def _publisher(self) -> object | None:
        return self._state.publisher

    @_publisher.setter
    def _publisher(self, value: object) -> None:
        self._state.publisher = value  # type: ignore[assignment]

    @property
    def _publisher_config(self) -> object | None:
        return self._state.publisher_config

    @_publisher_config.setter
    def _publisher_config(self, value: object) -> None:
        self._state.publisher_config = value

    @property
    def _vllm_backend(self) -> object | None:
        return self._state.vllm_backend

    @_vllm_backend.setter
    def _vllm_backend(self, value: object) -> None:
        self._state.vllm_backend = value  # type: ignore[assignment]

    @property
    def _shutdown_in_progress(self) -> bool:
        return self._state.shutdown_in_progress

    @_shutdown_in_progress.setter
    def _shutdown_in_progress(self, value: bool) -> None:
        self._state.shutdown_in_progress = value

    @property
    def _compliance_stop_event(self) -> object | None:
        worker = self._state.workers.get("compliance-subscriber")
        return worker.stop_event if worker else None

    @_compliance_stop_event.setter
    def _compliance_stop_event(self, value: object) -> None:
        # Used by tests to inject mock stop events
        worker = self._state.workers.get("compliance-subscriber")
        if worker is not None:
            worker.stop_event = value  # type: ignore[assignment]
        elif value is not None:
            self._state.workers["compliance-subscriber"] = _WorkerDescriptor(
                name="compliance-subscriber",
                stop_event=value,  # type: ignore[arg-type]
            )

    @property
    def _compliance_thread(self) -> object | None:
        worker = self._state.workers.get("compliance-subscriber")
        return worker.thread if worker else None

    @_compliance_thread.setter
    def _compliance_thread(self, value: object) -> None:
        # Used by tests to inject mock threads
        if value is not None:
            existing = self._state.workers.get("compliance-subscriber")
            if existing is not None:
                existing.thread = value  # type: ignore[assignment]
            else:
                self._state.workers["compliance-subscriber"] = _WorkerDescriptor(
                    name="compliance-subscriber",
                    thread=value,  # type: ignore[arg-type]
                )
        elif "compliance-subscriber" in self._state.workers:
            del self._state.workers["compliance-subscriber"]

    @property
    def _decision_record_stop_event(self) -> object | None:
        worker = self._state.workers.get("decision-record-subscriber")
        return worker.stop_event if worker else None

    @_decision_record_stop_event.setter
    def _decision_record_stop_event(self, value: object) -> None:
        worker = self._state.workers.get("decision-record-subscriber")
        if worker is not None:
            worker.stop_event = value  # type: ignore[assignment]
        elif value is not None:
            self._state.workers["decision-record-subscriber"] = _WorkerDescriptor(
                name="decision-record-subscriber",
                stop_event=value,  # type: ignore[arg-type]
            )

    @property
    def _decision_record_thread(self) -> object | None:
        worker = self._state.workers.get("decision-record-subscriber")
        return worker.thread if worker else None

    @_decision_record_thread.setter
    def _decision_record_thread(self, value: object) -> None:
        if value is not None:
            existing = self._state.workers.get("decision-record-subscriber")
            if existing is not None:
                existing.thread = value  # type: ignore[assignment]
            else:
                self._state.workers["decision-record-subscriber"] = _WorkerDescriptor(
                    name="decision-record-subscriber",
                    thread=value,  # type: ignore[arg-type]
                )
        elif "decision-record-subscriber" in self._state.workers:
            del self._state.workers["decision-record-subscriber"]


# Import for backward-compat property setters
from omniclaude.runtime.lifecycle import _WorkerDescriptor  # noqa: E402


# -----------------------------------------------------------------------
# Module-level protocol compliance check.
# Safe because __init__ does no env parsing or network calls.
# -----------------------------------------------------------------------
def _check_protocol_compliance() -> None:
    """Verify PluginClaude satisfies ProtocolDomainPlugin at import time."""
    try:
        import omnibase_infra.runtime.protocol_domain_plugin as _pdp

        assert isinstance(PluginClaude(), _pdp.ProtocolDomainPlugin)
    except (ImportError, AssertionError):
        # omnibase_infra not installed or protocol mismatch — skip check
        pass


_check_protocol_compliance()

__all__: list[str] = ["PluginClaude"]
