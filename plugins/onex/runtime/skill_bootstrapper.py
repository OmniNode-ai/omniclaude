# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SkillBootstrapper: lightweight in-memory runtime for skill execution.

Manages lifecycle (initialize/shutdown) and invocation for the skill
bootstrapper runtime. The bootstrapper owns schema normalization and result
wrapping -- handlers execute behavior only.

Uses ``EventBusInmemory`` for topology parity -- not for production routing.
All dispatch is synchronous in Phase 1.

Dependency boundary rule:
    Only ``EventBusInmemory`` is imported from omnibase_infra.
    No imports from ``omnibase_infra.runtime.*``.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from omnibase_core.container import ModelONEXContainer
from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

from plugins.onex.runtime.models import (
    SkillConfigurationError,
    SkillContext,
    SkillExecutionError,
    SkillNotFoundError,
    SkillResult,
)
from plugins.onex.runtime.util_skill_wiring import wire_skill_handlers_only

if TYPE_CHECKING:
    pass

SUPPORTED_RUNTIMES: frozenset[str] = frozenset(
    {"skill-bootstrapper", "mcp", "ci-script", "gh-native", "legacy-bash"}
)

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
        self._skill_registry: dict[str, dict[str, Any]] = {}

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
        self._skill_registry.clear()

    def register_skill(
        self,
        skill_name: str,
        *,
        runtime: str = "skill-bootstrapper",
        handler_name: str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a skill with the bootstrapper.

        Args:
            skill_name: Canonical skill name (e.g., ``ci-watch``).
            runtime: Runtime mode from skill YAML front-matter.
            handler_name: Handler class name to resolve for execution.
            schema: Optional input schema for validation.
        """
        self._skill_registry[skill_name] = {
            "runtime": runtime,
            "handler_name": handler_name,
            "schema": schema or {},
        }

    async def invoke(
        self,
        skill_name: str,
        inputs: dict[str, Any],
        *,
        context: SkillContext | None = None,
    ) -> SkillResult:
        """Invoke a skill through the bootstrapper's 5-step error contract.

        The bootstrapper owns schema normalization and result wrapping.
        Handlers execute behavior only and return ``dict[str, Any]``.

        Steps:
            1. Validate ``skill_name`` exists in registry
            2. Normalize inputs against schema
            3. Resolve handler from ``runtime:`` metadata
            4. Execute handler (catch all exceptions)
            5. Return ``SkillResult``

        Args:
            skill_name: Canonical skill name.
            inputs: Skill-specific inputs.
            context: Optional invocation context.

        Returns:
            SkillResult with success/failure and structured output.

        Raises:
            SkillNotFoundError: If skill_name is not registered.
            SkillConfigurationError: If runtime value is unsupported.
        """
        invocation_id = context.invocation_id if context else str(uuid4())
        start_ms = _now_ms()

        # Step 1: Validate skill exists
        if skill_name not in self._skill_registry:
            raise SkillNotFoundError(
                f"Skill {skill_name!r} not found in registry. "
                f"Registered skills: {sorted(self._skill_registry.keys())}"
            )

        skill_meta = self._skill_registry[skill_name]

        # Step 2: Normalize inputs (validate against schema if present)
        schema = skill_meta.get("schema", {})
        if schema:
            required_fields = schema.get("required", [])
            missing = [f for f in required_fields if f not in inputs]
            if missing:
                from plugins.onex.runtime.models import SkillInputValidationError

                raise SkillInputValidationError(
                    f"Missing required inputs for {skill_name!r}: {missing}"
                )

        # Step 3: Resolve handler from runtime metadata
        runtime = skill_meta.get("runtime", "skill-bootstrapper")
        if runtime not in SUPPORTED_RUNTIMES:
            raise SkillConfigurationError(
                f"Unsupported runtime {runtime!r} for skill {skill_name!r}. "
                f"Supported values: {sorted(SUPPORTED_RUNTIMES)}"
            )

        handler_name = skill_meta.get("handler_name")
        handler_used = None

        # Step 4: Execute handler
        try:
            output: dict[str, Any] = {}
            if handler_name and self._container:
                registry = self._container.service_registry
                if handler_name in registry._name_map:
                    handler_used = handler_name
                    # For now, stub execution -- full handler dispatch in future
                    output = {
                        "handler": handler_name,
                        "skill": skill_name,
                        "status": "executed",
                    }
                else:
                    output = {
                        "handler": handler_name,
                        "skill": skill_name,
                        "status": "handler_not_in_registry",
                    }
            else:
                output = {"skill": skill_name, "status": "no_handler_configured"}

        except Exception as exc:
            duration_ms = _now_ms() - start_ms
            raise SkillExecutionError(
                f"Handler execution failed for {skill_name!r}: {exc}"
            ) from exc

        # Step 5: Return SkillResult
        duration_ms = _now_ms() - start_ms
        return SkillResult(
            success=True,
            skill_name=skill_name,
            invocation_id=invocation_id,
            output=output,
            handler_used=handler_used,
            duration_ms=duration_ms,
            runtime_mode=runtime,
        )


def _now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.monotonic() * 1000)
