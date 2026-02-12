"""
Manifest Injector - Dynamic System Manifest via Event Bus

Provides agents with complete system awareness at spawn through dynamic queries
to onex-intelligence-adapter via Kafka event bus.

Key Features:
- Event-driven manifest generation (no static YAML)
- Queries Qdrant, Memgraph, PostgreSQL via onex-intelligence-adapter
- Request-response pattern with correlation tracking
- Graceful fallback to minimal manifest on timeout
- Compatible with existing hook infrastructure
- Async context manager for proper resource cleanup

Architecture:
    manifest_injector.py
      → Publishes to Kafka "intelligence.requests"
      → onex-intelligence-adapter consumes and queries backends
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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path as _Path
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)
from uuid import UUID

# NOTE: Package must be installed (pip install -e .) for this import to work.
# No sys.path manipulation needed when package is properly installed.
from omniclaude.config import settings

# Import nest_asyncio for nested event loop support
try:
    import nest_asyncio

    nest_asyncio.apply()  # Enable nested event loops globally
except ImportError:
    nest_asyncio = None

# FAIL FAST: Required dependencies
# FAIL FAST: Required ONEX error classes
from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.errors import EnumCoreErrorCode, OnexError
from omniclaude.lib.intelligence_usage_tracker import IntelligenceUsageTracker
from omniclaude.lib.pattern_quality_scorer import PatternQualityScorer
from omniclaude.lib.task_classifier import TaskClassifier, TaskContext, TaskIntent

from .intelligence_cache import IntelligenceCache
from .intelligence_event_client import IntelligenceEventClient

# Import ActionLogger type under TYPE_CHECKING for proper type hints
if TYPE_CHECKING:
    from .action_logger import ActionLogger as _ActionLoggerType

# Import ActionLogger for tracking intelligence gathering performance
ACTION_LOGGER_AVAILABLE: bool = False
ActionLogger: type | None = None


def _load_action_logger() -> bool:
    """Try to load ActionLogger from various locations."""
    global ACTION_LOGGER_AVAILABLE, ActionLogger
    try:
        from .action_logger import ActionLogger as _ALImport

        ActionLogger = _ALImport
        ACTION_LOGGER_AVAILABLE = True
        return True
    except ImportError:
        ACTION_LOGGER_AVAILABLE = False
        return False


_load_action_logger()


# Import data sanitizer for secure logging (optional integration)
def _load_sanitizers() -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    """
    Try to load sanitizer functions.

    Returns no-op functions if data_sanitizer module is not available.
    This is expected in minimal deployments without sanitization requirements.
    """
    try:
        from omniclaude.lib.data_sanitizer import sanitize_dict, sanitize_string

        return sanitize_dict, sanitize_string
    except ImportError:  # nosec B110 - Optional dependency, graceful degradation
        # Fallback: no-op sanitization functions
        def fallback_dict(d: Any, **kwargs: Any) -> Any:
            return d

        def fallback_string(s: Any, **kwargs: Any) -> Any:
            return s

        return fallback_dict, fallback_string


sanitize_dict, sanitize_string = _load_sanitizers()


logger = logging.getLogger(__name__)


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
            "last_hit": (self.last_hit_timestamp.isoformat() if self.last_hit_timestamp else None),
            "last_miss": (
                self.last_miss_timestamp.isoformat() if self.last_miss_timestamp else None
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
        self._caches: dict[str, CacheEntry] = {}
        self._ttls: dict[str, int] = {
            "patterns": default_ttl_seconds * 3,  # 15 minutes
            "infrastructure": default_ttl_seconds * 2,  # 10 minutes
            "models": default_ttl_seconds * 3,  # 15 minutes
            "database_schemas": default_ttl_seconds,  # 5 minutes
            "debug_intelligence": default_ttl_seconds // 2,  # 2.5 minutes
            "filesystem": default_ttl_seconds,  # 5 minutes
            "full_manifest": default_ttl_seconds,  # 5 minutes
        }
        self.metrics: dict[str, CacheMetrics] = {}
        if enable_metrics:
            for query_type in self._ttls:
                self.metrics[query_type] = CacheMetrics()
        self.logger = logging.getLogger(__name__)

    def get(self, query_type: str) -> Any | None:
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

    def set(self, query_type: str, data: Any, ttl_seconds: int | None = None) -> None:
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

    def invalidate(self, query_type: str | None = None) -> int:
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

    def get_metrics(self, query_type: str | None = None) -> dict[str, Any]:
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

    def get_cache_info(self) -> dict[str, Any]:
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
        db_host: str | None = None,
        db_port: int | None = None,
        db_name: str | None = None,
        db_user: str | None = None,
        db_password: str | None = None,
    ):
        """
        Initialize storage handler.

        Args:
            db_host: PostgreSQL host (default: env POSTGRES_HOST or localhost)
            db_port: PostgreSQL port (default: env POSTGRES_PORT or 5436)
            db_name: Database name (default: env POSTGRES_DATABASE or omninode_bridge)
            db_user: Database user (default: env POSTGRES_USER or postgres)
            db_password: Database password (default: env POSTGRES_PASSWORD)
        """
        self.db_host = db_host or os.environ.get("POSTGRES_HOST", "localhost")
        self.db_port = db_port or int(os.environ.get("POSTGRES_PORT", "5436"))
        self.db_name = db_name or os.environ.get("POSTGRES_DATABASE", "omninode_bridge")
        self.db_user = db_user or os.environ.get("POSTGRES_USER", "postgres")
        self.db_password = db_password or os.environ.get("POSTGRES_PASSWORD")
        if not self.db_password:
            raise ValueError("POSTGRES_PASSWORD environment variable not set. Run: source .env")

    @staticmethod
    def _serialize_for_json(obj: Any) -> Any:
        """
        Recursively convert Pydantic types to JSON-serializable types.

        Handles:
        - All Pydantic URL types (HttpUrl, AnyUrl, Url) → str
        - Pydantic models → dict
        - dict → recursively process values
        - list → recursively process items

        Args:
            obj: Object to serialize

        Returns:
            JSON-serializable version of obj
        """
        from pydantic import BaseModel

        # Handle None
        if obj is None:
            return None

        # Handle Pydantic URL types - check class name to avoid import issues
        # This catches HttpUrl, AnyUrl, Url, and other Pydantic URL types
        obj_type_name = type(obj).__name__
        if "Url" in obj_type_name or obj_type_name in ("HttpUrl", "AnyUrl", "Url"):
            return str(obj)

        # Alternative: check if object has __str__ and looks like a URL
        # This is a fallback for any URL-like objects we might have missed
        if hasattr(obj, "__str__") and hasattr(obj, "__class__"):
            module_name = type(obj).__module__
            if "pydantic" in module_name and (
                "url" in obj_type_name.lower() or "uri" in obj_type_name.lower()
            ):
                return str(obj)

        # Handle Pydantic models
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")

        # Handle dicts recursively
        if isinstance(obj, dict):
            return {k: ManifestInjectionStorage._serialize_for_json(v) for k, v in obj.items()}

        # Handle lists recursively
        if isinstance(obj, (list, tuple)):
            return [ManifestInjectionStorage._serialize_for_json(item) for item in obj]

        # Handle other types (str, int, bool, etc.)
        return obj

    def store_manifest_injection(
        self,
        correlation_id: UUID,
        agent_name: str,
        manifest_data: dict[str, Any],
        formatted_text: str,
        query_times: dict[str, int],
        sections_included: list[str],
        **kwargs: Any,
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

            # Serialize manifest_data to handle HttpUrl and other Pydantic types
            manifest_data = self._serialize_for_json(manifest_data)

            # Extract metadata
            metadata = manifest_data.get("manifest_metadata", {})
            manifest_version = metadata.get("version", "unknown")
            generation_source = metadata.get("source", "unknown")
            is_fallback = generation_source == "fallback"

            # Serialize query_times to handle any Pydantic types
            query_times = self._serialize_for_json(query_times)

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

            # Collections queried (serialize for JSON)
            collections_queried = self._serialize_for_json(kwargs.get("collections_queried", {}))

            # Query failures (serialize for JSON)
            query_failures = self._serialize_for_json(kwargs.get("query_failures", {}))

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
            logger.error(f"Failed to store manifest injection record: {e}", exc_info=True)
            return False

    def mark_agent_completed(
        self,
        correlation_id: UUID,
        success: bool = True,
        error_message: str | None = None,
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

    Replaces static YAML with real-time queries to onex-intelligence-adapter,
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
        kafka_brokers: str | None = None,
        enable_intelligence: bool = True,
        query_timeout_ms: int = 10000,
        enable_storage: bool = True,
        enable_cache: bool = True,
        cache_ttl_seconds: int | None = None,
        agent_name: str | None = None,
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
        # Initialize logger early for use throughout __init__
        self.logger = logging.getLogger(__name__)

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
        self._cache: ManifestCache | None
        if enable_cache:
            self._cache = ManifestCache(
                default_ttl_seconds=self.cache_ttl_seconds,
                enable_metrics=True,
            )
        else:
            self._cache = None

        # Initialize Valkey cache (distributed, persistent)
        # Valkey cache is checked BEFORE in-memory cache for better hit rates
        self._valkey_cache: IntelligenceCache | None = None
        if enable_cache:
            self._valkey_cache = IntelligenceCache()
        else:
            self._valkey_cache = None

        # Cached manifest data (for backward compatibility)
        self._manifest_data: dict[str, Any] | None = None
        self._cached_formatted: str | None = None
        self._last_update: datetime | None = None

        # Tracking for current generation
        self._current_correlation_id: UUID | None = None
        self._current_query_times: dict[str, int] = {}
        self._current_query_failures: dict[str, str | None] = {}
        self._current_warnings: list[str] = []

        # Storage handler
        self._storage: ManifestInjectionStorage | None
        if self.enable_storage:
            self._storage = ManifestInjectionStorage()
        else:
            self._storage = None

        # Intelligence usage tracker
        self._usage_tracker: IntelligenceUsageTracker | None = None
        if self.enable_storage:
            try:
                self._usage_tracker = IntelligenceUsageTracker()
            except Exception as e:
                self.logger.warning(f"Failed to initialize intelligence usage tracker: {e}")

        # Quality scoring configuration
        self.quality_scorer = PatternQualityScorer()
        self.enable_quality_filtering = settings.enable_pattern_quality_filter
        self.min_quality_threshold = settings.min_pattern_quality

        # Disabled pattern kill switch (OMN-1682)
        self.enable_disabled_pattern_filter = settings.enable_disabled_pattern_filter

        # ActionLogger cache (performance optimization - avoid recreating on every manifest generation)
        self._action_logger_cache: dict[str, _ActionLoggerType | None] = {}

    async def __aenter__(self) -> ManifestInjector:
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
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
            self.logger.error(f"Error during ManifestInjector cleanup: {e}", exc_info=True)

        # Return False to propagate any exceptions
        return False

    async def _filter_by_quality(self, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        metric_tasks = []

        for pattern in patterns:
            try:
                # Score pattern
                score = self.quality_scorer.score_pattern(pattern)

                # Store metrics asynchronously (collect tasks to await later)
                task = asyncio.create_task(self.quality_scorer.store_quality_metrics(score))
                metric_tasks.append(task)
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

        # Await all metric storage tasks to ensure data persistence
        if metric_tasks:
            self.logger.debug(f"Awaiting {len(metric_tasks)} metric storage tasks...")
            results = await asyncio.gather(*metric_tasks, return_exceptions=True)

            # Log any exceptions from metric storage
            failed_tasks = 0
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_tasks += 1
                    self.logger.warning(f"Metric storage task {idx + 1} failed: {result}")

            if failed_tasks > 0:
                self.logger.warning(
                    f"{failed_tasks}/{len(metric_tasks)} metric storage tasks failed"
                )
            else:
                self.logger.debug(
                    f"All {len(metric_tasks)} metric storage tasks completed successfully"
                )

        # Log filtering statistics
        self.logger.info(
            f"Quality filter: {len(filtered)}/{len(patterns)} patterns passed "
            f"(threshold: {self.min_quality_threshold}, scores recorded: {scores_recorded})"
        )

        return filtered

    async def _get_disabled_patterns(self) -> list[DisabledPattern]:
        """Get currently disabled patterns from the materialized view.

        Queries the disabled_patterns_current materialized view which computes
        the most recent disable/enable state per pattern from the event log.

        Returns:
            List of DisabledPattern entries. Empty list on any failure.
        """
        # Fast-path: skip when feature or Postgres is disabled
        if not self.enable_disabled_pattern_filter:
            return []
        if not settings.enable_postgres:
            return []

        def _blocking_query() -> list[DisabledPattern]:
            import psycopg2

            host = settings.postgres_host
            port = settings.postgres_port
            database = settings.postgres_database
            user = settings.postgres_user

            try:
                password = settings.get_effective_postgres_password()  # nosec
            except ValueError:
                return []

            if not password:
                return []

            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,  # nosec
                connect_timeout=1,
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT pattern_id, pattern_class, reason, event_at, actor "
                        "FROM disabled_patterns_current"
                    )
                    rows = cursor.fetchall()
                return [
                    DisabledPattern(
                        pattern_id=str(row[0]) if row[0] else None,
                        pattern_class=row[1],
                        reason=row[2] or "",
                        event_at=row[3],
                        actor=row[4] or "",
                    )
                    for row in rows
                ]
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_blocking_query)
        except Exception as e:
            self.logger.warning(f"Failed to query disabled patterns: {e}")
            return []

    async def _filter_disabled_patterns(
        self, patterns: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Filter out patterns that have been disabled via the kill switch.

        Checks each pattern against the disabled_patterns_current materialized
        view. Precedence rules:
        1. pattern_id match overrides pattern_class (specific beats general)
        2. Most recent event wins (handled by the materialized view)
        3. Default: enabled (no event = enabled)

        Args:
            patterns: List of pattern dictionaries from Qdrant.

        Returns:
            Filtered list excluding disabled patterns.
        """
        if not self.enable_disabled_pattern_filter:
            return patterns

        disabled = await self._get_disabled_patterns()
        if not disabled:
            return patterns

        disabled_ids = {d.pattern_id for d in disabled if d.pattern_id}
        disabled_classes = {d.pattern_class for d in disabled if d.pattern_class}

        if not disabled_ids and not disabled_classes:
            return patterns

        filtered = []
        skipped_by_id = 0
        skipped_by_class = 0

        for pattern in patterns:
            pid = pattern.get("pattern_id", "")
            ptype = pattern.get("pattern_type", "")

            # Check specific pattern ID first (highest precedence)
            if pid and str(pid) in disabled_ids:
                skipped_by_id += 1
                self.logger.info(f"Skipping disabled pattern (by ID): {pid}")
                continue

            # Check pattern class/type (lower precedence than ID)
            if ptype and ptype in disabled_classes:
                # Class is disabled. But if this specific pattern's ID was
                # explicitly re-enabled, the materialized view won't contain
                # a disabled row for it. However, we can't distinguish
                # "never mentioned" from "re-enabled" without querying the
                # full event log, so class disables are treated as absolute.
                skipped_by_class += 1
                self.logger.info(
                    f"Skipping pattern in disabled class: {ptype} "
                    f"(pattern: {pattern.get('name', 'unknown')})"
                )
                continue

            filtered.append(pattern)

        total_skipped = skipped_by_id + skipped_by_class
        if total_skipped > 0:
            self.logger.info(
                f"Disabled pattern filter: {len(filtered)}/{len(patterns)} patterns passed "
                f"(skipped {skipped_by_id} by ID, {skipped_by_class} by class)"
            )

        return filtered

    def generate_dynamic_manifest(
        self,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
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
            if self._manifest_data is None:
                # Cache consistency error - should not happen but handle gracefully
                self.logger.warning(
                    "Cache marked valid but manifest_data is None - forcing refresh"
                )
            else:
                return self._manifest_data

        # Run async query in event loop
        try:
            loop = asyncio.get_event_loop()
            # With nest_asyncio.apply(), we can run_until_complete even in running loop
            return loop.run_until_complete(
                self.generate_dynamic_manifest_async(correlation_id, force_refresh=force_refresh)
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
                            correlation_id, force_refresh=force_refresh
                        )
                    )
                finally:
                    loop.close()
            else:
                self.logger.error(f"Failed to generate dynamic manifest: {e}", exc_info=True)
                return self._get_minimal_manifest()
        except Exception as e:
            self.logger.error(f"Failed to generate dynamic manifest: {e}", exc_info=True)
            return self._get_minimal_manifest()

    def _get_action_logger(self, correlation_id: str) -> _ActionLoggerType | None:
        """
        Get or create ActionLogger instance with caching.

        Performance optimization: Avoid creating ActionLogger on every manifest
        generation by caching instances per correlation_id.

        Args:
            correlation_id: Correlation ID for this request

        Returns:
            ActionLogger instance or None if unavailable/failed
        """
        # Check cache first
        if correlation_id in self._action_logger_cache:
            return self._action_logger_cache[correlation_id]

        # Check availability (explicit check added for consistency)
        if not ACTION_LOGGER_AVAILABLE or ActionLogger is None:
            self.logger.debug("ActionLogger not available, skipping logging")
            self._action_logger_cache[correlation_id] = None
            return None

        # Create new instance
        try:
            logger = cast(
                "_ActionLoggerType",
                ActionLogger(
                    agent_name=self.agent_name or "manifest-injector",
                    correlation_id=correlation_id,
                    project_path=os.getcwd(),
                ),
            )
            self._action_logger_cache[correlation_id] = logger
            return logger
        except Exception as e:
            self.logger.warning(f"Failed to create ActionLogger: {e}")
            self._action_logger_cache[correlation_id] = None
            return None

    async def generate_dynamic_manifest_async(
        self,
        correlation_id: str,
        user_prompt: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
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
            user_prompt: User's task prompt for task-aware section selection (optional)
            force_refresh: Force refresh even if cache is valid

        Returns:
            Manifest data dictionary
        """
        import time

        # Convert correlation_id to UUID
        # correlation_id is always str per function signature, so direct conversion
        correlation_id_uuid = UUID(correlation_id)

        # Store correlation ID for tracking
        self._current_correlation_id = correlation_id_uuid

        # Reset tracking
        self._current_query_times = {}
        self._current_query_failures = {}
        self._current_warnings = []

        # Get or create ActionLogger for performance tracking (cached)
        action_logger = self._get_action_logger(str(correlation_id_uuid))

        # Check cache first
        if not force_refresh and self._is_cache_valid():
            self.logger.debug(f"Using cached manifest data (correlation_id: {correlation_id})")
            # Still log cache hit
            self._store_manifest_if_enabled(from_cache=True)

            # Log cache hit for performance tracking
            if action_logger:
                try:
                    await action_logger.log_success(
                        success_name="manifest_generation_complete",
                        success_details=sanitize_dict(
                            {
                                "total_time_ms": 0,  # Cache hit is instant
                                "cache_used": True,
                                "sections_included": (
                                    list(self._manifest_data.keys()) if self._manifest_data else []
                                ),
                            }
                        ),
                        duration_ms=0,
                    )
                except Exception as log_err:
                    self.logger.debug(f"ActionLogger cache hit logging failed: {log_err}")

            if self._manifest_data is None:
                # Cache consistency error - should not happen but handle gracefully
                self.logger.warning(
                    "Cache marked valid but manifest_data is None - forcing refresh"
                )
                # Fall through to regeneration below
            else:
                return self._manifest_data

        start_time = time.time()
        self.logger.info(
            f"[{correlation_id}] Generating dynamic manifest for agent '{self.agent_name or 'unknown'}'"
        )

        # Log intelligence query start
        if action_logger:
            try:
                await action_logger.log_decision(
                    decision_name="manifest_generation_start",
                    decision_context=sanitize_dict(
                        {
                            "agent_name": self.agent_name or "unknown",
                            "enable_intelligence": self.enable_intelligence,
                            "query_timeout_ms": self.query_timeout_ms,
                        }
                    ),
                )
            except Exception as log_err:
                self.logger.debug(f"ActionLogger decision logging failed: {log_err}")

        # Task classification for section selection
        task_context = None
        if user_prompt:
            try:
                classifier = TaskClassifier()
                task_context = classifier.classify(user_prompt)
                self.logger.info(
                    f"[{correlation_id}] Task classified: {task_context.primary_intent.value} "
                    f"(confidence: {task_context.confidence:.2f})"
                )
            except Exception as e:
                self.logger.warning(
                    f"[{correlation_id}] Failed to classify task: {e}. Proceeding with default sections.",
                    exc_info=True,
                )

        # Always query filesystem (local operation, doesn't require intelligence service)
        filesystem_result = await self._query_filesystem(correlation_id)

        # If intelligence disabled, return minimal manifest with filesystem and debug loop
        if not self.enable_intelligence:
            self.logger.info(
                f"Intelligence queries disabled, using minimal manifest with filesystem "
                f"(correlation_id: {correlation_id})"
            )
            manifest = self._get_minimal_manifest()
            manifest["filesystem"] = self._format_filesystem_result(filesystem_result)

            # Add debug loop context (always query, even when intelligence disabled)
            try:
                debug_loop_result = await self._query_debug_loop_context(correlation_id)
                manifest["debug_loop"] = self._format_debug_loop_result(debug_loop_result)
            except Exception as e:
                self.logger.warning(f"[{correlation_id}] Debug loop query failed: {e}")
                manifest["debug_loop"] = {
                    "available": False,
                    "reason": f"Query failed: {str(e)}",
                    "stf_count": 0,
                    "categories": [],
                    "top_stfs": [],
                }

            self._manifest_data = manifest
            self._cached_formatted = None  # Invalidate formatted cache for fresh manifest
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

            # Select sections based on task context
            sections_to_query = self._select_sections_for_task(task_context)
            self.logger.info(f"[{correlation_id}] Selected sections: {sections_to_query}")

            # Build query_tasks based on selected sections
            query_tasks = {}

            if "patterns" in sections_to_query:
                query_tasks["patterns"] = self._query_patterns(
                    correlation_id, task_context, user_prompt
                )

            if "infrastructure" in sections_to_query:
                query_tasks["infrastructure"] = self._query_infrastructure(correlation_id)

            if "models" in sections_to_query:
                query_tasks["models"] = self._query_models(correlation_id)

            if "database_schemas" in sections_to_query:
                query_tasks["database_schemas"] = self._query_database_schemas(
                    client, correlation_id
                )

            if "debug_intelligence" in sections_to_query:
                query_tasks["debug_intelligence"] = self._query_debug_intelligence(
                    client, correlation_id
                )

            # Add debug loop context query (always include for STF availability)
            query_tasks["debug_loop"] = self._query_debug_loop_context(correlation_id)

            if "semantic_search" in sections_to_query:
                # Use user_prompt for semantic search, or default query
                search_query = user_prompt or "ONEX patterns implementation examples"
                query_tasks["semantic_search"] = self._query_semantic_search(
                    query=search_query, limit=10
                )

            # Wait for all queries with timeout
            results = await asyncio.gather(
                *query_tasks.values(),
                return_exceptions=True,
            )

            # Build manifest from results (including filesystem queried earlier)
            # strict=False: Defensive - keys/results should match (same dict source),
            # but prefer partial results over ValueError if counts ever diverge
            all_results = dict(zip(query_tasks.keys(), results, strict=False))
            all_results["filesystem"] = filesystem_result  # Add filesystem result
            manifest = self._build_manifest_from_results(all_results)

            # Cache manifest
            self._manifest_data = manifest
            self._cached_formatted = None  # Invalidate formatted cache for fresh manifest
            self._last_update = datetime.now(UTC)

            # Calculate total generation time
            total_time_ms = int((time.time() - start_time) * 1000)

            # Extract pattern metrics
            pattern_count = len(manifest.get("patterns", {}).get("available", []))
            debug_successes = manifest.get("debug_intelligence", {}).get("total_successes", 0)
            debug_failures = manifest.get("debug_intelligence", {}).get("total_failures", 0)

            # Log pattern discovery performance
            if action_logger:
                try:
                    await action_logger.log_decision(
                        decision_name="pattern_discovery",
                        decision_context=sanitize_dict(
                            {
                                "collections_queried": list(query_tasks.keys()),
                                "sections_selected": sections_to_query,
                            }
                        ),
                        decision_result=sanitize_dict(
                            {
                                "pattern_count": pattern_count,
                                "debug_successes": debug_successes,
                                "debug_failures": debug_failures,
                                "query_times_ms": self._current_query_times,
                            }
                        ),
                        duration_ms=total_time_ms,
                    )
                except Exception as log_err:
                    self.logger.debug(f"ActionLogger pattern logging failed: {log_err}")

            self.logger.info(
                f"[{correlation_id}] Dynamic manifest generated successfully "
                f"(total_time: {total_time_ms}ms, patterns: {pattern_count}, "
                f"debug_intel: {debug_successes} successes/{debug_failures} failures)"
            )

            # Store manifest injection record
            self._store_manifest_if_enabled(from_cache=False)

            # Log successful manifest generation
            if action_logger:
                try:
                    await action_logger.log_success(
                        success_name="manifest_generation_complete",
                        success_details=sanitize_dict(
                            {
                                "total_time_ms": total_time_ms,
                                "pattern_count": pattern_count,
                                "sections_included": list(manifest.keys()),
                                "cache_used": False,
                            }
                        ),
                        duration_ms=total_time_ms,
                    )
                except Exception as log_err:
                    self.logger.debug(f"ActionLogger final logging failed: {log_err}")

            return manifest

        except Exception as e:
            self.logger.error(
                f"[{correlation_id}] Failed to query intelligence service: {e}",
                exc_info=True,
            )
            self._current_warnings.append(f"Intelligence query failed: {str(e)}")

            # Log intelligence query failure
            if action_logger:
                try:
                    await action_logger.log_error(
                        error_type="IntelligenceQueryError",
                        error_message=str(e),
                        error_context=sanitize_dict(
                            {
                                "agent_name": self.agent_name or "unknown",
                                "correlation_id": str(correlation_id),
                                "query_timeout_ms": self.query_timeout_ms,
                                "warnings": self._current_warnings,
                            }
                        ),
                        severity="error",
                    )
                except Exception as log_err:
                    self.logger.debug(f"ActionLogger error logging failed: {log_err}")

            # Fall back to minimal manifest
            return self._get_minimal_manifest()

        finally:
            # Stop client
            await client.stop()

    async def _embed_text(self, text: str, model: str | None = None) -> list[float]:
        """
        Embed text using GTE-Qwen2-1.5B embedding service.

        Args:
            text: Text to embed
            model: Embedding model name (default: Alibaba-NLP/gte-Qwen2-1.5B-instruct for 1536-dim)

        Returns:
            Embedding vector as list of floats (1536 dimensions)

        Raises:
            RuntimeError: If embedding service is unavailable or returns an error
        """
        import aiohttp

        if model is None:
            # Default to GTE-Qwen2-1.5B (1536 dimensions, matches archon_vectors collection)
            model = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"

        # GTE-Qwen2 embedding service (OpenAI-compatible API)
        # Default to localhost - production URLs should be set via EMBEDDING_SERVICE_URL env var
        embedding_url = os.environ.get(
            "EMBEDDING_SERVICE_URL", "http://localhost:8002/v1/embeddings"
        )

        try:
            payload = {
                "input": text,
                "model": model,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    embedding_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        # OpenAI-compatible format: data[0].embedding
                        embedding = data["data"][0]["embedding"]
                        return cast(list[float], embedding)
                    else:
                        error_text = await response.text()
                        raise OnexError(
                            code=EnumCoreErrorCode.DEPENDENCY_ERROR,
                            message=f"GTE-Qwen2 embedding failed with status {response.status}: {error_text}",
                        )
        except Exception as e:
            self.logger.error(f"GTE-Qwen2 embedding service error: {e}")
            raise OnexError(
                code=EnumCoreErrorCode.DEPENDENCY_ERROR,
                message=f"Embedding service unavailable at {embedding_url}",
            ) from e

    async def _query_patterns_direct_qdrant(
        self,
        correlation_id: str,
        collections: list[str] | None = None,
        limit_per_collection: int = 20,
        task_context: TaskContext | None = None,
        user_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Direct fallback: Query Qdrant HTTP API directly for patterns.

        This method bypasses the event bus and queries Qdrant directly via HTTP.
        Uses vector search API for semantic similarity when user_prompt is provided.
        Falls back to scroll API when no prompt is available.

        Args:
            correlation_id: Correlation ID for tracking
            collections: List of collection names (default: ["code_generation_patterns"])
            limit_per_collection: Number of patterns to retrieve per collection
            task_context: Classified task context for relevance filtering (optional)
            user_prompt: Original user prompt for semantic search (optional)

        Returns:
            Patterns data dictionary with results from Qdrant
        """
        import time

        import aiohttp

        if collections is None:
            # Use archon_vectors which has 1536-dim vectors (matches gte-qwen2 model)
            collections = ["archon_vectors"]

        start_time = time.time()
        all_patterns = []

        # Embed user prompt for semantic search
        query_vector = None
        if user_prompt:
            try:
                self.logger.info(f"[{correlation_id}] Embedding user prompt for semantic search")
                query_vector = await self._embed_text(user_prompt)
                self.logger.info(
                    f"[{correlation_id}] Generated embedding vector (dim={len(query_vector)})"
                )
            except Exception as e:
                # NO FALLBACKS - fail loudly if embedding service is unavailable
                self.logger.error(
                    f"[{correlation_id}] GTE-Qwen2 embedding service unavailable: {e}"
                )
                raise OnexError(
                    code=EnumCoreErrorCode.DEPENDENCY_ERROR,
                    message="Embedding service required for semantic search. "
                    "Set EMBEDDING_SERVICE_URL in .env to the GTE-Qwen2 service endpoint.",
                ) from e

        try:
            # Get Qdrant URL and strip trailing slashes to avoid double-slash in URL
            qdrant_url = os.environ.get("QDRANT_URL", str(settings.qdrant_url)).rstrip("/")

            async with aiohttp.ClientSession() as session:
                for collection_name in collections:
                    try:
                        # Use search API if we have a query vector, otherwise use scroll
                        if query_vector:
                            # Vector search for semantic similarity
                            url = f"{qdrant_url}/collections/{collection_name}/points/search"
                            payload = {
                                "vector": query_vector,
                                "limit": limit_per_collection,
                                "with_payload": True,
                                "with_vector": False,
                            }
                            search_method = "search (vector)"
                        else:
                            # Fallback to scroll API
                            url = f"{qdrant_url}/collections/{collection_name}/points/scroll"
                            payload = {
                                "limit": limit_per_collection,
                                "with_payload": True,
                                "with_vector": False,
                            }
                            search_method = "scroll"

                        async with session.post(url, json=payload) as response:
                            if response.status == 200:
                                data = await response.json()
                                result = data.get("result", [])

                                # Handle different response structures:
                                # - search API returns result as direct list: {"result": [...]}
                                # - scroll API returns result as dict with points: {"result": {"points": [...]}}
                                if isinstance(result, list):
                                    points = result
                                elif isinstance(result, dict):
                                    points = result.get("points", [])
                                else:
                                    points = []

                                # Transform Qdrant points to pattern format
                                for point in points:
                                    try:
                                        point_payload = point.get("payload", {})

                                        # Handle different collection structures
                                        # archon_vectors: has quality_score, pattern_confidence at top level
                                        # code_generation_patterns: has source_context.quality_score
                                        source_context = point_payload.get("source_context", {})
                                        metadata = point_payload.get("metadata", {})

                                        # Extract node_types - check multiple locations
                                        node_types = point_payload.get("node_types", [])
                                        if not node_types and isinstance(metadata, dict):
                                            node_types = metadata.get("node_types", [])
                                        if (
                                            not node_types
                                            and isinstance(source_context, dict)
                                            and source_context.get("node_type")
                                        ):
                                            node_types = [source_context.get("node_type")]

                                        # Extract use_cases - check multiple locations
                                        use_cases = point_payload.get("use_cases", [])
                                        if not use_cases and isinstance(metadata, dict):
                                            use_cases = metadata.get("use_cases", [])
                                        if not use_cases:
                                            reuse_conds = point_payload.get("reuse_conditions", [])
                                            if isinstance(reuse_conds, list):
                                                use_cases = reuse_conds

                                        # Extract file_path - check both payload and metadata
                                        file_path = point_payload.get("file_path", "")
                                        if not file_path and isinstance(metadata, dict):
                                            file_path = metadata.get("file_path", "")

                                        # Extract full content for code snippets (don't truncate here)
                                        full_content = point_payload.get("content", "")

                                        # Extract language information
                                        language = point_payload.get("language", "")
                                        if not language and isinstance(metadata, dict):
                                            language = metadata.get("language", "")
                                        if not language and file_path:
                                            # Infer language from file extension
                                            if file_path.endswith(".py"):
                                                language = "python"
                                            elif file_path.endswith((".ts", ".tsx")):
                                                language = "typescript"
                                            elif file_path.endswith((".js", ".jsx")):
                                                language = "javascript"
                                            elif file_path.endswith(".go"):
                                                language = "go"
                                            elif file_path.endswith(".rs"):
                                                language = "rust"

                                        # Extract semantic score from point.score (for search API)
                                        # This is the vector similarity score from Qdrant search
                                        semantic_score = point.get("score", 0.5)

                                        # Extract quality score - prioritize source_context, then top-level
                                        if (
                                            isinstance(source_context, dict)
                                            and "quality_score" in source_context
                                        ):
                                            quality_score = source_context.get("quality_score", 0.5)
                                        else:
                                            quality_score = point_payload.get("quality_score", 0.5)

                                        # Extract confidence - use pattern_confidence or confidence_score
                                        confidence = point_payload.get("pattern_confidence", 0.0)
                                        if confidence == 0.0:
                                            confidence = point_payload.get("confidence_score", 0.0)
                                        if confidence == 0.0 and isinstance(metadata, dict):
                                            confidence = metadata.get("confidence", 0.0)
                                        if confidence == 0.0:
                                            # If using vector search, semantic_score is meaningful
                                            confidence = semantic_score

                                        # Extract keywords - from reuse_conditions, concepts, or themes
                                        keywords = point_payload.get("reuse_conditions", [])
                                        if not keywords:
                                            keywords = point_payload.get("concepts", [])
                                        if not keywords:
                                            keywords = point_payload.get("themes", [])
                                        if not isinstance(keywords, list):
                                            keywords = []

                                        pattern = {
                                            "name": point_payload.get(
                                                "pattern_name",
                                                point_payload.get(
                                                    "title",
                                                    point_payload.get("name", "Unknown Pattern"),
                                                ),
                                            ),
                                            "description": point_payload.get(
                                                "pattern_description",
                                                point_payload.get(
                                                    "content",
                                                    point_payload.get("description", ""),
                                                )[:500],  # Limit description length for display
                                            ),
                                            "file_path": file_path,
                                            "content": full_content,  # Preserve full content for code snippets
                                            "language": language,  # Language for syntax highlighting
                                            "node_types": (
                                                node_types if isinstance(node_types, list) else []
                                            ),
                                            "confidence": confidence,
                                            "use_cases": (
                                                use_cases if isinstance(use_cases, list) else []
                                            ),
                                            "pattern_id": point_payload.get(
                                                "pattern_id",
                                                point_payload.get("entity_id", ""),
                                            ),
                                            "pattern_type": point_payload.get(
                                                "pattern_type",
                                                point_payload.get("entity_type", ""),
                                            ),
                                            "confidence_score": point_payload.get(
                                                "confidence_score",
                                                point_payload.get("pattern_confidence", 0.0),
                                            ),
                                            "usage_count": point_payload.get("usage_count", 0),
                                            "success_rate": point_payload.get("success_rate", 0.0),
                                            "source_context": (
                                                source_context
                                                if isinstance(source_context, dict)
                                                else {}
                                            ),
                                            "example_usage": point_payload.get(
                                                "example_usage",
                                                point_payload.get("examples", []),
                                            ),
                                            "pattern_template": point_payload.get(
                                                "pattern_template", ""
                                            ),
                                            "reuse_conditions": point_payload.get(
                                                "reuse_conditions", []
                                            ),
                                            # Keywords from various sources
                                            "keywords": keywords,
                                            # Proper metadata extraction
                                            "metadata": {
                                                # Use quality_score from source_context or top-level
                                                "quality_score": quality_score,
                                                "confidence_score": point_payload.get(
                                                    "confidence_score",
                                                    point_payload.get("pattern_confidence", 0.5),
                                                ),
                                                "success_rate": point_payload.get(
                                                    "success_rate", 0.5
                                                ),
                                                "usage_count": point_payload.get("usage_count", 0),
                                                "pattern_type": point_payload.get(
                                                    "pattern_type",
                                                    point_payload.get("entity_type", ""),
                                                ),
                                                "node_type": (
                                                    source_context.get("node_type", "")
                                                    if isinstance(source_context, dict)
                                                    else ""
                                                ),
                                                "onex_type": point_payload.get("onex_type", ""),
                                                "onex_compliance": point_payload.get(
                                                    "onex_compliance", 0.0
                                                ),
                                                # FIXED: Extract semantic_score from point.score (vector similarity)
                                                # When using search API, this is the cosine similarity (0.0-1.0)
                                                # When using scroll API, defaults to 0.5 (neutral)
                                                "semantic_score": semantic_score,
                                            },
                                        }
                                        all_patterns.append(pattern)
                                    except Exception as e:
                                        self.logger.warning(
                                            f"[{correlation_id}] Failed to parse pattern from {collection_name}: {e}"
                                        )
                                        continue

                                self.logger.info(
                                    f"[{correlation_id}] Direct Qdrant query ({search_method}): Retrieved {len(points)} patterns from {collection_name}"
                                )
                            else:
                                self.logger.warning(
                                    f"[{correlation_id}] Qdrant query ({search_method}) failed for {collection_name}: HTTP {response.status}"
                                )
                    except Exception as e:
                        import traceback

                        self.logger.warning(
                            f"[{correlation_id}] Failed to query {collection_name}: {e}\n{traceback.format_exc()}"
                        )
                        continue

            # Apply relevance filtering if task_context and user_prompt are provided
            if task_context and user_prompt and all_patterns:
                original_count = len(all_patterns)

                # Use Qdrant semantic scores directly (from GTE-Qwen2 vector similarity)
                # These are already high-quality semantic scores, no need to re-score
                relevance_threshold = 0.3

                # Extract semantic_score from metadata and use as hybrid_score
                for pattern in all_patterns:
                    metadata = pattern.get("metadata", {})
                    semantic_score = metadata.get("semantic_score", 0.5)

                    # Map semantic_score to hybrid_score for consistency with downstream code
                    pattern["hybrid_score"] = semantic_score
                    pattern["score_breakdown"] = {"semantic_score": semantic_score}
                    pattern["score_metadata"] = {
                        "source": "qdrant_vector_similarity",
                        "model": "GTE-Qwen2-7B-instruct",
                    }

                # Filter by semantic score threshold
                filtered_patterns = [
                    p for p in all_patterns if p.get("hybrid_score", 0.0) > relevance_threshold
                ]

                # Sort by score descending
                filtered_patterns.sort(key=lambda p: p.get("hybrid_score", 0.0), reverse=True)

                # Limit to configured maximum
                all_patterns = filtered_patterns[:limit_per_collection]

                if filtered_patterns:
                    avg_score = sum(p.get("hybrid_score", 0.0) for p in filtered_patterns) / len(
                        filtered_patterns
                    )
                    self.logger.info(
                        f"[{correlation_id}] Filtered patterns by Qdrant semantic score: "
                        f"{len(all_patterns)} relevant (from {original_count} total), "
                        f"threshold={relevance_threshold}, avg_score={avg_score:.2f}"
                    )
                else:
                    self.logger.warning(
                        f"[{correlation_id}] No patterns met semantic score threshold (>{relevance_threshold})"
                    )

            elapsed_ms = int((time.time() - start_time) * 1000)

            result = {
                "patterns": all_patterns,
                "query_time_ms": elapsed_ms,
                "total_count": len(all_patterns),
                "collections_queried": {
                    collection: len([p for p in all_patterns if collection in str(p)])
                    for collection in collections
                },
                "fallback_method": "direct_qdrant_http",
            }

            self.logger.info(
                f"[{correlation_id}] Direct Qdrant fallback completed: {len(all_patterns)} patterns in {elapsed_ms}ms"
            )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"[{correlation_id}] Direct Qdrant fallback failed: {e}")
            return {"patterns": [], "error": str(e), "query_time_ms": elapsed_ms}

    async def _query_patterns(
        self,
        correlation_id: str,
        task_context: TaskContext | None = None,
        user_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Query available code generation patterns from BOTH collections.

        Queries both archon_vectors (ONEX templates) and code_generation_patterns
        (real code implementations) from Qdrant vector database via direct HTTP.

        Uses direct Qdrant HTTP queries (no Kafka event bus dependency).

        Args:
            correlation_id: Correlation ID for tracking
            task_context: Classified task context for relevance filtering (optional)
            user_prompt: Original user prompt for relevance filtering (optional)

        Returns:
            Patterns data dictionary with merged results from both collections
        """
        import time

        start_time = time.time()

        # Check Valkey cache first (distributed, persistent)
        if self._valkey_cache:
            cache_params = {
                "collections": ["archon_vectors", "code_generation_patterns"],
                "limits": {"archon_vectors": 50, "code_generation_patterns": 100},
            }
            try:
                cached_result = await self._valkey_cache.get("pattern_discovery", cache_params)
                if cached_result is not None:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["patterns"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Pattern query: VALKEY CACHE HIT ({elapsed_ms}ms)"
                    )
                    # Also store in in-memory cache for faster subsequent access
                    if self.enable_cache and self._cache:
                        self._cache.set("patterns", cached_result)
                    # Cast to dict for type safety
                    cached_dict: dict[str, Any] = (
                        cached_result if isinstance(cached_result, dict) else {}
                    )
                    return cached_dict
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
                # Cast to dict for type safety
                cached_dict_mem: dict[str, Any] = (
                    cached_result if isinstance(cached_result, dict) else {}
                )
                return cached_dict_mem

        try:
            self.logger.debug(
                f"[{correlation_id}] Querying patterns from both collections via direct HTTP (PARALLEL)"
            )

            # Execute BOTH collection queries in parallel using direct Qdrant HTTP
            # Query archon_vectors (ONEX templates) and code_generation_patterns (real implementations)
            templates_task = self._query_patterns_direct_qdrant(
                correlation_id=correlation_id,
                collections=["archon_vectors"],
                limit_per_collection=50,
                task_context=task_context,
                user_prompt=user_prompt,
            )

            codegen_task = self._query_patterns_direct_qdrant(
                correlation_id=correlation_id,
                collections=["code_generation_patterns"],
                limit_per_collection=100,
                task_context=task_context,
                user_prompt=user_prompt,
            )

            # Wait for both queries to complete in parallel
            self.logger.debug("Waiting for both pattern queries to complete in parallel...")
            results = await asyncio.gather(templates_task, codegen_task, return_exceptions=True)
            templates_result, codegen_result = results

            # Handle exceptions from gather
            templates_dict: dict[str, Any] = {"patterns": [], "query_time_ms": 0}
            codegen_dict: dict[str, Any] = {"patterns": [], "query_time_ms": 0}

            if isinstance(templates_result, Exception):
                self.logger.warning(f"archon_vectors query failed: {templates_result}")
                templates_dict = {"patterns": [], "query_time_ms": 0}
            elif isinstance(templates_result, dict):
                templates_dict = templates_result

            if isinstance(codegen_result, Exception):
                self.logger.warning(f"code_generation_patterns query failed: {codegen_result}")
                codegen_dict = {"patterns": [], "query_time_ms": 0}
            elif isinstance(codegen_result, dict):
                codegen_dict = codegen_result

            # Merge results from both collections
            template_patterns = templates_dict.get("patterns", [])
            codegen_patterns = codegen_dict.get("patterns", [])

            all_patterns = template_patterns + codegen_patterns

            # Apply quality filtering if enabled
            all_patterns = await self._filter_by_quality(all_patterns)

            # Apply disabled pattern kill switch (OMN-1682)
            all_patterns = await self._filter_disabled_patterns(all_patterns)

            # Calculate combined query time
            exec_time = templates_dict.get("query_time_ms", 0)
            code_time = codegen_dict.get("query_time_ms", 0)
            total_query_time = exec_time + code_time

            # Track timing
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["patterns"] = elapsed_ms

            # Calculate speedup factor from parallelization
            speedup = round(total_query_time / max(elapsed_ms, 1), 1)

            self.logger.info(
                f"[{correlation_id}] Pattern query results (PARALLEL via direct HTTP): {len(template_patterns)} from archon_vectors, "
                f"{len(codegen_patterns)} from code_generation_patterns, "
                f"{len(all_patterns)} total patterns, "
                f"query_time={total_query_time}ms, elapsed={elapsed_ms}ms, speedup={speedup}x"
            )

            if all_patterns:
                self.logger.debug(
                    f"[{correlation_id}] First pattern: {all_patterns[0].get('name', 'unknown')}"
                )
            else:
                self.logger.warning(
                    f"[{correlation_id}] Direct Qdrant query returned 0 patterns from both collections"
                )

            result = {
                "patterns": all_patterns,
                "query_time_ms": total_query_time,
                "total_count": len(all_patterns),
                "collections_queried": {
                    "archon_vectors": len(template_patterns),
                    "code_generation_patterns": len(codegen_patterns),
                },
            }

            # Track intelligence usage for each pattern retrieved
            if self._usage_tracker:
                try:
                    tracking_successes = 0
                    tracking_failures = 0

                    # Track archon_vectors collection patterns
                    for i, pattern in enumerate(template_patterns):
                        success = await self._usage_tracker.track_retrieval(
                            correlation_id=UUID(correlation_id),
                            agent_name=self.agent_name or "unknown",
                            intelligence_type="pattern",
                            intelligence_source="qdrant",
                            intelligence_name=pattern.get("name", "unknown"),
                            collection_name="archon_vectors",
                            confidence_score=pattern.get(
                                "confidence", pattern.get("confidence_score")
                            ),
                            query_time_ms=exec_time,
                            query_used="PATTERN_EXTRACTION",
                            query_results_rank=i + 1,
                            intelligence_snapshot=pattern,
                            intelligence_summary=pattern.get("description", ""),
                            metadata={
                                "source": "direct_http",
                                "parallel_query": True,
                            },
                        )
                        if success:
                            tracking_successes += 1
                        else:
                            tracking_failures += 1
                            self.logger.warning(
                                f"[{correlation_id}] Failed to track archon_vectors pattern retrieval: "
                                f"{pattern.get('name', 'unknown')}"
                            )

                    # Track code_generation_patterns
                    for i, pattern in enumerate(codegen_patterns):
                        success = await self._usage_tracker.track_retrieval(
                            correlation_id=UUID(correlation_id),
                            agent_name=self.agent_name or "unknown",
                            intelligence_type="pattern",
                            intelligence_source="qdrant",
                            intelligence_name=pattern.get("name", "unknown"),
                            collection_name="code_generation_patterns",
                            confidence_score=pattern.get(
                                "confidence", pattern.get("confidence_score")
                            ),
                            query_time_ms=code_time,
                            query_used="PATTERN_EXTRACTION",
                            query_results_rank=i + 1,
                            intelligence_snapshot=pattern,
                            intelligence_summary=pattern.get("description", ""),
                            metadata={
                                "source": "direct_http",
                                "parallel_query": True,
                            },
                        )
                        if success:
                            tracking_successes += 1
                        else:
                            tracking_failures += 1
                            self.logger.warning(
                                f"[{correlation_id}] Failed to track code_generation_patterns pattern retrieval: "
                                f"{pattern.get('name', 'unknown')}"
                            )

                    # Log summary of tracking results
                    total_patterns = len(all_patterns)
                    if tracking_successes > 0:
                        self.logger.debug(
                            f"[{correlation_id}] Tracked {tracking_successes}/{total_patterns} pattern retrievals successfully"
                        )

                    # Alert if systematic tracking failures
                    if tracking_failures > 0:
                        failure_rate = (
                            (tracking_failures / total_patterns) * 100 if total_patterns > 0 else 0
                        )
                        self.logger.warning(
                            f"[{correlation_id}] Intelligence tracking failures: {tracking_failures}/{total_patterns} "
                            f"({failure_rate:.1f}% failure rate). Check database connectivity and POSTGRES_PASSWORD."
                        )

                except Exception as track_error:
                    self.logger.warning(
                        f"[{correlation_id}] Failed to track pattern retrievals: {track_error}"
                    )

            # Cache the result in both Valkey and in-memory caches
            # Valkey cache (distributed, persistent)
            if self._valkey_cache:
                cache_params = {
                    "collections": ["archon_vectors", "code_generation_patterns"],
                    "limits": {"archon_vectors": 50, "code_generation_patterns": 100},
                }
                try:
                    await self._valkey_cache.set("pattern_discovery", cache_params, result)
                    self.logger.debug(f"[{correlation_id}] Stored patterns in Valkey cache")
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
            self.logger.error(f"[{correlation_id}] Pattern query via direct HTTP failed: {e}")

            return {"patterns": [], "error": str(e)}

    async def _query_infrastructure(
        self,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query current infrastructure topology.

        Queries for:
        - PostgreSQL databases and schemas
        - Kafka/Redpanda topics
        - Qdrant collections
        - Memgraph graph database
        - Docker services

        Args:
            correlation_id: Correlation ID for tracking

        Returns:
            Infrastructure data dictionary with actual service connection details
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying infrastructure topology")

            # Query all services in parallel
            postgres_task = self._query_postgresql()
            kafka_task = self._query_kafka()
            qdrant_task = self._query_qdrant()
            memgraph_task = self._query_memgraph()
            docker_task = self._query_docker_services()

            # Wait for all queries to complete
            (
                postgres_info,
                kafka_info,
                qdrant_info,
                memgraph_info,
                docker_services,
            ) = await asyncio.gather(
                postgres_task,
                kafka_task,
                qdrant_task,
                memgraph_task,
                docker_task,
                return_exceptions=True,
            )

            # Handle exceptions from gather
            if isinstance(postgres_info, Exception):
                self.logger.warning(f"PostgreSQL query failed: {postgres_info}")
                postgres_info = {"status": "unavailable", "error": str(postgres_info)}

            if isinstance(kafka_info, Exception):
                self.logger.warning(f"Kafka query failed: {kafka_info}")
                kafka_info = {"status": "unavailable", "error": str(kafka_info)}

            if isinstance(qdrant_info, Exception):
                self.logger.warning(f"Qdrant query failed: {qdrant_info}")
                qdrant_info = {"status": "unavailable", "error": str(qdrant_info)}

            if isinstance(memgraph_info, Exception):
                self.logger.warning(f"Memgraph query failed: {memgraph_info}")
                memgraph_info = {"status": "unavailable", "error": str(memgraph_info)}

            if isinstance(docker_services, Exception):
                self.logger.warning(f"Docker query failed: {docker_services}")
                docker_services = []

            # Build infrastructure result
            result = {
                "remote_services": {"postgresql": postgres_info, "kafka": kafka_info},
                "local_services": {
                    "qdrant": qdrant_info,
                    "memgraph": memgraph_info,
                },
                "docker_services": docker_services,
            }

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["infrastructure"] = elapsed_ms
            self.logger.info(f"[{correlation_id}] Infrastructure query completed in {elapsed_ms}ms")

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["infrastructure"] = elapsed_ms
            self._current_query_failures["infrastructure"] = str(e)
            self.logger.warning(f"[{correlation_id}] Infrastructure query failed: {e}")
            return {
                "remote_services": {"postgresql": {}, "kafka": {}},
                "local_services": {"qdrant": {}, "memgraph": {}},
                "docker_services": [],
                "error": str(e),
            }

    async def _query_postgresql(self) -> dict[str, Any]:
        """
        Query PostgreSQL for connection details and statistics.

        Returns:
            Dictionary with PostgreSQL connection info, status, and table count
        """

        def _blocking_query() -> dict[str, Any]:
            """Blocking PostgreSQL operations."""
            import psycopg2

            # Get connection details from centralized settings (NO hardcoded defaults)
            host = settings.postgres_host
            port = settings.postgres_port
            database = settings.postgres_database
            user = settings.postgres_user

            try:
                password = settings.get_effective_postgres_password()  # nosec
            except ValueError:
                password = ""  # nosec

            if not password:
                return {
                    "host": host,
                    "port": port,
                    "database": database,
                    "status": "unavailable",
                    "error": "POSTGRES_PASSWORD not set in environment",
                }

            # Try to connect and query table count
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                connect_timeout=2,
            )

            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            result = cursor.fetchone()
            table_count = result[0] if result else 0
            cursor.close()
            conn.close()

            return {
                "host": host,
                "port": port,
                "database": database,
                "status": "connected",
                "tables": table_count,
                "note": f"Connected with {table_count} tables in public schema",
            }

        try:
            # Run blocking I/O in thread pool
            return await asyncio.to_thread(_blocking_query)

        except ImportError:
            return {
                "status": "unavailable",
                "error": "psycopg2 not installed (pip install psycopg2-binary)",
            }
        except Exception as e:
            return {"status": "unavailable", "error": f"Connection failed: {str(e)}"}

    async def _query_kafka(self) -> dict[str, Any]:
        """
        Query Kafka/Redpanda for connection details and topic count.

        Returns:
            Dictionary with Kafka connection info, status, and topic count
        """

        def _blocking_query() -> dict[str, Any]:
            """Blocking Kafka operations."""
            from kafka import KafkaAdminClient

            # Get bootstrap servers from settings
            bootstrap_servers = settings.get_effective_kafka_bootstrap_servers()

            # Try to connect and list topics
            admin = KafkaAdminClient(
                bootstrap_servers=bootstrap_servers,
                request_timeout_ms=2000,
                api_version_auto_timeout_ms=2000,
            )

            topics = admin.list_topics()
            admin.close()

            return {
                "bootstrap_servers": bootstrap_servers,
                "status": "connected",
                "topics": len(topics),
                "note": f"Connected with {len(topics)} topics",
            }

        try:
            # Run blocking I/O in thread pool
            return await asyncio.to_thread(_blocking_query)

        except ImportError:
            return {
                "status": "unavailable",
                "error": "kafka-python not installed (pip install kafka-python)",
            }
        except Exception as e:
            return {"status": "unavailable", "error": f"Connection failed: {str(e)}"}

    async def _query_qdrant(self) -> dict[str, Any]:
        """
        Query Qdrant for connection details and collection statistics.

        Returns:
            Dictionary with Qdrant connection info, status, and collection stats
        """
        try:
            import aiohttp

            # Get Qdrant URL from settings and strip trailing slashes to avoid double-slash in URL
            qdrant_url = str(settings.qdrant_url).rstrip("/")

            # Try to fetch collections
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{qdrant_url}/collections", timeout=aiohttp.ClientTimeout(total=2)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        collections = data.get("result", {}).get("collections", [])

                        # Count total vectors across all collections
                        total_vectors = 0
                        for collection in collections:
                            if isinstance(collection, dict):
                                total_vectors += collection.get("points_count", 0)

                        return {
                            "url": qdrant_url,
                            "status": "available",
                            "collections": len(collections),
                            "vectors": total_vectors,
                            "note": f"Connected with {len(collections)} collections, {total_vectors} vectors",
                        }
                    else:
                        return {
                            "url": qdrant_url,
                            "status": "unavailable",
                            "error": f"HTTP {response.status}",
                        }

        except ImportError:
            return {
                "status": "unavailable",
                "error": "aiohttp not installed (pip install aiohttp)",
            }
        except Exception as e:
            return {"status": "unavailable", "error": f"Connection failed: {str(e)}"}

    async def _query_docker_services(self) -> list[dict[str, Any]]:
        """
        Query Docker for running ONEX-related services.

        Returns:
            List of Docker service info dictionaries
        """

        def _blocking_query() -> list[dict[str, Any]]:
            """Blocking Docker operations."""
            import docker

            client = docker.from_env()
            containers = client.containers.list()

            # Filter for onex-*, archon-*, and omninode-* services
            services = []
            for container in containers:
                name = container.name
                if name and (
                    name.startswith("onex-")
                    or name.startswith("archon-")
                    or name.startswith("omninode-")
                ):
                    services.append(
                        {
                            "name": name,
                            "status": container.status,
                            "image": (
                                container.image.tags[0]
                                if container.image and container.image.tags
                                else "unknown"
                            ),
                            "ports": (
                                [
                                    f"{k}/{v[0]['HostPort']}" if v else str(k)
                                    for k, v in container.ports.items()
                                ]
                                if container.ports
                                else []
                            ),
                        }
                    )

            return services

        try:
            # Run blocking I/O in thread pool
            return await asyncio.to_thread(_blocking_query)

        except ImportError:
            self.logger.debug("docker library not installed (pip install docker)")
            return []
        except Exception as e:
            self.logger.debug(f"Docker query failed: {e}")
            return []

    async def _query_memgraph(self) -> dict[str, Any]:
        """
        Query Memgraph for graph database statistics and file relationships.

        Returns:
            Dictionary with Memgraph connection info, statistics, and insights
        """

        def _blocking_memgraph_query() -> dict[str, Any]:
            """Blocking Memgraph operations using neo4j driver."""
            try:
                from neo4j import GraphDatabase
            except ImportError:
                return {
                    "status": "unavailable",
                    "error": "neo4j driver not installed (pip install neo4j)",
                }

            driver = None
            # Get Memgraph URL from environment (default to localhost for development)
            memgraph_url = os.environ.get("MEMGRAPH_URL", "bolt://localhost:7687")
            try:
                # Connect to Memgraph
                driver = GraphDatabase.driver(memgraph_url)

                with driver.session() as session:
                    # Query file statistics by language
                    file_stats_result = session.run(
                        """
                        MATCH (f:FILE)
                        WHERE f.language IS NOT NULL
                        RETURN f.language as lang, count(f) as count
                        ORDER BY count DESC
                        LIMIT 10
                        """
                    )
                    file_stats = [
                        {"language": record["lang"], "count": record["count"]}
                        for record in file_stats_result
                    ]

                    # Query relationship statistics
                    rel_stats_result = session.run(
                        """
                        MATCH ()-[r]->()
                        RETURN type(r) as rel_type, count(r) as count
                        ORDER BY count DESC
                        LIMIT 10
                        """
                    )
                    relationships = [
                        {"type": record["rel_type"], "count": record["count"]}
                        for record in rel_stats_result
                    ]

                    # Query total entities and files
                    total_stats_result = session.run(
                        """
                        MATCH (n)
                        WITH labels(n) as labels, count(n) as count
                        UNWIND labels as label
                        RETURN label, sum(count) as total
                        ORDER BY total DESC
                        LIMIT 5
                        """
                    )
                    entity_stats = [
                        {"label": record["label"], "count": record["total"]}
                        for record in total_stats_result
                    ]

                    # Count total files with pattern-related content
                    pattern_files_result = session.run(
                        """
                        MATCH (f:FILE)
                        WHERE f.file_path CONTAINS 'pattern' OR f.file_path CONTAINS 'node_'
                        RETURN count(f) as pattern_file_count
                        """
                    )
                    pattern_count = pattern_files_result.single()
                    pattern_files = pattern_count["pattern_file_count"] if pattern_count else 0

                    return {
                        "url": memgraph_url,
                        "status": "connected",
                        "file_stats": file_stats,
                        "relationships": relationships,
                        "entity_stats": entity_stats,
                        "pattern_files": pattern_files,
                        "note": f"Connected to Memgraph with {len(entity_stats)} entity types, {len(file_stats)} languages",
                    }

            except Exception as e:
                return {
                    "url": memgraph_url,
                    "status": "unavailable",
                    "error": f"Connection failed: {str(e)}",
                }
            finally:
                if driver:
                    driver.close()

        try:
            # Run blocking I/O in thread pool
            return await asyncio.to_thread(_blocking_memgraph_query)
        except Exception as e:
            self.logger.debug(f"Memgraph query failed: {e}")
            return {
                "url": memgraph_url,
                "status": "unavailable",
                "error": str(e),
            }

    async def _query_semantic_search(
        self,
        query: str = "ONEX patterns implementation examples",
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Query semantic search service for code search.

        Uses hybrid search (full-text + semantic) to find
        relevant code examples, ONEX patterns, and implementation examples
        from the codebase graph (Memgraph + embeddings).

        Args:
            query: Search query (default: ONEX patterns)
            limit: Maximum results to return (default: 10)

        Returns:
            Dictionary with search results and metadata:
            {
                "status": "success" | "unavailable" | "error",
                "query": str,
                "total_results": int,
                "returned_results": int,
                "results": list[dict],  # Search result objects
                "query_time_ms": float,
                "error": str (if error/unavailable)
            }

        Example result format:
            {
                "entity_id": "/path/to/file.py",
                "entity_type": "page",
                "title": "file.py",
                "content": "...",  # Full file content
                "relevance_score": 0.85,
                "semantic_score": 0.82,
                "project_name": "omniclaude",
                ...
            }
        """
        import time

        start_time = time.time()
        semantic_search_url = str(settings.semantic_search_url)

        try:
            import aiohttp

            # Try the /search endpoint (confirmed working)
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": query,
                    "limit": limit,
                }

                async with session.post(
                    f"{semantic_search_url}/search",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5.0),
                ) as response:
                    query_time_ms = (time.time() - start_time) * 1000

                    if response.status == 200:
                        data = await response.json()

                        return {
                            "status": "success",
                            "query": data.get("query", query),
                            "mode": data.get("mode", "hybrid"),
                            "total_results": data.get("total_results", 0),
                            "returned_results": data.get("returned_results", 0),
                            "results": data.get("results", []),
                            "query_time_ms": query_time_ms,
                        }
                    else:
                        error_text = await response.text()
                        self.logger.warning(
                            f"semantic-search returned HTTP {response.status}: {error_text}"
                        )
                        return {
                            "status": "unavailable",
                            "error": f"HTTP {response.status}: {error_text}",
                            "query_time_ms": query_time_ms,
                        }

        except ImportError:
            return {
                "status": "unavailable",
                "error": "aiohttp not installed (pip install aiohttp)",
            }
        except TimeoutError:
            query_time_ms = (time.time() - start_time) * 1000
            self.logger.warning(f"semantic-search query timed out after {query_time_ms:.0f}ms")
            return {
                "status": "unavailable",
                "error": f"Query timed out after {query_time_ms:.0f}ms",
                "query_time_ms": query_time_ms,
            }
        except Exception as e:
            query_time_ms = (time.time() - start_time) * 1000
            self.logger.warning(f"semantic-search query failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": f"Connection failed: {str(e)}",
                "query_time_ms": query_time_ms,
            }

    async def _query_models(
        self,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query available AI models and ONEX data models.

        Queries for:
        - AI model providers (Anthropic, Google, Z.ai)
        - ONEX node types and contracts
        - Model quorum configuration

        Args:
            correlation_id: Correlation ID for tracking

        Returns:
            Models data dictionary
        """
        import json
        import time
        from pathlib import Path

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying available models")

            # Initialize result structure
            ai_models = {}
            intelligence_models = []

            # 1. Read environment variables for API keys
            env_keys = {
                "gemini": os.environ.get("GEMINI_API_KEY", ""),
                "google": os.environ.get("GOOGLE_API_KEY", ""),
                "zai": os.environ.get("ZAI_API_KEY", ""),
                "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
            }

            # 2. Try to load claude-providers.json for provider configuration
            providers_file = Path(__file__).parent.parent.parent / "claude-providers.json"
            provider_config = {}
            if providers_file.exists():
                try:
                    with open(providers_file) as f:
                        provider_config = json.load(f).get("providers", {})
                except Exception as e:
                    self.logger.warning(f"[{correlation_id}] Failed to load provider config: {e}")

            # 3. Build AI models section
            # Check Anthropic provider
            if env_keys.get("anthropic"):
                ai_models["anthropic"] = {
                    "provider": "anthropic",
                    "models": {
                        "haiku": "claude-3-5-haiku-20241022",
                        "sonnet": "claude-3-5-sonnet-20241022",
                        "opus": "claude-3-opus-20240229",
                    },
                    "available": True,
                    "api_key_set": True,
                }

            # Check Gemini provider
            if env_keys.get("gemini") or env_keys.get("google"):
                gemini_config = provider_config.get("gemini-2.5-flash", {})
                ai_models["gemini"] = {
                    "provider": "google",
                    "models": gemini_config.get(
                        "models",
                        {
                            "haiku": "gemini-2.5-flash",
                            "sonnet": "gemini-2.5-flash",
                            "opus": "gemini-2.5-pro",
                        },
                    ),
                    "available": True,
                    "api_key_set": True,
                }

            # Check Z.ai provider
            if env_keys.get("zai"):
                zai_config = provider_config.get("zai", {})
                ai_models["zai"] = {
                    "provider": "z.ai",
                    "models": zai_config.get(
                        "models",
                        {
                            "haiku": "glm-4.5-air",
                            "sonnet": "glm-4.5",
                            "opus": "glm-4.6",
                        },
                    ),
                    "available": True,
                    "api_key_set": True,
                    "rate_limits": zai_config.get("rate_limits", {}),
                }

            # 4. Add intelligence models (AI Quorum configuration)
            intelligence_models = [
                {
                    "name": "Gemini Flash",
                    "model": "gemini-1.5-flash",
                    "provider": "google",
                    "weight": 1.0,
                    "use_case": "Fast analysis, quick validation",
                },
                {
                    "name": "Codestral",
                    "model": "codestral-latest",
                    "provider": "mistral",
                    "weight": 1.5,
                    "use_case": "Code generation, ONEX compliance",
                },
                {
                    "name": "DeepSeek Lite",
                    "model": "deepseek-coder-lite",
                    "provider": "deepseek",
                    "weight": 1.0,
                    "use_case": "Code understanding, pattern matching",
                },
                {
                    "name": "Llama 3.1",
                    "model": "llama-3.1-70b",
                    "provider": "together",
                    "weight": 2.0,
                    "use_case": "Architectural decisions, quality assessment",
                },
                {
                    "name": "DeepSeek Full",
                    "model": "deepseek-coder-33b",
                    "provider": "deepseek",
                    "weight": 2.0,
                    "use_case": "Critical validation, complex analysis",
                },
            ]

            # Build result
            result = {
                "ai_models": ai_models,
                "intelligence_models": intelligence_models,
            }

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["models"] = elapsed_ms
            self.logger.info(
                f"[{correlation_id}] Models query completed in {elapsed_ms}ms - "
                f"Found {len(ai_models)} AI providers"
            )

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["models"] = elapsed_ms
            self._current_query_failures["models"] = str(e)
            self.logger.warning(f"[{correlation_id}] Model query failed: {e}")
            return {
                "ai_models": {},
                "intelligence_models": [],
                "error": str(e),
            }

    async def _query_database_schemas_direct_postgres(
        self,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Direct fallback: Query PostgreSQL directly for database schemas.

        Args:
            correlation_id: Correlation ID for tracking

        Returns:
            Database schemas dictionary
        """
        import time

        import asyncpg

        start_time = time.time()
        schemas = []

        try:
            # Get PostgreSQL connection details from environment
            # Default to localhost - production values should be set via .env
            pg_host = os.environ.get("POSTGRES_HOST", "localhost")
            pg_port = int(os.environ.get("POSTGRES_PORT", "5436"))
            pg_user = os.environ.get("POSTGRES_USER", "postgres")
            pg_password = os.environ.get("POSTGRES_PASSWORD", "")
            pg_database = os.environ.get("POSTGRES_DATABASE", "omninode_bridge")

            if not pg_password:
                self.logger.warning(
                    f"[{correlation_id}] POSTGRES_PASSWORD not set, direct query may fail"
                )

            # Connect to PostgreSQL
            conn = await asyncpg.connect(
                host=pg_host,
                port=pg_port,
                user=pg_user,
                password=pg_password,
                database=pg_database,
                timeout=5,
            )

            try:
                # First, get table descriptions from pg_description
                table_descriptions_query = """
                    SELECT
                        c.relname as table_name,
                        pgd.description as table_description
                    FROM pg_class c
                    LEFT JOIN pg_description pgd ON pgd.objoid = c.oid AND pgd.objsubid = 0
                    WHERE c.relkind = 'r'
                      AND c.relnamespace = 'public'::regnamespace
                    ORDER BY c.relname;
                """

                table_desc_rows = await conn.fetch(table_descriptions_query)
                table_descriptions = {
                    row["table_name"]: row["table_description"] or "No description available"
                    for row in table_desc_rows
                }

                # Then, query table schemas (columns)
                query = """
                    SELECT
                        table_name,
                        column_name,
                        data_type,
                        is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position
                    LIMIT 500;
                """

                rows = await conn.fetch(query)

                # Group columns by table and include descriptions
                tables = {}
                for row in rows:
                    table_name = row["table_name"]
                    if table_name not in tables:
                        tables[table_name] = {
                            "name": table_name,
                            "purpose": table_descriptions.get(
                                table_name, "No description available"
                            ),
                            "columns": [],
                        }

                    tables[table_name]["columns"].append(
                        {
                            "name": row["column_name"],
                            "type": row["data_type"],
                            "nullable": row["is_nullable"] == "YES",
                        }
                    )

                schemas = list(tables.values())

                self.logger.info(
                    f"[{correlation_id}] Direct PostgreSQL query: Retrieved {len(schemas)} table schemas"
                )

            finally:
                await conn.close()

            elapsed_ms = int((time.time() - start_time) * 1000)

            result = {
                "tables": schemas,  # Use "tables" key to match _format_schemas_result
                "schemas": schemas,  # Also keep "schemas" for backward compatibility
                "query_time_ms": elapsed_ms,
                "total_tables": len(schemas),
                "fallback_method": "direct_postgres",
            }

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"[{correlation_id}] Direct PostgreSQL fallback failed: {e}")
            return {"schemas": [], "error": str(e), "query_time_ms": elapsed_ms}

    async def _query_database_schemas(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query database schemas and table definitions.

        Queries PostgreSQL for:
        - Table schemas
        - Column definitions
        - Indexes and constraints

        Uses event-based approach first, falls back to direct PostgreSQL queries if needed.

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

            # Cast result to dict to satisfy type checker
            result_dict: dict[str, Any] = result if isinstance(result, dict) else {}

            # Check if result has actual schemas, trigger fallback if empty
            schemas = result_dict.get("schemas", result_dict.get("database_schemas", []))
            if not schemas or len(schemas) == 0:
                self.logger.warning(
                    f"[{correlation_id}] Event-based schema query returned 0 schemas, trying direct PostgreSQL fallback..."
                )
                try:
                    fallback_result = await self._query_database_schemas_direct_postgres(
                        correlation_id=correlation_id
                    )

                    if fallback_result.get("schemas") or fallback_result.get("tables"):
                        table_count = len(
                            fallback_result.get("tables", fallback_result.get("schemas", []))
                        )
                        self.logger.info(
                            f"[{correlation_id}] Direct PostgreSQL fallback succeeded: {table_count} tables"
                        )
                        return fallback_result
                    else:
                        self.logger.warning(
                            f"[{correlation_id}] Direct PostgreSQL fallback also returned no schemas"
                        )
                except Exception as fallback_error:
                    self.logger.error(
                        f"[{correlation_id}] Direct PostgreSQL fallback failed: {fallback_error}"
                    )

            return result_dict

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["database_schemas"] = elapsed_ms
            self._current_query_failures["database_schemas"] = str(e)
            self.logger.warning(
                f"[{correlation_id}] Database schema query via events failed ({e}), trying direct PostgreSQL fallback..."
            )

            # Try direct PostgreSQL fallback
            try:
                fallback_result = await self._query_database_schemas_direct_postgres(
                    correlation_id=correlation_id
                )

                if fallback_result.get("schemas"):
                    self.logger.info(
                        f"[{correlation_id}] Direct PostgreSQL fallback succeeded: {len(fallback_result.get('schemas', []))} tables"
                    )
                    return fallback_result
                else:
                    self.logger.warning(
                        f"[{correlation_id}] Direct PostgreSQL fallback returned no schemas"
                    )
            except Exception as fallback_error:
                self.logger.error(
                    f"[{correlation_id}] Direct PostgreSQL fallback also failed: {fallback_error}"
                )

            return {"schemas": {}, "error": str(e)}

    async def _query_debug_intelligence(
        self,
        client: IntelligenceEventClient,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query debug intelligence from workflow_events collection.

        Retrieves similar past issues/workflows to avoid retrying failed approaches.

        Multi-layered approach:
        1. Try Qdrant workflow_events collection (if exists)
        2. Query PostgreSQL pattern_quality_metrics + pattern_feedback_log
        3. Check AgentExecutionLogger fallback logs (JSON files)
        4. Return minimal empty structure if nothing available

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
                f"[{correlation_id}] Querying debug intelligence from multiple sources"
            )

            # Try event bus query first (Qdrant workflow_events)
            try:
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
                    timeout_ms=min(
                        self.query_timeout_ms, 3000
                    ),  # Shorter timeout for first attempt
                )

                # Cast result to dict
                result_dict: dict[str, Any] = result if isinstance(result, dict) else {}
                if result_dict and result_dict.get("similar_workflows"):
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["debug_intelligence"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Debug intelligence from Qdrant: "
                        f"{len(result_dict.get('similar_workflows', []))} workflows in {elapsed_ms}ms"
                    )
                    return result_dict
            except Exception as qdrant_error:
                self.logger.debug(
                    f"[{correlation_id}] Qdrant workflow_events unavailable: {qdrant_error}"
                )

            # Fallback 1: Query PostgreSQL agent_execution_logs (primary source)
            try:
                execution_workflows = await self._query_agent_execution_logs()
                if execution_workflows:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["debug_intelligence"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Debug intelligence from agent_execution_logs: "
                        f"{len(execution_workflows)} workflows in {elapsed_ms}ms"
                    )
                    return self._format_execution_workflows(execution_workflows)
            except Exception as exec_error:
                self.logger.debug(
                    f"[{correlation_id}] PostgreSQL agent_execution_logs unavailable: {exec_error}"
                )

            # Fallback 2: Query PostgreSQL for pattern feedback
            try:
                db_workflows = await self._query_pattern_feedback_from_db()
                if db_workflows:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["debug_intelligence"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Debug intelligence from PostgreSQL: "
                        f"{len(db_workflows)} workflows in {elapsed_ms}ms"
                    )
                    return self._format_db_workflows(db_workflows)
            except Exception as db_error:
                self.logger.debug(
                    f"[{correlation_id}] PostgreSQL pattern feedback unavailable: {db_error}"
                )

            # Fallback 3: Check local JSON logs from AgentExecutionLogger
            try:
                log_workflows = await self._query_local_execution_logs()
                if log_workflows:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["debug_intelligence"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Debug intelligence from local logs: "
                        f"{len(log_workflows)} workflows in {elapsed_ms}ms"
                    )
                    return self._format_log_workflows(log_workflows)
            except Exception as log_error:
                self.logger.debug(
                    f"[{correlation_id}] Local execution logs unavailable: {log_error}"
                )

            # No data available - return empty structure
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["debug_intelligence"] = elapsed_ms
            self.logger.info(
                f"[{correlation_id}] No debug intelligence available - first run or no history"
            )
            return {
                "similar_workflows": [],
                "query_time_ms": elapsed_ms,
                "note": "No historical workflow data available yet",
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["debug_intelligence"] = elapsed_ms
            self._current_query_failures["debug_intelligence"] = str(e)
            self.logger.warning(f"[{correlation_id}] Debug intelligence query failed: {e}")
            # Not critical - return empty result
            return {
                "similar_workflows": [],
                "error": str(e),
                "query_time_ms": elapsed_ms,
            }

    async def _query_agent_execution_logs(self) -> list[dict[str, Any]]:
        """
        Query agent execution logs from PostgreSQL agent_execution_logs table.

        Returns:
            List of workflow dictionaries with execution success/failure data
        """
        try:
            from .db import get_pg_pool

            pool = await get_pg_pool()
            if pool is None:
                return []

            async with pool.acquire() as conn:
                # Query recent agent executions (last 100 entries)
                # Get both successes and failures for learning
                rows = await conn.fetch(
                    """
                    SELECT
                        execution_id,
                        correlation_id,
                        agent_name,
                        user_prompt,
                        status,
                        quality_score,
                        error_message,
                        error_type,
                        duration_ms,
                        metadata,
                        created_at
                    FROM agent_execution_logs
                    WHERE status IN ('success', 'error', 'failed')
                    ORDER BY created_at DESC
                    LIMIT 100
                    """
                )

                workflows = []
                for row in rows:
                    # Extract relevant metadata
                    metadata = row["metadata"] or {}

                    workflows.append(
                        {
                            "execution_id": str(row["execution_id"]),
                            "correlation_id": str(row["correlation_id"]),
                            "agent_name": row["agent_name"],
                            "user_prompt": row["user_prompt"],
                            "status": row["status"],
                            "quality_score": (
                                float(row["quality_score"]) if row["quality_score"] else None
                            ),
                            "error_message": row["error_message"],
                            "error_type": row["error_type"],
                            "duration_ms": row["duration_ms"],
                            "metadata": metadata,
                            "timestamp": (
                                row["created_at"].isoformat() if row["created_at"] else None
                            ),
                            "success": row["status"] == "success",
                        }
                    )

                return workflows

        except Exception as e:
            self.logger.debug(f"PostgreSQL agent execution logs query failed: {e}")
            return []

    async def _query_pattern_feedback_from_db(self) -> list[dict[str, Any]]:
        """
        Query pattern feedback from PostgreSQL pattern_feedback_log table.

        Returns:
            List of workflow dictionaries with success/failure data
        """
        try:
            from .db import get_pg_pool

            pool = await get_pg_pool()
            if pool is None:
                return []

            async with pool.acquire() as conn:
                # Query recent pattern feedback (last 100 entries)
                rows = await conn.fetch(
                    """
                    SELECT
                        pattern_name,
                        feedback_type,
                        contract_json,
                        actual_pattern,
                        detected_confidence,
                        created_at
                    FROM pattern_feedback_log
                    ORDER BY created_at DESC
                    LIMIT 100
                    """
                )

                workflows = []
                for row in rows:
                    workflows.append(
                        {
                            "pattern_name": row["pattern_name"],
                            "feedback_type": row["feedback_type"],
                            "contract_json": row["contract_json"],
                            "actual_pattern": row["actual_pattern"],
                            "detected_confidence": (
                                float(row["detected_confidence"])
                                if row["detected_confidence"]
                                else None
                            ),
                            "timestamp": (
                                row["created_at"].isoformat() if row["created_at"] else None
                            ),
                            "success": row["feedback_type"]
                            in (
                                "correct",
                                "adjusted",
                            ),  # Correct feedback types per schema
                        }
                    )

                return workflows

        except Exception as e:
            self.logger.debug(f"PostgreSQL pattern feedback query failed: {e}")
            return []

    async def _query_local_execution_logs(self) -> list[dict[str, Any]]:
        """
        Query local JSON execution logs from AgentExecutionLogger fallback directory.

        Returns:
            List of workflow dictionaries with execution data
        """
        import json
        import tempfile
        from pathlib import Path

        try:
            # Check fallback log directory (same as AgentExecutionLogger)
            log_dir = Path(tempfile.gettempdir()) / "omniclaude_logs"
            if not log_dir.exists():
                log_dir = Path.cwd() / ".omniclaude_logs"
                if not log_dir.exists():
                    return []

            workflows = []
            # Read recent log files (last 50)
            log_files = sorted(
                log_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[:50]

            for log_file in log_files:
                try:
                    with open(log_file) as f:
                        log_data = json.load(f)

                    # Extract workflow info
                    workflows.append(
                        {
                            "agent_name": log_data.get("agent_name", "unknown"),
                            "user_prompt": log_data.get("user_prompt", "")[:100],
                            "status": log_data.get("status", "unknown"),
                            "quality_score": log_data.get("quality_score"),
                            "duration_ms": log_data.get("duration_ms"),
                            "timestamp": log_data.get("start_time"),
                            "success": log_data.get("status") == "success",
                        }
                    )
                except Exception as file_error:
                    self.logger.debug(f"Failed to parse log file {log_file}: {file_error}")
                    continue

            return workflows

        except Exception as e:
            self.logger.debug(f"Local execution logs query failed: {e}")
            return []

    def _format_execution_workflows(self, workflows: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Format agent execution log results for debug intelligence.

        Args:
            workflows: List of workflow dicts from agent_execution_logs

        Returns:
            Raw format compatible with _format_debug_intelligence_result
        """
        # Format workflows with enriched information
        formatted_workflows = []
        for workflow in workflows[:20]:  # Top 20 workflows
            # Build quality info
            quality_info = ""
            if workflow.get("quality_score"):
                quality_info = f" (quality: {workflow['quality_score']:.2f})"

            # Build duration info
            duration_info = ""
            if workflow.get("duration_ms"):
                duration_info = f" in {workflow['duration_ms']}ms"

            # Build reasoning based on success or failure
            if workflow.get("success"):
                reasoning = (
                    f"Agent '{workflow.get('agent_name', 'unknown')}' successfully completed "
                    f"task '{workflow.get('user_prompt', 'N/A')[:50]}...'{quality_info}{duration_info}"
                )
                error_msg = None
            else:
                error_type = workflow.get("error_type", "Unknown error")
                error_msg = workflow.get("error_message", "No details")
                reasoning = (
                    f"Agent '{workflow.get('agent_name', 'unknown')}' failed "
                    f"on task '{workflow.get('user_prompt', 'N/A')[:50]}...': "
                    f"{error_type}{duration_info}"
                )

            # Add formatted workflow
            formatted_workflows.append(
                {
                    "success": workflow.get("success", False),
                    "tool_name": workflow.get("agent_name", "unknown"),
                    "reasoning": reasoning,
                    "error": error_msg,
                    "timestamp": workflow.get("timestamp"),
                    "quality_score": workflow.get("quality_score"),
                    "duration_ms": workflow.get("duration_ms"),
                    "user_prompt": workflow.get("user_prompt"),
                }
            )

        return {
            "similar_workflows": formatted_workflows,
            "query_time_ms": 0,
        }

    def _format_db_workflows(self, workflows: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Format database workflow results for debug intelligence.

        Args:
            workflows: List of workflow dicts from pattern_feedback_log

        Returns:
            Raw format compatible with _format_debug_intelligence_result
        """
        # Format workflows with enriched information
        formatted_workflows = []
        for workflow in workflows[:20]:  # Top 20 workflows
            confidence_info = ""
            if workflow.get("detected_confidence"):
                confidence_info = f" (confidence: {workflow['detected_confidence']:.2f})"

            actual_pattern = workflow.get("actual_pattern")
            actual_info = f" -> {actual_pattern}" if actual_pattern else ""

            # Add tool_name for display and success flag for filtering
            formatted_workflows.append(
                {
                    "success": workflow.get("success", False),
                    "tool_name": workflow.get("pattern_name", "unknown"),
                    "reasoning": f"Pattern marked as {workflow.get('feedback_type', 'correct')}{confidence_info}{actual_info}",
                    "error": (
                        f"Detected as {workflow.get('pattern_name')}, should be {actual_pattern}"
                        if actual_pattern
                        else None
                    ),
                    "timestamp": workflow.get("timestamp"),
                }
            )

        return {
            "similar_workflows": formatted_workflows,
            "query_time_ms": 0,
        }

    def _format_log_workflows(self, workflows: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Format local log workflow results for debug intelligence.

        Args:
            workflows: List of workflow dicts from execution logs

        Returns:
            Raw format compatible with _format_debug_intelligence_result
        """
        # Format workflows with enriched information
        formatted_workflows = []
        for workflow in workflows[:20]:  # Top 20 workflows
            quality_info = ""
            if workflow.get("quality_score"):
                quality_info = f" (quality: {workflow['quality_score']:.2f})"

            # Add tool_name for display and success flag for filtering
            formatted_workflows.append(
                {
                    "success": workflow.get("success", False),
                    "tool_name": workflow.get("agent_name", "unknown"),
                    "reasoning": f"{workflow.get('user_prompt', 'Task completed')}{quality_info}",
                    "error": (
                        f"Execution failed: {workflow.get('status', 'error')}"
                        if not workflow.get("success")
                        else None
                    ),
                    "timestamp": workflow.get("timestamp"),
                }
            )

        return {
            "similar_workflows": formatted_workflows,
            "query_time_ms": 0,
        }

    async def _query_filesystem(
        self,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query filesystem tree and metadata.

        Scans current working directory for:
        - Complete file tree structure
        - File metadata (size, modified date)
        - ONEX compliance metadata where available
        - File counts by type

        Args:
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
            file_types: dict[str, int] = {}
            onex_files: dict[str, list[str]] = {
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
                return path.suffix in ignored_extensions

            def get_onex_node_type(file_path: Path) -> str | None:
                """Detect ONEX node type from filename."""
                name = file_path.name.lower()
                if "_effect.py" in name or name == "effect.py":
                    return "EFFECT"
                elif "_compute.py" in name or name == "compute.py":
                    return "COMPUTE"
                elif "_reducer.py" in name or name == "reducer.py":
                    return "REDUCER"
                elif "_orchestrator.py" in name or name == "orchestrator.py":
                    return "ORCHESTRATOR"
                return None

            def scan_directory(
                directory: Path, depth: int = 0, max_depth: int = 5
            ) -> list[dict[str, Any]]:
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

                                modified_time = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
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

    async def _query_debug_loop_context(
        self,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Query debug loop STF database for available transformation patterns.

        Retrieves Specific Transformation Functions (STFs) from the debug loop
        system that agents can use to solve similar problems.

        Multi-layered approach:
        1. Query PostgreSQL debug_transform_functions table directly
        2. Group STFs by problem category and signature
        3. Include model pricing information for cost-aware decisions
        4. Return graceful fallback if debug loop unavailable

        Args:
            correlation_id: Correlation ID for tracking

        Returns:
            Debug loop context dictionary with STF availability and model pricing
        """
        import time

        start_time = time.time()

        try:
            self.logger.debug(f"[{correlation_id}] Querying debug loop STF database")

            # Try direct PostgreSQL query for debug_transform_functions
            try:
                from .db import get_pg_pool

                pool = await get_pg_pool()
                if pool is None:
                    # Database unavailable - return graceful fallback
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._current_query_times["debug_loop"] = elapsed_ms
                    self.logger.info(
                        f"[{correlation_id}] Debug loop database unavailable - graceful fallback"
                    )
                    return {
                        "available": False,
                        "reason": "Database connection unavailable",
                        "stf_count": 0,
                        "categories": [],
                        "top_stfs": [],
                        "query_time_ms": elapsed_ms,
                    }

                # Query top quality STFs grouped by category
                async with pool.acquire() as conn:
                    # Get total count
                    count_query = """
                    SELECT COUNT(*) as total_count
                    FROM debug_transform_functions
                    WHERE approval_status = 'approved'
                    AND quality_score >= 0.7
                    """
                    count_result = await conn.fetchrow(count_query)
                    stf_count = count_result["total_count"] if count_result else 0

                    # Get categories
                    categories_query = """
                    SELECT DISTINCT problem_category, COUNT(*) as stf_count
                    FROM debug_transform_functions
                    WHERE approval_status = 'approved'
                    AND quality_score >= 0.7
                    AND problem_category IS NOT NULL
                    GROUP BY problem_category
                    ORDER BY stf_count DESC
                    LIMIT 10
                    """
                    categories_result = await conn.fetch(categories_query)
                    categories = [
                        {
                            "category": row["problem_category"],
                            "count": row["stf_count"],
                        }
                        for row in categories_result
                    ]

                    # Get top quality STFs
                    stfs_query = """
                    SELECT
                        stf_id, stf_name, stf_description, problem_category,
                        problem_signature, quality_score, usage_count,
                        CASE WHEN usage_count > 0
                             THEN (success_count::float / usage_count) * 100
                             ELSE 0.0
                        END as success_rate
                    FROM debug_transform_functions
                    WHERE approval_status = 'approved'
                    AND quality_score >= 0.7
                    ORDER BY quality_score DESC, usage_count DESC
                    LIMIT 10
                    """
                    stfs_result = await conn.fetch(stfs_query)
                    top_stfs = [
                        {
                            "stf_id": str(row["stf_id"]),
                            "stf_name": row["stf_name"],
                            "description": row["stf_description"] or "No description",
                            "category": row["problem_category"] or "uncategorized",
                            "signature": row["problem_signature"] or "none",
                            "quality_score": float(row["quality_score"]),
                            "usage_count": row["usage_count"],
                            "success_rate": float(row["success_rate"]),
                        }
                        for row in stfs_result
                    ]

                elapsed_ms = int((time.time() - start_time) * 1000)
                self._current_query_times["debug_loop"] = elapsed_ms
                self.logger.info(
                    f"[{correlation_id}] Debug loop query completed: "
                    f"{stf_count} STFs, {len(categories)} categories in {elapsed_ms}ms"
                )

                return {
                    "available": True,
                    "stf_count": stf_count,
                    "categories": categories,
                    "top_stfs": top_stfs,
                    "query_time_ms": elapsed_ms,
                }

            except Exception as db_error:
                # Database query failed - graceful fallback
                elapsed_ms = int((time.time() - start_time) * 1000)
                self._current_query_times["debug_loop"] = elapsed_ms
                self.logger.debug(
                    f"[{correlation_id}] Debug loop database query failed: {db_error}"
                )
                return {
                    "available": False,
                    "reason": f"Database query failed: {str(db_error)}",
                    "stf_count": 0,
                    "categories": [],
                    "top_stfs": [],
                    "query_time_ms": elapsed_ms,
                }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._current_query_times["debug_loop"] = elapsed_ms
            self._current_query_failures["debug_loop"] = str(e)
            self.logger.warning(f"[{correlation_id}] Debug loop context query failed: {e}")
            # Not critical - return graceful fallback
            return {
                "available": False,
                "reason": f"Query failed: {str(e)}",
                "stf_count": 0,
                "categories": [],
                "top_stfs": [],
                "error": str(e),
                "query_time_ms": elapsed_ms,
            }

    def _select_sections_for_task(
        self,
        task_context: TaskContext | None,
    ) -> list[str]:
        """
        Select manifest sections based on task intent.

        Returns all core sections to provide complete system context to agents.
        Previous conditional logic was excluding critical information.

        Args:
            task_context: Classified task context (unused - kept for API compatibility)

        Returns:
            List of all core section names to include in manifest
        """
        # ALWAYS include all core sections - agents need complete context
        sections = [
            "patterns",  # Code patterns from Qdrant
            "database_schemas",  # Database table structures
            "infrastructure",  # Service connectivity info
            "models",  # AI models and ONEX node types
            "debug_intelligence",  # Historical workflow data
            "semantic_search",  # Semantic search capability
        ]

        self.logger.info(f"Including all {len(sections)} core sections for complete context")
        return sections

    def _build_manifest_from_results(
        self,
        results: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build structured manifest from query results.

        Transforms raw query results into the manifest structure
        expected by format_for_prompt().

        Args:
            results: Dictionary of query results by section

        Returns:
            Structured manifest dictionary
        """
        manifest: dict[str, Any] = {
            "manifest_metadata": {
                "version": "2.0.0",
                "generated_at": datetime.now(UTC).isoformat(),
                "purpose": "Dynamic system context via event bus",
                "target_agents": ["polymorphic-agent", "all-specialized-agents"],
                "update_frequency": "on_demand",
                "source": "onex-intelligence-adapter",
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
            manifest["infrastructure"] = self._format_infrastructure_result(infra_result)

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
            manifest["debug_intelligence"] = self._format_debug_intelligence_result(debug_result)

        # Extract filesystem
        filesystem_result = results.get("filesystem", {})
        if isinstance(filesystem_result, Exception):
            self.logger.warning(f"Filesystem query failed: {filesystem_result}")
            manifest["filesystem"] = {"error": str(filesystem_result)}
        else:
            manifest["filesystem"] = self._format_filesystem_result(filesystem_result)

        # Extract debug loop
        debug_loop_result = results.get("debug_loop", {})
        if isinstance(debug_loop_result, Exception):
            self.logger.warning(f"Debug loop query failed: {debug_loop_result}")
            manifest["debug_loop"] = {
                "available": False,
                "error": str(debug_loop_result),
            }
        else:
            manifest["debug_loop"] = self._format_debug_loop_result(debug_loop_result)

        # Extract semantic_search results
        semantic_search_result = results.get("semantic_search", {})
        if isinstance(semantic_search_result, Exception):
            self.logger.warning(f"Semantic search query failed: {semantic_search_result}")
            manifest["semantic_search"] = {"error": str(semantic_search_result)}
        else:
            manifest["semantic_search"] = self._format_semantic_search_result(
                semantic_search_result
            )

        # Add action logging (always included - uses local context only)
        # No Kafka query needed - correlation_id and agent_name come from self
        manifest["action_logging"] = {
            "status": "available",
            "framework": "ActionLogger (omniclaude.lib.core.action_logger)",
            "kafka_integration": {
                "enabled": True,
                "topic": TopicBase.AGENT_ACTIONS,
                "bootstrap_servers": os.environ.get(
                    "KAFKA_BOOTSTRAP_SERVERS", ""
                ),
            },
            "correlation_tracking": True,
            "performance_overhead": "<5ms per action",
            "features": [
                "Tool call logging with timing",
                "Decision logging with context",
                "Error logging with stack traces",
                "Success milestone tracking",
                "Non-blocking async publishing",
            ],
        }

        return manifest

    def _deduplicate_patterns(
        self, patterns: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Deduplicate patterns by name, keeping the highest confidence version
        and tracking instance counts and metadata from all occurrences.

        Args:
            patterns: List of pattern dictionaries

        Returns:
            Tuple of (deduplicated_patterns_with_metadata, duplicates_removed_count)
        """
        if not patterns:
            return [], 0

        # Group patterns by name
        pattern_groups: dict[str, Any] = {}

        for pattern in patterns:
            name = pattern.get("name", "Unknown Pattern")
            confidence = pattern.get("confidence", 0.0)

            if name not in pattern_groups:
                pattern_groups[name] = {
                    "pattern": pattern,  # Will be replaced with highest confidence version
                    "count": 0,
                    "node_types": set(),
                    "domains": set(),
                    "services": set(),
                    "files": set(),
                }

            group = pattern_groups[name]
            group["count"] += 1

            # Update to highest confidence version
            # Handle None confidence values (treat as 0.0)
            current_confidence = confidence if confidence is not None else 0.0
            existing_confidence = group["pattern"].get("confidence")
            if existing_confidence is None:
                existing_confidence = 0.0

            if current_confidence > existing_confidence:
                group["pattern"] = pattern

            # Accumulate metadata from all instances
            if pattern.get("node_types"):
                group["node_types"].update(pattern["node_types"])
            if pattern.get("file_path"):
                group["files"].add(pattern["file_path"])

            # Extract domain and service from source context
            source_context = pattern.get("source_context", {})
            if source_context.get("domain"):
                group["domains"].add(source_context["domain"])
            if source_context.get("service_name"):
                group["services"].add(source_context["service_name"])

        # Build deduplicated list with enhanced metadata
        deduplicated = []
        for _name, group in pattern_groups.items():
            pattern = group["pattern"].copy()

            # Add aggregated metadata to pattern
            pattern["instance_count"] = group["count"]
            pattern["all_node_types"] = sorted(group["node_types"])
            pattern["all_domains"] = sorted(group["domains"])
            pattern["all_services"] = sorted(group["services"])
            pattern["all_files"] = sorted(group["files"])

            deduplicated.append(pattern)

        # Calculate duplicates removed
        original_count = len(patterns)
        duplicates_removed = original_count - len(deduplicated)

        # Sort by confidence (highest first) to show best patterns
        deduplicated.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)

        return deduplicated, duplicates_removed

    def _format_patterns_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format patterns query result into manifest structure."""
        patterns = result.get("patterns", [])
        collections_queried = result.get("collections_queried", {})

        # Deduplicate patterns by name (keeping highest confidence version)
        deduplicated_patterns, duplicates_removed = self._deduplicate_patterns(patterns)

        # Log deduplication metrics
        if duplicates_removed > 0:
            self.logger.info(
                f"Pattern deduplication: removed {duplicates_removed} duplicates "
                f"({len(patterns)} → {len(deduplicated_patterns)} patterns)"
            )

        return {
            "available": [
                {
                    "name": p.get("name", "Unknown Pattern"),
                    "file": p.get("file_path", ""),
                    "description": p.get("description", ""),
                    "node_types": p.get("node_types", []),
                    "confidence": p.get("confidence", 0.0),
                    "use_cases": p.get("use_cases", []),
                    # Enhanced metadata from deduplication
                    "instance_count": p.get("instance_count", 1),
                    "all_node_types": p.get("all_node_types", p.get("node_types", [])),
                    "all_domains": p.get("all_domains", []),
                    "all_services": p.get("all_services", []),
                    "all_files": p.get("all_files", []),
                }
                for p in deduplicated_patterns
            ],
            "total_count": len(deduplicated_patterns),
            "original_count": len(patterns),
            "duplicates_removed": duplicates_removed,
            "query_time_ms": result.get("query_time_ms", 0),
            "collections_queried": collections_queried,
        }

    def _format_infrastructure_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format infrastructure query result into manifest structure."""
        # Check if result already has the correct structure (new direct query format)
        if "remote_services" in result or "local_services" in result:
            # Result already in correct format from direct queries
            return result

        # Handle old event-based format (services at top level)
        return {
            "remote_services": {
                "postgresql": result.get("postgresql", {}),
                "kafka": result.get("kafka", {}),
            },
            "local_services": {
                "qdrant": result.get("qdrant", {}),
            },
            "docker_services": result.get("docker_services", []),
        }

    def _format_models_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format models query result into manifest structure."""
        return {
            "ai_models": result.get("ai_models", {}),
            "onex_models": result.get("onex_models", {}),
            "intelligence_models": result.get("intelligence_models", []),
        }

    def _format_schemas_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format database schemas query result into manifest structure."""
        # Check both "tables" and "schemas" keys for compatibility
        # Event-based queries return "schemas", direct PostgreSQL returns "tables"
        tables = result.get("tables", result.get("schemas", []))

        # Normalize table structure: ensure each table has a "name" key
        # Some sources use "table_name" instead of "name"
        normalized_tables = []
        for table in tables:
            if isinstance(table, dict):
                # If "name" is missing but "table_name" exists, normalize it
                if "name" not in table and "table_name" in table:
                    normalized_table = dict(table)  # Create a copy
                    normalized_table["name"] = table["table_name"]
                    normalized_tables.append(normalized_table)
                else:
                    normalized_tables.append(table)
            else:
                normalized_tables.append(table)

        return {
            "tables": normalized_tables,
            "total_tables": len(normalized_tables),
        }

    def _format_debug_intelligence_result(self, result: dict[str, Any]) -> dict[str, Any]:
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

    def _format_filesystem_result(self, result: dict[str, Any]) -> dict[str, Any]:
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

    def _format_debug_loop_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format debug loop query result into manifest structure."""
        return {
            "available": result.get("available", False),
            "reason": result.get("reason"),
            "stf_count": result.get("stf_count", 0),
            "categories": result.get("categories", []),
            "top_stfs": result.get("top_stfs", []),
            "query_time_ms": result.get("query_time_ms", 0),
        }

    def _format_semantic_search_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Format semantic search query result into manifest structure."""
        if result.get("status") != "success":
            return {
                "status": result.get("status", "error"),
                "error": result.get("error", "Unknown error"),
                "query_time_ms": result.get("query_time_ms", 0),
            }

        # Format search results for manifest
        formatted_results = []
        for item in result.get("results", [])[:5]:  # Top 5 results only
            # Extract key information
            formatted_results.append(
                {
                    "title": item.get("title", "Unknown"),
                    "entity_id": item.get("entity_id", ""),
                    "entity_type": item.get("entity_type", "page"),
                    "relevance_score": item.get("relevance_score", 0.0),
                    "semantic_score": item.get("semantic_score", 0.0),
                    "project_name": item.get("project_name", "unknown"),
                    # Include first 500 chars of content as preview
                    "content_preview": (
                        item.get("content", "")[:500] + "..."
                        if len(item.get("content", "")) > 500
                        else item.get("content", "")
                    ),
                }
            )

        return {
            "status": "success",
            "query": result.get("query", ""),
            "mode": result.get("mode", "hybrid"),
            "total_results": result.get("total_results", 0),
            "returned_results": len(formatted_results),
            "results": formatted_results,
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

    def _get_minimal_manifest(self) -> dict[str, Any]:
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
                        "host": os.environ.get("POSTGRES_HOST", "localhost"),
                        "port": int(os.environ.get("POSTGRES_PORT", "5436")),
                        "database": os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
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
                },
            },
            "models": {
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
            "semantic_search": {
                "status": "unavailable",
                "error": "Intelligence service unavailable (fallback manifest)",
            },
            "note": "This is a minimal fallback manifest. Full system context requires intelligence service.",
        }

    def format_for_prompt(self, sections: list[str] | None = None) -> str:
        """
        Format manifest for injection into agent prompt.

        Maintains backward compatibility with static YAML version.

        Args:
            sections: Optional list of sections to include.
                     If None, includes all sections.
                     Available: ['patterns', 'models', 'infrastructure',
                                'database_schemas', 'debug_intelligence',
                                'filesystem', 'debug_loop', 'action_logging',
                                'semantic_search']

        Returns:
            Formatted string ready for prompt injection
        """
        # Use cached version if available and no specific sections requested
        if sections is None and self._cached_formatted is not None:
            return self._cached_formatted

        # Get manifest data
        if self._manifest_data is None:
            self.logger.warning("Manifest data not loaded - call generate_dynamic_manifest() first")
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
            "debug_loop": self._format_debug_loop,
            "action_logging": self._format_action_logging,
            "semantic_search": self._format_semantic_search,
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
            output.append("Full system context requires onex-intelligence-adapter service.")
            output.append("")

        output.append("=" * 70)
        output.append("END SYSTEM MANIFEST")
        output.append("=" * 70)

        formatted = "\n".join(output)

        # Cache if all sections included
        if sections is None:
            self._cached_formatted = formatted

        return formatted

    def _extract_code_snippet(self, content: str, language: str = "", max_lines: int = 15) -> str:
        """
        Extract a meaningful code snippet from file content.

        Tries to extract the first class or function definition, falling back
        to the first N lines if no clear definition is found.

        Args:
            content: Full file content
            language: Programming language for language-specific extraction
            max_lines: Maximum number of lines to include

        Returns:
            Extracted code snippet (may be truncated with "...")
        """
        if not content:
            return ""

        lines = content.split("\n")
        if not lines:
            return ""

        # Remove empty lines from start
        while lines and not lines[0].strip():
            lines.pop(0)

        if not lines:
            return ""

        # For Python, try to extract first class or function
        if language == "python":
            # Look for class or def keyword
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("class ") or stripped.startswith("def "):
                    # Found a definition, extract it with docstring if present
                    snippet_lines = [lines[i]]
                    j = i + 1

                    # Check for docstring
                    while j < len(lines) and j < i + max_lines:
                        snippet_lines.append(lines[j])
                        # Stop after docstring ends or max lines reached
                        if '"""' in lines[j] and j > i:
                            # Count quotes
                            quote_count = sum(1 for k in range(i, j + 1) if '"""' in lines[k])
                            if quote_count >= 2:  # Docstring complete
                                break
                        j += 1

                    # Add ellipsis if truncated
                    if j >= len(lines) or len(snippet_lines) >= max_lines:
                        snippet_lines.append("    ...")

                    return "\n".join(snippet_lines[:max_lines])

        # For other languages or if no definition found, take first N lines
        snippet_lines = lines[:max_lines]
        if len(lines) > max_lines:
            snippet_lines.append("...")

        return "\n".join(snippet_lines)

    def _format_patterns(self, patterns_data: dict[str, Any]) -> str:
        """Format patterns section with grouped duplicate counts."""
        output = ["AVAILABLE PATTERNS:"]

        patterns = patterns_data.get("available", [])
        collections_queried = patterns_data.get("collections_queried", {})
        duplicates_removed = patterns_data.get("duplicates_removed", 0)
        original_count = patterns_data.get("original_count", len(patterns))

        if not patterns:
            output.append("  (No patterns discovered - use built-in patterns)")
            return "\n".join(output)

        # Show collection statistics
        if collections_queried:
            output.append(
                f"  Collections: archon_vectors ({collections_queried.get('archon_vectors', 0)}), "
                f"code_generation_patterns ({collections_queried.get('code_generation_patterns', 0)})"
            )

            # Show deduplication metrics if duplicates were removed
            if duplicates_removed > 0:
                output.append(
                    f"  Deduplication: {duplicates_removed} duplicates removed "
                    f"({original_count} → {len(patterns)} unique patterns)"
                )

            output.append("")

        # Show top 20 patterns (increased from 10 to show more variety)
        display_limit = 20
        for pattern in patterns[:display_limit]:
            # Get instance count (defaults to 1 if not present)
            instance_count = pattern.get("instance_count", 1)

            # Format pattern name with instance count for duplicates
            # Handle None values for name and confidence
            pattern_name = pattern.get("name") or "Unnamed Pattern"
            confidence = pattern.get("confidence")
            confidence_str = f"{confidence:.0%}" if confidence is not None else "N/A"

            if instance_count > 1:
                pattern_header = (
                    f"  • {pattern_name} ({confidence_str} confidence) [{instance_count} instances]"
                )
            else:
                pattern_header = f"  • {pattern_name} ({confidence_str} confidence)"

            output.append(pattern_header)

            # Show file path if available
            file_path = pattern.get("file_path", pattern.get("file", ""))
            if file_path and instance_count == 1:
                output.append(f"    File: {file_path}")

            # Show language if available
            language = pattern.get("language", "")
            if language:
                output.append(f"    Language: {language}")

            # Show aggregated node types (from all instances)
            all_node_types = pattern.get("all_node_types", pattern.get("node_types", []))
            if all_node_types:
                output.append(f"    Node Types: {', '.join(all_node_types)}")

            # Show domains for multi-instance patterns
            all_domains = pattern.get("all_domains", [])
            if all_domains and instance_count > 1:
                domains_str = ", ".join(all_domains[:3])  # Show first 3 domains
                if len(all_domains) > 3:
                    domains_str += f", +{len(all_domains) - 3} more"
                output.append(f"    Domains: {domains_str}")

            # Show files count for multi-instance patterns
            if instance_count > 1:
                file_count = len(pattern.get("all_files", []))
                if file_count > 0:
                    output.append(f"    Files: {file_count} files across services")

            # Show code snippet if content is available
            content = pattern.get("content", "")
            if content and instance_count == 1:
                snippet = self._extract_code_snippet(content, language)
                if snippet:
                    output.append("")
                    output.append("    Code Preview:")
                    # Add markdown code block with language syntax highlighting
                    lang_tag = language if language else ""
                    output.append(f"    ```{lang_tag}")
                    # Indent each line of the snippet
                    for line in snippet.split("\n"):
                        output.append(f"    {line}")
                    output.append("    ```")
                    output.append("")

        if len(patterns) > display_limit:
            output.append(f"  ... and {len(patterns) - display_limit} more patterns")

        output.append("")
        output.append(f"  Total: {len(patterns)} unique patterns available")

        return "\n".join(output)

    def _format_models(self, models_data: dict[str, Any]) -> str:
        """Format models section."""
        output = ["AI MODELS & DATA MODELS:"]

        # AI Models
        if "ai_models" in models_data:
            ai_models = models_data["ai_models"]
            if ai_models:  # Only show if we have actual provider data
                output.append("  AI Providers:")
                for provider_key, provider_config in ai_models.items():
                    provider_name = provider_config.get("provider", provider_key)
                    models = provider_config.get("models", {})
                    api_key_set = provider_config.get("api_key_set", False)  # nosec

                    # Format models list
                    if isinstance(models, dict):
                        model_names = list(models.values())
                        models_str = ", ".join(model_names[:2])  # Show first 2 models
                        if len(model_names) > 2:
                            models_str += f", +{len(model_names) - 2} more"
                    else:
                        models_str = str(models)

                    # Add rate limits if available
                    rate_limits = provider_config.get("rate_limits", {})
                    if rate_limits:
                        output.append(
                            f"    • {provider_name.title()}: {models_str} (API key: {'✓' if api_key_set else '✗'})"
                        )
                    else:
                        output.append(
                            f"    • {provider_name.title()}: {models_str} (API key: {'✓' if api_key_set else '✗'})"
                        )

        # ONEX Models
        if "onex_models" in models_data:
            onex_models = models_data["onex_models"]
            if onex_models:
                output.append("  ONEX Node Types:")
                for node_type, status in onex_models.items():
                    output.append(f"    • {node_type.title()}: {status}")

        # Intelligence Models (AI Quorum)
        if "intelligence_models" in models_data:
            intelligence_models = models_data["intelligence_models"]
            if intelligence_models:
                output.append("  AI Quorum Models:")
                total_weight = sum(m.get("weight", 0) for m in intelligence_models)
                for model in intelligence_models[:3]:  # Show first 3
                    name = model.get("name", "Unknown")
                    model_id = model.get("model", "unknown")
                    weight = model.get("weight", 0)
                    use_case = model.get("use_case", "")
                    output.append(f"    • {name} ({model_id}): weight={weight} - {use_case}")
                if len(intelligence_models) > 3:
                    output.append(
                        f"    ... and {len(intelligence_models) - 3} more (total weight: {total_weight})"
                    )

        return "\n".join(output)

    def _format_infrastructure(self, infra_data: dict[str, Any]) -> str:
        """Format infrastructure section."""
        output = ["INFRASTRUCTURE TOPOLOGY:"]

        remote = infra_data.get("remote_services", {})

        # PostgreSQL
        if "postgresql" in remote:
            pg = remote["postgresql"]
            if pg is not None and pg:  # Check not empty dict
                host = pg.get("host", "unknown")
                port = pg.get("port", "unknown")
                db = pg.get("database", "unknown")
                status = pg.get("status", "unknown")
                tables = pg.get("tables", 0)
                output.append(f"  PostgreSQL: {host}:{port}/{db} ({status})")
                if tables > 0:
                    output.append(f"    Tables: {tables}")
                if "note" in pg:
                    output.append(f"    Note: {pg['note']}")
            else:
                output.append("  PostgreSQL: unknown (scan failed)")

        # Kafka
        if "kafka" in remote:
            kafka = remote["kafka"]
            if kafka is not None and kafka:  # Check not empty dict
                bootstrap = kafka.get("bootstrap_servers", "unknown")
                status = kafka.get("status", "unknown")
                topics = kafka.get("topics", 0)
                output.append(f"  Kafka: {bootstrap} ({status})")
                if topics > 0:
                    output.append(f"    Topics: {topics}")
                if "note" in kafka:
                    output.append(f"    Note: {kafka['note']}")
            else:
                output.append("  Kafka: unknown (scan failed)")

        # Qdrant
        local = infra_data.get("local_services", {})
        if "qdrant" in local:
            qdrant = local["qdrant"]
            if qdrant is not None and qdrant:  # Check not empty dict
                endpoint = qdrant.get("url", qdrant.get("endpoint", "unknown"))
                status = qdrant.get("status", "unknown")
                collections = qdrant.get("collections", 0)
                vectors = qdrant.get("vectors", 0)
                output.append(f"  Qdrant: {endpoint} ({status})")
                if collections > 0 or vectors > 0:
                    output.append(f"    Collections: {collections}, Vectors: {vectors}")
                if "note" in qdrant:
                    output.append(f"    Note: {qdrant['note']}")
            else:
                output.append("  Qdrant: unknown (scan failed)")

        # Memgraph
        if "memgraph" in local:
            memgraph = local["memgraph"]
            if memgraph is not None and memgraph:  # Check not empty dict
                endpoint = memgraph.get("url", "unknown")
                status = memgraph.get("status", "unknown")
                output.append(f"  Memgraph: {endpoint} ({status})")

                # Entity statistics
                entity_stats = memgraph.get("entity_stats", [])
                if entity_stats:
                    entities_str = ", ".join(
                        [f"{e['label']}: {e['count']}" for e in entity_stats[:3]]
                    )
                    output.append(f"    Entities: {entities_str}")

                # File statistics by language
                file_stats = memgraph.get("file_stats", [])
                if file_stats:
                    files_str = ", ".join(
                        [f"{f['language']}: {f['count']}" for f in file_stats[:3]]
                    )
                    output.append(f"    Files: {files_str}")

                # Relationship statistics
                relationships = memgraph.get("relationships", [])
                if relationships:
                    total_rels = sum(r["count"] for r in relationships)
                    output.append(f"    Relationships: {total_rels:,} total")

                # Pattern files count
                pattern_files = memgraph.get("pattern_files", 0)
                if pattern_files > 0:
                    output.append(f"    Pattern Files: {pattern_files}")

                if "note" in memgraph:
                    output.append(f"    Note: {memgraph['note']}")
            else:
                output.append("  Memgraph: unknown (scan failed)")

        return "\n".join(output)

    def _format_database_schemas(self, schemas_data: dict[str, Any]) -> str:
        """Format database schemas section."""
        output = ["DATABASE SCHEMAS:"]

        tables = schemas_data.get("tables", [])
        if not tables:
            output.append("  (Schema information unavailable)")
            return "\n".join(output)

        output.append(f"  Total Tables: {schemas_data.get('total_tables', len(tables))}")

        for table in tables[:5]:  # Limit to top 5
            table_name = table.get("name", "unknown")
            output.append(f"  • {table_name}")

        if len(tables) > 5:
            output.append(f"  ... and {len(tables) - 5} more tables")

        return "\n".join(output)

    def _format_debug_intelligence(self, debug_data: dict[str, Any]) -> str:
        """Format debug intelligence section."""
        output = ["DEBUG INTELLIGENCE (Similar Workflows):"]

        workflows = debug_data.get("similar_workflows", {})
        successes = workflows.get("successes", [])
        failures = workflows.get("failures", [])

        if not successes and not failures:
            output.append("  (No similar workflows found - first time seeing this pattern)")
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

    def _format_semantic_search(self, search_data: dict[str, Any]) -> str:
        """Format semantic search section with search results."""
        output = ["SEMANTIC SEARCH RESULTS:"]

        # Check status
        status = search_data.get("status", "unknown")

        # Get semantic search URL from settings
        semantic_url = str(settings.semantic_search_url)

        if status == "error" or status == "unavailable":
            error_msg = search_data.get("error", "Unknown error")
            output.append(f"  Service: {semantic_url} (unavailable)")
            output.append(f"  Status: ❌ {error_msg}")
            return "\n".join(output)

        # Show query information
        query = search_data.get("query", "unknown")
        mode = search_data.get("mode", "hybrid")
        total_results = search_data.get("total_results", 0)
        returned_results = search_data.get("returned_results", 0)
        query_time_ms = search_data.get("query_time_ms", 0)

        output.append(f"  Service: {semantic_url}")
        output.append("  Status: ✅ Available")
        output.append(f'  Query: "{query}"')
        output.append(f"  Mode: {mode} (full-text + semantic)")
        output.append(f"  Results: {returned_results} of {total_results} total")
        output.append(f"  Query Time: {query_time_ms:.0f}ms")
        output.append("")

        # Show search results
        results = search_data.get("results", [])
        if not results:
            output.append("  (No results found)")
            return "\n".join(output)

        output.append("  Top Results:")
        for i, result in enumerate(results[:5], 1):  # Top 5 results
            title = result.get("title", "Unknown")
            entity_id = result.get("entity_id", "")
            entity_type = result.get("entity_type", "page")
            relevance_score = result.get("relevance_score", 0.0)
            semantic_score = result.get("semantic_score", 0.0)
            project_name = result.get("project_name", "unknown")
            content_preview = result.get("content_preview", "")

            output.append(f"  {i}. {title}")
            output.append(f"     Project: {project_name}")
            output.append(f"     Type: {entity_type}")
            output.append(f"     Path: {entity_id}")
            output.append(f"     Relevance: {relevance_score:.2%} | Semantic: {semantic_score:.2%}")

            # Show content preview if available (first 200 chars)
            if content_preview:
                preview_text = content_preview[:200].strip()
                if len(content_preview) > 200:
                    preview_text += "..."
                output.append(f"     Preview: {preview_text}")

            output.append("")

        return "\n".join(output)

    def _format_filesystem(self, filesystem_data: dict[str, Any]) -> str:
        """
        Format filesystem section.

        REMOVED: Filesystem tree dumps are 100% noise (1,309 files, ~2,000 tokens).
        Agents should use Glob/Grep tools for targeted file discovery.

        This method now returns an empty string to eliminate token waste.
        """
        return ""  # Return empty string instead of full tree

    def _format_debug_loop(self, debug_loop_data: dict[str, Any]) -> str:
        """Format debug loop section with STF availability and model pricing."""
        output = ["AVAILABLE DEBUG PATTERNS (STFs):"]

        if not debug_loop_data.get("available", False):
            reason = debug_loop_data.get("reason", "Unknown reason")
            output.append(f"  ⚠️  Debug loop unavailable: {reason}")
            output.append("  (No transformation patterns available yet)")
            return "\n".join(output)

        stf_count = debug_loop_data.get("stf_count", 0)
        categories = debug_loop_data.get("categories", [])
        top_stfs = debug_loop_data.get("top_stfs", [])

        output.append(f"  Total STFs: {stf_count}")

        if categories:
            output.append(f"  Categories: {', '.join([c['category'] for c in categories[:5]])}")
            output.append("")

        if top_stfs:
            output.append("  Top Quality STFs:")
            for stf in top_stfs[:5]:  # Show top 5
                output.append(f"    • {stf['stf_name']} (quality: {stf['quality_score']:.2f})")
                output.append(f"      Category: {stf['category']}")
                output.append(f"      Success Rate: {stf['success_rate']:.1f}%")
                output.append(f"      Usage: {stf['usage_count']} times")
                if stf["description"] != "No description":
                    output.append(f"      Description: {stf['description'][:80]}")
                output.append("")

        output.append("HOW TO USE STFs:")
        output.append("  1. Query by problem_signature or problem_category")
        output.append("  2. Retrieve full code by stf_id")
        output.append("  3. Update usage metrics on success")
        output.append("  4. Use NodeDebugSTFStorageEffect for all operations")

        return "\n".join(output)

    def _format_action_logging(self, action_logging_data: dict[str, Any]) -> str:
        """
        Format action logging requirements section.

        Provides agents with ready-to-use ActionLogger code and examples.
        This ensures all agents automatically log their actions for observability.
        """
        output = ["ACTION LOGGING REQUIREMENTS:"]
        output.append("")

        # Get correlation ID and agent name from current context
        correlation_id = (
            str(self._current_correlation_id) if self._current_correlation_id else "auto-generated"
        )
        agent_name = self.agent_name or "your-agent-name"
        project_name = action_logging_data.get("project_name", "omniclaude")

        output.append(f"  Correlation ID: {correlation_id}")
        output.append("")

        # Initialization code
        output.append("  Initialize ActionLogger:")
        output.append("  ```python")
        output.append("  from omniclaude.lib.core.action_logger import ActionLogger")
        output.append("")
        output.append("  logger = ActionLogger(")
        output.append(f'      agent_name="{agent_name}",')
        output.append(f'      correlation_id="{correlation_id}",')
        output.append(f'      project_name="{project_name}"')
        output.append("  )")
        output.append("  ```")
        output.append("")

        # Tool call example with context manager
        output.append("  Log tool calls (automatic timing):")
        output.append("  ```python")
        output.append('  async with logger.tool_call("Read", {"file_path": "..."}) as action:')
        output.append("      result = await read_file(...)")
        output.append('      action.set_result({"line_count": len(result)})')
        output.append("  ```")
        output.append("")

        # Decision logging example
        output.append("  Log decisions:")
        output.append("  ```python")
        output.append('  await logger.log_decision("select_strategy",')
        output.append('      decision_result={"chosen": "approach_a", "confidence": 0.92})')
        output.append("  ```")
        output.append("")

        # Error logging example
        output.append("  Log errors:")
        output.append("  ```python")
        output.append('  await logger.log_error("ErrorType", "error message",')
        output.append('      error_context={"file": "...", "line": 42},')
        output.append('      severity="error")')
        output.append("  ```")
        output.append("")

        # Success logging example
        output.append("  Log successes:")
        output.append("  ```python")
        output.append('  await logger.log_success("task_completed",')
        output.append('      success_details={"files_processed": 5},')
        output.append("      duration_ms=250)")
        output.append("  ```")
        output.append("")

        # Performance and infrastructure note
        output.append("  Performance: <5ms overhead per action, non-blocking")
        output.append("  Kafka Topic: onex.evt.omniclaude.agent-actions.v1")
        output.append("  Benefits: Complete traceability, debug intelligence, performance metrics")

        return "\n".join(output)

    def get_manifest_summary(self) -> dict[str, Any]:
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

            # Count models (ai_models is a dict with provider names as keys)
            ai_models = models_data.get("ai_models", {})
            models_count = len(ai_models)

            # Count schemas
            database_schemas_count = len(schemas_data.get("tables", []))

            # Debug intelligence counts (use total counts, not limited display list)
            debug_intelligence_successes = debug_data.get("total_successes", 0)
            debug_intelligence_failures = debug_data.get("total_failures", 0)

            # Filesystem counts
            filesystem_data = manifest.get("filesystem", {})
            filesystem_files_count = filesystem_data.get("total_files", 0)
            filesystem_directories_count = filesystem_data.get("total_directories", 0)

            # Get formatted text
            # For fresh manifests, invalidate cache to ensure formatted text matches new data
            if not from_cache:
                self._cached_formatted = None
            formatted_text = self._cached_formatted or self.format_for_prompt()

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

    def get_cache_metrics(self, query_type: str | None = None) -> dict[str, Any]:
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

    def invalidate_cache(self, query_type: str | None = None) -> int:
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

    def get_cache_info(self) -> dict[str, Any]:
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
        error_message: str | None = None,
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
    correlation_id: str | None = None,
    sections: list[str] | None = None,
    agent_name: str | None = None,
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

        formatted = injector.format_for_prompt(sections)

    return formatted


# Convenience function for quick access (sync wrapper for backward compatibility)
def inject_manifest(
    correlation_id: str | None = None,
    sections: list[str] | None = None,
    agent_name: str | None = None,
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
        return loop.run_until_complete(inject_manifest_async(correlation_id, sections, agent_name))
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
    "CacheEntry",
    "CacheMetrics",
    "DisabledPattern",
    "ManifestCache",
    "ManifestInjectionStorage",
    "ManifestInjector",
    "inject_manifest",
    "inject_manifest_async",
]
