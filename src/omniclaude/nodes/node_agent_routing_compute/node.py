# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Agent Routing Compute - 100% contract-driven.

This module provides the NodeAgentRoutingCompute class, a minimal shell
that inherits from NodeCompute. All compute logic is driven by the contract.yaml.

Capability: agent.routing.compute

The node exposes one operation:
- compute_routing: Compute routing decision for a user prompt

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolAgentRouting). The actual routing backend implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeAgentRoutingCompute(NodeCompute[Any, Any]):
    """Compute node for agent routing decisions.

    Capability: agent.routing.compute

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the agent routing compute node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeAgentRoutingCompute"]
