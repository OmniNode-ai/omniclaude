#!/usr/bin/env python3
"""
Test script for manifest caching implementation.

Tests:
1. Cache initialization
2. Cache hit/miss tracking
3. TTL expiration
4. Cache metrics
5. Cache invalidation
"""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path


# Add parent directory to path for imports
parent_path = Path(__file__).parent.parent
sys.path.insert(0, str(parent_path))

from agents.lib.manifest_injector import (  # noqa: E402
    CacheEntry,
    CacheMetrics,
    ManifestCache,
)


def test_cache_metrics():
    """Test CacheMetrics class."""
    print("\n=== Testing CacheMetrics ===")

    metrics = CacheMetrics()

    # Record some operations
    metrics.record_hit(query_time_ms=5)
    metrics.record_hit(query_time_ms=3)
    metrics.record_miss(query_time_ms=100)
    metrics.record_miss(query_time_ms=120)

    # Check metrics
    assert metrics.total_queries == 4
    assert metrics.cache_hits == 2
    assert metrics.cache_misses == 2
    assert metrics.hit_rate == 50.0

    print(f"✅ Total queries: {metrics.total_queries}")
    print(f"✅ Cache hits: {metrics.cache_hits}")
    print(f"✅ Cache misses: {metrics.cache_misses}")
    print(f"✅ Hit rate: {metrics.hit_rate}%")
    print(f"✅ Avg query time: {metrics.average_query_time_ms:.1f}ms")
    print(f"✅ Avg cache time: {metrics.average_cache_query_time_ms:.1f}ms")

    print("✅ CacheMetrics tests passed")


def test_cache_entry():
    """Test CacheEntry class."""
    print("\n=== Testing CacheEntry ===")

    # Create entry with 1-second TTL (use timezone-aware datetime)
    entry = CacheEntry(
        data={"test": "data"},
        timestamp=datetime.now(UTC),
        ttl_seconds=1,
        query_type="test",
        size_bytes=100,
    )

    # Should not be expired immediately
    assert not entry.is_expired
    print(f"✅ Entry not expired: age={entry.age_seconds:.3f}s")

    # Wait for expiration
    time.sleep(1.1)
    # Note: mypy can't track that time.sleep causes is_expired to change
    expired = entry.is_expired
    assert expired
    print(f"✅ Entry expired: age={entry.age_seconds:.3f}s")  # type: ignore[unreachable]

    print("✅ CacheEntry tests passed")


def test_manifest_cache():
    """Test ManifestCache class."""
    print("\n=== Testing ManifestCache ===")

    # Initialize cache with 2-second default TTL
    cache = ManifestCache(default_ttl_seconds=2, enable_metrics=True)

    # Test cache miss (use "filesystem" which has 1x TTL multiplier)
    result = cache.get("filesystem")
    assert result is None
    print("✅ Cache miss for 'filesystem'")

    # Set cache entry
    test_data = {"files": ["file1.py", "file2.py"], "total": 2}
    cache.set("filesystem", test_data)
    print("✅ Cache entry set for 'filesystem'")

    # Test cache hit
    result = cache.get("filesystem")
    assert result is not None
    assert result["total"] == 2
    print("✅ Cache hit for 'filesystem'")

    # Test metrics
    metrics = cache.get_metrics("filesystem")
    assert metrics["total_queries"] == 2
    assert metrics["cache_hits"] == 1
    assert metrics["cache_misses"] == 1
    assert metrics["hit_rate_percent"] == 50.0
    print(f"✅ Cache metrics: hit_rate={metrics['hit_rate_percent']}%")

    # Test cache info
    info = cache.get_cache_info()
    assert info["cache_size"] == 1
    print(
        f"✅ Cache info: {info['cache_size']} entries, {info['total_size_bytes']} bytes"
    )

    # Test expiration (filesystem uses 1x TTL = 2 seconds)
    print("⏳ Waiting for cache expiration (2 seconds)...")
    time.sleep(2.1)
    result = cache.get("filesystem")
    assert result is None
    print("✅ Cache entry expired and removed")

    # Test invalidation
    cache.set("test1", {"data": 1})
    cache.set("test2", {"data": 2})
    assert cache.get("test1") is not None
    assert cache.get("test2") is not None

    count = cache.invalidate("test1")
    assert count == 1
    assert cache.get("test1") is None
    assert cache.get("test2") is not None
    print("✅ Selective cache invalidation works")

    count = cache.invalidate()
    assert count == 1
    assert cache.get("test2") is None
    print("✅ Full cache invalidation works")

    print("✅ ManifestCache tests passed")


def test_per_query_type_ttls():
    """Test per-query-type TTL configuration."""
    print("\n=== Testing Per-Query-Type TTLs ===")

    cache = ManifestCache(default_ttl_seconds=10, enable_metrics=True)

    # Check TTL configuration
    expected_ttls = {
        "patterns": 30,  # 3x default
        "infrastructure": 20,  # 2x default
        "models": 30,  # 3x default
        "database_schemas": 10,  # 1x default
        "debug_intelligence": 5,  # 0.5x default
    }

    for query_type, expected_ttl in expected_ttls.items():
        actual_ttl = cache._ttls.get(query_type)
        assert (
            actual_ttl == expected_ttl
        ), f"{query_type}: expected {expected_ttl}, got {actual_ttl}"
        print(f"✅ {query_type}: TTL={actual_ttl}s")

    print("✅ Per-query-type TTL tests passed")


def test_cache_metrics_aggregation():
    """Test cache metrics aggregation across multiple query types."""
    print("\n=== Testing Cache Metrics Aggregation ===")

    cache = ManifestCache(default_ttl_seconds=10, enable_metrics=True)

    # Simulate queries for different types
    query_types = ["patterns", "infrastructure", "models"]

    for query_type in query_types:
        # Cache miss
        cache.get(query_type)
        # Cache set
        cache.set(query_type, {"data": f"{query_type}_data"})
        # Cache hit
        cache.get(query_type)
        # Another hit
        cache.get(query_type)

    # Get overall metrics
    metrics = cache.get_metrics()
    overall = metrics["overall"]

    # Each query type: 1 miss + 2 hits = 3 queries
    # Total: 3 types * 3 queries = 9 queries
    assert overall["total_queries"] == 9
    assert overall["cache_hits"] == 6  # 2 hits per type * 3 types
    assert overall["cache_misses"] == 3  # 1 miss per type * 3 types
    # Round expected value to match the rounding in CacheMetrics.to_dict()
    assert overall["hit_rate_percent"] == round((6 / 9) * 100, 2)

    print("✅ Overall metrics:")
    print(f"   Total queries: {overall['total_queries']}")
    print(f"   Cache hits: {overall['cache_hits']}")
    print(f"   Cache misses: {overall['cache_misses']}")
    print(f"   Hit rate: {overall['hit_rate_percent']:.1f}%")

    # Check per-type metrics
    for query_type in query_types:
        type_metrics = cache.get_metrics(query_type)
        assert type_metrics["total_queries"] == 3
        assert type_metrics["cache_hits"] == 2
        assert type_metrics["cache_misses"] == 1
        print(f"✅ {query_type}: {type_metrics['hit_rate_percent']:.1f}% hit rate")

    print("✅ Cache metrics aggregation tests passed")


def main():
    """Run all tests."""
    print("=" * 70)
    print("MANIFEST CACHING IMPLEMENTATION TESTS")
    print("=" * 70)

    try:
        test_cache_metrics()
        test_cache_entry()
        test_manifest_cache()
        test_per_query_type_ttls()
        test_cache_metrics_aggregation()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
