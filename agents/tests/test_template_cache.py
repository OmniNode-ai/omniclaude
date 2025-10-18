#!/usr/bin/env python3
"""
Comprehensive tests for Template Cache (Phase 7 Stream 2)

Tests cover:
- Cache hit/miss behavior
- LRU eviction
- TTL expiration
- Content-based invalidation
- Thread safety
- Performance improvements
- Statistics tracking
"""

import pytest

# Mark all tests in this module as integration tests (require database)
pytestmark = pytest.mark.integration
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from agents.lib.template_cache import TemplateCache


class TestCacheBasics:
    """Test basic cache operations"""

    def test_cache_initialization(self):
        """Test cache initialization with different configurations"""
        cache = TemplateCache(max_templates=50, max_size_mb=25, ttl_seconds=1800, enable_persistence=False)

        assert cache.max_templates == 50
        assert cache.max_size_mb == 25
        assert cache.ttl_seconds == 1800
        assert not cache.enable_persistence
        assert cache.hits == 0
        assert cache.misses == 0

    def test_cache_miss_then_hit(self, tmp_path):
        """Test cache miss followed by cache hit"""
        cache = TemplateCache(enable_persistence=False)

        # Create test template
        template_file = tmp_path / "test_template.py"
        template_file.write_text("# Test template content\nclass TestNode:\n    pass\n")

        # First access - cache miss
        content1, hit1 = cache.get(
            template_name="test_template",
            template_type="TEST",
            file_path=template_file,
            loader_func=lambda p: p.read_text(),
        )

        assert not hit1, "First access should be cache miss"
        assert cache.misses == 1
        assert cache.hits == 0
        assert "Test template content" in content1

        # Second access - cache hit
        content2, hit2 = cache.get(
            template_name="test_template",
            template_type="TEST",
            file_path=template_file,
            loader_func=lambda p: p.read_text(),
        )

        assert hit2, "Second access should be cache hit"
        assert cache.hits == 1
        assert cache.misses == 1
        assert content1 == content2

    def test_cache_multiple_templates(self, tmp_path):
        """Test caching multiple templates"""
        cache = TemplateCache(enable_persistence=False)

        templates = []
        for i in range(5):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\nclass Node{i}:\n    pass\n")
            templates.append(template_file)

        # Load all templates (should be misses)
        for i, template_file in enumerate(templates):
            content, hit = cache.get(
                template_name=f"template_{i}",
                template_type="TEST",
                file_path=template_file,
                loader_func=lambda p: p.read_text(),
            )
            assert not hit

        assert cache.misses == 5
        assert cache.hits == 0

        # Access all templates again (should be hits)
        for i, template_file in enumerate(templates):
            content, hit = cache.get(
                template_name=f"template_{i}",
                template_type="TEST",
                file_path=template_file,
                loader_func=lambda p: p.read_text(),
            )
            assert hit

        assert cache.hits == 5
        assert cache.misses == 5

    def test_manual_invalidation(self, tmp_path):
        """Test manual cache invalidation"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Original content\n")

        # Load and cache
        cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert cache.misses == 1

        # Verify cache hit
        _, hit = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert hit

        # Manually invalidate
        cache.invalidate("template")
        assert cache.invalidations == 1

        # Next access should be cache miss
        _, hit = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert not hit
        assert cache.misses == 2

    def test_invalidate_all(self, tmp_path):
        """Test invalidating all cached templates"""
        cache = TemplateCache(enable_persistence=False)

        # Cache multiple templates
        for i in range(3):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            cache.get(f"template_{i}", "TEST", template_file, lambda p: p.read_text())

        stats = cache.get_stats()
        assert stats["cached_templates"] == 3

        # Invalidate all
        cache.invalidate_all()
        assert cache.invalidations == 3

        stats = cache.get_stats()
        assert stats["cached_templates"] == 0


class TestContentBasedInvalidation:
    """Test content-based cache invalidation"""

    def test_file_modification_invalidates_cache(self, tmp_path):
        """Test that modifying file invalidates cache"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Original content\n")

        # Load and cache
        content1, hit1 = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert not hit1
        assert "Original content" in content1

        # Verify cache hit
        _, hit2 = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert hit2

        # Modify file
        template_file.write_text("# Modified content\n")

        # Next access should detect change and reload
        content3, hit3 = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert not hit3, "Modified file should invalidate cache"
        assert "Modified content" in content3
        assert cache.invalidations == 1

    def test_file_hash_computation(self, tmp_path):
        """Test file hash computation"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Test content\n")

        # Compute hash
        hash1 = cache._compute_file_hash(template_file)
        assert hash1
        assert len(hash1) == 64  # SHA-256 hex digest length

        # Same content = same hash
        hash2 = cache._compute_file_hash(template_file)
        assert hash1 == hash2

        # Different content = different hash
        template_file.write_text("# Different content\n")
        hash3 = cache._compute_file_hash(template_file)
        assert hash1 != hash3


class TestLRUEviction:
    """Test LRU eviction strategy"""

    def test_count_limit_eviction(self, tmp_path):
        """Test eviction based on template count limit"""
        cache = TemplateCache(max_templates=3, enable_persistence=False)

        # Add 4 templates (should evict oldest)
        for i in range(4):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            cache.get(f"template_{i}", "TEST", template_file, lambda p: p.read_text())

        stats = cache.get_stats()
        assert stats["cached_templates"] == 3, "Should have evicted 1 template"
        assert cache.evictions == 1

        # template_0 should be evicted (least recently used)
        template_0_file = tmp_path / "template_0.py"
        _, hit = cache.get("template_0", "TEST", template_0_file, lambda p: p.read_text())
        assert not hit, "Evicted template should be cache miss"

    def test_size_limit_eviction(self, tmp_path):
        """Test eviction based on size limit"""
        # Create small cache (1MB)
        cache = TemplateCache(max_size_mb=1, max_templates=100, enable_persistence=False)

        # Create large templates
        large_content = "# " + ("X" * 500_000)  # ~500KB each

        template_files = []
        for i in range(3):
            template_file = tmp_path / f"large_template_{i}.py"
            template_file.write_text(large_content)
            template_files.append(template_file)
            cache.get(f"large_template_{i}", "TEST", template_file, lambda p: p.read_text())

        # Should have evicted some templates due to size limit
        stats = cache.get_stats()
        assert cache.evictions > 0, "Should have evicted templates due to size limit"
        assert stats["total_size_mb"] <= cache.max_size_mb

    def test_lru_ordering(self, tmp_path):
        """Test that least recently used template is evicted first"""
        cache = TemplateCache(max_templates=2, enable_persistence=False)

        # Add template 0
        t0 = tmp_path / "template_0.py"
        t0.write_text("# Template 0\n")
        cache.get("template_0", "TEST", t0, lambda p: p.read_text())

        # Add template 1
        t1 = tmp_path / "template_1.py"
        t1.write_text("# Template 1\n")
        cache.get("template_1", "TEST", t1, lambda p: p.read_text())

        # Access template 0 again (makes it more recently used)
        cache.get("template_0", "TEST", t0, lambda p: p.read_text())

        # Add template 2 (should evict template_1, not template_0)
        t2 = tmp_path / "template_2.py"
        t2.write_text("# Template 2\n")
        cache.get("template_2", "TEST", t2, lambda p: p.read_text())

        assert cache.evictions == 1

        # template_0 should still be cached
        _, hit0 = cache.get("template_0", "TEST", t0, lambda p: p.read_text())
        assert hit0, "Most recently used template should not be evicted"

        # template_1 should be evicted
        _, hit1 = cache.get("template_1", "TEST", t1, lambda p: p.read_text())
        assert not hit1, "Least recently used template should be evicted"


class TestTTLExpiration:
    """Test TTL-based cache expiration"""

    def test_ttl_expiration(self, tmp_path):
        """Test that templates expire after TTL"""
        # Very short TTL for testing
        cache = TemplateCache(ttl_seconds=1, enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Test content\n")

        # Load and cache
        cache.get("template", "TEST", template_file, lambda p: p.read_text())

        # Immediate access should hit cache
        _, hit1 = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert hit1

        # Wait for TTL to expire
        time.sleep(1.5)

        # Should be expired now
        _, hit2 = cache.get("template", "TEST", template_file, lambda p: p.read_text())
        assert not hit2, "Template should expire after TTL"
        assert cache.invalidations == 1

    def test_ttl_within_limit(self, tmp_path):
        """Test that templates remain cached within TTL"""
        cache = TemplateCache(ttl_seconds=5, enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Test content\n")

        # Load and cache
        cache.get("template", "TEST", template_file, lambda p: p.read_text())

        # Multiple accesses within TTL should hit cache
        for _ in range(5):
            time.sleep(0.5)  # Total 2.5 seconds, well within 5 second TTL
            _, hit = cache.get("template", "TEST", template_file, lambda p: p.read_text())
            assert hit, "Template should remain cached within TTL"


class TestCacheWarmup:
    """Test cache warmup functionality"""

    def test_warmup_loads_all_templates(self, tmp_path):
        """Test that warmup preloads all templates"""
        cache = TemplateCache(enable_persistence=False)

        # Create standard template files
        for template_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            template_file = tmp_path / f"{template_type.lower()}_node_template.py"
            template_file.write_text(f"# {template_type} template\n")

        # Warmup cache
        cache.warmup(tmp_path, ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"])

        stats = cache.get_stats()
        assert stats["cached_templates"] == 4, "Warmup should load all 4 templates"
        assert stats["hit_rate"] == 0.0, "Initial load should all be misses"

        # Subsequent accesses should be cache hits
        template_file = tmp_path / "effect_node_template.py"
        _, hit = cache.get("EFFECT_template", "EFFECT", template_file, lambda p: p.read_text())
        assert hit, "Warmed template should be cache hit"

    def test_warmup_skips_missing_templates(self, tmp_path):
        """Test that warmup handles missing template files gracefully"""
        cache = TemplateCache(enable_persistence=False)

        # Only create EFFECT template
        effect_template = tmp_path / "effect_node_template.py"
        effect_template.write_text("# EFFECT template\n")

        # Warmup with all types (some missing)
        cache.warmup(tmp_path, ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"])

        stats = cache.get_stats()
        assert stats["cached_templates"] == 1, "Should only cache existing templates"


class TestStatistics:
    """Test cache statistics tracking"""

    def test_basic_statistics(self, tmp_path):
        """Test basic statistics collection"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Test content\n")

        # Generate some cache activity
        for _ in range(3):
            cache.get("template", "TEST", template_file, lambda p: p.read_text())

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.6667, rel=0.01)
        assert stats["cached_templates"] == 1
        assert stats["total_size_bytes"] > 0

    def test_performance_metrics(self, tmp_path):
        """Test performance metrics calculation"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# " + ("X" * 10000))  # Make it non-trivial size

        # First load (miss)
        cache.get("template", "TEST", template_file, lambda p: p.read_text())

        # Multiple hits
        for _ in range(10):
            cache.get("template", "TEST", template_file, lambda p: p.read_text())

        stats = cache.get_stats()
        assert stats["avg_uncached_load_ms"] > 0
        assert stats["avg_cached_load_ms"] >= 0
        assert stats["time_saved_ms"] >= 0
        assert stats["improvement_percent"] >= 0

    def test_detailed_statistics(self, tmp_path):
        """Test detailed statistics with per-template breakdown"""
        cache = TemplateCache(enable_persistence=False)

        # Add multiple templates
        for i in range(3):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            # Access different numbers of times
            for _ in range(i + 1):
                cache.get(f"template_{i}", "TEST", template_file, lambda p: p.read_text())

        detailed_stats = cache.get_detailed_stats()
        assert "templates" in detailed_stats
        assert len(detailed_stats["templates"]) == 3

        # Templates should be sorted by access count
        templates = detailed_stats["templates"]
        assert templates[0]["access_count"] >= templates[1]["access_count"]
        assert templates[1]["access_count"] >= templates[2]["access_count"]

    def test_capacity_usage_metrics(self, tmp_path):
        """Test capacity usage percentage calculations"""
        cache = TemplateCache(max_templates=10, max_size_mb=10, enable_persistence=False)

        # Add 3 templates
        for i in range(3):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            cache.get(f"template_{i}", "TEST", template_file, lambda p: p.read_text())

        stats = cache.get_stats()
        assert stats["capacity_usage_percent"] == 30.0  # 3/10 * 100
        assert stats["memory_usage_percent"] < 10.0  # Should be very small


class TestThreadSafety:
    """Test thread-safety of cache operations"""

    def test_concurrent_access_same_template(self, tmp_path):
        """Test concurrent access to the same template"""
        cache = TemplateCache(enable_persistence=False)

        template_file = tmp_path / "template.py"
        template_file.write_text("# Test content\n" * 100)

        def load_template():
            for _ in range(5):
                cache.get("template", "TEST", template_file, lambda p: p.read_text())

        # Run multiple threads concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(load_template) for _ in range(10)]
            for future in futures:
                future.result()

        # All operations should complete successfully
        stats = cache.get_stats()
        assert stats["cached_templates"] == 1
        assert stats["hits"] + stats["misses"] == 50  # 10 threads * 5 accesses

    def test_concurrent_access_different_templates(self, tmp_path):
        """Test concurrent access to different templates"""
        cache = TemplateCache(enable_persistence=False)

        # Create multiple templates
        templates = []
        for i in range(10):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            templates.append((i, template_file))

        def load_template(template_id, template_file):
            for _ in range(3):
                cache.get(f"template_{template_id}", "TEST", template_file, lambda p: p.read_text())

        # Load templates concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(load_template, tid, tfile) for tid, tfile in templates]
            for future in futures:
                future.result()

        stats = cache.get_stats()
        assert stats["cached_templates"] == 10
        assert stats["hits"] + stats["misses"] == 30  # 10 templates * 3 accesses


class TestPerformanceBenchmark:
    """Performance benchmark tests"""

    def test_cache_performance_improvement(self, tmp_path):
        """Test that cache provides significant performance improvement"""
        # Create realistic large template (5000 classes = ~135KB)
        # Larger size ensures I/O time dominates over cache overhead
        template_content = "# Large template\n" + ("class Node:\n    pass\n" * 5000)
        template_file = tmp_path / "template.py"
        template_file.write_text(template_content)

        def process_template(content: str) -> int:
            """Simulate template processing overhead"""
            # Count lines and classes to simulate parsing
            lines = content.count("\n")
            classes = content.count("class ")
            return lines + classes

        def uncached_load(path: Path) -> str:
            """Simulate uncached load with processing"""
            content = path.read_text()
            process_template(content)  # Add processing overhead
            return content

        # Test without cache - measure file I/O + processing
        uncached_times = []
        for _ in range(10):
            # Clear Python's string cache by creating new Path object
            test_file = Path(str(template_file))
            start = time.perf_counter()
            uncached_load(test_file)
            elapsed_ms = (time.perf_counter() - start) * 1000
            uncached_times.append(elapsed_ms)

        avg_uncached_ms = sum(uncached_times) / len(uncached_times)

        # Test with cache
        cache_enabled = TemplateCache(enable_persistence=False)

        def cached_loader(p: Path) -> str:
            """Cached loader with processing"""
            content = p.read_text()
            process_template(content)
            return content

        # First load (miss) - not measured
        cache_enabled.get("template", "TEST", template_file, cached_loader)

        # Measure subsequent cache hits
        cached_times = []
        for _ in range(10):
            start = time.perf_counter()
            cache_enabled.get("template", "TEST", template_file, cached_loader)
            elapsed_ms = (time.perf_counter() - start) * 1000
            cached_times.append(elapsed_ms)

        avg_cached_ms = sum(cached_times) / len(cached_times)

        # Calculate improvement
        improvement_pct = ((avg_uncached_ms - avg_cached_ms) / avg_uncached_ms) * 100

        print(f"\n  Template size: {len(template_content)} bytes")
        print(f"  Avg uncached: {avg_uncached_ms:.3f}ms")
        print(f"  Avg cached: {avg_cached_ms:.3f}ms")
        print(f"  Improvement: {improvement_pct:.1f}%")
        print(f"  Cache hit rate: {cache_enabled.get_stats()['hit_rate']:.1%}")

        # Cache should show measurable improvement
        # Note: Even with OS caching, avoiding file I/O should provide some benefit
        assert avg_cached_ms < avg_uncached_ms, (
            f"Cache should improve performance. " f"Uncached: {avg_uncached_ms:.3f}ms, Cached: {avg_cached_ms:.3f}ms"
        )

        # Verify cache is actually being used
        stats = cache_enabled.get_stats()
        assert stats["hits"] == 10, "Should have 10 cache hits"
        assert stats["misses"] == 1, "Should have 1 cache miss (initial load)"
        assert stats["hit_rate"] >= 0.90, "Hit rate should be ≥90%"

    def test_hit_rate_after_warmup(self, tmp_path):
        """Test that hit rate reaches target after warmup"""
        cache = TemplateCache(enable_persistence=False)

        # Create templates
        templates = []
        for i in range(4):
            template_file = tmp_path / f"template_{i}.py"
            template_file.write_text(f"# Template {i}\n")
            templates.append((f"template_{i}", "TEST", template_file))

        # Warmup
        cache.warmup(tmp_path, [f"template_{i}" for i in range(4)])

        # Simulate realistic usage (20 accesses with distribution)
        for _ in range(20):
            for name, ttype, tfile in templates:
                cache.get(name, ttype, tfile, lambda p: p.read_text())

        stats = cache.get_stats()
        print(f"\n  Hit rate after warmup: {stats['hit_rate']:.1%}")

        # After warmup, hit rate should be very high
        assert stats["hit_rate"] >= 0.80, "Hit rate should be ≥80% after warmup"


# Fixtures
@pytest.fixture
def tmp_path(tmp_path_factory):
    """Provide temporary directory for tests"""
    return tmp_path_factory.mktemp("template_cache_test")


@pytest.fixture
async def async_cleanup():
    """Cleanup fixture for async background tasks"""
    caches = []

    def register_cache(cache):
        """Register a cache for cleanup"""
        caches.append(cache)
        return cache

    yield register_cache

    # Cleanup all registered caches
    for cache in caches:
        await cache.cleanup_async(timeout=2.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
