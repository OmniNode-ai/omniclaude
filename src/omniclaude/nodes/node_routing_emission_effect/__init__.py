# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeRoutingEmissionEffect - Contract-driven effect node for routing emission.

This package provides the NodeRoutingEmissionEffect node for emitting
routing decision events with pluggable backends.

Capability: routing.emission

Exported Components:
    Node:
        NodeRoutingEmissionEffect - The effect node class (minimal shell)

    Models:
        ModelEmissionRequest - Routing decision emission request
        ModelEmissionResult - Emission operation result

    Protocols:
        ProtocolRoutingEmitter - Interface for emission backends

Example Usage:
    ```python
    from omniclaude.nodes.node_routing_emission_effect import (
        NodeRoutingEmissionEffect,
        ModelEmissionRequest,
        ProtocolRoutingEmitter,
    )

    # Resolve handler via container
    handler = await container.get_service_async(ProtocolRoutingEmitter)

    # Emit routing decision
    result = await handler.emit_routing_decision(request, correlation_id=cid)
    ```
"""

from .models import (
    ModelEmissionRequest,
    ModelEmissionResult,
)
from .node import NodeRoutingEmissionEffect
from .protocols import ProtocolRoutingEmitter

__all__ = [
    # Node
    "NodeRoutingEmissionEffect",
    # Models
    "ModelEmissionRequest",
    "ModelEmissionResult",
    # Protocols
    "ProtocolRoutingEmitter",
]
