# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Manifest Injector Models

Data classes, enums, and type aliases extracted from manifest_injector.py.
These are the pure data structures used by the ManifestInjector subsystem.

Classes:
    EnumTargetAgent: Valid target agent values for manifest metadata.
    DisabledPattern: A pattern or pattern class that has been disabled.
    CacheMetrics: Cache performance metrics tracking.
    CacheEntry: Individual cache entry with data and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EnumTargetAgent(StrEnum):
    """Valid target agent values for manifest metadata."""

    GENERAL_PURPOSE = "general-purpose"
    ALL_SPECIALIZED_AGENTS = "all-specialized-agents"


@dataclass
class DisabledPattern:
    """A pattern or pattern class that has been disabled via the kill switch.

    Populated from the disabled_patterns_current materialized view, which
    computes the current disable state from the pattern_disable_events log.
    """

    pattern_id: str | None
    pattern_class: str | None
    reason: str
    event_at: datetime | None
    actor: str


@dataclass
class CacheMetrics:
    """Cache performance metrics tracking."""

    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_query_time_ms: int = 0
    cache_query_time_ms: int = 0
    last_hit_timestamp: datetime | None = None
    last_miss_timestamp: datetime | None = None

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate percentage."""
        if self.total_queries == 0:
            return 0.0
        return (self.cache_hits / self.total_queries) * 100

    @property
    def average_query_time_ms(self) -> float:
        """Calculate average query time in milliseconds."""
        if self.total_queries == 0:
            return 0.0
        return self.total_query_time_ms / self.total_queries

    @property
    def average_cache_query_time_ms(self) -> float:
        """Calculate average cache query time in milliseconds."""
        if self.cache_hits == 0:
            return 0.0
        return self.cache_query_time_ms / self.cache_hits

    def record_hit(self, query_time_ms: int = 0) -> None:
        """Record a cache hit."""
        self.total_queries += 1
        self.cache_hits += 1
        self.cache_query_time_ms += query_time_ms
        self.total_query_time_ms += query_time_ms
        self.last_hit_timestamp = datetime.now(UTC)

    def record_miss(self, query_time_ms: int = 0) -> None:
        """Record a cache miss."""
        self.total_queries += 1
        self.cache_misses += 1
        self.total_query_time_ms += query_time_ms
        self.last_miss_timestamp = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for logging."""
        return {
            "total_queries": self.total_queries,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate_percent": round(self.hit_rate, 2),
            "average_query_time_ms": round(self.average_query_time_ms, 2),
            "average_cache_query_time_ms": round(self.average_cache_query_time_ms, 2),
            "last_hit": (
                self.last_hit_timestamp.isoformat() if self.last_hit_timestamp else None
            ),
            "last_miss": (
                self.last_miss_timestamp.isoformat()
                if self.last_miss_timestamp
                else None
            ),
        }


@dataclass
class CacheEntry:
    """Individual cache entry with data and metadata."""

    data: Any  # Why: polymorphic — different query types store different shapes
    timestamp: datetime
    ttl_seconds: int
    query_type: str
    size_bytes: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        age_seconds = (datetime.now(UTC) - self.timestamp).total_seconds()
        return age_seconds >= self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Get age of cache entry in seconds."""
        return (datetime.now(UTC) - self.timestamp).total_seconds()


__all__ = [
    "CacheEntry",
    "CacheMetrics",
    "DisabledPattern",
    "EnumTargetAgent",
]
