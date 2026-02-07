# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Handler for routing history storage via PostgreSQL.

Phase 1: In-memory storage returning default statistics (0.5 success rate).
Phase 2+: Will use actual PostgreSQL queries for real historical data.

Implements ProtocolHistoryStore.

Design Notes:
    - Thread-safe via threading.Lock on the in-memory store
    - No external dependencies (pure Python for Phase 1)
    - Default success_rate of 0.5 matches existing ConfidenceScorer behavior
      (see confidence_scorer.py: _calculate_historical_score)
    - The in-memory store is intentional for Phase 1; entries are lost on
      process restart. Phase 2+ will persist to PostgreSQL.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

from omniclaude.nodes.node_routing_history_reducer.models import (
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
)

logger = logging.getLogger(__name__)

# Default success rate matching ConfidenceScorer._calculate_historical_score
_DEFAULT_SUCCESS_RATE = 0.5


class HandlerHistoryPostgres:
    """Handler for routing history storage via PostgreSQL.

    Phase 1: Returns default statistics (0.5 success rate).
    Phase 2+: Will use actual PostgreSQL queries for real historical data.

    Implements ProtocolHistoryStore.

    Thread Safety:
        All access to the in-memory store is protected by a threading.Lock.
        This ensures correctness when hooks or async tasks access the handler
        concurrently from different threads.

    Example:
        >>> handler = HandlerHistoryPostgres()
        >>> assert handler.handler_key == "postgresql"
        >>> entry = ModelAgentStatsEntry(agent_name="api-architect")
        >>> import asyncio
        >>> stats = asyncio.run(handler.record_routing_decision(entry))
        >>> assert stats.total_routing_decisions == 1
    """

    def __init__(self) -> None:
        """Initialize the handler with an empty in-memory store."""
        self._lock = threading.Lock()
        # agent_name -> list of recorded entries (append-only)
        self._store: dict[str, list[ModelAgentStatsEntry]] = {}

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing.

        Returns:
            The string 'postgresql' identifying this backend type.
        """
        return "postgresql"

    async def record_routing_decision(
        self,
        entry: ModelAgentStatsEntry,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRoutingStats:
        """Record a routing decision and return updated stats snapshot.

        Accepts the entry, stores it in the in-memory dict keyed by
        agent_name, and returns the current aggregate stats snapshot.

        Args:
            entry: The per-agent statistics entry to record. Must include
                at minimum an agent_name.
            correlation_id: Optional correlation ID for request tracing.
                If not provided, one is generated internally.

        Returns:
            ModelAgentRoutingStats snapshot reflecting all recorded decisions
            including the newly recorded entry.
        """
        cid = correlation_id or uuid4()

        with self._lock:
            if entry.agent_name not in self._store:
                self._store[entry.agent_name] = []
            self._store[entry.agent_name].append(entry)

            logger.debug(
                "Recorded routing decision for agent=%s "
                "total_entries=%d correlation_id=%s",
                entry.agent_name,
                len(self._store[entry.agent_name]),
                cid,
            )

            return self._build_stats_snapshot()

    async def query_routing_stats(
        self,
        agent_name: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRoutingStats:
        """Query historical routing statistics.

        If agent_name is provided, returns stats filtered to that agent only.
        If agent_name is None, returns aggregate stats for all agents.

        When no history exists for an agent, returns default stats with a
        success_rate of 0.5, matching the existing ConfidenceScorer behavior.

        Args:
            agent_name: If provided, return stats for this agent only.
                If None, return aggregate stats for all agents.
            correlation_id: Optional correlation ID for request tracing.
                If not provided, one is generated internally.

        Returns:
            ModelAgentRoutingStats snapshot, optionally filtered by agent_name.
        """
        cid = correlation_id or uuid4()

        with self._lock:
            if agent_name is not None:
                logger.debug(
                    "Querying routing stats for agent=%s correlation_id=%s",
                    agent_name,
                    cid,
                )
                return self._build_stats_for_agent(agent_name)

            logger.debug(
                "Querying aggregate routing stats correlation_id=%s",
                cid,
            )
            return self._build_stats_snapshot()

    # ------------------------------------------------------------------
    # Private helpers (must be called while holding self._lock)
    # ------------------------------------------------------------------

    def _build_stats_for_agent(self, agent_name: str) -> ModelAgentRoutingStats:
        """Build a stats snapshot for a single agent.

        If the agent has no recorded history, returns default stats with
        success_rate=0.5.

        Args:
            agent_name: The agent to build stats for.

        Returns:
            ModelAgentRoutingStats containing a single entry for the agent.
        """
        entries_list = self._store.get(agent_name)

        if not entries_list:
            # No history: return default stats matching ConfidenceScorer
            default_entry = ModelAgentStatsEntry(
                agent_name=agent_name,
                total_routings=0,
                successful_routings=0,
                success_rate=_DEFAULT_SUCCESS_RATE,
                avg_confidence=0.0,
                last_routed_at=None,
            )
            return ModelAgentRoutingStats(
                entries=(default_entry,),
                total_routing_decisions=0,
                snapshot_at=datetime.now(UTC),
            )

        aggregate_entry = self._aggregate_entries(agent_name, entries_list)
        return ModelAgentRoutingStats(
            entries=(aggregate_entry,),
            total_routing_decisions=len(entries_list),
            snapshot_at=datetime.now(UTC),
        )

    def _build_stats_snapshot(self) -> ModelAgentRoutingStats:
        """Build an aggregate stats snapshot across all agents.

        Returns:
            ModelAgentRoutingStats with one entry per agent and the total
            routing decision count across all agents.
        """
        if not self._store:
            return ModelAgentRoutingStats(
                entries=(),
                total_routing_decisions=0,
                snapshot_at=datetime.now(UTC),
            )

        agent_entries: list[ModelAgentStatsEntry] = []
        total_decisions = 0

        for agent_name, entries_list in sorted(self._store.items()):
            aggregate_entry = self._aggregate_entries(agent_name, entries_list)
            agent_entries.append(aggregate_entry)
            total_decisions += len(entries_list)

        return ModelAgentRoutingStats(
            entries=tuple(agent_entries),
            total_routing_decisions=total_decisions,
            snapshot_at=datetime.now(UTC),
        )

    @staticmethod
    def _aggregate_entries(
        agent_name: str,
        entries: list[ModelAgentStatsEntry],
    ) -> ModelAgentStatsEntry:
        """Aggregate a list of entries into a single summary entry.

        Computes totals, averages, and the most recent routing timestamp
        from the recorded entries for a given agent.

        Args:
            agent_name: The agent name for the aggregate entry.
            entries: Non-empty list of recorded entries to aggregate.

        Returns:
            A single ModelAgentStatsEntry summarizing all recorded entries.
        """
        total_routings = sum(e.total_routings for e in entries)
        successful_routings = sum(e.successful_routings for e in entries)

        # Compute success_rate from aggregate counts, falling back to default
        if total_routings > 0:
            success_rate = successful_routings / total_routings
        else:
            success_rate = _DEFAULT_SUCCESS_RATE

        # Weighted average confidence (by total_routings per entry)
        total_weight = sum(e.total_routings for e in entries)
        if total_weight > 0:
            avg_confidence = (
                sum(e.avg_confidence * e.total_routings for e in entries) / total_weight
            )
        else:
            # Fall back to simple average when no routings recorded
            avg_confidence = (
                sum(e.avg_confidence for e in entries) / len(entries)
                if entries
                else 0.0
            )

        # Most recent routing timestamp
        routed_times = [
            e.last_routed_at for e in entries if e.last_routed_at is not None
        ]
        last_routed_at = max(routed_times) if routed_times else None

        return ModelAgentStatsEntry(
            agent_name=agent_name,
            total_routings=total_routings,
            successful_routings=successful_routings,
            success_rate=round(success_rate, 6),
            avg_confidence=round(avg_confidence, 6),
            last_routed_at=last_routed_at,
        )


__all__ = ["HandlerHistoryPostgres"]
