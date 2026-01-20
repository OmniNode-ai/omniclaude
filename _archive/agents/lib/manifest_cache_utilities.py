"""
Manifest Cache Utilities Mixin

Provides cache management utilities for ManifestInjector.
This mixin extracts cache-related functionality into a reusable component.

Usage:
    class ManifestInjector(ManifestCacheUtilitiesMixin, ...):
        pass
"""

import logging
from typing import TYPE_CHECKING, Any, Optional, cast

if TYPE_CHECKING:
    from .manifest_injector import ManifestCache


class ManifestCacheUtilitiesMixin:
    """Mixin providing cache utilities for ManifestInjector.

    This mixin requires the following attributes to be present in the inheriting class:
    - self.enable_cache: bool - Whether caching is enabled
    - self._cache: Cache instance - The cache implementation
    - self.logger: logging.Logger - Logger instance

    Methods:
    - get_cache_metrics(): Get cache performance metrics
    - invalidate_cache(): Invalidate cache entries
    - get_cache_info(): Get cache information and statistics
    - log_cache_metrics(): Log current cache metrics for monitoring
    """

    # Declare expected attributes from parent class (for type checking)
    _cache: Optional["ManifestCache"]
    enable_cache: bool

    def get_cache_metrics(self, query_type: str | None = None) -> dict[str, Any]:
        """
        Get cache performance metrics.

        Args:
            query_type: Specific query type metrics (None = all metrics)

        Returns:
            Cache metrics dictionary with hit rates, query times, etc.
            Returns {"error": "Caching disabled"} if caching is not enabled.
        """
        if not getattr(self, "enable_cache", False) or not getattr(
            self, "_cache", None
        ):
            return {"error": "Caching disabled"}

        cache = cast("ManifestCache", self._cache)
        return cache.get_metrics(query_type)

    def invalidate_cache(self, query_type: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            query_type: Specific query type to invalidate (None = invalidate all)

        Returns:
            Number of entries invalidated
        """
        if not getattr(self, "enable_cache", False) or not getattr(
            self, "_cache", None
        ):
            return 0

        cache = cast("ManifestCache", self._cache)
        return cache.invalidate(query_type)

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get cache information and statistics.

        Returns:
            Cache information dictionary with sizes, TTLs, and entry details.
            Returns {"error": "Caching disabled"} if caching is not enabled.
        """
        if not getattr(self, "enable_cache", False) or not getattr(
            self, "_cache", None
        ):
            return {"error": "Caching disabled"}

        cache = cast("ManifestCache", self._cache)
        return cache.get_cache_info()

    def log_cache_metrics(self) -> None:
        """
        Log current cache metrics for monitoring.

        Logs overall cache performance including hit rates and query times.
        """
        logger = getattr(self, "logger", logging.getLogger(__name__))

        if not getattr(self, "enable_cache", False) or not getattr(
            self, "_cache", None
        ):
            logger.info("Cache metrics: caching disabled")
            return

        metrics = self.get_cache_metrics()
        overall = metrics.get("overall", {})

        logger.info(
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
        for query_type_key, type_metrics in by_type.items():
            if type_metrics.get("total_queries", 0) > 0:
                logger.debug(
                    f"Cache metrics [{query_type_key}]: "
                    f"hit_rate={type_metrics.get('hit_rate_percent', 0):.1f}%, "
                    f"queries={type_metrics.get('total_queries', 0)}"
                )

    def clear_cache(self, query_type: str | None = None) -> int:
        """
        Clear cache entries (alias for invalidate_cache).

        Args:
            query_type: Specific query type to clear (None = clear all)

        Returns:
            Number of entries cleared
        """
        return self.invalidate_cache(query_type)
