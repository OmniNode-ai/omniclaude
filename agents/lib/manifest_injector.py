"""
Manifest Injector - Dynamic System Manifest via Event Bus

Provides agents with complete system awareness at spawn through dynamic queries
to archon-intelligence-adapter via Kafka event bus.

Key Features:
- Event-driven manifest generation (no static YAML)
- Queries Qdrant, Memgraph, PostgreSQL via archon-intelligence-adapter
- Request-response pattern with correlation tracking
- Graceful fallback to minimal manifest on timeout
- Compatible with existing hook infrastructure
- Async context manager for proper resource cleanup

Architecture:
    manifest_injector.py
      → Publishes to Kafka "intelligence.requests"
      → archon-intelligence-adapter consumes and queries backends
      → Publishes response to "intelligence.responses"
      → manifest_injector formats response for agent

Event Flow:
1. ManifestInjector.generate_dynamic_manifest()
2. Publishes multiple intelligence requests (patterns, infrastructure, models)
3. Waits for responses with timeout (default: 2000ms)
4. Formats responses into structured manifest
5. Falls back to minimal manifest on timeout

Integration:
- Uses IntelligenceEventClient for event bus communication
- Maintains same format_for_prompt() API for backward compatibility
- Sync wrapper for use in hooks
- Async context manager (__aenter__/__aexit__) for resource cleanup

Usage:
    # Async with context manager (recommended)
    async with ManifestInjector() as injector:
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)
        formatted = injector.format_for_prompt()

    # Sync wrapper (backward compatibility)
    manifest_text = inject_manifest(correlation_id)

Performance Targets:
- Query time: <2000ms total (parallel queries)
- Success rate: >90%
- Fallback on timeout: minimal manifest with core info

Created: 2025-10-26
Updated: 2025-10-28 (added context manager support)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

# Import nest_asyncio for nested event loop support
try:
    import nest_asyncio

    nest_asyncio.apply()  # Enable nested event loops globally
except ImportError:
    nest_asyncio = None

# Import IntelligenceEventClient for event bus communication
try:
    from intelligence_event_client import IntelligenceEventClient
except ImportError:
    # Handle imports when module is installed in ~/.claude/agents/lib/
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from intelligence_event_client import IntelligenceEventClient

# Import IntelligenceCache for Valkey-backed caching
try:
    from intelligence_cache import IntelligenceCache
except ImportError:
    # Handle imports when module is installed in ~/.claude/agents/lib/
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from intelligence_cache import IntelligenceCache

# Import PatternQualityScorer for quality filtering
try:
    from pattern_quality_scorer import PatternQualityScorer
except ImportError:
    # Handle imports when module is installed in ~/.claude/agents/lib/
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from pattern_quality_scorer import PatternQualityScorer

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """Cache performance metrics tracking."""

    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_query_time_ms: int = 0
    cache_query_time_ms: int = 0
    last_hit_timestamp: Optional[datetime] = None
    last_miss_timestamp: Optional[datetime] = None

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

    def to_dict(self) -> Dict[str, Any]:
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

    data: Any
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


class ManifestCache:
    """
    Enhanced caching layer for manifest intelligence queries.

    Features:
    - Per-query-type caching (patterns, infrastructure, models, etc.)
    - Configurable TTL per query type
    - Cache metrics tracking (hit rate, query times)
    - Cache invalidation (selective or full)
    - Size tracking and management
    """

    def __init__(self, default_ttl_seconds: int = 300, enable_metrics: bool = True):
        """Initialize manifest cache."""
        self.default_ttl_seconds = default_ttl_seconds
        self.enable_metrics = enable_metrics
        self._caches: Dict[str, CacheEntry] = {}
        self._ttls: Dict[str, int] = {
            "patterns": default_ttl_seconds * 3,  # 15 minutes
            "infrastructure": default_ttl_seconds * 2,  # 10 minutes
            "models": default_ttl_seconds * 3,  # 15 minutes
            "database_schemas": default_ttl_seconds,  # 5 minutes
            "debug_intelligence": default_ttl_seconds // 2,  # 2.5 minutes
            "filesystem": default_ttl_seconds,  # 5 minutes
            "full_manifest": default_ttl_seconds,  # 5 minutes
        }
        self.metrics: Dict[str, CacheMetrics] = {}
        if enable_metrics:
            for query_type in self._ttls.keys():
                self.metrics[query_type] = CacheMetrics()
        self.logger = logging.getLogger(__name__)

    def get(self, query_type: str) -> Optional[Any]:
        """Get cached data for query type."""
        import time

        start_time = time.time()
        entry = self._caches.get(query_type)

        if entry is None:
            elapsed_ms = int((time.time() - start_time) * 1000)
            if self.enable_metrics and query_type in self.metrics:
                self.metrics[query_type].record_miss(elapsed_ms)
            self.logger.debug(f"Cache MISS: {query_type} (not found)")
            return None

        if entry.is_expired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            if self.enable_metrics and query_type in self.metrics:
                self.metrics[query_type].record_miss(elapsed_ms)
            self.logger.debug(f"Cache MISS: {query_type} (expired)")
            del self._caches[query_type]
            return None

        elapsed_ms = int((time.time() - start_time) * 1000)
        if self.enable_metrics and query_type in self.metrics:
            self.metrics[query_type].record_hit(elapsed_ms)
        self.logger.debug(f"Cache HIT: {query_type}")
        return entry.data

    def set(
        self, query_type: str, data: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        """Store data in cache."""
        ttl = ttl_seconds or self._ttls.get(query_type, self.default_ttl_seconds)
        size_bytes = len(str(data).encode("utf-8"))
        entry = CacheEntry(
            data=data,
            timestamp=datetime.now(UTC),
            ttl_seconds=ttl,
            query_type=query_type,
            size_bytes=size_bytes,
        )
        self._caches[query_type] = entry
        self.logger.debug(f"Cache SET: {query_type} (ttl: {ttl}s)")

    def invalidate(self, query_type: Optional[str] = None) -> int:
        """Invalidate cache entries."""
        if query_type is None:
            count = len(self._caches)
            self._caches.clear()
            self.logger.info(f"Cache invalidated: ALL ({count} entries)")
            return count
        if query_type in self._caches:
            del self._caches[query_type]
            self.logger.info(f"Cache invalidated: {query_type}")
            return 1
        return 0

    def get_metrics(self, query_type: Optional[str] = None) -> Dict[str, Any]:
        """Get cache metrics."""
        if not self.enable_metrics:
            return {"error": "Metrics disabled"}
        if query_type is not None:
            if query_type in self.metrics:
                return {"query_type": query_type, **self.metrics[query_type].to_dict()}
            return {"error": f"No metrics for {query_type}"}

        total_metrics = CacheMetrics()
        for metric in self.metrics.values():
            total_metrics.total_queries += metric.total_queries
            total_metrics.cache_hits += metric.cache_hits
            total_metrics.cache_misses += metric.cache_misses
            total_metrics.total_query_time_ms += metric.total_query_time_ms
            total_metrics.cache_query_time_ms += metric.cache_query_time_ms

        return {
            "overall": total_metrics.to_dict(),
            "by_query_type": {qt: m.to_dict() for qt, m in self.metrics.items()},
            "cache_size": len(self._caches),
            "cache_entries": list(self._caches.keys()),
        }

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information and statistics."""
        total_size_bytes = sum(entry.size_bytes for entry in self._caches.values())
        entries_info = [
            {
                "query_type": query_type,
                "age_seconds": round(entry.age_seconds, 2),
                "ttl_seconds": entry.ttl_seconds,
                "size_bytes": entry.size_bytes,
                "expired": entry.is_expired,
            }
            for query_type, entry in self._caches.items()
        ]
        return {
            "cache_size": len(self._caches),
            "total_size_bytes": total_size_bytes,
            "entries": entries_info,
            "ttl_configuration": self._ttls,
        }


class ManifestInjectionStorage:
    """
    Storage handler for manifest injection records.

    Stores complete manifest injection records in PostgreSQL for traceability
    and replay capability.
    """

    def __init__(
        self,
        db_host: Optional[str] = None,
        db_port: Optional[int] = None,
        db_name: Optional[str] = None,
        db_user: Optional[str] = None,
        db_password: Optional[str] = None,
    ):
        """
        Initialize storage handler.

        Args:
            db_host: PostgreSQL host (default: env POSTGRES_HOST or 192.168.86.200)
            db_port: PostgreSQL port (default: env POSTGRES_PORT or 5436)
            db_name: Database name (default: env POSTGRES_DATABASE or omninode_bridge)
            db_user: Database user (default: env POSTGRES_USER or postgres)
            db_password: Database password (default: env POSTGRES_PASSWORD)
        """
        self.db_host = db_host or os.environ.get("POSTGRES_HOST", "192.168.86.200")
        self.db_port = db_port or int(os.environ.get("POSTGRES_PORT", "5436"))
        self.db_name = db_name or os.environ.get("POSTGRES_DATABASE", "omninode_bridge")
        self.db_user = db_user or os.environ.get("POSTGRES_USER", "postgres")
        self.db_password = db_password or os.environ.get(
            "POSTGRES_PASSWORD", "omninode-bridge-postgres-dev-2024"
        )

    def store_manifest_injection(
        self,
        correlation_id: UUID,
        agent_name: str,
        manifest_data: Dict[str, Any],
        formatted_text: str,
        query_times: Dict[str, int],
        sections_included: List[str],
        **kwargs,
    ) -> bool:
        """
        Store manifest injection record in database.

        Args:
            correlation_id: Correlation ID linking to routing decision
            agent_name: Agent receiving the manifest
            manifest_data: Complete manifest data structure
            formatted_text: Formatted manifest text injected into prompt
            query_times: Query performance breakdown {"patterns": 450, ...}
            sections_included: Sections included in manifest
            **kwargs: Additional fields (patterns_count, debug_intelligence_successes, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            import psycopg2
            import psycopg2.extras

            # Extract metadata
            metadata = manifest_data.get("manifest_metadata", {})
            manifest_version = metadata.get("version", "unknown")
            generation_source = metadata.get("source", "unknown")
            is_fallback = generation_source == "fallback"

            # Calculate totals
            total_query_time_ms = sum(query_times.values())
            manifest_size_bytes = len(formatted_text.encode("utf-8"))

            # Extract section counts
            patterns_count = kwargs.get("patterns_count", 0)
            infrastructure_services = kwargs.get("infrastructure_services", 0)
            models_count = kwargs.get("models_count", 0)
            database_schemas_count = kwargs.get("database_schemas_count", 0)
            debug_intelligence_successes = kwargs.get("debug_intelligence_successes", 0)
            debug_intelligence_failures = kwargs.get("debug_intelligence_failures", 0)

            # Collections queried
            collections_queried = kwargs.get("collections_queried", {})

            # Query failures
            query_failures = kwargs.get("query_failures", {})

            # Warnings
            warnings = kwargs.get("warnings", [])

            # Connect to database with context manager for automatic cleanup
            with (
                psycopg2.connect(
                    host=self.db_host,
                    port=self.db_port,
                    dbname=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                ) as conn,
                conn.cursor() as cursor,
            ):
                # Insert record
                cursor.execute(
                    """
                    INSERT INTO agent_manifest_injections (
                        correlation_id,
                        agent_name,
                        manifest_version,
                        generation_source,
                        is_fallback,
                        sections_included,
                        patterns_count,
                        infrastructure_services,
                        models_count,
                        database_schemas_count,
                        debug_intelligence_successes,
                        debug_intelligence_failures,
                        collections_queried,
                        query_times,
                        total_query_time_ms,
                        full_manifest_snapshot,
                        formatted_manifest_text,
                        manifest_size_bytes,
                        intelligence_available,
                        query_failures,
                        warnings,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    """,
                    (
                        str(correlation_id),
                        agent_name,
                        manifest_version,
                        generation_source,
                        is_fallback,
                        sections_included,
                        patterns_count,
                        infrastructure_services,
                        models_count,
                        database_schemas_count,
                        debug_intelligence_successes,
                        debug_intelligence_failures,
                        psycopg2.extras.Json(collections_queried),
                        psycopg2.extras.Json(query_times),
                        total_query_time_ms,
                        psycopg2.extras.Json(manifest_data),
                        formatted_text,
                        manifest_size_bytes,
                        not is_fallback,
                        psycopg2.extras.Json(query_failures),
                        warnings,
                    ),
                )

                conn.commit()

            logger.info(
                f"Stored manifest injection record: correlation_id={correlation_id}, "
                f"agent={agent_name}, patterns={patterns_count}, "
                f"query_time={total_query_time_ms}ms"
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to store manifest injection record: {e}", exc_info=True
            )
            return False

    def mark_agent_completed(
        self,
        correlation_id: UUID,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Mark agent execution as completed by updating lifecycle fields.

        This fixes the "Active Agents never reaches 0" bug by properly updating
        completed_at, executed_at, and agent_execution_success fields.

        Args:
            correlation_id: Correlation ID linking to manifest injection record
            success: Whether agent execution succeeded (default: True)
            error_message: Optional error message if execution failed

        Returns:
            True if successful, False otherwise

        Example:
            >>> storage = ManifestInjectionStorage()
            >>> storage.mark_agent_completed(correlation_id, success=True)
            True
        """
        try:
            import psycopg2

            # Connect to database with context manager for automatic cleanup
            with (
                psycopg2.connect(
                    host=self.db_host,
                    port=self.db_port,
                    dbname=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                ) as conn,
                conn.cursor() as cursor,
            ):
                # Update lifecycle fields
                cursor.execute(
                    """
                    UPDATE agent_manifest_injections
                    SET
                        completed_at = NOW(),
                        executed_at = NOW(),
                        agent_execution_success = %s,
                        warnings = CASE
                            WHEN %s IS NOT NULL THEN array_append(COALESCE(warnings, ARRAY[]::text[]), %s)
                            ELSE warnings
                        END
                    WHERE correlation_id = %s
                    """,
                    (
                        success,
                        error_message,
                        error_message,
                        str(correlation_id),
                    ),
                )

                rows_updated = cursor.rowcount
                conn.commit()

            if rows_updated > 0:
                logger.info(
                    f"Marked agent as completed: correlation_id={correlation_id}, "
                    f"success={success}, rows_updated={rows_updated}"
                )
                return True
            else:
                logger.warning(
                    f"No manifest injection record found for correlation_id={correlation_id}"
                )
                return False

        except Exception as e:
            logger.error(f"Failed to mark agent as completed: {e}", exc_info=True)
            return False


class ManifestInjector:
    """
    Dynamic manifest generator using event bus intelligence.

    Replaces static YAML with real-time queries to archon-intelligence-adapter,
    which queries Qdrant, Memgraph, and PostgreSQL for current system state.

    Features:
    - Async event bus queries
    - Parallel query execution
    - Timeout handling with fallback
    - Sync wrapper for hooks
    - Same output format as static YAML version

    Usage:
        # Async usage
        injector = ManifestInjector()
        manifest = await injector.generate_dynamic_manifest_async(correlation_id)
        formatted = injector.format_for_prompt()

        # Sync usage (for hooks)
        injector = ManifestInjector()
        manifest = injector.generate_dynamic_manifest(correlation_id)
        formatted = injector.format_for_prompt()
    """

    def __init__(
        self,
        kafka_brokers: Optional[str] = None,
        enable_intelligence: bool = True,
        query_timeout_ms: int = 10000,
        enable_storage: bool = True,
        enable_cache: bool = True,
        cache_ttl_seconds: Optional[int] = None,
        agent_name: Optional[str] = None,
    ):
        """
        Initialize manifest injector.

        Args:
            kafka_brokers: Kafka bootstrap servers
                Default: KAFKA_BOOTSTRAP_SERVERS env var or "omninode-bridge-redpanda:9092"
            enable_intelligence: Enable event-based queries
            query_timeout_ms: Timeout for intelligence queries (default: 10000ms)
                             Increased from 5000ms to account for Kafka delivery retries
            enable_storage: Enable database storage of manifest injections
            enable_cache: Enable caching of intelligence queries (default: True)
            cache_ttl_seconds: Cache TTL override (default: from env or 300)
            agent_name: Agent name for logging (if known at init time)
                       Falls back to AGENT_NAME environment variable if not provided
        """
        self.kafka_brokers = kafka_brokers or os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "omninode-bridge-redpanda:9092"
        )
        self.enable_intelligence = enable_intelligence
        self.query_timeout_ms = query_timeout_ms
        self.enable_storage = enable_storage
        self.enable_cache = enable_cache
        # Read agent_name from parameter or environment variable (fixes "unknown" agent names)
        self.agent_name = agent_name or os.environ.get("AGENT_NAME")

        # Get cache TTL from environment or use default
        default_ttl = int(os.environ.get("MANIFEST_CACHE_TTL_SECONDS", "300"))
        self.cache_ttl_seconds = cache_ttl_seconds or default_ttl

        # Initialize enhanced caching layer (in-memory)
        if enable_cache:
            self._cache = ManifestCache(
                default_ttl_seconds=self.cache_ttl_seconds,
                enable_metrics=True,
            )
        else:
            self._cache = None

        # Initialize Valkey cache (distributed, persistent)
        # Valkey cache is checked BEFORE in-memory cache for better hit rates
        self._valkey_cache: Optional[IntelligenceCache] = None
        if enable_cache:
            self._valkey_cache = IntelligenceCache()
        else:
            self._valkey_cache = None

        # Cached manifest data (for backward compatibility)
        self._manifest_data: Optional[Dict[str, Any]] = None
        self._cached_formatted: Optional[str] = None
        self._last_update: Optional[datetime] = None

        # Tracking for current generation
        self._current_correlation_id: Optional[UUID] = None
        self._current_query_times: Dict[str, int] = {}
        self._current_query_failures: Dict[str, Optional[str]] = {}
        self._current_warnings: List[str] = []

        # Storage handler
        if self.enable_storage:
            self._storage = ManifestInjectionStorage()
        else:
            self._storage = None

        # Quality scoring configuration
        self.quality_scorer = PatternQualityScorer()
        self.enable_quality_filtering = os.getenv(
            "ENABLE_PATTERN_QUALITY_FILTER",
            "false"
        ).lower() == "true"
        self.min_quality_threshold = float(
            os.getenv("MIN_PATTERN_QUALITY", "0.5")
        )

        self.logger = logging.getLogger(__name__)

    async def __aenter__(self):
        """
        Async context manager entry.

        Returns:
            Self for use in async with statement
        """
        self.logger.debug("ManifestInjector context manager entered")

        # Connect to Valkey cache
        if self._valkey_cache:
            try:
                await self._valkey_cache.connect()
                self.logger.debug("Valkey cache connected")
            except Exception as e:
                self.logger.warning(f"Failed to connect to Valkey cache: {e}")
                self._valkey_cache = None

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Async context manager exit with proper resource cleanup.

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value if an error occurred
            exc_tb: Exception traceback if an error occurred

        Returns:
            False to propagate exceptions (default behavior)
        """
        try:
            # Log cache metrics before cleanup
            if self.enable_cache and self._cache:
                self.log_cache_metrics()

            # Log Valkey cache stats
            if self._valkey_cache:
                try:
                    stats = await self._valkey_cache.get_stats()
                    if stats.get("enabled"):
                        self.logger.info(
                            f"Valkey cache stats: hit_rate={stats.get('hit_rate_percent', 0)}%, "
                            f"hits={stats.get('keyspace_hits', 0)}, "
                            f"misses={stats.get('keyspace_misses', 0)}"
                        )
                except Exception as e:
                    self.logger.warning(f"Failed to get Valkey cache stats: {e}")

            # Close Valkey connection
            if self._valkey_cache:
                try:
                    await self._valkey_cache.close()
                    self.logger.debug("Valkey cache connection closed")
                except Exception as e:
                    self.logger.warning(f"Error closing Valkey cache: {e}")

            # Clear in-memory cache
            if self.enable_cache and self._cache:
                invalidated = self._cache.invalidate()
                self.logger.debug(f"Cleared {invalidated} in-memory cache entries")

            # Clear cached data
            self._manifest_data = None
            self._cached_formatted = None
            self._last_update = None

            self.logger.debug("ManifestInjector context manager exited cleanly")

        except Exception as e:
            self.logger.error(
                f"Error during ManifestInjector cleanup: {e}", exc_info=True
            )

        # Return False to propagate any exceptions
        return False

    async def _filter_by_quality(self, patterns: List[Dict]) -> List[Dict]:
        """
        Filter patterns by quality score.

        Args:
            patterns: List of pattern dictionaries from Qdrant

        Returns:
            Filtered list of patterns meeting quality threshold
        """
        if not self.enable_quality_filtering:
            return patterns

        filtered = []
        scores_recorded = 0

        for pattern in patterns:
            try:
                # Score pattern
                score = self.quality_scorer.score_pattern(pattern)

                # Store metrics asynchronously (non-blocking)
                asyncio.create_task(
                    self.quality_scorer.store_quality_metrics(score)
                )
                scores_recorded += 1

                # Filter by threshold
                if score.composite_score >= self.min_quality_threshold:
                    filtered.append(pattern)
            except Exception as e:
                # Log error but don't fail - include pattern in results
                self.logger.warning(
                    f"Failed to score pattern {pattern.get('name', 'unknown')}: {e}"
                )
                filtered.append(pattern)  # Include pattern on scoring failure

        # Log filtering statistics
        self.logger.info(
            f"Quality filter: {len(filtered)}/{len(patterns)} patterns passed "
            f"(threshold: {self.min_quality_threshold}, scores recorded: {scores_recorded})"
        )

        return filtered

    def generate_dynamic_manifest(
        self,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate manifest by querying intelligence service (synchronous wrapper).

        This is a synchronous wrapper around generate_dynamic_manifest_async()
        for use in hooks and synchronous contexts.

        Uses nest_asyncio to support nested event loops when called from
        async contexts (like Claude Code).

        Args:
            correlation_id: Correlation ID for tracking
            force_refresh: Force refresh even if cache is valid

        Returns:
            Manifest data dictionary
        """
        # Check cache first
        if not force_refresh and self._is_cache_valid():
            self.logger.debug("Using cached manifest data")
            return self._manifest_data

        # Run async query in event loop
        try:
            loop = asyncio.get_event_loop()
            # With nest_asyncio.apply(), we can run_until_complete even in running loop
            return loop.run_until_complete(
                self.generate_dynamic_manifest_async(correlation_id, force_refresh)
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # Create new event loop if none exists
                self.logger.debug("Creating new event loop")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(
                        self.generate_dynamic_manifest_async(
                            correlation_id, force_refresh
                        )
                    )
                finally:
                    loop.close()
            else:
                self.logger.error(
                    f"Failed to generate dynamic manifest: {e}", exc_info=True
                )
                return self._get_minimal_manifest()
        except Exception as e:
            self.logger.error(
                f"Failed to generate dynamic manifest: {e}", exc_info=True
            )
            return self._get_minimal_manifest()

    async def generate_dynamic_manifest_async(
        self,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate manifest by querying intelligence service (async).

        Flow:
        1. Check cache validity
        2. Create IntelligenceEventClient
        3. Execute parallel queries for different manifest sections
        4. Wait for responses with timeout
        5. Format responses into manifest structure
        6. Cache and return

        Args:
            correlation_id: Correlation ID for tracking
            force_refresh: Force refresh even if cache is valid

        Returns:
            Manifest data dictionary
        """
        import time

        # Convert correlation_id to UUID
        if isinstance(correlation_id, str):
            correlation_id_uuid = UUID(correlation_id)
        else:
            correlation_id_uuid = correlation_id

        # Store correlation ID for tracking
        self._current_correlation_id = correlation_id_uuid

        # Reset tracking
        self._current_query_times = {}
        self._current_query_failures = {}
        self._current_warnings = []

        # Check cache first
        if not force_refresh and self._is_cache_valid():
            self.logger.debug(
                f"Using cached manifest data (correlation_id: {correlation_id})"
            )
            # Still log cache hit
            self._store_manifest_if_enabled(from_cache=True)
            return self._manifest_data

        start_time = time.time()
        self.logger.info(
            f"[{correlation_id}] Generating dynamic manifest for agent '{self.agent_name or 'unknown'}'"
        )

        # Always query filesystem (local operation, doesn't require intelligence service)
        # Create a dummy client for filesystem query (not actually used)
        from intelligence_event_client import IntelligenceEventClient

        dummy_client = IntelligenceEventClient(
            bootstrap_servers=self.kafka_brokers,
            enable_intelligence=False,
        )

        # Query filesystem first (always)
        filesystem_result = await self._query_filesystem(dummy_client, correlation_id)

        # If intelligence disabled, return minimal manifest with filesystem
        if not self.enable_intelligence:
            self.logger.info(
                f"Intelligence queries disabled, using minimal manifest with filesystem "
                f"(correlation_id: {correlation_id})"
            )
            manifest = self._get_minimal_manifest()
            manifest["filesystem"] = self._format_filesystem_result(filesystem_result)
            self._manifest_data = manifest
            self._last_update = datetime.now(UTC)
            return manifest

        # Create intelligence client for remote queries
        client = IntelligenceEventClient(
            bootstrap_servers=self.kafka_brokers,
            enable_intelligence=True,
            request_timeout_ms=self.query_timeout_ms,
        )

        try:
            # Start client
            await client.start()

            # Execute parallel queries for different manifest sections
            # Note: filesystem already queried above
            query_tasks = {
                "patterns": self._query_patterns(client, correlation_id),
                "infrastructure": self._query_infrastructure(client, correlation_id),
                "models": self._query_models(client, correlation_id),
                "database_schemas": self._query_database_schemas(
                    client, correlation_id
                ),
                "debug_intelligence": self._query_debug_intelligence(
                    client, correlation_id
                ),
            }

            # Wait for all queries with timeout
            results = await asyncio.gather(
                *query_tasks.values(),
                return_exceptions=True,
            )

            # Build manifest from results (including filesystem queried earlier)
            all_results = dict(zip(query_tasks.keys(), results))
            all_results["filesystem"] = filesystem_result  # Add filesystem result
            manifest = self._build_manifest_from_results(all_results)

            # Cache manifest
            self._manifest_data = manifest
            self._last_update = datetime.now(UTC)

            # Calculate total generation time
            total_time_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"[{correlation_id}] Dynamic manifest generated successfully "
                f"(total_time: {total_time_ms}ms, patterns: {len(manifest.get('patterns', {}).get('available', []))}, "
                f"debug_intel: {manifest.get('debug_intelligence', {}).get('total_successes', 0)} successes/"
                f"{manifest.get('debug_intelligence', {}).get('total_failures', 0)} failures)"
            )

            # Store manifest injection record
            self._store_manifest_if_enabled(from_cache=False)

            return manifest

        except Exception as e:
            self.logger.error(
                f"[{correlation_id}] Failed to query intelligence service: {e}",
                exc_info=True,
            )
            self._current_warnings.append(f"Intelligence query failed: {str(e)}")
            # Fall back to minimal manifest
            return self._get_minimal_manifest()

        finally:
            # Stop client
            await client.stop()

    async def _query_patterns(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query available code generation patterns from BOTH collections.

        Queries both execution_patterns (ONEX templates) and code_patterns
        (real code implementations) from Qdrant vector database.

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Patterns data dictionary with merged results from both collections
        """
        import time

        start_time = time.time()

        # Check Valkey cache first (distributed, persistent)
        if self._valkey_cache:
            cache_params = {
                "collections": ["execution_patterns", "code_patterns"],
                "limits": {"execution_patterns": 50, "code_patterns": 100},
            }
            try:
                cached_result = await self._valkey_cache.get(
                    "pattern_discovery", cache_params
                )
                if cached_result is not None:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["patterns"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Pattern query: VALKEY CACHE HIT ({elapsed_ms}ms)"
                    )
                    # Also store in in-memory cache for faster subsequent access
                    if self.enable_cache and self._cache:
                        self._cache.set("patterns", cached_result)
                    return cached_result
            except Exception as e:
                self.logger.warning(f"Valkey cache check failed: {e}")

        # Check in-memory cache second (local, fast)
        if self.enable_cache and self._cache:
            cached_result = self._cache.get("patterns")
            if cached_result is not None:
                elapsed_ms = int((time.time() - start_time) * 1000)
                self._current_query_times["patterns"] = elapsed_ms
                self.logger.info(
                    f"[{correlation_id}] Pattern query: IN-MEMORY CACHE HIT ({elapsed_ms}ms)"
                )
                return cached_result

        try:
            self.logger.debug(
                f"[{correlation_id}] Querying patterns from both collections (PARALLEL)"
            )

            # Execute BOTH collection queries in parallel using asyncio.gather
            # This reduces total query time from sum(query_times) to max(query_times)
            exec_task = client.request_code_analysis(
                content="",  # Empty content for pattern discovery
                source_path="node_*_*.py",  # Pattern for ONEX nodes
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                    "include_metrics": False,
                    "collection_name": "execution_patterns",
                    "limit": 50,  # Get more patterns from this collection
                },
                timeout_ms=self.query_timeout_ms,
            )

            code_task = client.request_code_analysis(
                content="",  # Empty content for pattern discovery
                source_path="*.py",  # All Python files
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                    "include_metrics": False,
                    "collection_name": "code_patterns",
                    "limit": 100,  # Get more patterns from this collection
                },
                timeout_ms=self.query_timeout_ms,
            )

            # Wait for both queries to complete in parallel
            self.logger.debug(
                "Waiting for both pattern queries to complete in parallel..."
            )
            results = await asyncio.gather(exec_task, code_task, return_exceptions=True)
            exec_result, code_result = results

            # Handle exceptions from gather
            if isinstance(exec_result, Exception):
                self.logger.warning(f"execution_patterns query failed: {exec_result}")
                exec_result = None
            if isinstance(code_result, Exception):
                self.logger.warning(f"code_patterns query failed: {code_result}")
                code_result = None

            # Merge results from both collections
            exec_patterns = exec_result.get("patterns", []) if exec_result else []
            code_patterns = code_result.get("patterns", []) if code_result else []

            all_patterns = exec_patterns + code_patterns

            # Apply quality filtering if enabled
            all_patterns = await self._filter_by_quality(all_patterns)

            # Calculate combined query time
            exec_time = exec_result.get("query_time_ms", 0) if exec_result else 0
            code_time = code_result.get("query_time_ms", 0) if code_result else 0
            total_query_time = exec_time + code_time

            # Track timing
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["patterns"] = elapsed_ms

            # Calculate speedup factor from parallelization
            speedup = round(total_query_time / max(elapsed_ms, 1), 1)

            self.logger.info(
                f"[{correlation_id}] Pattern query results (PARALLEL): {len(exec_patterns)} from execution_patterns, "
                f"{len(code_patterns)} from code_patterns, "
                f"{len(all_patterns)} total patterns, "
                f"query_time={total_query_time}ms, elapsed={elapsed_ms}ms, speedup={speedup}x"
            )

            if all_patterns:
                self.logger.debug(
                    f"[{correlation_id}] First pattern: {all_patterns[0].get('name', 'unknown')}"
                )

            result = {
                "patterns": all_patterns,
                "query_time_ms": total_query_time,
                "total_count": len(all_patterns),
                "collections_queried": {
                    "execution_patterns": len(exec_patterns),
                    "code_patterns": len(code_patterns),
                },
            }

            # Cache the result in both Valkey and in-memory caches
            # Valkey cache (distributed, persistent)
            if self._valkey_cache:
                cache_params = {
                    "collections": ["execution_patterns", "code_patterns"],
                    "limits": {"execution_patterns": 50, "code_patterns": 100},
                }
                try:
                    await self._valkey_cache.set(
                        "pattern_discovery", cache_params, result
                    )
                    self.logger.debug(
                        f"[{correlation_id}] Stored patterns in Valkey cache"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to store in Valkey cache: {e}")

            # In-memory cache (local, fast)
            if self.enable_cache and self._cache:
                self._cache.set("patterns", result)

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["patterns"] = elapsed_ms
            self._current_query_failures["patterns"] = str(e)
            self.logger.warning(f"[{correlation_id}] Pattern query failed: {e}")
            return {"patterns": [], "error": str(e)}

    async def _query_infrastructure(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query current infrastructure topology.

        Queries for:
        - PostgreSQL databases and schemas
        - Kafka/Redpanda topics
        - Qdrant collections
        - Docker services

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Infrastructure data dictionary
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying infrastructure topology")

            result = await client.request_code_analysis(
                content="",  # Empty content for infrastructure scan
                source_path="infrastructure",
                language="yaml",
                options={
                    "operation_type": "INFRASTRUCTURE_SCAN",
                    "include_databases": True,
                    "include_kafka_topics": True,
                    "include_qdrant_collections": True,
                    "include_docker_services": True,
                },
                timeout_ms=self.query_timeout_ms,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["infrastructure"] = elapsed_ms
            self.logger.info(
                f"[{correlation_id}] Infrastructure query completed in {elapsed_ms}ms"
            )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["infrastructure"] = elapsed_ms
            self._current_query_failures["infrastructure"] = str(e)
            self.logger.warning(f"[{correlation_id}] Infrastructure query failed: {e}")
            return {"infrastructure": {}, "error": str(e)}

    async def _query_models(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query available AI models and ONEX data models.

        Queries for:
        - AI model providers (Anthropic, Google, Z.ai)
        - ONEX node types and contracts
        - Model quorum configuration

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Models data dictionary
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying available models")

            result = await client.request_code_analysis(
                content="",  # Empty content for model discovery
                source_path="models",
                language="python",
                options={
                    "operation_type": "MODEL_DISCOVERY",
                    "include_ai_models": True,
                    "include_onex_models": True,
                    "include_quorum_config": True,
                },
                timeout_ms=self.query_timeout_ms,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["models"] = elapsed_ms
            self.logger.info(
                f"[{correlation_id}] Models query completed in {elapsed_ms}ms"
            )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["models"] = elapsed_ms
            self._current_query_failures["models"] = str(e)
            self.logger.warning(f"[{correlation_id}] Model query failed: {e}")
            return {"models": {}, "error": str(e)}

    async def _query_database_schemas(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query database schemas and table definitions.

        Queries PostgreSQL for:
        - Table schemas
        - Column definitions
        - Indexes and constraints

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Database schemas dictionary
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying database schemas")

            result = await client.request_code_analysis(
                content="",  # Empty content for schema discovery
                source_path="database_schemas",
                language="sql",
                options={
                    "operation_type": "SCHEMA_DISCOVERY",
                    "include_tables": True,
                    "include_columns": True,
                    "include_indexes": False,
                },
                timeout_ms=self.query_timeout_ms,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["database_schemas"] = elapsed_ms
            self.logger.info(
                f"[{correlation_id}] Database schemas query completed in {elapsed_ms}ms"
            )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["database_schemas"] = elapsed_ms
            self._current_query_failures["database_schemas"] = str(e)
            self.logger.warning(f"[{correlation_id}] Database schema query failed: {e}")
            return {"schemas": {}, "error": str(e)}

    async def _query_debug_intelligence(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query debug intelligence from workflow_events collection.

        Retrieves similar past issues/workflows to avoid retrying failed approaches.

        Queries workflow_events collection in Qdrant for:
        - Similar workflows that failed (what didn't work)
        - Similar workflows that succeeded (what worked)
        - Common error patterns
        - Successful resolution patterns

        Args:
            client: Intelligence event client
            correlation_id: Correlation ID for tracking

        Returns:
            Debug intelligence dictionary with past successes/failures
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(
                f"[{correlation_id}] Querying debug intelligence from workflow_events"
            )

            # Query workflow_events collection for similar issues
            result = await client.request_code_analysis(
                content="",  # Empty content for workflow discovery
                source_path="workflow_events",
                language="json",
                options={
                    "operation_type": "DEBUG_INTELLIGENCE_QUERY",
                    "collection_name": "workflow_events",
                    "include_failures": True,  # Get failed workflows to avoid retrying
                    "include_successes": True,  # Get successful workflows as examples
                    "limit": 20,  # Get recent similar workflows
                },
                timeout_ms=self.query_timeout_ms,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["debug_intelligence"] = elapsed_ms

            if result:
                self.logger.info(
                    f"[{correlation_id}] Debug intelligence query completed in {elapsed_ms}ms: "
                    f"{len(result.get('similar_workflows', []))} similar workflows"
                )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["debug_intelligence"] = elapsed_ms
            self._current_query_failures["debug_intelligence"] = str(e)
            self.logger.warning(
                f"[{correlation_id}] Debug intelligence query failed: {e}"
            )
            # Not critical - return empty result
            return {"similar_workflows": [], "error": str(e)}

    async def _query_filesystem(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Query filesystem tree and metadata.

        Scans current working directory for:
        - Complete file tree structure
        - File metadata (size, modified date)
        - ONEX compliance metadata where available
        - File counts by type

        Args:
            client: Intelligence event client (not used for filesystem scan)
            correlation_id: Correlation ID for tracking

        Returns:
            Filesystem data dictionary with tree structure and metadata
        """
        import time
        from pathlib import Path

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Scanning filesystem tree")

            # Get current working directory
            cwd = Path(os.getcwd())

            # Define ignored paths
            ignored_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "dist",
                "build",
                ".egg-info",
                ".tox",
                ".coverage",
                "htmlcov",
                ".DS_Store",
            }

            ignored_extensions = {
                ".pyc",
                ".pyo",
                ".pyd",
                ".so",
                ".dylib",
                ".dll",
                ".exe",
            }

            # Scan filesystem
            file_tree = []
            file_types = {}
            onex_files = {
                "effect": [],
                "compute": [],
                "reducer": [],
                "orchestrator": [],
            }
            total_files = 0
            total_dirs = 0
            total_size_bytes = 0

            def should_ignore(path: Path) -> bool:
                """Check if path should be ignored."""
                # Check if any parent directory is in ignored list
                for parent in path.parents:
                    if parent.name in ignored_dirs:
                        return True
                # Check if file itself is ignored
                if path.name in ignored_dirs:
                    return True
                # Check file extension
                if path.suffix in ignored_extensions:
                    return True
                return False

            def get_onex_node_type(file_path: Path) -> Optional[str]:
                """Detect ONEX node type from filename."""
                name = file_path.name.lower()
                if "_effect.py" in name or "effect.py" == name:
                    return "EFFECT"
                elif "_compute.py" in name or "compute.py" == name:
                    return "COMPUTE"
                elif "_reducer.py" in name or "reducer.py" == name:
                    return "REDUCER"
                elif "_orchestrator.py" in name or "orchestrator.py" == name:
                    return "ORCHESTRATOR"
                return None

            def scan_directory(
                directory: Path, depth: int = 0, max_depth: int = 5
            ) -> List[Dict[str, Any]]:
                """Recursively scan directory."""
                nonlocal total_files, total_dirs, total_size_bytes

                if depth > max_depth:
                    return []

                items = []

                try:
                    for item in sorted(directory.iterdir()):
                        if should_ignore(item):
                            continue

                        try:
                            stat = item.stat()
                            rel_path = item.relative_to(cwd)

                            if item.is_dir():
                                total_dirs += 1
                                # Recursively scan subdirectory
                                children = scan_directory(item, depth + 1, max_depth)
                                items.append(
                                    {
                                        "name": item.name,
                                        "type": "directory",
                                        "path": str(rel_path),
                                        "children": children,
                                        "depth": depth,
                                    }
                                )
                            elif item.is_file():
                                total_files += 1
                                file_size = stat.st_size
                                total_size_bytes += file_size

                                # Track file types
                                ext = item.suffix or "no_extension"
                                file_types[ext] = file_types.get(ext, 0) + 1

                                # Check for ONEX node type
                                onex_type = get_onex_node_type(item)
                                if onex_type:
                                    onex_files[onex_type.lower()].append(str(rel_path))

                                # Format file size
                                if file_size < 1024:
                                    size_str = f"{file_size}B"
                                elif file_size < 1024 * 1024:
                                    size_str = f"{file_size / 1024:.1f}KB"
                                else:
                                    size_str = f"{file_size / (1024 * 1024):.1f}MB"

                                # Format modified time
                                from datetime import UTC, datetime

                                modified_time = datetime.fromtimestamp(
                                    stat.st_mtime, tz=UTC
                                )
                                time_diff = datetime.now(UTC) - modified_time
                                if time_diff.days > 0:
                                    modified_str = f"{time_diff.days}d ago"
                                elif time_diff.seconds > 3600:
                                    modified_str = f"{time_diff.seconds // 3600}h ago"
                                elif time_diff.seconds > 60:
                                    modified_str = f"{time_diff.seconds // 60}m ago"
                                else:
                                    modified_str = "just now"

                                items.append(
                                    {
                                        "name": item.name,
                                        "type": "file",
                                        "path": str(rel_path),
                                        "size_bytes": file_size,
                                        "size_formatted": size_str,
                                        "modified": modified_str,
                                        "modified_timestamp": modified_time.isoformat(),
                                        "extension": ext,
                                        "onex_type": onex_type,
                                        "depth": depth,
                                    }
                                )
                        except (PermissionError, OSError) as e:
                            self.logger.debug(f"Cannot access {item}: {e}")
                            continue

                except (PermissionError, OSError) as e:
                    self.logger.warning(f"Cannot scan directory {directory}: {e}")

                return items

            # Scan from current working directory
            file_tree = scan_directory(cwd, depth=0, max_depth=5)

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["filesystem"] = elapsed_ms

            self.logger.info(
                f"[{correlation_id}] Filesystem scan completed in {elapsed_ms}ms: "
                f"{total_files} files, {total_dirs} directories, "
                f"{total_size_bytes / (1024 * 1024):.1f}MB total"
            )

            return {
                "root_path": str(cwd),
                "file_tree": file_tree,
                "total_files": total_files,
                "total_directories": total_dirs,
                "total_size_bytes": total_size_bytes,
                "file_types": file_types,
                "onex_files": onex_files,
                "query_time_ms": elapsed_ms,
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["filesystem"] = elapsed_ms
            self._current_query_failures["filesystem"] = str(e)
            self.logger.warning(f"[{correlation_id}] Filesystem scan failed: {e}")
            return {
                "root_path": os.getcwd(),
                "file_tree": [],
                "error": str(e),
            }

    def _build_manifest_from_results(
        self,
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build structured manifest from query results.

        Transforms raw query results into the manifest structure
        expected by format_for_prompt().

        Args:
            results: Dictionary of query results by section

        Returns:
            Structured manifest dictionary
        """
        manifest = {
            "manifest_metadata": {
                "version": "2.0.0",
                "generated_at": datetime.now(UTC).isoformat(),
                "purpose": "Dynamic system context via event bus",
                "target_agents": ["polymorphic-agent", "all-specialized-agents"],
                "update_frequency": "on_demand",
                "source": "archon-intelligence-adapter",
            }
        }

        # Extract patterns
        patterns_result = results.get("patterns", {})
        if isinstance(patterns_result, Exception):
            self.logger.warning(f"Patterns query failed: {patterns_result}")
            manifest["patterns"] = {"available": [], "error": str(patterns_result)}
        else:
            manifest["patterns"] = self._format_patterns_result(patterns_result)

        # Extract infrastructure
        infra_result = results.get("infrastructure", {})
        if isinstance(infra_result, Exception):
            self.logger.warning(f"Infrastructure query failed: {infra_result}")
            manifest["infrastructure"] = {"error": str(infra_result)}
        else:
            manifest["infrastructure"] = self._format_infrastructure_result(
                infra_result
            )

        # Extract models
        models_result = results.get("models", {})
        if isinstance(models_result, Exception):
            self.logger.warning(f"Models query failed: {models_result}")
            manifest["models"] = {"error": str(models_result)}
        else:
            manifest["models"] = self._format_models_result(models_result)

        # Extract database schemas
        schemas_result = results.get("database_schemas", {})
        if isinstance(schemas_result, Exception):
            self.logger.warning(f"Database schemas query failed: {schemas_result}")
            manifest["database_schemas"] = {"error": str(schemas_result)}
        else:
            manifest["database_schemas"] = self._format_schemas_result(schemas_result)

        # Extract debug intelligence
        debug_result = results.get("debug_intelligence", {})
        if isinstance(debug_result, Exception):
            self.logger.warning(f"Debug intelligence query failed: {debug_result}")
            manifest["debug_intelligence"] = {"error": str(debug_result)}
        else:
            manifest["debug_intelligence"] = self._format_debug_intelligence_result(
                debug_result
            )

        # Extract filesystem
        filesystem_result = results.get("filesystem", {})
        if isinstance(filesystem_result, Exception):
            self.logger.warning(f"Filesystem query failed: {filesystem_result}")
            manifest["filesystem"] = {"error": str(filesystem_result)}
        else:
            manifest["filesystem"] = self._format_filesystem_result(filesystem_result)

        return manifest

    def _format_patterns_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format patterns query result into manifest structure."""
        patterns = result.get("patterns", [])
        collections_queried = result.get("collections_queried", {})

        return {
            "available": [
                {
                    "name": p.get("name", "Unknown Pattern"),
                    "file": p.get("file_path", ""),
                    "description": p.get("description", ""),
                    "node_types": p.get("node_types", []),
                    "confidence": p.get("confidence", 0.0),
                    "use_cases": p.get("use_cases", []),
                }
                for p in patterns
            ],
            "total_count": len(patterns),
            "query_time_ms": result.get("query_time_ms", 0),
            "collections_queried": collections_queried,
        }

    def _format_infrastructure_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format infrastructure query result into manifest structure."""
        return {
            "remote_services": {
                "postgresql": result.get("postgresql", {}),
                "kafka": result.get("kafka", {}),
            },
            "local_services": {
                "qdrant": result.get("qdrant", {}),
                "archon_mcp": result.get("archon_mcp", {}),
            },
            "docker_services": result.get("docker_services", []),
        }

    def _format_models_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format models query result into manifest structure."""
        return {
            "ai_models": result.get("ai_models", {}),
            "onex_models": result.get("onex_models", {}),
            "intelligence_models": result.get("intelligence_models", []),
        }

    def _format_schemas_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format database schemas query result into manifest structure."""
        return {
            "tables": result.get("tables", []),
            "total_tables": len(result.get("tables", [])),
        }

    def _format_debug_intelligence_result(
        self, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format debug intelligence query result into manifest structure."""
        similar_workflows = result.get("similar_workflows", [])

        # Separate successes and failures
        successes = [w for w in similar_workflows if w.get("success", False)]
        failures = [w for w in similar_workflows if not w.get("success", True)]

        return {
            "similar_workflows": {
                "successes": successes[:10],  # Top 10 successful workflows
                "failures": failures[:10],  # Top 10 failed workflows
            },
            "total_successes": len(successes),
            "total_failures": len(failures),
            "query_time_ms": result.get("query_time_ms", 0),
        }

    def _format_filesystem_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format filesystem query result into manifest structure."""
        return {
            "root_path": result.get("root_path", "unknown"),
            "file_tree": result.get("file_tree", []),
            "total_files": result.get("total_files", 0),
            "total_directories": result.get("total_directories", 0),
            "total_size_bytes": result.get("total_size_bytes", 0),
            "file_types": result.get("file_types", {}),
            "onex_files": result.get("onex_files", {}),
            "query_time_ms": result.get("query_time_ms", 0),
        }

    def _is_cache_valid(self) -> bool:
        """
        Check if cached manifest is still valid.

        Returns:
            True if cache is valid, False if refresh needed
        """
        if self._manifest_data is None or self._last_update is None:
            return False

        age_seconds = (datetime.now(UTC) - self._last_update).total_seconds()
        return age_seconds < self.cache_ttl_seconds

    def _get_minimal_manifest(self) -> Dict[str, Any]:
        """
        Get minimal fallback manifest.

        Provides basic system information when event bus queries fail.

        Returns:
            Minimal manifest dictionary
        """
        return {
            "manifest_metadata": {
                "version": "2.0.0-minimal",
                "generated_at": datetime.now(UTC).isoformat(),
                "purpose": "Fallback manifest (intelligence queries unavailable)",
                "target_agents": ["polymorphic-agent", "all-specialized-agents"],
                "update_frequency": "on_demand",
                "source": "fallback",
            },
            "patterns": {
                "available": [],
                "note": "Pattern discovery unavailable - use built-in patterns",
            },
            "infrastructure": {
                "remote_services": {
                    "postgresql": {
                        "host": "192.168.86.200",
                        "port": 5436,
                        "database": "omninode_bridge",
                        "note": "Connection details only - schemas unavailable",
                    },
                    "kafka": {
                        "bootstrap_servers": self.kafka_brokers,
                        "note": "Connection details only - topics unavailable",
                    },
                },
                "local_services": {
                    "qdrant": {
                        "endpoint": os.environ.get("QDRANT_HOST", "localhost")
                        + ":"
                        + os.environ.get("QDRANT_PORT", "6333"),
                        "note": "Connection details only - collections unavailable",
                    },
                    "archon_mcp": {
                        "endpoint": os.environ.get(
                            "ARCHON_MCP_URL", "http://localhost:8051"
                        ),
                        "note": "Use archon_menu() MCP tool for intelligence queries",
                    },
                },
            },
            "models": {
                "ai_models": {
                    "providers": [
                        {"name": "Anthropic", "note": "Claude models available"},
                        {"name": "Google Gemini", "note": "Gemini models available"},
                    ]
                },
                "onex_models": {
                    "node_types": [
                        {"name": "EFFECT", "naming_pattern": "Node<Name>Effect"},
                        {"name": "COMPUTE", "naming_pattern": "Node<Name>Compute"},
                        {"name": "REDUCER", "naming_pattern": "Node<Name>Reducer"},
                        {
                            "name": "ORCHESTRATOR",
                            "naming_pattern": "Node<Name>Orchestrator",
                        },
                    ]
                },
            },
            "note": "This is a minimal fallback manifest. Full system context requires intelligence service.",
        }

    def format_for_prompt(self, sections: Optional[List[str]] = None) -> str:
        """
        Format manifest for injection into agent prompt.

        Maintains backward compatibility with static YAML version.

        Args:
            sections: Optional list of sections to include.
                     If None, includes all sections.
                     Available: ['patterns', 'models', 'infrastructure',
                                'file_structure', 'dependencies', 'interfaces',
                                'agent_framework', 'skills']

        Returns:
            Formatted string ready for prompt injection
        """
        # Use cached version if available and no specific sections requested
        if sections is None and self._cached_formatted is not None:
            return self._cached_formatted

        # Get manifest data
        if self._manifest_data is None:
            self.logger.warning(
                "Manifest data not loaded - call generate_dynamic_manifest() first"
            )
            self._manifest_data = self._get_minimal_manifest()

        manifest = self._manifest_data

        # Build formatted output
        output = []
        output.append("=" * 70)
        output.append("SYSTEM MANIFEST - Dynamic Context via Event Bus")
        output.append("=" * 70)
        output.append("")

        # Metadata
        metadata = manifest.get("manifest_metadata", {})
        output.append(f"Version: {metadata.get('version', 'unknown')}")
        output.append(f"Generated: {metadata.get('generated_at', 'unknown')}")
        output.append(f"Source: {metadata.get('source', 'unknown')}")
        output.append("")

        # Include requested sections or all if not specified
        available_sections = {
            "patterns": self._format_patterns,
            "models": self._format_models,
            "infrastructure": self._format_infrastructure,
            "database_schemas": self._format_database_schemas,
            "debug_intelligence": self._format_debug_intelligence,
            "filesystem": self._format_filesystem,
        }

        sections_to_include = sections or list(available_sections.keys())

        for section_name in sections_to_include:
            if section_name in available_sections:
                formatter = available_sections[section_name]
                section_output = formatter(manifest.get(section_name, {}))
                if section_output:
                    output.append(section_output)
                    output.append("")

        # Add note about minimal manifest
        if metadata.get("source") == "fallback":
            output.append("⚠️  NOTE: This is a minimal fallback manifest.")
            output.append(
                "Full system context requires archon-intelligence-adapter service."
            )
            output.append(
                "Use archon_menu() MCP tool for dynamic intelligence queries."
            )
            output.append("")

        output.append("=" * 70)
        output.append("END SYSTEM MANIFEST")
        output.append("=" * 70)

        formatted = "\n".join(output)

        # Cache if all sections included
        if sections is None:
            self._cached_formatted = formatted

        return formatted

    def _format_patterns(self, patterns_data: Dict) -> str:
        """Format patterns section."""
        output = ["AVAILABLE PATTERNS:"]

        patterns = patterns_data.get("available", [])
        collections_queried = patterns_data.get("collections_queried", {})

        if not patterns:
            output.append("  (No patterns discovered - use built-in patterns)")
            return "\n".join(output)

        # Show collection statistics
        if collections_queried:
            output.append(
                f"  Collections: execution_patterns ({collections_queried.get('execution_patterns', 0)}), "
                f"code_patterns ({collections_queried.get('code_patterns', 0)})"
            )
            output.append("")

        # Show top 20 patterns (increased from 10 to show more variety)
        display_limit = 20
        for pattern in patterns[:display_limit]:
            output.append(
                f"  • {pattern['name']} ({pattern.get('confidence', 0):.0%} confidence)"
            )
            if pattern.get("file"):
                output.append(f"    File: {pattern['file']}")
            if pattern.get("node_types"):
                output.append(f"    Node Types: {', '.join(pattern['node_types'])}")

        if len(patterns) > display_limit:
            output.append(f"  ... and {len(patterns) - display_limit} more patterns")

        output.append("")
        output.append(f"  Total: {len(patterns)} patterns available")

        return "\n".join(output)

    def _format_models(self, models_data: Dict) -> str:
        """Format models section."""
        output = ["AI MODELS & DATA MODELS:"]

        # AI Models
        if "ai_models" in models_data:
            output.append("  AI Providers:")
            providers = models_data["ai_models"].get("providers", [])
            for provider in providers:
                name = provider.get("name", "Unknown")
                note = provider.get("note", "")
                if note:
                    output.append(f"    • {name}: {note}")
                else:
                    models = provider.get("models", [])
                    if models:
                        models_str = (
                            ", ".join(models) if isinstance(models, list) else models
                        )
                        output.append(f"    • {name}: {models_str}")

        # ONEX Models
        if "onex_models" in models_data:
            output.append("  ONEX Node Types:")
            node_types = models_data["onex_models"].get("node_types", [])
            for node_type in node_types:
                name = node_type.get("name", "Unknown")
                pattern = node_type.get("naming_pattern", "")
                output.append(f"    • {name}: {pattern}")

        return "\n".join(output)

    def _format_infrastructure(self, infra_data: Dict) -> str:
        """Format infrastructure section."""
        output = ["INFRASTRUCTURE TOPOLOGY:"]

        remote = infra_data.get("remote_services", {})

        # PostgreSQL
        if "postgresql" in remote:
            pg = remote["postgresql"]
            if pg is not None:
                host = pg.get("host", "unknown")
                port = pg.get("port", "unknown")
                db = pg.get("database", "unknown")
                output.append(f"  PostgreSQL: {host}:{port}/{db}")
                if "note" in pg:
                    output.append(f"    Note: {pg['note']}")
            else:
                output.append("  PostgreSQL: unknown (scan failed)")

        # Kafka
        if "kafka" in remote:
            kafka = remote["kafka"]
            if kafka is not None:
                bootstrap = kafka.get("bootstrap_servers", "unknown")
                output.append(f"  Kafka: {bootstrap}")
                if "note" in kafka:
                    output.append(f"    Note: {kafka['note']}")
            else:
                output.append("  Kafka: unknown (scan failed)")

        # Qdrant
        local = infra_data.get("local_services", {})
        if "qdrant" in local:
            qdrant = local["qdrant"]
            if qdrant is not None:
                endpoint = qdrant.get("endpoint", "unknown")
                output.append(f"  Qdrant: {endpoint}")
                if "note" in qdrant:
                    output.append(f"    Note: {qdrant['note']}")
            else:
                output.append("  Qdrant: unknown (scan failed)")

        # Archon MCP
        if "archon_mcp" in local:
            archon = local["archon_mcp"]
            if archon is not None:
                endpoint = archon.get("endpoint", "unknown")
                output.append(f"  Archon MCP: {endpoint}")
                if "note" in archon:
                    output.append(f"    Note: {archon['note']}")
            else:
                output.append("  Archon MCP: unknown (scan failed)")

        return "\n".join(output)

    def _format_database_schemas(self, schemas_data: Dict) -> str:
        """Format database schemas section."""
        output = ["DATABASE SCHEMAS:"]

        tables = schemas_data.get("tables", [])
        if not tables:
            output.append("  (Schema information unavailable)")
            return "\n".join(output)

        output.append(
            f"  Total Tables: {schemas_data.get('total_tables', len(tables))}"
        )

        for table in tables[:5]:  # Limit to top 5
            table_name = table.get("name", "unknown")
            output.append(f"  • {table_name}")

        if len(tables) > 5:
            output.append(f"  ... and {len(tables) - 5} more tables")

        return "\n".join(output)

    def _format_debug_intelligence(self, debug_data: Dict) -> str:
        """Format debug intelligence section."""
        output = ["DEBUG INTELLIGENCE (Similar Workflows):"]

        workflows = debug_data.get("similar_workflows", {})
        successes = workflows.get("successes", [])
        failures = workflows.get("failures", [])

        if not successes and not failures:
            output.append(
                "  (No similar workflows found - first time seeing this pattern)"
            )
            return "\n".join(output)

        output.append(
            f"  Total Similar: {debug_data.get('total_successes', 0)} successes, "
            f"{debug_data.get('total_failures', 0)} failures"
        )
        output.append("")

        # Show successful approaches
        if successes:
            output.append("  ✅ SUCCESSFUL APPROACHES (what worked):")
            for workflow in successes[:5]:  # Top 5 successes
                tool = workflow.get("tool_name", "unknown")
                reasoning = workflow.get("reasoning", "")
                if reasoning:
                    output.append(f"    • {tool}: {reasoning[:80]}")
                else:
                    output.append(f"    • {tool}")

        # Show failed approaches to avoid
        if failures:
            output.append("")
            output.append("  ❌ FAILED APPROACHES (avoid retrying):")
            for workflow in failures[:5]:  # Top 5 failures
                tool = workflow.get("tool_name", "unknown")
                error = workflow.get("error", "")
                if error:
                    output.append(f"    • {tool}: {error[:80]}")
                else:
                    output.append(f"    • {tool}")

        return "\n".join(output)

    def _format_filesystem(self, filesystem_data: Dict) -> str:
        """Format filesystem section."""
        output = ["FILESYSTEM STRUCTURE:"]

        root_path = filesystem_data.get("root_path", "unknown")
        total_files = filesystem_data.get("total_files", 0)
        total_dirs = filesystem_data.get("total_directories", 0)
        total_size_bytes = filesystem_data.get("total_size_bytes", 0)
        file_types = filesystem_data.get("file_types", {})
        onex_files = filesystem_data.get("onex_files", {})
        file_tree = filesystem_data.get("file_tree", [])

        if "error" in filesystem_data:
            output.append(f"  Error: {filesystem_data['error']}")
            return "\n".join(output)

        # Format total size
        if total_size_bytes < 1024 * 1024:
            size_str = f"{total_size_bytes / 1024:.1f}KB"
        else:
            size_str = f"{total_size_bytes / (1024 * 1024):.1f}MB"

        output.append(f"  Root: {root_path}")
        output.append(f"  Total Files: {total_files}")
        output.append(f"  Total Directories: {total_dirs}")
        output.append(f"  Total Size: {size_str}")
        output.append("")

        # Show key directories (top level only)
        if file_tree:
            output.append("  Key Directories:")
            key_dirs = [item for item in file_tree if item.get("type") == "directory"]
            for directory in sorted(key_dirs, key=lambda x: x.get("name", ""))[:15]:
                dir_name = directory.get("name", "unknown")
                children = directory.get("children", [])
                file_count = sum(1 for child in children if child.get("type") == "file")
                subdir_count = sum(
                    1 for child in children if child.get("type") == "directory"
                )

                if file_count > 0 or subdir_count > 0:
                    output.append(
                        f"    {dir_name}/ ({file_count} files, {subdir_count} subdirs)"
                    )
                else:
                    output.append(f"    {dir_name}/")

            output.append("")

        # Show file types
        if file_types:
            output.append("  File Types:")
            # Sort by count descending, show top 10
            sorted_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[
                :10
            ]
            for ext, count in sorted_types:
                ext_display = ext if ext != "no_extension" else "(no extension)"
                output.append(f"    {ext_display}: {count} files")

            if len(file_types) > 10:
                output.append(f"    ... and {len(file_types) - 10} more file types")

            output.append("")

        # Show ONEX compliance
        onex_total = sum(len(files) for files in onex_files.values())
        if onex_total > 0:
            output.append("  ONEX Compliance:")
            for node_type, files in onex_files.items():
                if files:
                    output.append(f"    {node_type.upper()} nodes: {len(files)} files")
            output.append("")

        # Add duplicate prevention guidance
        output.append("  ⚠️  DUPLICATE PREVENTION GUIDANCE:")
        output.append("  Before creating new files, check if similar files exist in:")

        # Suggest key directories to check based on common patterns
        check_dirs = []
        if any("agents" in d.get("name", "") for d in file_tree):
            check_dirs.append("    • agents/ - Agent implementations and patterns")
        if any("lib" in d.get("name", "") for d in file_tree):
            check_dirs.append("    • lib/ - Library modules and utilities")
        if any("tests" in d.get("name", "") for d in file_tree):
            check_dirs.append("    • tests/ - Test files")
        if any(
            "hooks" in d.get("name", "").lower() or "claude" in d.get("name", "")
            for d in file_tree
        ):
            check_dirs.append("    • claude_hooks/ - Hook scripts")
        if any(
            d.get("name", "").endswith(".md")
            for d in file_tree
            if d.get("type") == "file"
        ):
            check_dirs.append("    • Root *.md files - Documentation")

        if check_dirs:
            for check_dir in check_dirs:
                output.append(check_dir)
        else:
            output.append("    • Review file tree above before creating new files")

        output.append("")
        output.append("  💡 TIP: Use Glob or Grep tools to search for existing files")
        output.append(
            "       before creating duplicates with similar names or purposes."
        )

        return "\n".join(output)

    def get_manifest_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about the manifest.

        Returns:
            Dictionary with counts and metadata
        """
        if self._manifest_data is None:
            return {
                "status": "not_loaded",
                "message": "Call generate_dynamic_manifest() first",
            }

        manifest = self._manifest_data
        metadata = manifest.get("manifest_metadata", {})

        return {
            "version": metadata.get("version"),
            "source": metadata.get("source"),
            "generated_at": metadata.get("generated_at"),
            "patterns_count": len(manifest.get("patterns", {}).get("available", [])),
            "cache_valid": self._is_cache_valid(),
            "cache_age_seconds": (
                (datetime.now(UTC) - self._last_update).total_seconds()
                if self._last_update
                else None
            ),
        }

    def _store_manifest_if_enabled(self, from_cache: bool = False) -> None:
        """
        Store manifest injection record if storage is enabled.

        Args:
            from_cache: Whether manifest came from cache
        """
        if not self.enable_storage or not self._storage:
            return

        if self._manifest_data is None:
            self.logger.warning("Cannot store manifest: no manifest data available")
            return

        if self._current_correlation_id is None:
            self.logger.warning("Cannot store manifest: no correlation ID set")
            return

        try:
            # Extract section counts
            manifest = self._manifest_data
            patterns_data = manifest.get("patterns", {})
            infrastructure_data = manifest.get("infrastructure", {})
            models_data = manifest.get("models", {})
            schemas_data = manifest.get("database_schemas", {})
            debug_data = manifest.get("debug_intelligence", {})

            patterns_count = len(patterns_data.get("available", []))
            collections_queried = patterns_data.get("collections_queried", {})

            # Count infrastructure services
            remote_services = infrastructure_data.get("remote_services", {})
            local_services = infrastructure_data.get("local_services", {})
            infrastructure_services = len(remote_services) + len(local_services)

            # Count models
            ai_models = models_data.get("ai_models", {})
            models_count = len(ai_models.get("providers", []))

            # Count schemas
            database_schemas_count = len(schemas_data.get("tables", []))

            # Debug intelligence counts
            workflows = debug_data.get("similar_workflows", {})
            debug_intelligence_successes = len(workflows.get("successes", []))
            debug_intelligence_failures = len(workflows.get("failures", []))

            # Filesystem counts
            filesystem_data = manifest.get("filesystem", {})
            filesystem_files_count = filesystem_data.get("total_files", 0)
            filesystem_directories_count = filesystem_data.get("total_directories", 0)

            # Get formatted text (generate if not cached)
            if self._cached_formatted:
                formatted_text = self._cached_formatted
            else:
                formatted_text = self.format_for_prompt()

            # Determine sections included
            sections_included = list(manifest.keys())
            if "manifest_metadata" in sections_included:
                sections_included.remove("manifest_metadata")

            # Store record
            success = self._storage.store_manifest_injection(
                correlation_id=self._current_correlation_id,
                agent_name=self.agent_name or "unknown",
                manifest_data=manifest,
                formatted_text=formatted_text,
                query_times=self._current_query_times,
                sections_included=sections_included,
                patterns_count=patterns_count,
                infrastructure_services=infrastructure_services,
                models_count=models_count,
                database_schemas_count=database_schemas_count,
                debug_intelligence_successes=debug_intelligence_successes,
                debug_intelligence_failures=debug_intelligence_failures,
                collections_queried=collections_queried,
                query_failures=self._current_query_failures,
                warnings=self._current_warnings,
                filesystem_files_count=filesystem_files_count,
                filesystem_directories_count=filesystem_directories_count,
            )

            if success:
                self.logger.debug(
                    f"[{self._current_correlation_id}] Stored manifest injection record "
                    f"(from_cache: {from_cache})"
                )
            else:
                self.logger.warning(
                    f"[{self._current_correlation_id}] Failed to store manifest injection record"
                )

        except Exception as e:
            self.logger.error(
                f"[{self._current_correlation_id}] Error storing manifest: {e}",
                exc_info=True,
            )

    def get_cache_metrics(self, query_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cache performance metrics.

        Args:
            query_type: Specific query type metrics (None = all metrics)

        Returns:
            Cache metrics dictionary with hit rates, query times, etc.
        """
        if not self.enable_cache or not self._cache:
            return {"error": "Caching disabled"}

        return self._cache.get_metrics(query_type)

    def invalidate_cache(self, query_type: Optional[str] = None) -> int:
        """
        Invalidate cache entries.

        Args:
            query_type: Specific query type to invalidate (None = invalidate all)

        Returns:
            Number of entries invalidated
        """
        if not self.enable_cache or not self._cache:
            return 0

        return self._cache.invalidate(query_type)

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Get cache information and statistics.

        Returns:
            Cache information dictionary with sizes, TTLs, and entry details
        """
        if not self.enable_cache or not self._cache:
            return {"error": "Caching disabled"}

        return self._cache.get_cache_info()

    def log_cache_metrics(self) -> None:
        """
        Log current cache metrics for monitoring.

        Logs overall cache performance including hit rates and query times.
        """
        if not self.enable_cache or not self._cache:
            self.logger.info("Cache metrics: caching disabled")
            return

        metrics = self.get_cache_metrics()
        overall = metrics.get("overall", {})

        self.logger.info(
            f"Cache metrics: "
            f"hit_rate={overall.get('hit_rate_percent', 0):.1f}%, "
            f"total_queries={overall.get('total_queries', 0)}, "
            f"cache_hits={overall.get('cache_hits', 0)}, "
            f"cache_misses={overall.get('cache_misses', 0)}, "
            f"avg_query_time={overall.get('average_query_time_ms', 0):.1f}ms, "
            f"avg_cache_time={overall.get('average_cache_query_time_ms', 0):.1f}ms"
        )

        # Log per-query-type metrics if available
        by_type = metrics.get("by_query_type", {})
        for query_type, type_metrics in by_type.items():
            if type_metrics.get("total_queries", 0) > 0:
                self.logger.debug(
                    f"Cache metrics [{query_type}]: "
                    f"hit_rate={type_metrics.get('hit_rate_percent', 0):.1f}%, "
                    f"queries={type_metrics.get('total_queries', 0)}"
                )

    def mark_agent_completed(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Mark agent execution as completed (lifecycle tracking).

        This fixes the "Active Agents never reaches 0" bug by properly updating
        the agent_manifest_injections table with completion timestamp.

        Uses the current correlation ID set during manifest generation.

        Args:
            success: Whether agent execution succeeded (default: True)
            error_message: Optional error message if execution failed

        Returns:
            True if successful, False otherwise

        Example:
            >>> async with ManifestInjector(agent_name="agent-researcher") as injector:
            ...     await injector.generate_dynamic_manifest_async(correlation_id)
            ...     # ... do agent work ...
            ...     injector.mark_agent_completed(success=True)
        """
        if not self.enable_storage or not self._storage:
            self.logger.debug("Agent completion tracking disabled (storage disabled)")
            return False

        if self._current_correlation_id is None:
            self.logger.warning(
                "Cannot mark agent as completed: no correlation ID set. "
                "Call generate_dynamic_manifest() first."
            )
            return False

        return self._storage.mark_agent_completed(
            correlation_id=self._current_correlation_id,
            success=success,
            error_message=error_message,
        )


# Convenience function for quick access (async with context manager)
async def inject_manifest_async(
    correlation_id: Optional[str] = None,
    sections: Optional[List[str]] = None,
    agent_name: Optional[str] = None,
) -> str:
    """
    Quick function to load and format manifest (asynchronous with context manager).

    Args:
        correlation_id: Optional correlation ID for tracking
        sections: Optional list of sections to include
        agent_name: Optional agent name for logging/traceability

    Returns:
        Formatted manifest string
    """
    from uuid import uuid4

    correlation_id = correlation_id or str(uuid4())

    async with ManifestInjector(agent_name=agent_name) as injector:
        # Generate manifest (will use cache if valid)
        try:
            await injector.generate_dynamic_manifest_async(correlation_id)
        except Exception as e:
            logger.error(f"Failed to generate dynamic manifest: {e}")
            # Will use minimal manifest

        return injector.format_for_prompt(sections)


# Convenience function for quick access (sync wrapper for backward compatibility)
def inject_manifest(
    correlation_id: Optional[str] = None,
    sections: Optional[List[str]] = None,
    agent_name: Optional[str] = None,
) -> str:
    """
    Quick function to load and format manifest (synchronous wrapper).

    Note: This is a synchronous wrapper around inject_manifest_async() for
    backward compatibility. Prefer using inject_manifest_async() directly
    in async contexts for better resource management.

    Uses nest_asyncio to support nested event loops when called from
    async contexts (like Claude Code).

    Args:
        correlation_id: Optional correlation ID for tracking
        sections: Optional list of sections to include
        agent_name: Optional agent name for logging/traceability

    Returns:
        Formatted manifest string
    """
    from uuid import uuid4

    correlation_id = correlation_id or str(uuid4())

    # Run async version in event loop
    # With nest_asyncio, we can always use run_until_complete
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            inject_manifest_async(correlation_id, sections, agent_name)
        )
    except RuntimeError as e:
        if "no running event loop" in str(e).lower():
            # Create new event loop if none exists
            logger.debug("Creating new event loop")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    inject_manifest_async(correlation_id, sections, agent_name)
                )
            finally:
                loop.close()
        else:
            logger.error(f"Failed to run inject_manifest_async: {e}", exc_info=True)
            # Fallback to minimal manifest
            injector = ManifestInjector(agent_name=agent_name)
            return injector.format_for_prompt(sections)
    except Exception as e:
        logger.error(f"Failed to run inject_manifest_async: {e}", exc_info=True)
        # Fallback to minimal manifest
        injector = ManifestInjector(agent_name=agent_name)
        return injector.format_for_prompt(sections)


__all__ = [
    "CacheMetrics",
    "CacheEntry",
    "ManifestCache",
    "ManifestInjector",
    "ManifestInjectionStorage",
    "inject_manifest",
    "inject_manifest_async",
]
