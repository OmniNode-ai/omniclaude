# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""PluginClaude — transitional bootstrap adapter for Claude Code kernel integration.

Implements ProtocolDomainPlugin so that omniclaude's lifecycle can be
managed by the kernel's generic plugin loader (OMN-2002).

Deletion criteria
-----------------
Remove this entire module when the runtime supports dependency factories
and dispatcher wiring from contracts.

Required environment surface
----------------------------
- ``KAFKA_BOOTSTRAP_SERVERS``          — required (gate: should_activate)
- ``OMNICLAUDE_PUBLISHER_SOCKET_PATH`` — optional (default: /tmp/omniclaude-emit.sock)
- ``OMNICLAUDE_PUBLISHER_ENVIRONMENT`` — optional (default: dev)
- ``OMNICLAUDE_CONTRACTS_ROOT``        — optional (gate: wire_handlers)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_infra.runtime.protocol_domain_plugin import (
        ModelDomainPluginConfig,
        ModelDomainPluginResult,
    )

    from omniclaude.publisher.embedded_publisher import EmbeddedEventPublisher

logger = logging.getLogger(__name__)

_PLUGIN_ID = "claude"
_DISPLAY_NAME = "Claude Code Integration"


class PluginClaude:
    """Transitional bootstrap adapter for Claude Code kernel integration.

    Encapsulates the EmbeddedEventPublisher lifecycle and handler wiring
    into the kernel plugin protocol.  The constructor is deliberately
    side-effect-free (no env parsing, no network calls) so that
    module-level protocol checks are safe.

    Deletion criteria: remove when the runtime supports dependency factories
    + dispatcher wiring from contracts.
    """

    # ------------------------------------------------------------------
    # Construction — must be safe for module-level protocol check
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._publisher: EmbeddedEventPublisher | None = None
        self._publisher_config: object | None = None
        self._shutdown_in_progress: bool = False
        self._compliance_stop_event: threading.Event | None = None
        self._compliance_thread: threading.Thread | None = None
        self._decision_record_stop_event: threading.Event | None = None
        self._decision_record_thread: threading.Thread | None = None

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
        """Start the EmbeddedEventPublisher.

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

        try:
            from omniclaude.publisher.embedded_publisher import (
                EmbeddedEventPublisher,
            )
            from omniclaude.publisher.publisher_config import PublisherConfig

            publisher_config = PublisherConfig(
                kafka_bootstrap_servers=kafka_servers,
            )
            publisher = EmbeddedEventPublisher(config=publisher_config)
            await publisher.start()

            self._publisher_config = publisher_config
            self._publisher = publisher

            return ModelDomainPluginResult(
                plugin_id=_PLUGIN_ID,
                success=True,
                message="EmbeddedEventPublisher started",
                resources_created=[
                    "embedded-event-publisher",
                    "kafka-connection",
                ],
            )
        except Exception as exc:
            # Best-effort cleanup
            await self._cleanup_publisher()
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message=str(exc),
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
                message="Handler contracts published",
                services_registered=["wire_omniclaude_services"],
            )
        except Exception as exc:
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message=str(exc),
            )

    async def wire_dispatchers(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Dispatcher wiring is not yet contract-driven — skip."""
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        return ModelDomainPluginResult.skipped(
            plugin_id=_PLUGIN_ID,
            reason="dispatcher wiring not yet contract-driven",
        )

    async def start_consumers(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Start background Kafka subscriber threads.

        Starts two daemon subscriber threads:
        - compliance-evaluated subscriber: subscribes to
          ``onex.evt.omniintelligence.compliance-evaluated.v1`` and transforms
          violations into PatternAdvisory entries for context injection.
        - decision-record subscriber (OMN-2720): subscribes to
          ``onex.cmd.omniintelligence.decision-recorded.v1`` and appends full
          DecisionRecord payloads to the local audit log
          ``~/.claude/decision_audit.jsonl``.

        Skips gracefully when ``KAFKA_BOOTSTRAP_SERVERS`` is not set.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        # Shutdown guard: if shutdown() is in progress it has already cleared
        # subscriber threads to None but the old threads may still be draining.
        # Spawning new threads here would create consumers racing the
        # old ones — return early to prevent that.
        if self._shutdown_in_progress:
            logger.debug("Subscribers start skipped — shutdown in progress")
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="shutdown in progress; subscribers not started",
            )

        # Idempotency guard: SessionStart may be called multiple times on reconnect.
        # If both threads are still alive, return early rather than spawning second
        # daemon threads and silently leaking the first ones.
        if (
            self._compliance_thread is not None
            and self._compliance_thread.is_alive()
            and self._decision_record_thread is not None
            and self._decision_record_thread.is_alive()
        ):
            logger.debug("All subscribers already running — skipping duplicate start")
            return ModelDomainPluginResult(
                plugin_id=_PLUGIN_ID,
                success=True,
                message="Subscribers already running (idempotent)",
                resources_created=[],
            )

        bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        if not bootstrap_servers:
            logger.debug("KAFKA_BOOTSTRAP_SERVERS not set — subscribers not started")
            return ModelDomainPluginResult.skipped(
                plugin_id=_PLUGIN_ID,
                reason="KAFKA_BOOTSTRAP_SERVERS not set; subscribers skipped",
            )

        resources_created: list[str] = []

        # ----------------------------------------------------------------
        # Start compliance-evaluated subscriber
        # ----------------------------------------------------------------
        if self._compliance_thread is None or not self._compliance_thread.is_alive():
            try:
                from omniclaude.hooks.lib.compliance_result_subscriber import (  # noqa: PLC0415
                    run_subscriber_background as _compliance_run_bg,
                )

                self._compliance_stop_event = threading.Event()
                self._compliance_thread = _compliance_run_bg(
                    kafka_bootstrap_servers=bootstrap_servers,
                    group_id="omniclaude-compliance-subscriber.v1",
                    stop_event=self._compliance_stop_event,
                )
                resources_created.append("compliance-subscriber-thread")
            except Exception as exc:
                logger.warning("Failed to start compliance subscriber: %s", exc)
                self._compliance_stop_event = None
                self._compliance_thread = None

        # ----------------------------------------------------------------
        # Start decision-record subscriber (OMN-2720)
        # ----------------------------------------------------------------
        if (
            self._decision_record_thread is None
            or not self._decision_record_thread.is_alive()
        ):
            try:
                from omniclaude.hooks.lib.decision_record_subscriber import (  # noqa: PLC0415
                    run_subscriber_background as _decision_run_bg,
                )

                self._decision_record_stop_event = threading.Event()
                self._decision_record_thread = _decision_run_bg(
                    kafka_bootstrap_servers=bootstrap_servers,
                    group_id="omniclaude-decision-record-subscriber.v1",
                    stop_event=self._decision_record_stop_event,
                )
                resources_created.append("decision-record-subscriber-thread")
            except Exception as exc:
                logger.warning("Failed to start decision-record subscriber: %s", exc)
                self._decision_record_stop_event = None
                self._decision_record_thread = None

        if not resources_created:
            return ModelDomainPluginResult.failed(
                plugin_id=_PLUGIN_ID,
                error_message="All subscriber starts failed",
            )

        # ----------------------------------------------------------------
        # Publish skill node introspection events (OMN-2403)
        # ----------------------------------------------------------------
        # Best-effort: failures are caught by SkillNodeIntrospectionProxy
        # and logged, never propagated. Introspection is published with the
        # event bus from the publisher, or None if not yet started.
        try:
            from omniclaude.runtime.introspection import (  # noqa: PLC0415
                SkillNodeIntrospectionProxy,
            )

            introspection_proxy = SkillNodeIntrospectionProxy(
                event_bus=self._publisher,  # type: ignore[arg-type]
            )
            await introspection_proxy.publish_all(reason="startup")
            resources_created.append("skill-node-introspection")
        except Exception as exc:
            logger.warning("Skill node introspection proxy failed to start: %s", exc)

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
        """Idempotent, exception-safe shutdown.

        Stops the publisher and clears all references regardless of
        whether stop() raises.  Also signals the compliance subscriber
        daemon thread to stop gracefully.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        if self._shutdown_in_progress:
            return ModelDomainPluginResult.succeeded(plugin_id=_PLUGIN_ID)

        self._shutdown_in_progress = True
        try:
            # Signal compliance subscriber to stop (non-blocking — thread drains itself)
            if self._compliance_stop_event is not None:
                self._compliance_stop_event.set()
                self._compliance_stop_event = None
                # Intentionally not joined: the daemon thread will drain its own
                # Kafka poll loop once the stop_event is set, then exit naturally.
                # Blocking here would delay shutdown and risk deadlock if the
                # Kafka consumer is stuck waiting on a network call.
                # stop_event already set; daemon self-terminates.
                # Narrow race: if start_consumers() is called before the daemon fully stops,
                # stop_event being set means the thread will exit without processing new work.
                # No data loss risk — the publisher handles event delivery independently.
            # Clear unconditionally: if _compliance_thread is set but
            # _compliance_stop_event is None (e.g. partially initialised state),
            # the thread reference must still be released to avoid a leak.
            self._compliance_thread = None

            # Signal decision-record subscriber to stop (OMN-2720)
            if self._decision_record_stop_event is not None:
                self._decision_record_stop_event.set()
                self._decision_record_stop_event = None
            self._decision_record_thread = None

            if self._publisher is None:
                return ModelDomainPluginResult.succeeded(
                    plugin_id=_PLUGIN_ID,
                    message="No publisher to shut down",
                )

            errors: list[str] = []
            try:
                # EmbeddedEventPublisher.stop() is async
                await self._publisher.stop()
            except Exception as exc:
                errors.append(str(exc))

            # Clear references regardless of outcome
            self._publisher = None
            self._publisher_config = None

            if errors:
                return ModelDomainPluginResult.failed(
                    plugin_id=_PLUGIN_ID,
                    error_message="; ".join(errors),
                )
            return ModelDomainPluginResult.succeeded(
                plugin_id=_PLUGIN_ID,
                message="Publisher stopped",
            )
        finally:
            self._shutdown_in_progress = False

    # ------------------------------------------------------------------
    # Extra: status line (not part of protocol)
    # ------------------------------------------------------------------

    def get_status_line(self) -> str:
        """Return human-readable status for diagnostics."""
        if self._publisher is None:
            return "disabled"
        return "enabled (Publisher + Kafka)"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _cleanup_publisher(self) -> None:
        """Best-effort cleanup after a failed initialisation."""
        if self._publisher is not None:
            try:
                await self._publisher.stop()
            except Exception:
                logger.debug("Cleanup: publisher stop failed", exc_info=True)
        self._publisher = None
        self._publisher_config = None


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
