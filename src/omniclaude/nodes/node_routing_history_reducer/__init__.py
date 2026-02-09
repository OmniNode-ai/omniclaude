# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeRoutingHistoryReducer - Contract-driven reducer node for routing history.

This package provides the NodeRoutingHistoryReducer node for recording routing
decisions and querying historical agent performance statistics with pluggable
backends.

Capability: routing.history

Exported Components:
    Node:
        NodeRoutingHistoryReducer - The reducer node class (minimal shell)

    Models:
        ModelAgentStatsEntry - Per-agent statistics entry for routing decisions
        ModelAgentRoutingStats - Aggregate routing statistics snapshot

    Protocols:
        ProtocolHistoryStore - Interface for history storage backends

Example Usage:
    ```python
    from omniclaude.nodes.node_routing_history_reducer import (
        NodeRoutingHistoryReducer,
        ModelAgentStatsEntry,
        ProtocolHistoryStore,
    )

    # Resolve handler via container
    handler = await container.get_service_async(ProtocolHistoryStore)

    # Query routing stats
    result = await handler.query_routing_stats(agent_name="api-architect")
    ```
"""

from .models import (
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
)
from .node import NodeRoutingHistoryReducer
from .protocols import ProtocolHistoryStore

__all__ = [
    # Node
    "NodeRoutingHistoryReducer",
    # Models
    "ModelAgentStatsEntry",
    "ModelAgentRoutingStats",
    # Protocols
    "ProtocolHistoryStore",
]
