"""
Cache Manager for AI Quality Enforcement System

Simple file-based cache with TTL for RAG and AI model results.
Provides significant performance improvements for repeated queries.
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Any, Dict


class CacheManager:
    """Simple file-based cache for RAG and AI results.

    Features:
    - Time-to-live (TTL) expiration
    - Automatic cleanup of expired entries
    - Content-addressed storage via SHA256 hashing
    - JSON serialization for complex objects

    Cache keys are hashed to create safe filenames, and each cache entry
    stores both the value and a timestamp for TTL enforcement.
    """

    def __init__(self, cache_dir: Path, ttl_seconds: int = 3600):
        """Initialize cache manager.

        Args:
            cache_dir: Directory for storing cache files
            ttl_seconds: Time-to-live for cache entries in seconds (default: 1 hour)
        """
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired.

        Args:
            key: Cache key (will be hashed for storage)

        Returns:
            Cached value if found and not expired, None otherwise
        """
        cache_file = self.cache_dir / self._hash(key)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)

            # Check expiration
            age = time.time() - data["timestamp"]
            if age > self.ttl_seconds:
                # Expired - delete and return None
                cache_file.unlink()
                return None

            return data["value"]

        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupted or invalid cache file - delete it
            cache_file.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any):
        """Cache a value with current timestamp.

        Args:
            key: Cache key (will be hashed for storage)
            value: Value to cache (must be JSON-serializable)
        """
        cache_file = self.cache_dir / self._hash(key)

        data = {"timestamp": time.time(), "value": value}

        try:
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except (TypeError, OSError) as e:
            # Value not serializable or write failed - log but don't crash
            print(f"Warning: Failed to cache value for key {key[:20]}...: {e}")

    def delete(self, key: str) -> bool:
        """Delete a cached value.

        Args:
            key: Cache key to delete

        Returns:
            True if cache entry existed and was deleted, False otherwise
        """
        cache_file = self.cache_dir / self._hash(key)

        if cache_file.exists():
            cache_file.unlink()
            return True

        return False

    def clear(self):
        """Clear all cached entries."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()

    def cleanup_expired(self) -> int:
        """Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        removed = 0
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)

                age = current_time - data["timestamp"]
                if age > self.ttl_seconds:
                    cache_file.unlink()
                    removed += 1

            except (json.JSONDecodeError, KeyError, OSError):
                # Corrupted file - remove it
                cache_file.unlink(missing_ok=True)
                removed += 1

        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics:
            - total_entries: Total number of cache entries
            - expired_entries: Number of expired entries
            - total_size_mb: Total size of cache in MB
            - oldest_entry_age_hours: Age of oldest entry in hours
        """
        total_entries = 0
        expired_entries = 0
        total_size = 0
        oldest_timestamp = None
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            total_entries += 1
            total_size += cache_file.stat().st_size

            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)

                timestamp = data["timestamp"]

                # Track oldest entry
                if oldest_timestamp is None or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp

                # Check if expired
                age = current_time - timestamp
                if age > self.ttl_seconds:
                    expired_entries += 1

            except (json.JSONDecodeError, KeyError, OSError):
                expired_entries += 1

        oldest_age_hours = (
            (current_time - oldest_timestamp) / 3600
            if oldest_timestamp is not None
            else 0
        )

        return {
            "total_entries": total_entries,
            "expired_entries": expired_entries,
            "total_size_mb": total_size / (1024 * 1024),
            "oldest_entry_age_hours": oldest_age_hours,
            "cache_dir": str(self.cache_dir),
            "ttl_seconds": self.ttl_seconds,
        }

    def _hash(self, key: str) -> str:
        """Generate cache filename from key.

        Uses SHA256 hash for content-addressing.
        Truncated to 16 characters for reasonable filename length.

        Args:
            key: Cache key to hash

        Returns:
            Hashed filename with .json extension
        """
        hash_digest = hashlib.sha256(key.encode()).hexdigest()
        return hash_digest[:16] + ".json"


# Example usage and testing
if __name__ == "__main__":
    # Test the cache manager
    cache = CacheManager(Path("~/.claude/hooks/.cache"), ttl_seconds=60)

    # Test basic operations
    print("Testing cache operations...")

    # Set some values
    cache.set("test_key_1", {"result": "value1", "score": 0.95})
    cache.set("test_key_2", ["item1", "item2", "item3"])
    cache.set("test_key_3", "simple_string")

    # Get values
    value1 = cache.get("test_key_1")
    print(f"Retrieved value1: {value1}")

    value2 = cache.get("test_key_2")
    print(f"Retrieved value2: {value2}")

    # Test cache miss
    missing = cache.get("nonexistent_key")
    print(f"Missing key result: {missing}")

    # Test expiration (with short TTL)
    short_cache = CacheManager(Path("~/.claude/hooks/.cache/.test"), ttl_seconds=1)
    short_cache.set("expire_test", "will_expire")
    print(f"Before expiration: {short_cache.get('expire_test')}")

    time.sleep(2)
    print(f"After expiration: {short_cache.get('expire_test')}")

    # Get statistics
    stats = cache.get_stats()
    print(f"\nCache Statistics:")
    print(f"  Total entries: {stats['total_entries']}")
    print(f"  Expired entries: {stats['expired_entries']}")
    print(f"  Total size: {stats['total_size_mb']:.2f} MB")
    print(f"  Oldest entry: {stats['oldest_entry_age_hours']:.2f} hours")

    # Cleanup test cache
    short_cache.clear()

    print("\nCache manager test complete!")
