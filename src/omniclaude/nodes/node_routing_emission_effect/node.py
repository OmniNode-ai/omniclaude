# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Routing Emission Effect - 100% contract-driven.

This module provides the NodeRoutingEmissionEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: routing.emission

The node exposes one operation:
- emit_routing_decision: Emit a routing decision event to configured topics

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolRoutingEmitter). The actual emission backend (e.g., Kafka)
implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeRoutingEmissionEffect(NodeEffect):
    """Effect node for routing decision emission.

    Capability: routing.emission

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the routing emission effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeRoutingEmissionEffect"]
