# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SkillBootstrapper: lightweight in-memory runtime for skill execution.

Manages lifecycle (initialize/shutdown) for the skill bootstrapper runtime.
Uses ``EventBusInmemory`` for topology parity -- not for production routing.
All dispatch is synchronous in Phase 1.

Dependency boundary rule:
    Only ``EventBusInmemory`` is imported from omnibase_infra.
    No imports from ``omnibase_infra.runtime.*``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from omnibase_core.container import ModelONEXContainer
from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

from plugins.onex.runtime.util_skill_wiring import wire_skill_handlers_only

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SkillBootstrapper:
    """Lightweight in-memory runtime bootstrapper for skill execution.

    Lifecycle:
        1. ``initialize()`` -- start event bus, wire handlers
        2. Use bootstrapper for skill invocation (Phase 2: invoke())
        3. ``shutdown()`` -- stop event bus, clear registry

    The bootstrapper owns normalization and result wrapping.
    Handlers execute behavior only.

    Partial-init failure contract:
        If ``initialize()`` fails after event bus start but before wiring
        completes, ``shutdown()`` still closes the bus cleanly. After
        ``shutdown()``, the bootstrapper is safe to re-``initialize()``.
    """

    def __init__(self) -> None:
        self._container: ModelONEXContainer | None = None
        self._event_bus: EventBusInmemory | None = None
        self._initialized: bool = False

    @property
    def initialized(self) -> bool:
        """Whether the bootstrapper has been fully initialized."""
        return self._initialized

    @property
    def container(self) -> ModelONEXContainer | None:
        """The ONEX container, or None if not initialized."""
        return self._container

    @property
    def event_bus(self) -> EventBusInmemory | None:
        """The in-memory event bus, or None if not initialized."""
        return self._event_bus

    async def initialize(self) -> None:
        """Start the bootstrapper runtime.

        1. Check that ONEX_EVENT_BUS_TYPE is not 'kafka' (fail fast)
        2. Create and start EventBusInmemory
        3. Create container and wire skill handlers

        Raises:
            NotImplementedError: If ONEX_EVENT_BUS_TYPE=kafka
            RuntimeError: If already initialized
        """
        if self._initialized:
            raise RuntimeError("SkillBootstrapper is already initialized")

        # Fail fast if someone tries to use Kafka with the bootstrapper
        bus_type = os.environ.get("ONEX_EVENT_BUS_TYPE", "").lower()
        if bus_type == "kafka":
            raise NotImplementedError(
                "SkillBootstrapper does not support ONEX_EVENT_BUS_TYPE=kafka. "
                "The bootstrapper uses EventBusInmemory for topology parity only."
            )

        # Step 1: Start event bus (topology parity, not routing)
        self._event_bus = EventBusInmemory(
            environment="skill-bootstrapper",
            group="skill-handlers",
        )
        await self._event_bus.start()
        logger.info("SkillBootstrapper: EventBusInmemory started")

        # Step 2: Create container and wire handlers
        # If wiring fails, _event_bus is set but _initialized remains False
        # shutdown() will still close the bus cleanly
        self._container = ModelONEXContainer()
        await wire_skill_handlers_only(self._container)
        logger.info("SkillBootstrapper: handlers wired into container")

        self._initialized = True

    async def shutdown(self) -> None:
        """Stop the bootstrapper runtime.

        Stops the event bus and clears the handler registry.
        Safe to call even if initialization was partial (bus started but
        wiring failed).
        """
        if self._event_bus is not None:
            try:
                await self._event_bus.shutdown()
                logger.info("SkillBootstrapper: EventBusInmemory stopped")
            except Exception:
                logger.warning(
                    "SkillBootstrapper: error during event bus shutdown",
                    exc_info=True,
                )
            self._event_bus = None

        if self._container is not None:
            # Clear the service registry
            registry = self._container.service_registry
            registry._registrations.clear()
            registry._name_map.clear()
            registry._interface_map.clear()
            self._container = None
            logger.info("SkillBootstrapper: container registry cleared")

        self._initialized = False
