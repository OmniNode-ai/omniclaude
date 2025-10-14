"""
Result Cache - Phase 1
======================

Simple in-memory cache with TTL for routing results.

Features:
- Hash-based key generation
- Time-to-live (TTL) expiration
- Hit/miss tracking
- Cache statistics
- Automatic expiration cleanup

Target Performance:
- Cache hit: <5ms
- Cache miss: 0ms overhead
- Hit rate: >60% after warmup
"""

from typing import Optional, Any, Dict
import time
import hashlib


class ResultCache:
    """
    Simple in-memory cache with TTL.

    Caches routing results to avoid expensive recomputation
    for repeated queries.
    """

    def __init__(self, default_ttl_seconds: int = 3600):
        """
        Initialize cache.

        Args:
            default_ttl_seconds: Default time-to-live in seconds (default: 1 hour)
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl_seconds

    def _generate_key(self, query: str, context: Optional[Dict] = None) -> str:
        """
        Generate cache key from query and context.

        Uses SHA-256 hash of query + sorted context to ensure
        same inputs always produce same key.

        Args:
            query: User's input text
            context: Optional execution context

        Returns:
            SHA-256 hash as cache key
        """
        key_data = query
        if context:
            # Sort context items for consistent hashing
            key_data += str(sorted(context.items()))

        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, query: str, context: Optional[Dict] = None) -> Optional[Any]:
        """
        Get cached result if valid.

        Checks TTL and automatically removes expired entries.

        Args:
            query: User's input text
            context: Optional execution context

        Returns:
            Cached value if found and valid, None otherwise
        """
        key = self._generate_key(query, context)

        if key not in self.cache:
            return None

        entry = self.cache[key]

        # Check TTL
        if time.time() > entry['expires_at']:
            # Expired - remove and return None
            del self.cache[key]
            return None

        # Update access tracking
        entry['hits'] += 1
        entry['last_accessed'] = time.time()

        return entry['value']

    def set(
        self,
        query: str,
        value: Any,
        context: Optional[Dict] = None,
        ttl_seconds: Optional[int] = None
    ):
        """
        Cache result with TTL.

        Args:
            query: User's input text
            value: Result to cache
            context: Optional execution context
            ttl_seconds: Custom TTL (uses default if None)
        """
        key = self._generate_key(query, context)
        ttl = ttl_seconds or self.default_ttl

        current_time = time.time()
        self.cache[key] = {
            'value': value,
            'created_at': current_time,
            'expires_at': current_time + ttl,
            'last_accessed': current_time,
            'hits': 0  # Number of times accessed after creation
        }

    def invalidate(self, query: str, context: Optional[Dict] = None):
        """
        Invalidate specific cache entry.

        Useful when agent definitions change or user wants fresh results.

        Args:
            query: User's input text
            context: Optional execution context
        """
        key = self._generate_key(query, context)
        if key in self.cache:
            del self.cache[key]

    def clear(self):
        """Clear entire cache."""
        self.cache.clear()

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if current_time > entry['expires_at']
        ]

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache performance metrics
        """
        if not self.cache:
            return {
                'entries': 0,
                'total_hits': 0,
                'avg_hits_per_entry': 0.0,
                'oldest_entry_age_seconds': 0.0,
                'cache_size_bytes': 0
            }

        current_time = time.time()
        total_hits = sum(entry['hits'] for entry in self.cache.values())
        total_entries = len(self.cache)

        # Find oldest entry
        oldest_created = min(entry['created_at'] for entry in self.cache.values())
        oldest_age = current_time - oldest_created

        return {
            'entries': total_entries,
            'total_hits': total_hits,
            'avg_hits_per_entry': total_hits / total_entries if total_entries else 0,
            'oldest_entry_age_seconds': oldest_age,
            'cache_size_bytes': len(str(self.cache))  # Approximate size
        }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """
        Get detailed cache statistics.

        Returns:
            Detailed statistics including hit rate distribution
        """
        stats = self.stats()

        if not self.cache:
            stats['hit_distribution'] = {}
            stats['ttl_distribution'] = {}
            return stats

        current_time = time.time()

        # Hit distribution
        hit_counts = [entry['hits'] for entry in self.cache.values()]
        stats['hit_distribution'] = {
            'min_hits': min(hit_counts),
            'max_hits': max(hit_counts),
            'median_hits': sorted(hit_counts)[len(hit_counts) // 2]
        }

        # TTL distribution
        ttls = [
            entry['expires_at'] - current_time
            for entry in self.cache.values()
        ]
        stats['ttl_distribution'] = {
            'min_ttl_seconds': min(ttls),
            'max_ttl_seconds': max(ttls),
            'avg_ttl_seconds': sum(ttls) / len(ttls)
        }

        return stats


# Standalone test
if __name__ == "__main__":
    import random

    cache = ResultCache(default_ttl_seconds=60)  # 1 minute for testing

    print("=== Testing Result Cache ===\n")

    # Test basic operations
    print("1. Set and Get:")
    cache.set("test query", ["agent-1", "agent-2"])
    result = cache.get("test query")
    print(f"   Cached: {result}")

    # Test cache miss
    print("\n2. Cache Miss:")
    result = cache.get("unknown query")
    print(f"   Result: {result}")

    # Test with context
    print("\n3. With Context:")
    cache.set("query", ["agent-3"], context={'domain': 'api'})
    result = cache.get("query", context={'domain': 'api'})
    print(f"   Cached: {result}")

    # Different context = different cache entry
    result = cache.get("query", context={'domain': 'debug'})
    print(f"   Different context: {result}")

    # Test hit tracking
    print("\n4. Hit Tracking:")
    for i in range(5):
        cache.get("test query")
    stats = cache.stats()
    print(f"   Total hits: {stats['total_hits']}")
    print(f"   Entries: {stats['entries']}")
    print(f"   Avg hits/entry: {stats['avg_hits_per_entry']:.1f}")

    # Test expiration
    print("\n5. TTL Expiration:")
    cache.set("expires-soon", ["agent-4"], ttl_seconds=1)
    print(f"   Immediate: {cache.get('expires-soon')}")
    time.sleep(1.5)
    print(f"   After 1.5s: {cache.get('expires-soon')}")

    # Test cleanup
    print("\n6. Cleanup:")
    expired = cache.cleanup_expired()
    print(f"   Removed {expired} expired entries")

    # Show detailed stats
    print("\n7. Detailed Stats:")
    detailed = cache.get_detailed_stats()
    for key, value in detailed.items():
        print(f"   {key}: {value}")

    # Test invalidation
    print("\n8. Invalidation:")
    cache.set("invalidate-me", ["agent-5"])
    print(f"   Before: {cache.get('invalidate-me')}")
    cache.invalidate("invalidate-me")
    print(f"   After: {cache.get('invalidate-me')}")

    # Test clear
    print("\n9. Clear All:")
    print(f"   Before: {cache.stats()['entries']} entries")
    cache.clear()
    print(f"   After: {cache.stats()['entries']} entries")
