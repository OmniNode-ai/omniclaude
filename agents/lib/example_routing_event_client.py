#!/usr/bin/env python3
"""
Example: Using Routing Event Client

This script demonstrates how to use the routing event client
to request agent routing decisions via Kafka events.

Prerequisites:
- Kafka/Redpanda running on configured bootstrap servers
- agent-router-service running (optional - will fallback to local routing)

Run:
    python3 agents/lib/example_routing_event_client.py

Created: 2025-10-30
"""

import asyncio
import sys
from pathlib import Path as PathLib


# Add agents/lib to path
sys.path.insert(0, str(PathLib(__file__).parent))

from routing_event_client import (
    RoutingEventClientContext,
    route_via_events,
)


async def example_basic():
    """Example 1: Basic routing with context manager."""
    print("\n" + "=" * 70)
    print("Example 1: Basic Routing (Context Manager)")
    print("=" * 70)

    async with RoutingEventClientContext(request_timeout_ms=5000) as client:
        recommendations = await client.request_routing(
            user_request="optimize my database queries",
            max_recommendations=3,
        )

        if recommendations:
            print(f"\n✅ Received {len(recommendations)} recommendations:\n")
            for i, rec in enumerate(recommendations, 1):
                confidence = rec["confidence"]
                print(f"{i}. {rec['agent_name']}")
                print(f"   Title: {rec['agent_title']}")
                print(f"   Confidence: {confidence['total']:.2%}")
                print(f"   Reason: {rec['reason']}")
                print(f"   Path: {rec['definition_path']}")
                print()
        else:
            print("❌ No recommendations received")


async def example_with_context():
    """Example 2: Routing with rich context."""
    print("\n" + "=" * 70)
    print("Example 2: Routing with Rich Context")
    print("=" * 70)

    async with RoutingEventClientContext(request_timeout_ms=5000) as client:
        recommendations = await client.request_routing(
            user_request="fix API performance issues",
            context={
                "domain": "api_development",
                "previous_agent": "agent-frontend-developer",
                "current_file": "api/endpoints.py",
            },
            max_recommendations=5,
            min_confidence=0.6,
        )

        if recommendations:
            print("\n✅ Context-aware routing successful:\n")
            for i, rec in enumerate(recommendations[:3], 1):
                confidence = rec["confidence"]
                print(f"{i}. {rec['agent_name']} ({confidence['total']:.2%})")
                print(f"   Trigger: {confidence['trigger_score']:.2%}")
                print(f"   Context: {confidence['context_score']:.2%}")
                print(f"   Capability: {confidence['capability_score']:.2%}")
                print(f"   Historical: {confidence['historical_score']:.2%}")
                print()


async def example_convenience_wrapper():
    """Example 3: Convenience wrapper with fallback."""
    print("\n" + "=" * 70)
    print("Example 3: Convenience Wrapper (Simplest)")
    print("=" * 70)

    recommendations = await route_via_events(
        user_request="optimize my API performance",
        context={"domain": "api_development"},
        max_recommendations=3,
        timeout_ms=5000,
        fallback_to_local=True,  # Fallback to local routing on failure
    )

    if recommendations:
        best = recommendations[0]
        print(f"\n✅ Selected agent: {best['agent_name']}")
        print(f"   Confidence: {best['confidence']['total']:.2%}")
        print(f"   Reason: {best['reason']}")
    else:
        print("❌ No recommendations received")


async def example_concurrent_requests():
    """Example 4: Multiple concurrent requests."""
    print("\n" + "=" * 70)
    print("Example 4: Concurrent Requests")
    print("=" * 70)

    async with RoutingEventClientContext(request_timeout_ms=5000) as client:
        # Send multiple requests in parallel
        tasks = [
            client.request_routing(
                user_request=f"optimize {domain}",
                context={"domain": domain},
                max_recommendations=3,
            )
            for domain in [
                "database_queries",
                "api_performance",
                "frontend_rendering",
            ]
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes
        success_count = sum(1 for r in results if isinstance(r, list))

        print(f"\n✅ Concurrent requests: {success_count}/{len(tasks)} successful\n")

        for i, (domain, result) in enumerate(
            zip(["database", "api", "frontend"], results), 1
        ):
            if isinstance(result, list) and len(result) > 0:
                best = result[0]
                print(
                    f"{i}. {domain.upper()}: {best['agent_name']} ({best['confidence']['total']:.2%})"
                )
            else:
                print(f"{i}. {domain.upper()}: Failed - {result}")


async def example_health_check():
    """Example 5: Health check before routing."""
    print("\n" + "=" * 70)
    print("Example 5: Health Check (Circuit Breaker)")
    print("=" * 70)

    async with RoutingEventClientContext(request_timeout_ms=5000) as client:
        # Check health before routing
        healthy = await client.health_check()

        if healthy:
            print("\n✅ Service healthy - using event routing")

            recommendations = await client.request_routing(
                user_request="optimize my database",
                max_recommendations=3,
            )

            if recommendations:
                print(f"✅ Received {len(recommendations)} recommendations")
        else:
            print("\n❌ Service unhealthy - would use fallback routing")


async def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("ROUTING EVENT CLIENT EXAMPLES")
    print("=" * 70)

    try:
        # Example 1: Basic routing
        await example_basic()

        # Example 2: Routing with context
        await example_with_context()

        # Example 3: Convenience wrapper
        await example_convenience_wrapper()

        # Example 4: Concurrent requests
        await example_concurrent_requests()

        # Example 5: Health check
        await example_health_check()

        print("\n" + "=" * 70)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
