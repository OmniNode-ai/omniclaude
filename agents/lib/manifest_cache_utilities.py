"""
Manifest Cache Utility Methods

These methods should be added to the ManifestInjector class in manifest_injector.py
to expose caching functionality and metrics.

Add these methods after _store_manifest_if_enabled() and before the convenience function.
"""

from typing import Any, Dict, Optional


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
