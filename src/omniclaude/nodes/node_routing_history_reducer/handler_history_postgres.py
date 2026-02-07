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
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from omniclaude.nodes.node_routing_history_reducer.models import (
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
)

logger = logging.getLogger(__name__)

# Default success rate matching ConfidenceScorer._calculate_historical_score
_DEFAULT_SUCCESS_RATE = 0.5

# Max tracked correlation_ids before eviction (Phase 1 in-memory limit)
_MAX_DEDUP_ENTRIES = 10_000


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

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the handler with an empty in-memory store.

        Args:
            clock: Optional callable returning current UTC datetime.
                Defaults to ``lambda: datetime.now(UTC)``.
                Inject a deterministic clock for testing.
        """
        self._lock = threading.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        # agent_name -> list of recorded entries (append-only)
        self._store: dict[str, list[ModelAgentStatsEntry]] = {}
        # Track seen correlation_ids for idempotency
        self._seen_correlation_ids: set[UUID] = set()

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
            # Idempotency: skip duplicate correlation_ids
            if cid in self._seen_correlation_ids:
                logger.debug(
                    "Duplicate correlation_id=%s for agent=%s, skipping",
                    cid,
                    entry.agent_name,
                )
                return self._build_stats_snapshot()

            # Evict oldest entries when cap reached (Phase 1 approximation;
            # Phase 2+ will use database-level UPSERT for true idempotency)
            if len(self._seen_correlation_ids) >= _MAX_DEDUP_ENTRIES:
                self._seen_correlation_ids.clear()
                logger.info("Dedup cache evicted at %d entries", _MAX_DEDUP_ENTRIES)

            self._seen_correlation_ids.add(cid)

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

    def _total_decisions(self) -> int:
        """Count total routing decisions across all agents.

        Per ProtocolHistoryStore contract, total_routing_decisions is always
        global (across all agents) regardless of query filter.
        """
        return sum(len(entries) for entries in self._store.values())

    def _build_stats_for_agent(self, agent_name: str) -> ModelAgentRoutingStats:
        """Build a stats snapshot for a single agent.

        If the agent has no recorded history, returns default stats with
        success_rate=0.5. The total_routing_decisions count is always global
        (across all agents) per the protocol specification.

        Args:
            agent_name: The agent to build stats for.

        Returns:
            ModelAgentRoutingStats containing a single entry for the agent.
        """
        entries_list = self._store.get(agent_name)
        global_total = self._total_decisions()

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
                total_routing_decisions=global_total,
                snapshot_at=self._clock(),
            )

        aggregate_entry = self._aggregate_entries(agent_name, entries_list)
        return ModelAgentRoutingStats(
            entries=(aggregate_entry,),
            total_routing_decisions=global_total,
            snapshot_at=self._clock(),
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
                snapshot_at=self._clock(),
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
            snapshot_at=self._clock(),
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
