# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Service wiring for omniclaude handlers.

This module bootstraps handler registration using contract-driven discovery.
Handlers are automatically discovered from contracts/handlers/**/contract.yaml
and registered with the container's ServiceRegistry.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

Contract-Driven Wiring Strategy:
    - Handler contracts define handler class, protocol, and capabilities
    - This module calls register_all_handlers() to discover and register all handlers
    - No manual imports or instantiation required for contract-defined handlers

For special cases that cannot be contract-driven, add manual registrations
below with a comment explaining WHY contract-driven doesn't work.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from omniclaude.contracts.registration import register_all_handlers

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


async def wire_omniclaude_services(container: ModelONEXContainer) -> None:
    """Register omniclaude handlers with container using contract discovery.

    This function performs contract-driven service wiring by discovering
    handler contracts and automatically registering handlers with the
    container's ServiceRegistry.

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
        from omniclaude.nodes.node_pattern_persistence_effect.protocols import (
            ProtocolPatternPersistence,
        )
        handler = await container.get_service_async(ProtocolPatternPersistence)
        result = await handler.query_patterns(query)
    """
    # Contract-driven handler registration
    # Path: src/omniclaude/runtime/wiring.py -> contracts/handlers/
    contracts_root = (
        Path(__file__).parent.parent.parent.parent / "contracts" / "handlers"
    )
    await register_all_handlers(container, contracts_root)

    # === Special manual registrations (explain WHY if adding any) ===
    # Currently none - all handlers are contract-driven
    #
    # If you need to add a manual registration, document WHY it cannot be
    # contract-driven. Valid reasons might include:
    # - Handler requires runtime-only configuration not expressible in YAML
    # - Handler is dynamically loaded based on environment variables
    # - Handler is a third-party class that doesn't follow our contract pattern
