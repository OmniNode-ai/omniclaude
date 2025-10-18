"""
Demo: Performance Metrics Collector

Demonstrates comprehensive metrics collection for routing operations.
Shows how to track all 33 performance thresholds with <10ms overhead.
"""

import asyncio
import time
from metrics_collector import get_metrics_collector, MetricType, ThresholdStatus


async def demo_routing_metrics():
    """Demonstrate routing decision metrics collection."""
    print("\n" + "=" * 80)
    print("📊 Demo: Routing Decision Metrics Collection")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()

    # Simulate routing decisions
    test_cases = [
        {"latency_ms": 45, "confidence": 0.95, "agent": "agent-contract-driven-generator", "cache_hit": True},
        {"latency_ms": 78, "confidence": 0.87, "agent": "agent-debug-intelligence", "cache_hit": False},
        {
            "latency_ms": 110,  # Exceeds 100ms threshold
            "confidence": 0.65,
            "agent": "agent-api-architect",
            "cache_hit": False,
        },
        {"latency_ms": 32, "confidence": 0.92, "agent": "agent-contract-driven-generator", "cache_hit": True},
    ]

    print("Recording routing decisions...\n")

    for i, case in enumerate(test_cases, 1):
        start = time.time()

        await collector.record_routing_decision(
            latency_ms=case["latency_ms"],
            confidence_score=case["confidence"],
            agent_selected=case["agent"],
            alternatives=[
                {"agent": "agent-debug-intelligence", "confidence": 0.45},
                {"agent": "agent-api-architect", "confidence": 0.35},
            ],
            cache_hit=case["cache_hit"],
            metadata={"test_case": i},
        )

        overhead_ms = (time.time() - start) * 1000

        print(f"✓ Case {i}: {case['agent']}")
        print(f"  Latency: {case['latency_ms']}ms, Confidence: {case['confidence']:.0%}")
        print(f"  Collection overhead: {overhead_ms:.2f}ms {'✓' if overhead_ms < 10 else '⚠️'}")
        print()

    # Show statistics
    print("\n" + "=" * 80)
    print("📈 Routing Statistics")
    print("=" * 80 + "\n")

    routing_stats = collector.get_routing_statistics()
    print(f"Total decisions: {routing_stats['total_decisions']}")
    print(f"Successful routings: {routing_stats['successful_routings']}")
    print(f"Fallback routings: {routing_stats['fallback_routings']}")
    print(f"Success rate: {routing_stats['success_rate_percent']:.1f}%\n")

    cache_stats = collector.get_cache_statistics()
    print(f"Cache queries: {cache_stats['total_queries']}")
    print(f"Cache hits: {cache_stats['cache_hits']}")
    print(f"Cache hit rate: {cache_stats['hit_rate_percent']:.1f}%")
    print(f"Meets target (60%): {'✓' if cache_stats['meets_target'] else '❌'}\n")


async def demo_threshold_monitoring():
    """Demonstrate threshold monitoring for all 33 thresholds."""
    print("\n" + "=" * 80)
    print("🎯 Demo: Performance Threshold Monitoring")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()

    # Test various thresholds
    threshold_tests = [
        # Intelligence thresholds
        ("INT-001", "RAG Query", 1450, "ms"),
        ("INT-002", "Intelligence Gathering", 85, "ms"),
        ("INT-003", "Pattern Recognition", 450, "ms"),
        # Parallel execution thresholds
        ("PAR-001", "Parallel Coordination Setup", 480, "ms"),
        ("PAR-002", "Context Distribution", 175, "ms"),
        ("PAR-004", "Result Aggregation", 280, "ms"),
        # Context management thresholds
        ("CTX-001", "Context Initialization", 45, "ms"),
        ("CTX-002", "Context Preservation", 22, "ms"),
        ("CTX-003", "Context Refresh", 68, "ms"),
        # Lifecycle thresholds
        ("LCL-001", "Agent Initialization", 285, "ms"),
        ("LCL-003", "Quality Gate Execution", 185, "ms"),
    ]

    print("Recording threshold measurements...\n")

    for threshold_id, name, value, unit in threshold_tests:
        await collector.record_threshold_metric(
            threshold_id=threshold_id, measured_value=value, metadata={"test": "demo", "name": name}
        )
        print(f"✓ {threshold_id}: {name} = {value}{unit}")

    # Show violations
    print("\n" + "=" * 80)
    print("⚠️  Threshold Violations")
    print("=" * 80 + "\n")

    violations = await collector.get_recent_violations(count=10, min_status=ThresholdStatus.WARNING)

    if violations:
        for v in violations:
            status_emoji = {
                ThresholdStatus.WARNING: "⚠️",
                ThresholdStatus.CRITICAL: "🔴",
                ThresholdStatus.EMERGENCY: "🚨",
            }.get(v.status, "ℹ️")

            print(f"{status_emoji} {v.threshold_id}: {v.threshold_name}")
            print(f"   Measured: {v.measured_value:.2f}, Threshold: {v.threshold_value:.2f}")
            print(f"   Violation: {v.violation_percent:.1f}%, Status: {v.status.value}")
            print()
    else:
        print("No violations detected ✓\n")


async def demo_trend_analysis():
    """Demonstrate performance trend analysis."""
    print("\n" + "=" * 80)
    print("📊 Demo: Performance Trend Analysis")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()

    # Generate baseline data (simulate historical metrics)
    print("Generating baseline data...\n")
    for i in range(150):
        # Simulate routing with stable performance
        base_latency = 50 + (i % 20)  # 50-70ms range
        await collector.record_routing_decision(
            latency_ms=base_latency,
            confidence_score=0.85,
            agent_selected="agent-contract-driven-generator",
            cache_hit=True,
        )

    # Establish baseline
    baseline = await collector.establish_baseline(MetricType.ROUTING_LATENCY)
    if baseline:
        print("✓ Baseline established:")
        print(f"  Mean: {baseline.baseline_mean:.2f}ms")
        print(f"  Median: {baseline.baseline_median:.2f}ms")
        print(f"  P95: {baseline.baseline_p95:.2f}ms")
        print(f"  P99: {baseline.baseline_p99:.2f}ms")
        print(f"  Samples: {baseline.sample_count}\n")

    # Simulate performance degradation
    print("Simulating performance degradation...\n")
    for i in range(50):
        # Gradually increase latency
        degraded_latency = 70 + (i * 0.5)  # 70-95ms range
        await collector.record_routing_decision(
            latency_ms=degraded_latency,
            confidence_score=0.80,
            agent_selected="agent-contract-driven-generator",
            cache_hit=False,
        )

    # Analyze trends
    trend = await collector.analyze_trends(MetricType.ROUTING_LATENCY)
    if trend:
        print("✓ Trend analysis complete:")
        print(f"  Current mean: {trend.current_mean:.2f}ms")
        print(f"  Baseline mean: {trend.baseline_mean:.2f}ms")
        print(f"  Degradation: {trend.degradation_percent:.1f}%")
        print(f"  Trend: {trend.trend_direction}")
        print(f"  Confidence: {trend.confidence:.2%}\n")

        if trend.recommendations:
            print("  Recommendations:")
            for rec in trend.recommendations:
                print(f"    • {rec}")
            print()


async def demo_agent_transformation():
    """Demonstrate agent transformation metrics."""
    print("\n" + "=" * 80)
    print("🔄 Demo: Agent Transformation Tracking")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()

    # Simulate transformations
    transformations = [
        ("workflow-coordinator", "agent-contract-driven-generator", 35, True),
        ("workflow-coordinator", "agent-debug-intelligence", 42, True),
        ("workflow-coordinator", "agent-api-architect", 55, False),  # Exceeds 50ms
        ("workflow-coordinator", "agent-contract-driven-generator", 28, True),
    ]

    print("Recording agent transformations...\n")

    for from_agent, to_agent, time_ms, success in transformations:
        await collector.record_agent_transformation(
            from_agent=from_agent,
            to_agent=to_agent,
            transformation_time_ms=time_ms,
            success=success,
            metadata={"test": "demo"},
        )

        status = "✓" if success else "❌"
        target = "✓" if time_ms < 50 else "⚠️"
        print(f"{status} {from_agent} → {to_agent}: {time_ms}ms {target}")

    print("\n" + "=" * 80)
    print("Transformation Statistics")
    print("=" * 80 + "\n")

    stats = collector.get_transformation_statistics()
    print(f"Total transformations: {stats['total_transformations']}")
    print(f"Successful: {stats['successful_transformations']}")
    print(f"Failed: {stats['failed_transformations']}")
    print(f"Success rate: {stats['success_rate_percent']:.1f}%\n")


async def demo_optimization_report():
    """Generate comprehensive optimization report."""
    print("\n" + "=" * 80)
    print("📋 Demo: Optimization Report Generation")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()

    print("Generating optimization report...\n")

    start = time.time()
    report = await collector.generate_optimization_report()
    generation_time = (time.time() - start) * 1000

    print(f"✓ Report generated in {generation_time:.2f}ms\n")

    print("=" * 80)
    print("Cache Performance")
    print("=" * 80)
    cache = report["cache_statistics"]
    print(f"Hit rate: {cache['hit_rate_percent']:.1f}% (target: {cache['target_hit_rate_percent']}%)")
    print(f"Queries: {cache['total_queries']}, Hits: {cache['cache_hits']}, Misses: {cache['cache_misses']}\n")

    print("=" * 80)
    print("Routing Performance")
    print("=" * 80)
    routing = report["routing_statistics"]
    print(f"Total decisions: {routing['total_decisions']}")
    print(f"Success rate: {routing['success_rate_percent']:.1f}%\n")

    if report["recent_violations"]:
        print("=" * 80)
        print("Recent Violations")
        print("=" * 80)
        for v in report["recent_violations"][:5]:
            print(f"• {v['threshold_name']}: {v['measured_value']:.2f} ({v['violation_percent']:.1f}%)")
        print()

    if report["optimization_recommendations"]:
        print("=" * 80)
        print("Optimization Recommendations")
        print("=" * 80)
        for i, rec in enumerate(report["optimization_recommendations"][:5], 1):
            print(f"{i}. {rec}")
        print()


async def main():
    """Run all demos."""
    print("\n" + "🚀 " + "=" * 78)
    print("RouterMetricsCollector Demo Suite")
    print("=" * 80 + "\n")

    # Run demos
    await demo_routing_metrics()
    await demo_threshold_monitoring()
    await demo_agent_transformation()
    await demo_trend_analysis()
    await demo_optimization_report()

    # Flush to file
    print("\n" + "=" * 80)
    print("💾 Flushing Metrics to File")
    print("=" * 80 + "\n")

    collector = get_metrics_collector()
    await collector.flush_to_file()
    print(f"✓ Metrics flushed to {collector.metrics_dir}\n")

    print("=" * 80)
    print("✓ Demo Complete")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
