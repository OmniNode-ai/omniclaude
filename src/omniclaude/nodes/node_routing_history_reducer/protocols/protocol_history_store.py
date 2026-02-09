# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for routing history storage backends.

Operation Mapping (from node contract io_operations):
    - record_routing_decision operation -> ProtocolHistoryStore.record_routing_decision()
    - query_routing_stats operation -> ProtocolHistoryStore.query_routing_stats()

Implementors must:
    1. Provide handler_key property identifying the backend (e.g., 'postgresql')
    2. Implement record_routing_decision with idempotent behavior
    3. Implement query_routing_stats with optional agent_name filtering

Result Semantics:
    - record_routing_decision returns an updated ModelAgentRoutingStats snapshot
      reflecting the recorded decision
    - query_routing_stats returns a ModelAgentRoutingStats snapshot filtered by
      agent_name if provided, or all agents if agent_name is None
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from omniclaude.nodes.node_routing_history_reducer.models import (
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
)


@runtime_checkable
class ProtocolHistoryStore(Protocol):
    """Protocol for routing history storage backends.

    This protocol defines the interface for storage backends that persist and
    retrieve routing decision history. Implementations are responsible for:

    - Recording routing decisions with idempotent behavior
    - Querying historical routing statistics per agent or across all agents
    - Supporting correlation ID tracing for request provenance

    Attributes:
        handler_key: Backend identifier used for routing (e.g., 'postgresql')

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolHistoryStore)
        result = await handler.query_routing_stats(agent_name="api-architect")
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'postgresql', 'sqlite', 'memory').

        This key is used for handler routing when multiple backends are
        registered. The node contract's handler_routing.backends configuration
        maps backend keys to handler implementations.
        """
        ...

    async def record_routing_decision(
        self,
        entry: ModelAgentStatsEntry,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRoutingStats:
        """Record a routing decision for historical tracking.

        This operation is idempotent: recording the same decision multiple times
        (identified by correlation_id) will not create duplicate entries.

        The implementation should update aggregate statistics (total_routings,
        successful_routings, success_rate, avg_confidence) for the agent
        identified in the entry.

        Args:
            entry: The agent stats entry representing the routing decision
                   to record. Contains agent_name, routing counts, and
                   confidence metrics.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelAgentRoutingStats with updated aggregate statistics reflecting
            the newly recorded decision. The snapshot_at field should indicate
            when the snapshot was taken.
        """
        ...

    async def query_routing_stats(
        self,
        agent_name: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRoutingStats:
        """Query historical routing statistics for agents.

        Returns aggregate routing performance statistics, optionally filtered
        to a specific agent by name.

        Args:
            agent_name: Optional agent name to filter statistics.
                       If None, returns statistics for all agents.
                       If provided, returns statistics only for the named agent.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelAgentRoutingStats with:
                - entries: Tuple of ModelAgentStatsEntry objects (filtered
                          by agent_name if provided)
                - total_routing_decisions: Total decisions recorded
                          (across all agents, regardless of filter)
                - snapshot_at: When this statistics snapshot was taken
        """
        ...
