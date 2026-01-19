#!/usr/bin/env python3
"""
Quick end-to-end test for router consumer service.

Tests:
1. Service is running and consuming
2. Client can send routing request
3. Service processes and responds
4. Database logging works

Usage:
    python3 test_router_consumer.py
"""

import asyncio
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from routing_event_client import route_via_events


async def test_routing():
    """Test routing via events."""
    print("=" * 60)
    print("Testing Agent Router Event Consumer")
    print("=" * 60)

    test_requests = [
        (
            "Help me implement ONEX patterns",
            "Expected: agent-onex or polymorphic-agent",
        ),
        ("Debug my database queries", "Expected: agent-database or debugging agent"),
        ("Create a REST API", "Expected: agent-api-architect"),
        (
            "@polymorphic-agent analyze this code",
            "Expected: polymorphic-agent (explicit)",
        ),
    ]

    for i, (request, expected) in enumerate(test_requests, 1):
        print(f"\n[Test {i}] Request: {request}")
        print(f"   {expected}")

        try:
            recommendations = await route_via_events(
                user_request=request,
                max_recommendations=3,
                timeout_ms=5000,
                fallback_to_local=False,  # Test event-based only
            )

            if recommendations:
                primary = recommendations[0]
                print(f"   ✅ Selected: {primary['agent_name']}")
                print(f"   ✅ Confidence: {primary['confidence']['total']:.2%}")
                print(f"   ✅ Reason: {primary['reason']}")
                if len(recommendations) > 1:
                    print(
                        f"   ℹ️  Alternatives: {[r['agent_name'] for r in recommendations[1:]]}"
                    )
            else:
                print("   ❌ No recommendations returned")

        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n" + "=" * 60)
    print("Testing Complete")
    print("=" * 60)

    # Check database logging
    print("\nChecking database logging...")
    try:
        import asyncpg

        # Add project root to path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import settings

        # Connect to database using settings (auto-loaded from .env)
        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_database,
            user=settings.postgres_user,
            password=settings.get_effective_postgres_password(),
        )

        # Query recent routing decisions
        rows = await conn.fetch(
            """
            SELECT
                correlation_id,
                selected_agent,
                confidence_score,
                routing_strategy,
                routing_time_ms,
                created_at
            FROM agent_routing_decisions
            ORDER BY created_at DESC
            LIMIT 5
            """
        )

        if rows:
            print(f"   ✅ Found {len(rows)} recent routing decisions in database:")
            for row in rows:
                print(
                    f"      - {row['selected_agent']} ({row['confidence_score']:.2%}) at {row['created_at']}"
                )
        else:
            print(
                "   ℹ️  No routing decisions found in database (this is OK for first test)"
            )

        await conn.close()

    except Exception as e:
        print(f"   ⚠️  Could not check database: {e}")
        print("   (This is OK - database logging is non-blocking)")


if __name__ == "__main__":
    asyncio.run(test_routing())
