"""Quick test of metrics collector - basic functionality only."""

import asyncio

from .metrics_collector import get_metrics_collector


async def main() -> None:
    """Test basic functionality of RouterMetricsCollector.

    Tests recording routing decisions, threshold metrics, and retrieving statistics.
    Prints test results to stdout.
    """
    print("Testing RouterMetricsCollector...")
    collector = get_metrics_collector()

    # Test routing decision recording
    await collector.record_routing_decision(
        latency_ms=45.0,
        confidence_score=0.95,
        agent_selected="agent-contract-driven-generator",
        alternatives=[{"agent": "agent-debug-intelligence", "confidence": 0.45}],
        cache_hit=True,
    )

    # Test threshold recording
    await collector.record_threshold_metric(
        threshold_id="INT-001", measured_value=1450.0
    )

    # Get statistics
    routing_stats = collector.get_routing_statistics()
    cache_stats = collector.get_cache_statistics()

    print("\n✓ Metrics collector working!")
    print(f"  Routing decisions: {routing_stats['total_decisions']}")
    print(f"  Cache hit rate: {cache_stats['hit_rate_percent']:.1f}%")
    print(f"  Thresholds defined: {len(collector._thresholds)}")


if __name__ == "__main__":
    asyncio.run(main())
