# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Manual service wiring for omniclaude handlers.

This module provides explicit handler registration with the container's
ServiceRegistry. This is the MVP approach using manual wiring.

Manual Wiring Strategy:
    - Handler contracts define what handlers exist and their capabilities
    - Node contracts define what protocols nodes require
    - This module explicitly binds protocol -> handler instance in container

Follow-up: OMN-XXXX will implement contract-driven handler registration
where the loader reads handler contracts and auto-registers handlers,
eliminating the need for manual wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.enums.enum_injection_scope import EnumInjectionScope

from omniclaude.handlers.pattern_storage_postgres.handler_pattern_storage_postgres import (
    HandlerPatternStoragePostgres,
)
from omniclaude.nodes.node_pattern_persistence_effect.protocols import (
    ProtocolPatternPersistence,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


async def wire_omniclaude_services(container: ModelONEXContainer) -> None:
    """Register omniclaude handlers with container.

    This function performs manual service wiring, binding handler implementations
    to their protocol interfaces in the container's ServiceRegistry.

    Manual wiring for MVP. Follow-up ticket will implement contract-driven loader.

    The wiring establishes:
        - ProtocolPatternPersistence -> HandlerPatternStoragePostgres

    After wiring, consumers can resolve handlers via:
        handler = await container.get_service_async(ProtocolPatternPersistence)

    Args:
        container: The ONEX container with ServiceRegistry for DI bindings.

    Example:
        from omniclaude.runtime import wire_omniclaude_services

        # During application bootstrap
        container = ModelONEXContainer(...)
        await wire_omniclaude_services(container)

        # Later, in handler_context_injection or other consumers
        handler = await container.get_service_async(ProtocolPatternPersistence)
        result = await handler.query_patterns(query)
    """
    # Create handler instance with container dependency
    handler = HandlerPatternStoragePostgres(container)

    # Register handler as the implementation of ProtocolPatternPersistence
    # Using GLOBAL scope since the handler is stateless and thread-safe
    await container.service_registry.register_instance(
        interface=ProtocolPatternPersistence,
        instance=handler,
        scope=EnumInjectionScope.GLOBAL,
        metadata={"handler_key": "postgresql", "version": "1.0.0"},
    )
