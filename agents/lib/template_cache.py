#!/usr/bin/env python3
"""
Template Cache - Phase 7 Stream 2
==================================

Intelligent template caching with LRU eviction, TTL, and content-based invalidation.

Features:
- LRU cache with configurable size limits
- Time-to-live (TTL) expiration
- Content-based invalidation (hash checking)
- Thread-safe operations
- Database metrics tracking
- Cache warmup on startup

Target Performance:
- Template load time: 50ms (50% reduction from 100ms baseline)
- Cache hit rate: ≥80% after warmup
- Memory usage: ≤50MB
"""

from typing import Dict, Any, Optional, Tuple, Callable
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from threading import RLock
import hashlib
import time
import logging
import asyncio
from collections import OrderedDict

logger = logging.getLogger(__name__)


@dataclass
class CachedTemplate:
    """Cached template with metadata"""
    template_name: str
    template_type: str
    content: str
    file_path: str
    file_hash: str
    loaded_at: datetime
    last_accessed_at: datetime
    access_count: int = 0
    size_bytes: int = 0

    def __post_init__(self):
        """Calculate size if not provided"""
        if self.size_bytes == 0:
            self.size_bytes = len(self.content.encode('utf-8'))


class TemplateCache:
    """
    Intelligent template cache with multiple eviction strategies.

    Features:
    - Content-based invalidation (hash-based)
    - LRU eviction for memory management
    - TTL support for time-sensitive templates
    - Thread-safe operations
    - Performance metrics tracking
    - Database persistence for analytics
    """

    def __init__(
        self,
        max_templates: int = 100,
        max_size_mb: int = 50,
        ttl_seconds: int = 3600,
        enable_persistence: bool = True
    ):
        """
        Initialize template cache.

        Args:
            max_templates: Maximum number of templates to cache (default: 100)
            max_size_mb: Maximum cache size in megabytes (default: 50)
            ttl_seconds: Time-to-live in seconds (default: 3600 = 1 hour)
            enable_persistence: Enable database persistence for metrics
        """
        # Use OrderedDict for LRU tracking
        self._cache: OrderedDict[str, CachedTemplate] = OrderedDict()
        self._lock = RLock()

        # Configuration
        self.max_templates = max_templates
        self.max_size_mb = max_size_mb
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl_seconds = ttl_seconds
        self.enable_persistence = enable_persistence

        # Metrics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.invalidations = 0
        self.total_load_time_ms = 0.0
        self.cached_load_time_ms = 0.0

        logger.info(
            f"TemplateCache initialized: max_templates={max_templates}, "
            f"max_size_mb={max_size_mb}, ttl_seconds={ttl_seconds}"
        )

    def get(
        self,
        template_name: str,
        template_type: str,
        file_path: Path,
        loader_func: Callable[[Path], str]
    ) -> Tuple[str, bool]:
        """
        Get template from cache or load from filesystem.

        Args:
            template_name: Unique template identifier
            template_type: Template type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            file_path: Path to template file
            loader_func: Function to load template from file

        Returns:
            Tuple of (template_content, cache_hit)
        """
        with self._lock:
            # Check if template exists in cache
            if template_name in self._cache:
                cached = self._cache[template_name]

                # Verify file hasn't changed (content-based invalidation)
                current_hash = self._compute_file_hash(file_path)
                if cached.file_hash != current_hash:
                    logger.info(f"Template {template_name} invalidated: hash mismatch")
                    self._invalidate_template(template_name)
                else:
                    # Check TTL
                    age = datetime.now(timezone.utc) - cached.loaded_at
                    if age.total_seconds() >= self.ttl_seconds:
                        logger.info(f"Template {template_name} expired: TTL {age.total_seconds():.1f}s")
                        self._invalidate_template(template_name)
                    else:
                        # Cache hit!
                        start_time = time.perf_counter()

                        # Update access tracking (LRU)
                        self._cache.move_to_end(template_name)
                        cached.access_count += 1
                        cached.last_accessed_at = datetime.now(timezone.utc)
                        self.hits += 1

                        # Track performance
                        cached_time_ms = (time.perf_counter() - start_time) * 1000
                        self.cached_load_time_ms += cached_time_ms

                        logger.debug(
                            f"Cache HIT for {template_name} "
                            f"(access #{cached.access_count}, age: {age.total_seconds():.1f}s, "
                            f"time: {cached_time_ms:.2f}ms)"
                        )

                        # Update metrics in background (non-blocking)
                        if self.enable_persistence:
                            try:
                                loop = asyncio.get_running_loop()
                                asyncio.create_task(
                                    self._update_cache_metrics_async(
                                        template_name=template_name,
                                        template_type=template_type,
                                        file_path=str(file_path),
                                        cache_hit=True,
                                        load_time_ms=cached_time_ms
                                    )
                                )
                            except RuntimeError:
                                # No event loop running - skip async metrics update
                                pass

                        return cached.content, True

            # Cache miss - load template from filesystem
            self.misses += 1
            start_time = time.perf_counter()

            try:
                content = loader_func(file_path)
                load_time_ms = (time.perf_counter() - start_time) * 1000
                self.total_load_time_ms += load_time_ms

                logger.debug(
                    f"Cache MISS for {template_name} "
                    f"(load time: {load_time_ms:.2f}ms)"
                )

                # Compute file hash for content-based invalidation
                file_hash = self._compute_file_hash(file_path)

                # Create cached entry
                cached = CachedTemplate(
                    template_name=template_name,
                    template_type=template_type,
                    content=content,
                    file_path=str(file_path),
                    file_hash=file_hash,
                    loaded_at=datetime.now(timezone.utc),
                    last_accessed_at=datetime.now(timezone.utc),
                    access_count=1
                )

                # Ensure capacity before adding
                self._ensure_capacity(cached.size_bytes)

                # Add to cache
                self._cache[template_name] = cached

                # Update metrics in background (non-blocking)
                if self.enable_persistence:
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(
                            self._update_cache_metrics_async(
                                template_name=template_name,
                                template_type=template_type,
                                file_path=str(file_path),
                                cache_hit=False,
                                load_time_ms=load_time_ms,
                                file_hash=file_hash,
                                size_bytes=cached.size_bytes
                            )
                        )
                    except RuntimeError:
                        # No event loop running - skip async metrics update
                        pass

                return content, False

            except Exception as e:
                logger.error(f"Failed to load template {template_name}: {e}")
                raise

    def _ensure_capacity(self, required_bytes: int):
        """
        Ensure cache has capacity for new template using LRU eviction.

        Args:
            required_bytes: Size of template to add
        """
        current_size = sum(t.size_bytes for t in self._cache.values())
        current_count = len(self._cache)

        # Check count limit
        while current_count >= self.max_templates and self._cache:
            # Evict least recently used (first item in OrderedDict)
            lru_key = next(iter(self._cache))
            self._evict_template(lru_key, reason="count_limit")
            current_count -= 1

        # Check size limit
        while (current_size + required_bytes) > self.max_size_bytes and self._cache:
            # Evict least recently used
            lru_key = next(iter(self._cache))
            evicted = self._cache[lru_key]
            self._evict_template(lru_key, reason="size_limit")
            current_size -= evicted.size_bytes

    def _evict_template(self, template_name: str, reason: str = "lru"):
        """
        Evict template from cache.

        Args:
            template_name: Template to evict
            reason: Reason for eviction (for logging)
        """
        if template_name in self._cache:
            cached = self._cache.pop(template_name)
            self.evictions += 1
            logger.debug(
                f"Evicted template {template_name} "
                f"(reason: {reason}, access_count: {cached.access_count}, "
                f"size: {cached.size_bytes} bytes)"
            )

    def _invalidate_template(self, template_name: str):
        """
        Invalidate template (due to file change or TTL expiry).

        Args:
            template_name: Template to invalidate
        """
        if template_name in self._cache:
            self._cache.pop(template_name)
            self.invalidations += 1

    def invalidate(self, template_name: str):
        """
        Manually invalidate specific template.

        Args:
            template_name: Template to invalidate
        """
        with self._lock:
            self._invalidate_template(template_name)
            logger.info(f"Manually invalidated template: {template_name}")

    def invalidate_all(self):
        """Invalidate all cached templates."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self.invalidations += count
            logger.info(f"Invalidated all templates (count: {count})")

    def warmup(self, templates_dir: Path, template_types: list[str]):
        """
        Warmup cache by preloading common templates.

        Args:
            templates_dir: Directory containing templates
            template_types: List of template types to preload
        """
        logger.info(f"Starting cache warmup for {len(template_types)} templates")
        start_time = time.perf_counter()

        loaded_count = 0
        for template_type in template_types:
            template_path = templates_dir / f"{template_type.lower()}_node_template.py"
            if template_path.exists():
                self.get(
                    template_name=f"{template_type}_template",
                    template_type=template_type,
                    file_path=template_path,
                    loader_func=lambda p: p.read_text()
                )
                loaded_count += 1

        warmup_time_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Cache warmup complete: {loaded_count} templates loaded "
            f"in {warmup_time_ms:.2f}ms"
        )

    def _compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA-256 hash of file content.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of SHA-256 hash
        """
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Failed to compute hash for {file_path}: {e}")
            return ""

    async def _update_cache_metrics_async(
        self,
        template_name: str,
        template_type: str,
        file_path: str,
        cache_hit: bool,
        load_time_ms: float,
        file_hash: Optional[str] = None,
        size_bytes: Optional[int] = None
    ):
        """
        Update cache metrics in database (async).

        Args:
            template_name: Template identifier
            template_type: Template type
            file_path: Path to template file
            cache_hit: Whether this was a cache hit
            load_time_ms: Time taken to load/retrieve
            file_hash: File hash (for misses)
            size_bytes: Template size (for misses)
        """
        if not self.enable_persistence:
            return

        try:
            # Import here to avoid circular dependencies
            from .persistence import CodegenPersistence

            persistence = CodegenPersistence()
            try:
                if not cache_hit:
                    # For cache misses, upsert the template metadata first
                    await persistence.upsert_template_cache_metadata(
                        template_name=template_name,
                        template_type=template_type,
                        cache_key=template_name,  # Simple key for now
                        file_path=file_path,
                        file_hash=file_hash or "",
                        size_bytes=size_bytes,
                        load_time_ms=int(load_time_ms)
                    )

                # Update hit/miss counters
                await persistence.update_cache_metrics(
                    template_name=template_name,
                    cache_hit=cache_hit,
                    load_time_ms=int(load_time_ms) if not cache_hit else None
                )
            finally:
                await persistence.close()
        except Exception as e:
            # Don't fail cache operations due to persistence errors
            logger.warning(f"Failed to update cache metrics: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache performance metrics
        """
        with self._lock:
            total_requests = self.hits + self.misses
            hit_rate = self.hits / total_requests if total_requests > 0 else 0.0

            # Calculate average load times
            avg_uncached_load_ms = (
                self.total_load_time_ms / self.misses if self.misses > 0 else 0.0
            )
            avg_cached_load_ms = (
                self.cached_load_time_ms / self.hits if self.hits > 0 else 0.0
            )

            # Calculate time savings
            if self.hits > 0 and avg_uncached_load_ms > 0:
                time_saved_ms = self.hits * (avg_uncached_load_ms - avg_cached_load_ms)
                improvement_pct = (
                    ((avg_uncached_load_ms - avg_cached_load_ms) / avg_uncached_load_ms) * 100
                )
            else:
                time_saved_ms = 0.0
                improvement_pct = 0.0

            # Calculate total cache size
            total_size_bytes = sum(t.size_bytes for t in self._cache.values())
            total_size_mb = total_size_bytes / (1024 * 1024)

            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 4),
                "evictions": self.evictions,
                "invalidations": self.invalidations,
                "cached_templates": len(self._cache),
                "total_size_bytes": total_size_bytes,
                "total_size_mb": round(total_size_mb, 2),
                "avg_uncached_load_ms": round(avg_uncached_load_ms, 2),
                "avg_cached_load_ms": round(avg_cached_load_ms, 2),
                "time_saved_ms": round(time_saved_ms, 2),
                "improvement_percent": round(improvement_pct, 1),
                "capacity_usage_percent": round(
                    (len(self._cache) / self.max_templates) * 100, 1
                ),
                "memory_usage_percent": round(
                    (total_size_mb / self.max_size_mb) * 100, 1
                )
            }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """
        Get detailed cache statistics including per-template metrics.

        Returns:
            Detailed statistics with template-level breakdown
        """
        with self._lock:
            stats = self.get_stats()

            # Add per-template breakdown
            template_stats = []
            for name, cached in self._cache.items():
                age_seconds = (
                    datetime.now(timezone.utc) - cached.loaded_at
                ).total_seconds()

                template_stats.append({
                    "name": name,
                    "type": cached.template_type,
                    "size_bytes": cached.size_bytes,
                    "access_count": cached.access_count,
                    "age_seconds": round(age_seconds, 1),
                    "file_hash": cached.file_hash[:8] + "...",  # Truncated for readability
                })

            # Sort by access count (most accessed first)
            template_stats.sort(key=lambda x: x["access_count"], reverse=True)

            stats["templates"] = template_stats
            return stats


# Standalone test
if __name__ == "__main__":
    import sys
    import tempfile

    print("=== Testing Template Cache ===\n")

    # Create temporary test templates
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create test template files
        effect_template = tmpdir / "effect_node_template.py"
        effect_template.write_text("# Effect template content\nclass NodeEffect:\n    pass\n")

        compute_template = tmpdir / "compute_node_template.py"
        compute_template.write_text("# Compute template content\nclass NodeCompute:\n    pass\n")

        # Initialize cache
        cache = TemplateCache(
            max_templates=10,
            max_size_mb=1,
            ttl_seconds=5,  # Short TTL for testing
            enable_persistence=False
        )

        # Test 1: Cache miss
        print("1. Cache Miss:")
        content, hit = cache.get(
            template_name="EFFECT_template",
            template_type="EFFECT",
            file_path=effect_template,
            loader_func=lambda p: p.read_text()
        )
        print(f"   Hit: {hit}, Content length: {len(content)}")
        assert not hit, "First access should be cache miss"

        # Test 2: Cache hit
        print("\n2. Cache Hit:")
        content, hit = cache.get(
            template_name="EFFECT_template",
            template_type="EFFECT",
            file_path=effect_template,
            loader_func=lambda p: p.read_text()
        )
        print(f"   Hit: {hit}, Content length: {len(content)}")
        assert hit, "Second access should be cache hit"

        # Test 3: Content-based invalidation
        print("\n3. Content-Based Invalidation:")
        effect_template.write_text("# Modified effect template\nclass NodeEffect:\n    def new_method(self): pass\n")
        content, hit = cache.get(
            template_name="EFFECT_template",
            template_type="EFFECT",
            file_path=effect_template,
            loader_func=lambda p: p.read_text()
        )
        print(f"   Hit after modification: {hit}")
        assert not hit, "Modified template should invalidate cache"

        # Test 4: TTL expiration
        print("\n4. TTL Expiration:")
        cache.get(
            template_name="COMPUTE_template",
            template_type="COMPUTE",
            file_path=compute_template,
            loader_func=lambda p: p.read_text()
        )
        print("   Sleeping 6 seconds to exceed TTL...")
        time.sleep(6)
        content, hit = cache.get(
            template_name="COMPUTE_template",
            template_type="COMPUTE",
            file_path=compute_template,
            loader_func=lambda p: p.read_text()
        )
        print(f"   Hit after TTL expiration: {hit}")
        assert not hit, "Expired template should not be cache hit"

        # Test 5: Statistics
        print("\n5. Cache Statistics:")
        stats = cache.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")

        # Test 6: Warmup
        print("\n6. Cache Warmup:")
        cache.invalidate_all()
        cache.warmup(tmpdir, ["EFFECT", "COMPUTE"])
        stats = cache.get_stats()
        print(f"   Templates cached after warmup: {stats['cached_templates']}")
        print(f"   Hit rate: {stats['hit_rate']:.1%}")

        # Test 7: LRU eviction
        print("\n7. LRU Eviction:")
        small_cache = TemplateCache(max_templates=2, enable_persistence=False)

        # Add 3 templates (should evict oldest)
        for i in range(3):
            template = tmpdir / f"template_{i}.py"
            template.write_text(f"# Template {i}\n")
            small_cache.get(
                template_name=f"template_{i}",
                template_type="TEST",
                file_path=template,
                loader_func=lambda p: p.read_text()
            )

        stats = small_cache.get_stats()
        print(f"   Templates in cache: {stats['cached_templates']}")
        print(f"   Evictions: {stats['evictions']}")
        assert stats['cached_templates'] == 2, "Should have evicted oldest template"
        assert stats['evictions'] == 1, "Should have 1 eviction"

        print("\n✅ All tests passed!")
