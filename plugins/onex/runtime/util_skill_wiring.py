# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Skill handler wiring for the bootstrapper runtime.

``wire_skill_handlers_only()`` registers ``HandlerGitHub`` and ``HandlerBash``
into the ONEX container's service registry. This is the ONLY wiring function
for the bootstrapper -- it deliberately excludes database, Qdrant, Infisical,
and Kafka production-runtime handlers.

Dependency boundary rule:
    Only ``omnibase_infra.event_bus.event_bus_inmemory.EventBusInmemory`` is
    imported from omnibase_infra. No imports from ``omnibase_infra.runtime.*``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.enums import EnumInjectionScope, EnumServiceLifecycle

from plugins.onex.runtime.handlers.handler_bash import HandlerBash
from plugins.onex.runtime.handlers.handler_github import HandlerGitHub

if TYPE_CHECKING:
    from omnibase_core.container import ModelONEXContainer


async def wire_skill_handlers_only(container: ModelONEXContainer) -> None:
    """Register skill bootstrapper handlers into the container service registry.

    Registers:
        - HandlerGitHub (singleton, global scope)
        - HandlerBash (transient, request scope)

    No database, Qdrant, or Kafka handlers are registered.
    The bootstrapper owns normalization -- handlers execute behavior only.

    Args:
        container: The ONEX container whose service_registry receives registrations.
    """
    registry = container.service_registry

    await registry.register_service(
        interface=HandlerGitHub,
        implementation=HandlerGitHub,
        lifecycle=EnumServiceLifecycle.SINGLETON,
        scope=EnumInjectionScope.GLOBAL,
    )

    await registry.register_service(
        interface=HandlerBash,
        implementation=HandlerBash,
        lifecycle=EnumServiceLifecycle.TRANSIENT,
        scope=EnumInjectionScope.REQUEST,
    )
