# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Routing History Reducer - 100% contract-driven.

This module provides the NodeRoutingHistoryReducer class, a minimal shell
that inherits from NodeReducer. All reducer logic is driven by the contract.yaml.

Capability: routing.history

The node exposes two operations:
- record_routing_decision: Record routing decisions for historical tracking
- query_routing_stats: Query historical agent performance statistics

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolHistoryStore). The actual storage backend (e.g., PostgreSQL)
implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_reducer import NodeReducer

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeRoutingHistoryReducer(NodeReducer[Any, Any]):
    """Reducer node for routing history operations.

    Capability: routing.history

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the routing history reducer node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeRoutingHistoryReducer"]
