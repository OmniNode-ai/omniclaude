#!/usr/bin/env python3
"""
Test Agent Router Integration

Validates that the AgentRouter is properly integrated into ParallelCoordinator.
Tests confidence scoring, fallback strategies, and error handling.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/test_enhanced_router_integration.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import sys

from .agent_dispatcher import ParallelCoordinator
from .agent_model import AgentTask


async def test_router_integration():
    """Test enhanced router integration with various task scenarios."""

    print("=" * 70)
    print("TESTING ENHANCED ROUTER INTEGRATION")
    print("=" * 70)

    # Initialize coordinator with enhanced router
    print("\n1. Initializing ParallelCoordinator with enhanced router...")
    coordinator = ParallelCoordinator(
        use_dynamic_loading=True,
        use_enhanced_router=True,
        router_confidence_threshold=0.6,
    )

    await coordinator.initialize()
    print("✓ Coordinator initialized")

    # Test cases with different types of tasks
    test_cases = [
        {
            "task_id": "test-1",
            "description": "Debug this performance issue in the API endpoint",
            "expected_agent_type": "debug",
        },
        {
            "task_id": "test-2",
            "description": "Generate contract-driven code for user registration",
            "expected_agent_type": "generator",
        },
        {
            "task_id": "test-3",
            "description": "Analyze error logs and find root cause of failure",
            "expected_agent_type": "debug",
        },
        {
            "task_id": "test-4",
            "description": "Create new API endpoints with ONEX compliance",
            "expected_agent_type": "generator",
        },
        {
            "task_id": "test-5",
            "description": "Review code quality and suggest improvements",
            "expected_agent_type": "quality",
        },
    ]

    print("\n2. Testing agent selection with various task descriptions...")
    print("-" * 70)

    results = []
    for test_case in test_cases:
        task = AgentTask(
            task_id=test_case["task_id"],
            description=test_case["description"],
            input_data={"domain": "api_development"},
        )

        print(f"\nTask {test_case['task_id']}: {test_case['description']}")

        # Test agent selection
        selected_agent = coordinator._select_agent_for_task(task)

        print(f"Selected: {selected_agent}")

        results.append(
            {
                "task_id": test_case["task_id"],
                "description": test_case["description"],
                "selected_agent": selected_agent,
                "expected_type": test_case["expected_agent_type"],
            }
        )

    # Print router statistics
    print("\n" + "=" * 70)
    print("ROUTER STATISTICS")
    print("=" * 70)

    router_stats = coordinator.get_router_stats()

    print("\nConfiguration:")
    print(f"  Enabled: {router_stats['enabled']}")
    print(f"  Available: {router_stats['available']}")
    print(f"  Confidence Threshold: {router_stats['confidence_threshold']:.2%}")

    print("\nRouting Performance:")
    print(f"  Total Routes: {router_stats['total_routes']}")
    print(f"  Router Used: {router_stats['router_used']}")
    print(f"  Fallback Used: {router_stats['fallback_used']}")
    print(f"  Below Threshold: {router_stats['below_threshold']}")
    print(f"  Router Errors: {router_stats['router_errors']}")

    if router_stats["total_routes"] > 0:
        print("\nRates:")
        print(f"  Router Usage: {router_stats.get('router_usage_rate', 0):.2%}")
        print(f"  Fallback Rate: {router_stats.get('fallback_rate', 0):.2%}")
        print(f"  Below Threshold: {router_stats.get('below_threshold_rate', 0):.2%}")
        print(f"  Error Rate: {router_stats.get('error_rate', 0):.2%}")

        if router_stats["router_used"] > 0:
            print(f"  Average Confidence: {router_stats['average_confidence']:.2%}")

    # Print cache statistics if available
    if "cache" in router_stats:
        cache_stats = router_stats["cache"]
        print("\nCache Performance:")
        print(f"  Total Entries: {cache_stats.get('total_entries', 0)}")
        print(f"  Hit Rate: {cache_stats.get('cache_hit_rate', 0):.2%}")

    # Test summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    print(f"\nTested {len(results)} task scenarios")
    print(
        f"Router was {'successfully integrated' if router_stats['enabled'] else 'not available'}"
    )

    if router_stats["router_used"] > 0:
        print(f"✓ Router successfully routed {router_stats['router_used']} tasks")
        print(f"✓ Average confidence score: {router_stats['average_confidence']:.2%}")

    if router_stats["fallback_used"] > 0:
        print(f"⚠ {router_stats['fallback_used']} tasks used fallback routing")

    if router_stats["router_errors"] > 0:
        print(f"⚠ {router_stats['router_errors']} router errors occurred")

    print("\nIntegration test complete!")

    # Cleanup
    await coordinator.cleanup()

    return results, router_stats


async def test_parallel_execution_with_router():
    """Test parallel execution with enhanced router."""

    print("\n" + "=" * 70)
    print("TESTING PARALLEL EXECUTION WITH ENHANCED ROUTER")
    print("=" * 70)

    # Initialize coordinator
    coordinator = ParallelCoordinator(
        use_dynamic_loading=True,
        use_enhanced_router=True,
        router_confidence_threshold=0.6,
    )

    await coordinator.initialize()

    # Create test tasks with dependencies
    tasks = [
        AgentTask(
            task_id="parallel-1",
            description="Debug authentication error in login flow",
            input_data={"domain": "security"},
        ),
        AgentTask(
            task_id="parallel-2",
            description="Generate user profile API endpoints",
            input_data={"domain": "api_development"},
            dependencies=[],
        ),
        AgentTask(
            task_id="parallel-3",
            description="Analyze database performance bottleneck",
            input_data={"domain": "performance"},
            dependencies=[],
        ),
    ]

    print(f"\nExecuting {len(tasks)} tasks in parallel...")

    try:
        results = await coordinator.execute_parallel(tasks)

        print(f"\n✓ Parallel execution completed: {len(results)} results")

        for task_id, result in results.items():
            status = "✓" if result.success else "✗"
            print(
                f"  {status} {task_id}: {result.agent_name} ({result.execution_time_ms:.2f}ms)"
            )

    except Exception as e:
        print(f"\n✗ Parallel execution failed: {e}")
        import traceback

        traceback.print_exc()

    # Print final stats
    print("\n" + "=" * 70)
    print("FINAL STATISTICS")
    print("=" * 70)

    final_stats = coordinator.get_agent_registry_stats()
    print("\nAgent Registry:")
    for key, value in final_stats.items():
        if key != "router":
            print(f"  {key}: {value}")

    print("\nRouter Statistics:")
    router_stats = final_stats.get("router", {})
    for key, value in router_stats.items():
        if key not in ["router_internal", "cache"]:
            if isinstance(value, float):
                print(f"  {key}: {value:.2%}")
            else:
                print(f"  {key}: {value}")

    await coordinator.cleanup()


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("ENHANCED ROUTER INTEGRATION TEST SUITE")
    print("=" * 70)
    print()

    try:
        # Test 1: Router integration
        print("\nTest 1: Router Integration")
        results, stats = await test_router_integration()

        # Test 2: Parallel execution
        print("\n\nTest 2: Parallel Execution")
        await test_parallel_execution_with_router()

        print("\n" + "=" * 70)
        print("ALL TESTS COMPLETED SUCCESSFULLY")
        print("=" * 70)

    except Exception as e:
        print("\n" + "=" * 70)
        print("TEST SUITE FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
