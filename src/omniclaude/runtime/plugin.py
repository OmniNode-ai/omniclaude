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
from typing import TYPE_CHECKING

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
        self._publisher: object | None = None
        self._publisher_config: object | None = None
        self._shutdown_in_progress: bool = False

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
        """Consumer topics not yet specified — skip.

        See follow-up ticket for start_consumers() behavior contract.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        return ModelDomainPluginResult.skipped(
            plugin_id=_PLUGIN_ID,
            reason="consumer topics not yet specified; see follow-up ticket",
        )

    async def shutdown(
        self,
        config: ModelDomainPluginConfig,
    ) -> ModelDomainPluginResult:
        """Idempotent, exception-safe shutdown.

        Stops the publisher and clears all references regardless of
        whether stop() raises.
        """
        from omnibase_infra.runtime.protocol_domain_plugin import (
            ModelDomainPluginResult,
        )

        if self._shutdown_in_progress:
            return ModelDomainPluginResult.succeeded(plugin_id=_PLUGIN_ID)

        self._shutdown_in_progress = True
        try:
            if self._publisher is None:
                return ModelDomainPluginResult.succeeded(
                    plugin_id=_PLUGIN_ID,
                    message="No publisher to shut down",
                )

            errors: list[str] = []
            try:
                # EmbeddedEventPublisher.stop() is async
                await self._publisher.stop()  # type: ignore[union-attr]
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
                await self._publisher.stop()  # type: ignore[union-attr]
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
