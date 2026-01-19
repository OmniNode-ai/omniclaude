"""Quick test of metrics collector - basic functionality only."""

import asyncio

from .metrics_collector import get_metrics_collector


async def main() -> None:
    """Quick validation test of RouterMetricsCollector functionality.

    Tests basic operations: recording routing decisions, recording threshold metrics,
    and retrieving statistics. Intended for manual validation during development.

    Returns:
        None

    Example:
        >>> await main()
        Testing RouterMetricsCollector...
        ✓ Metrics collector working!
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
    print(f"  Thresholds defined: {collector.threshold_count}")


if __name__ == "__main__":
    asyncio.run(main())
