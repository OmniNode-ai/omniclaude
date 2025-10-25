#!/usr/bin/env python3
"""
Performance Benchmark for Template Cache (Agent Framework)

Measures:
- Template load time improvement (target: 50% reduction)
- Cache hit rate (target: ≥80% after warmup)
- Memory usage
- Concurrent access performance

Setup:
    Run with pytest from project root:

        cd /path/to/omniclaude
        pytest agents/tests/benchmark_template_cache.py -v

    Or use PYTHONPATH:

        PYTHONPATH=/path/to/omniclaude python agents/tests/benchmark_template_cache.py
"""

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.lib.template_cache import TemplateCache

# Try to import template engine, but make it optional
try:
    from agents.lib.omninode_template_engine import OmniNodeTemplateEngine

    HAS_TEMPLATE_ENGINE = True
except ImportError:
    HAS_TEMPLATE_ENGINE = False


def benchmark_uncached_loads(templates_dir: Path, iterations: int = 100):
    """Benchmark template loading without cache"""
    print("\n" + "=" * 70)
    print("BENCHMARK 1: Uncached Template Loading")
    print("=" * 70)

    template_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
    load_times = []

    for i in range(iterations):
        for template_type in template_types:
            template_path = templates_dir / f"{template_type.lower()}_node_template.py"

            if template_path.exists():
                start = time.perf_counter()
                template_path.read_text(encoding="utf-8")
                elapsed_ms = (time.perf_counter() - start) * 1000
                load_times.append(elapsed_ms)

    avg_time = statistics.mean(load_times)
    median_time = statistics.median(load_times)
    p95_time = statistics.quantiles(load_times, n=20)[18]  # 95th percentile
    total_time = sum(load_times)

    print(f"  Iterations: {iterations}")
    print(f"  Total loads: {len(load_times)}")
    print(f"  Average load time: {avg_time:.3f}ms")
    print(f"  Median load time: {median_time:.3f}ms")
    print(f"  P95 load time: {p95_time:.3f}ms")
    print(f"  Total time: {total_time:.2f}ms")

    return {
        "avg_ms": avg_time,
        "median_ms": median_time,
        "p95_ms": p95_time,
        "total_ms": total_time,
        "count": len(load_times),
    }


def benchmark_cached_loads(templates_dir: Path, iterations: int = 100):
    """Benchmark template loading with cache"""
    print("\n" + "=" * 70)
    print("BENCHMARK 2: Cached Template Loading")
    print("=" * 70)

    cache = TemplateCache(enable_persistence=False)
    template_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

    # Warmup cache
    print("\n  Warming up cache...")
    cache.warmup(templates_dir, template_types)
    warmup_stats = cache.get_stats()
    print(f"  Cached templates: {warmup_stats['cached_templates']}")
    print(f"  Total size: {warmup_stats['total_size_mb']:.2f}MB")

    # Benchmark cached loads
    print("\n  Benchmarking cached loads...")
    load_times = []

    for i in range(iterations):
        for template_type in template_types:
            template_path = templates_dir / f"{template_type.lower()}_node_template.py"

            if template_path.exists():
                start = time.perf_counter()
                content, hit = cache.get(
                    template_name=f"{template_type}_template",
                    template_type=template_type,
                    file_path=template_path,
                    loader_func=lambda p: p.read_text(encoding="utf-8"),
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                load_times.append(elapsed_ms)

    stats = cache.get_stats()
    avg_time = statistics.mean(load_times)
    median_time = statistics.median(load_times)
    p95_time = statistics.quantiles(load_times, n=20)[18]
    total_time = sum(load_times)

    print(f"\n  Iterations: {iterations}")
    print(f"  Total loads: {len(load_times)}")
    print(f"  Cache hits: {stats['hits']}")
    print(f"  Cache misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")
    print(f"  Average load time: {avg_time:.3f}ms")
    print(f"  Median load time: {median_time:.3f}ms")
    print(f"  P95 load time: {p95_time:.3f}ms")
    print(f"  Total time: {total_time:.2f}ms")

    return {
        "avg_ms": avg_time,
        "median_ms": median_time,
        "p95_ms": p95_time,
        "total_ms": total_time,
        "count": len(load_times),
        "hit_rate": stats["hit_rate"],
        "hits": stats["hits"],
        "misses": stats["misses"],
    }


def benchmark_concurrent_loads(
    templates_dir: Path, num_threads: int = 10, iterations_per_thread: int = 10
):
    """Benchmark concurrent template loading"""
    print("\n" + "=" * 70)
    print("BENCHMARK 3: Concurrent Cached Loading")
    print("=" * 70)

    cache = TemplateCache(enable_persistence=False)
    template_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

    # Warmup
    cache.warmup(templates_dir, template_types)

    def worker_task(worker_id: int):
        """Worker task for concurrent loading"""
        for _ in range(iterations_per_thread):
            for template_type in template_types:
                template_path = (
                    templates_dir / f"{template_type.lower()}_node_template.py"
                )
                if template_path.exists():
                    cache.get(
                        template_name=f"{template_type}_template",
                        template_type=template_type,
                        file_path=template_path,
                        loader_func=lambda p: p.read_text(encoding="utf-8"),
                    )

    print(f"\n  Threads: {num_threads}")
    print(f"  Iterations per thread: {iterations_per_thread}")
    print(
        f"  Expected total loads: {num_threads * iterations_per_thread * len(template_types)}"
    )

    start_time = time.perf_counter()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_task, i) for i in range(num_threads)]
        for future in futures:
            future.result()

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    stats = cache.get_stats()

    print(f"\n  Total time: {elapsed_ms:.2f}ms")
    print(f"  Cache hits: {stats['hits']}")
    print(f"  Cache misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")
    print(
        f"  Throughput: {(stats['hits'] + stats['misses']) / (elapsed_ms / 1000):.0f} loads/sec"
    )

    return {
        "total_ms": elapsed_ms,
        "hit_rate": stats["hit_rate"],
        "throughput": (stats["hits"] + stats["misses"]) / (elapsed_ms / 1000),
    }


def benchmark_template_engine_integration(templates_dir: Path):
    """Benchmark OmniNodeTemplateEngine with caching"""
    if not HAS_TEMPLATE_ENGINE:
        print("\n" + "=" * 70)
        print("BENCHMARK 4: OmniNodeTemplateEngine Integration")
        print("=" * 70)
        print("\n  ⚠️  Skipped (omnibase_core not available)")
        return None

    print("\n" + "=" * 70)
    print("BENCHMARK 4: OmniNodeTemplateEngine Integration")
    print("=" * 70)

    # Test without cache
    print("\n  Testing WITHOUT cache...")
    start = time.perf_counter()
    OmniNodeTemplateEngine(enable_cache=False)
    init_time_no_cache = (time.perf_counter() - start) * 1000
    print(f"  Initialization time: {init_time_no_cache:.2f}ms")

    # Test with cache
    print("\n  Testing WITH cache...")
    start = time.perf_counter()
    engine_with_cache = OmniNodeTemplateEngine(enable_cache=True)
    init_time_with_cache = (time.perf_counter() - start) * 1000
    print(f"  Initialization time: {init_time_with_cache:.2f}ms")

    # Get cache stats
    cache_stats = engine_with_cache.get_cache_stats()
    if cache_stats:
        print("\n  Cache statistics:")
        print(f"    Cached templates: {cache_stats['cached_templates']}")
        print(f"    Hit rate: {cache_stats['hit_rate']:.1%}")
        print(f"    Total size: {cache_stats['total_size_mb']:.2f}MB")

    return {
        "init_time_no_cache_ms": init_time_no_cache,
        "init_time_with_cache_ms": init_time_with_cache,
        "cache_stats": cache_stats,
    }


def print_summary(uncached_results, cached_results):
    """Print performance summary"""
    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)

    # Calculate improvements
    avg_improvement_pct = (
        (uncached_results["avg_ms"] - cached_results["avg_ms"])
        / uncached_results["avg_ms"]
    ) * 100
    median_improvement_pct = (
        (uncached_results["median_ms"] - cached_results["median_ms"])
        / uncached_results["median_ms"]
    ) * 100
    total_time_improvement_pct = (
        (uncached_results["total_ms"] - cached_results["total_ms"])
        / uncached_results["total_ms"]
    ) * 100

    print("\n  Average Load Time:")
    print(f"    Uncached: {uncached_results['avg_ms']:.3f}ms")
    print(f"    Cached:   {cached_results['avg_ms']:.3f}ms")
    print(f"    Improvement: {avg_improvement_pct:.1f}%")

    print("\n  Median Load Time:")
    print(f"    Uncached: {uncached_results['median_ms']:.3f}ms")
    print(f"    Cached:   {cached_results['median_ms']:.3f}ms")
    print(f"    Improvement: {median_improvement_pct:.1f}%")

    print(f"\n  Total Time ({uncached_results['count']} loads):")
    print(f"    Uncached: {uncached_results['total_ms']:.2f}ms")
    print(f"    Cached:   {cached_results['total_ms']:.2f}ms")
    print(f"    Improvement: {total_time_improvement_pct:.1f}%")
    print(
        f"    Time saved: {uncached_results['total_ms'] - cached_results['total_ms']:.2f}ms"
    )

    print(f"\n  Cache Hit Rate: {cached_results['hit_rate']:.1%}")

    # Check targets
    print("\n  Target Achievement:")
    target_improvement = 50.0
    target_hit_rate = 0.80

    improvement_met = avg_improvement_pct >= target_improvement
    hit_rate_met = cached_results["hit_rate"] >= target_hit_rate

    print(
        f"    ✓ Load time reduction ≥50%: {'✓ PASS' if improvement_met else '✗ FAIL'} ({avg_improvement_pct:.1f}%)"
    )
    print(
        f"    ✓ Hit rate ≥80%: {'✓ PASS' if hit_rate_met else '✗ FAIL'} ({cached_results['hit_rate']:.1%})"
    )

    if improvement_met and hit_rate_met:
        print("\n  🎉 ALL TARGETS MET!")
    else:
        print("\n  ⚠️  Some targets not met (may vary due to test environment)")

    return {
        "improvement_pct": avg_improvement_pct,
        "hit_rate": cached_results["hit_rate"],
        "targets_met": improvement_met and hit_rate_met,
    }


def main():
    """Run all benchmarks"""
    print("\n" + "=" * 70)
    print("TEMPLATE CACHE PERFORMANCE BENCHMARK")
    print("Agent Framework: Template Caching System")
    print("=" * 70)

    # Find templates directory
    templates_dir = Path(__file__).parent.parent / "templates"
    if not templates_dir.exists():
        print(f"\n❌ Templates directory not found: {templates_dir}")
        return 1

    print(f"\nTemplates directory: {templates_dir}")

    # Count templates
    template_files = list(templates_dir.glob("*_node_template.py"))
    print(f"Templates found: {len(template_files)}")
    for template_file in template_files:
        size_kb = template_file.stat().st_size / 1024
        print(f"  - {template_file.name} ({size_kb:.1f}KB)")

    # Run benchmarks
    iterations = 100

    uncached_results = benchmark_uncached_loads(templates_dir, iterations=iterations)
    cached_results = benchmark_cached_loads(templates_dir, iterations=iterations)
    benchmark_concurrent_loads(templates_dir, num_threads=10, iterations_per_thread=10)
    benchmark_template_engine_integration(templates_dir)

    # Print summary
    summary = print_summary(uncached_results, cached_results)

    print("\n" + "=" * 70)
    print("Benchmark complete!")
    print("=" * 70 + "\n")

    return 0 if summary["targets_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
