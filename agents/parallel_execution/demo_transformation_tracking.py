"""
Demo: Agent Transformation Tracking Integration

Demonstrates how to use AgentTransformationTracker to track agent identity
transformations with the enhanced router and workflow coordinator.

Example workflow:
1. User request triggers routing decision
2. Enhanced router selects target agent
3. Workflow coordinator transforms identity
4. Transformation is tracked with full context
5. Metrics and patterns analyzed
"""

import asyncio

from transformation_tracker import get_transformation_tracker
from trace_logger import get_trace_logger


async def demo_basic_transformation():
    """Demonstrate basic transformation tracking."""
    print("\n" + "=" * 80)
    print("DEMO 1: Basic Transformation Tracking")
    print("=" * 80 + "\n")

    tracker = get_transformation_tracker()

    # Simulate a transformation event
    event = await tracker.track_transformation(
        source_identity="agent-workflow-coordinator",
        target_identity="agent-debug-intelligence",
        user_request="Analyze performance bottleneck in API endpoint",
        transformation_reason="Debug intelligence required for performance analysis",
        capabilities_inherited=[
            "systematic_debugging",
            "performance_profiling",
            "root_cause_analysis",
            "hypothesis_testing",
        ],
        context_preserved={
            "domain": "api_development",
            "previous_findings": ["slow database queries", "N+1 problem"],
            "project_context": "REST API performance optimization",
        },
        routing_confidence=0.92,
        task_id="task-123",
        agent_definition_path="/Users/jonah/.claude/agents/configs/agent-debug-intelligence.yaml",
    )

    print(f"✅ Transformation tracked: {event.transformation_id}")
    print(f"   Source: {event.source_identity}")
    print(f"   Target: {event.target_identity}")
    print(f"   Overhead: {event.transformation_overhead_ms:.2f}ms")
    print(f"   Confidence: {event.routing_confidence:.2%}")
    print(f"   Capabilities: {len(event.capabilities_inherited)} inherited")


async def demo_multiple_transformations():
    """Demonstrate tracking multiple transformations to build patterns."""
    print("\n" + "=" * 80)
    print("DEMO 2: Multiple Transformations & Pattern Recognition")
    print("=" * 80 + "\n")

    tracker = get_transformation_tracker()

    # Simulate multiple transformation scenarios
    transformations = [
        ("agent-workflow-coordinator", "agent-debug-intelligence", "Debug memory leak", 0.89, 15.3),
        ("agent-workflow-coordinator", "agent-api-architect", "Design REST API endpoints", 0.95, 12.7),
        ("agent-workflow-coordinator", "agent-debug-intelligence", "Analyze race condition", 0.87, 14.9),
        ("agent-workflow-coordinator", "agent-api-architect", "Review API security", 0.91, 13.2),
        ("agent-workflow-coordinator", "agent-debug-intelligence", "Investigate performance issue", 0.93, 16.1),
        ("agent-api-architect", "agent-security-analyzer", "Security audit", 0.88, 18.5),
    ]

    for source, target, request, confidence, load_time in transformations:
        await tracker.track_transformation_with_timing(
            source_identity=source,
            target_identity=target,
            user_request=request,
            transformation_reason=f"Specialized {target.split('-')[-1]} required",
            agent_load_time_ms=load_time,
            routing_confidence=confidence,
            capabilities_inherited=[f"{target}_capability_1", f"{target}_capability_2"],
        )
        await asyncio.sleep(0.1)  # Simulate time between transformations

    print(f"✅ Tracked {len(transformations)} transformations")

    # Analyze patterns
    patterns = await tracker.analyze_patterns(min_occurrences=2)
    print(f"\n📊 Identified {len(patterns)} transformation patterns:")
    for pattern in patterns:
        print(f"\n   Pattern: {pattern.source_target_pair[0]} → {pattern.source_target_pair[1]}")
        print(f"   Occurrences: {pattern.occurrence_count}")
        print(f"   Avg Time: {pattern.avg_transformation_time_ms:.2f}ms")
        print(f"   Avg Confidence: {pattern.avg_confidence_score:.2%}")
        print(f"   Success Rate: {pattern.success_rate:.2%}")


async def demo_performance_monitoring():
    """Demonstrate performance threshold monitoring."""
    print("\n" + "=" * 80)
    print("DEMO 3: Performance Threshold Monitoring")
    print("=" * 80 + "\n")

    tracker = get_transformation_tracker()

    # Create some transformations with varying performance
    fast_transformations = [
        ("agent-workflow-coordinator", "agent-coder", "Implement function", 0.94, 8.5),
        ("agent-workflow-coordinator", "agent-coder", "Fix bug", 0.91, 9.2),
    ]

    slow_transformations = [
        (
            "agent-workflow-coordinator",
            "agent-onex-generator",
            "Generate ONEX architecture",
            0.87,
            65.3,
        ),  # Over 50ms threshold
        (
            "agent-workflow-coordinator",
            "agent-onex-generator",
            "Create node structure",
            0.89,
            72.1,
        ),  # Over 50ms threshold
    ]

    print("Tracking fast transformations (under threshold)...")
    for source, target, request, confidence, load_time in fast_transformations:
        await tracker.track_transformation_with_timing(
            source_identity=source,
            target_identity=target,
            user_request=request,
            transformation_reason=f"Quick {target} operation",
            agent_load_time_ms=load_time,
            routing_confidence=confidence,
        )

    print("Tracking slow transformations (over threshold)...")
    for source, target, request, confidence, load_time in slow_transformations:
        await tracker.track_transformation_with_timing(
            source_identity=source,
            target_identity=target,
            user_request=request,
            transformation_reason=f"Complex {target} operation",
            agent_load_time_ms=load_time,
            routing_confidence=confidence,
        )

    # Get metrics
    metrics = await tracker.get_metrics()
    print("\n📈 Performance Analysis:")
    print(f"   Total Transformations: {metrics.total_transformations}")
    print(f"   Under Threshold (<50ms): {metrics.transformations_under_threshold}")
    print(f"   Over Threshold (≥50ms): {metrics.transformations_over_threshold}")
    print(f"   Threshold Compliance: {metrics.threshold_compliance_rate:.2%}")

    if metrics.transformations_over_threshold > 0:
        print(
            f"\n   ⚠️  Warning: {metrics.transformations_over_threshold} transformations "
            f"exceeded the 50ms threshold!"
        )
        print(f"   Consider optimizing agent loading for: {metrics.most_common_target}")


async def demo_metrics_dashboard():
    """Demonstrate comprehensive metrics for dashboard."""
    print("\n" + "=" * 80)
    print("DEMO 4: Dashboard Metrics Generation")
    print("=" * 80 + "\n")

    tracker = get_transformation_tracker()

    # The tracker should have accumulated events from previous demos
    await tracker.print_metrics_summary()

    # Show transformation history
    print(f"\n{'='*80}")
    print("Recent Transformation History:")
    print(f"{'='*80}")

    history = await tracker.get_transformation_history(limit=5)
    for i, event in enumerate(history, 1):
        print(f"\n{i}. {event.source_identity} → {event.target_identity}")
        print(f"   Request: {event.user_request[:60]}...")
        print(f"   Time: {event.datetime_str}")
        print(f"   Overhead: {event.transformation_overhead_ms:.2f}ms")
        print(f"   Confidence: {event.routing_confidence:.2%}" if event.routing_confidence else "   Confidence: N/A")


async def demo_integration_with_trace_logger():
    """Demonstrate integration with TraceLogger."""
    print("\n" + "=" * 80)
    print("DEMO 5: TraceLogger Integration")
    print("=" * 80 + "\n")

    trace_logger = get_trace_logger()
    tracker = get_transformation_tracker()

    # Start a coordinator trace
    trace_id = await trace_logger.start_coordinator_trace(coordinator_type="hybrid", total_agents=3)
    print(f"Started coordinator trace: {trace_id}")

    # Track transformation (will automatically log to TraceLogger)
    event = await tracker.track_transformation(
        source_identity="agent-workflow-coordinator",
        target_identity="agent-test-generator",
        user_request="Generate comprehensive test suite",
        transformation_reason="Test generation specialist required",
        capabilities_inherited=["test_generation", "coverage_analysis"],
        routing_confidence=0.91,
        task_id="task-456",
    )

    print("\n✅ Transformation logged to both systems:")
    print(f"   Transformation ID: {event.transformation_id}")
    print(f"   Coordinator Trace ID: {trace_id}")
    print("   Event written to: traces/transformations/")
    print("   Also logged to: TraceLogger AGENT_TRANSFORM event")

    # End coordinator trace
    await trace_logger.end_coordinator_trace(trace_id)


async def demo_transformation_stats():
    """Show tracker statistics."""
    print("\n" + "=" * 80)
    print("DEMO 6: Tracker Statistics")
    print("=" * 80 + "\n")

    tracker = get_transformation_tracker()
    stats = tracker.get_stats()

    print("📊 Tracker Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")


async def main():
    """Run all demos."""
    print("\n" + "🔄" * 40)
    print("Agent Transformation Tracking - Comprehensive Demo")
    print("🔄" * 40)

    try:
        await demo_basic_transformation()
        await asyncio.sleep(0.5)

        await demo_multiple_transformations()
        await asyncio.sleep(0.5)

        await demo_performance_monitoring()
        await asyncio.sleep(0.5)

        await demo_metrics_dashboard()
        await asyncio.sleep(0.5)

        await demo_integration_with_trace_logger()
        await asyncio.sleep(0.5)

        await demo_transformation_stats()

        print("\n" + "=" * 80)
        print("✅ All demos completed successfully!")
        print("=" * 80 + "\n")

        print("Next steps:")
        print("  1. Check traces/transformations/ directory for event files")
        print("  2. Review transformation patterns for optimization opportunities")
        print("  3. Monitor threshold compliance in production")
        print("  4. Integrate with enhanced router for automatic tracking")
        print("  5. Add database persistence when Stream 1 is complete")

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
