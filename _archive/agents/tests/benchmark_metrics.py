#!/usr/bin/env python3
"""
Quick benchmark for MetricsCollector performance.

Target: >1000 events/second throughput, <100ms aggregation latency
"""

import time

from agents.lib.metrics.metrics_collector import MetricsCollector
from agents.lib.models.enum_performance_threshold import EnumPerformanceThreshold


def benchmark_metrics_collector():
    """Benchmark MetricsCollector performance."""
    collector = MetricsCollector()

    # Benchmark 1: Recording performance
    print("=== Benchmark 1: Recording 1000 stage timings ===")
    start = time.perf_counter()

    for i in range(1000):
        collector.record_stage_timing(
            stage_name=f"stage_{i % 10}",
            duration_ms=100 + (i % 50),
            target_ms=150,
            threshold=EnumPerformanceThreshold.INTELLIGENCE_GATHERING_OVERHEAD,
        )

    recording_duration = (time.perf_counter() - start) * 1000  # ms
    events_per_second = 1000 / (recording_duration / 1000)

    print(f"Recording time: {recording_duration:.2f}ms")
    print(f"Events/second: {events_per_second:.0f}")
    print(
        f"Target: >1000 events/second - {'✅ PASS' if events_per_second > 1000 else '❌ FAIL'}"
    )

    # Benchmark 2: Aggregation performance
    print("\n=== Benchmark 2: Aggregating 1000 items ===")
    start = time.perf_counter()

    summary = collector.get_summary()

    aggregation_duration = (time.perf_counter() - start) * 1000  # ms

    print(f"Aggregation time: {aggregation_duration:.2f}ms")
    print(f"Target: <100ms - {'✅ PASS' if aggregation_duration < 100 else '❌ FAIL'}")

    # Summary statistics
    print("\n=== Summary Statistics ===")
    print(f"Total timings: {summary.total_timings}")
    print(f"Total breaches: {summary.total_breaches}")
    print(f"Avg duration: {summary.avg_duration_ms:.2f}ms")
    print(f"P50 duration: {summary.p50_duration_ms:.2f}ms")
    print(f"P95 duration: {summary.p95_duration_ms:.2f}ms")
    print(f"P99 duration: {summary.p99_duration_ms:.2f}ms")
    print(f"Stage metrics: {len(summary.stage_metrics)} unique stages")
    print(f"Threshold metrics: {len(summary.threshold_metrics)} unique thresholds")


if __name__ == "__main__":
    benchmark_metrics_collector()
