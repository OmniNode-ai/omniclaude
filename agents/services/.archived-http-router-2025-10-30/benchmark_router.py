#!/usr/bin/env python3
"""
Router Service Performance Benchmark
====================================

Measures routing performance metrics:
- Average latency (target <50ms)
- P95 latency (target <100ms)
- P99 latency (target <200ms)
- Cache hit rate (target >60%)

Usage:
    python3 agents/services/benchmark_router.py
    python3 agents/services/benchmark_router.py --iterations 1000
    python3 agents/services/benchmark_router.py --url http://localhost:8070
"""

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List

# Try to import requests, fall back to urllib if not available
try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    import urllib.error
    import urllib.request


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class BenchmarkResult:
    """Results from a single routing request."""

    success: bool
    latency_ms: float
    cache_hit: bool
    agent_name: str = ""
    confidence: float = 0.0
    error: str = ""


@dataclass
class BenchmarkStats:
    """Aggregate benchmark statistics."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Latency metrics
    latencies_ms: List[float] = field(default_factory=list)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = 0.0

    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0

    # Confidence metrics
    avg_confidence: float = 0.0

    def calculate(self):
        """Calculate aggregate statistics from raw data."""
        if not self.latencies_ms:
            return

        # Latency statistics
        self.avg_latency_ms = statistics.mean(self.latencies_ms)
        self.min_latency_ms = min(self.latencies_ms)
        self.max_latency_ms = max(self.latencies_ms)

        # Percentiles
        sorted_latencies = sorted(self.latencies_ms)
        n = len(sorted_latencies)

        self.p50_latency_ms = sorted_latencies[int(n * 0.50)]
        self.p95_latency_ms = sorted_latencies[int(n * 0.95)]
        self.p99_latency_ms = sorted_latencies[int(n * 0.99)]

        # Cache statistics
        total_with_cache_info = self.cache_hits + self.cache_misses
        if total_with_cache_info > 0:
            self.cache_hit_rate = self.cache_hits / total_with_cache_info


# ============================================================================
# HTTP Client
# ============================================================================


class RouterClient:
    """Client for router service."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> bool:
        """Check if router service is healthy."""
        try:
            if REQUESTS_AVAILABLE:
                response = requests.get(f"{self.base_url}/health", timeout=5)
                return response.status_code == 200
            else:
                req = urllib.request.Request(f"{self.base_url}/health")
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status == 200
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    def route(
        self, user_request: str, context: Dict = None, max_recommendations: int = 3
    ) -> BenchmarkResult:
        """Send routing request and measure performance."""
        start = time.time()

        payload = {
            "user_request": user_request,
            "max_recommendations": max_recommendations,
        }

        if context:
            payload["context"] = context

        try:
            if REQUESTS_AVAILABLE:
                response = requests.post(
                    f"{self.base_url}/route", json=payload, timeout=10
                )

                latency_ms = (time.time() - start) * 1000

                if response.status_code != 200:
                    return BenchmarkResult(
                        success=False,
                        latency_ms=latency_ms,
                        cache_hit=False,
                        error=f"HTTP {response.status_code}",
                    )

                data = response.json()
            else:
                # Fallback to urllib
                req = urllib.request.Request(
                    f"{self.base_url}/route",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    latency_ms = (time.time() - start) * 1000

                    if response.status != 200:
                        return BenchmarkResult(
                            success=False,
                            latency_ms=latency_ms,
                            cache_hit=False,
                            error=f"HTTP {response.status}",
                        )

                    data = json.loads(response.read().decode("utf-8"))

            # Extract metrics
            recommendations = data.get("recommendations", [])
            cache_hit = data.get("cache_hit", False)

            if not recommendations:
                return BenchmarkResult(
                    success=False,
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    error="No recommendations",
                )

            top_rec = recommendations[0]

            return BenchmarkResult(
                success=True,
                latency_ms=latency_ms,
                cache_hit=cache_hit,
                agent_name=top_rec.get("agent_name", ""),
                confidence=top_rec.get("confidence", {}).get("total", 0.0),
            )

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return BenchmarkResult(
                success=False, latency_ms=latency_ms, cache_hit=False, error=str(e)
            )


# ============================================================================
# Benchmark Runner
# ============================================================================


class BenchmarkRunner:
    """Run routing benchmarks."""

    def __init__(self, client: RouterClient, verbose: bool = False):
        self.client = client
        self.verbose = verbose

    def run(self, test_queries: List[str], iterations: int = 100) -> BenchmarkStats:
        """Run benchmark with given queries."""
        stats = BenchmarkStats()

        print(f"\nRunning benchmark with {iterations} iterations...")
        print(f"Test queries: {len(test_queries)}")
        print("-" * 60)

        for i in range(iterations):
            # Use different queries to test cache behavior
            query = test_queries[i % len(test_queries)]

            result = self.client.route(query)

            stats.total_requests += 1

            if result.success:
                stats.successful_requests += 1
                stats.latencies_ms.append(result.latency_ms)

                if result.cache_hit:
                    stats.cache_hits += 1
                else:
                    stats.cache_misses += 1

                if self.verbose and i % 10 == 0:
                    print(
                        f"  [{i+1:3d}] {result.latency_ms:6.1f}ms | "
                        f"{'HIT ' if result.cache_hit else 'MISS'} | "
                        f"{result.agent_name} ({result.confidence:.2f})"
                    )
            else:
                stats.failed_requests += 1
                if self.verbose:
                    print(f"  [{i+1:3d}] FAILED: {result.error}")

        stats.calculate()
        return stats


# ============================================================================
# Results Display
# ============================================================================


def print_results(stats: BenchmarkStats, targets: Dict[str, float]):
    """Print benchmark results with target comparison."""
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)

    # Request statistics
    print("\nRequest Statistics:")
    print(f"  Total Requests:      {stats.total_requests}")
    print(
        f"  Successful:          {stats.successful_requests} ({stats.successful_requests/stats.total_requests*100:.1f}%)"
    )
    print(
        f"  Failed:              {stats.failed_requests} ({stats.failed_requests/stats.total_requests*100:.1f}%)"
    )

    # Latency statistics
    print("\nLatency Statistics:")

    def print_metric(name: str, value: float, target: float, unit: str = "ms"):
        status = "✅" if value <= target else "❌"
        print(
            f"  {name:20s} {value:6.1f}{unit}  (target: <{target:.0f}{unit}) {status}"
        )

    print_metric("Average Latency:", stats.avg_latency_ms, targets["avg_latency"])
    print_metric("P50 Latency:", stats.p50_latency_ms, targets["avg_latency"])
    print_metric("P95 Latency:", stats.p95_latency_ms, targets["p95_latency"])
    print_metric("P99 Latency:", stats.p99_latency_ms, targets["p99_latency"])
    print_metric("Max Latency:", stats.max_latency_ms, targets["p99_latency"] * 2)
    print_metric("Min Latency:", stats.min_latency_ms, 0)

    # Cache statistics
    print("\nCache Statistics:")
    status = "✅" if stats.cache_hit_rate >= targets["cache_hit_rate"] else "❌"
    print(f"  Cache Hits:          {stats.cache_hits}")
    print(f"  Cache Misses:        {stats.cache_misses}")
    print(
        f"  Cache Hit Rate:      {stats.cache_hit_rate*100:.1f}%  (target: >{targets['cache_hit_rate']*100:.0f}%) {status}"
    )

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = (
        stats.avg_latency_ms <= targets["avg_latency"]
        and stats.p95_latency_ms <= targets["p95_latency"]
        and stats.p99_latency_ms <= targets["p99_latency"]
        and stats.cache_hit_rate >= targets["cache_hit_rate"]
    )

    if all_passed:
        print("✅ All performance targets met!")
    else:
        print("❌ Some performance targets not met")

        if stats.avg_latency_ms > targets["avg_latency"]:
            print(
                f"   - Average latency too high ({stats.avg_latency_ms:.1f}ms > {targets['avg_latency']:.0f}ms)"
            )
        if stats.p95_latency_ms > targets["p95_latency"]:
            print(
                f"   - P95 latency too high ({stats.p95_latency_ms:.1f}ms > {targets['p95_latency']:.0f}ms)"
            )
        if stats.p99_latency_ms > targets["p99_latency"]:
            print(
                f"   - P99 latency too high ({stats.p99_latency_ms:.1f}ms > {targets['p99_latency']:.0f}ms)"
            )
        if stats.cache_hit_rate < targets["cache_hit_rate"]:
            print(
                f"   - Cache hit rate too low ({stats.cache_hit_rate*100:.1f}% < {targets['cache_hit_rate']*100:.0f}%)"
            )

    return all_passed


# ============================================================================
# Main
# ============================================================================


def main():
    """Main benchmark entry point."""
    parser = argparse.ArgumentParser(description="Benchmark router service performance")
    parser.add_argument(
        "--url", default="http://localhost:8070", help="Router service URL"
    )
    parser.add_argument(
        "--iterations", type=int, default=100, help="Number of iterations"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--targets", help="Custom targets JSON file")

    args = parser.parse_args()

    # Default performance targets
    targets = {
        "avg_latency": 50.0,  # ms
        "p95_latency": 100.0,  # ms
        "p99_latency": 200.0,  # ms
        "cache_hit_rate": 0.60,  # 60%
    }

    # Load custom targets if provided
    if args.targets and os.path.exists(args.targets):
        with open(args.targets) as f:
            targets.update(json.load(f))

    # Test queries (mix of similar and unique for cache testing)
    test_queries = [
        # Repeated queries (should hit cache)
        "debug this error",
        "debug this error",
        "debug this error",
        "optimize performance",
        "optimize performance",
        "design api endpoint",
        "design api endpoint",
        # Unique queries (cache miss)
        "review security configuration",
        "analyze database query performance",
        "create ci/cd pipeline",
        "refactor authentication logic",
        "implement rate limiting",
        "add logging and monitoring",
        "write unit tests for api",
        "setup kubernetes deployment",
    ]

    # Initialize client
    client = RouterClient(args.url)

    # Health check
    print(f"Checking service health at {args.url}...")
    if not client.health_check():
        print(f"❌ Service not healthy at {args.url}")
        print("   Make sure router service is running:")
        print(f"   curl {args.url}/health")
        sys.exit(1)

    print("✅ Service healthy")

    # Run benchmark
    runner = BenchmarkRunner(client, verbose=args.verbose)
    stats = runner.run(test_queries, iterations=args.iterations)

    # Print results
    all_passed = print_results(stats, targets)

    # Exit code based on results
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
