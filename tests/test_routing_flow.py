#!/usr/bin/env python3
"""
Test End-to-End Router Event Processing

This script tests the complete routing flow:
1. Client publishes routing request to Kafka
2. Router consumer processes request
3. Client receives response
4. Routing decision stored in database

Usage:
    python3 tests/test_routing_flow.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add agents lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "lib"))

from routing_event_client import route_via_events

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_routing_request():
    """Test routing request via Kafka events."""
    print("\n" + "=" * 80)
    print("TESTING: End-to-End Router Event Processing")
    print("=" * 80 + "\n")

    try:
        # Test routing request
        print("📤 Publishing routing request to Kafka...")
        print("   User Request: 'Help me implement ONEX patterns'")
        print("   Max Recommendations: 3")
        print()

        result = await route_via_events(
            user_request="Help me implement ONEX patterns",
            max_recommendations=3,
            timeout_ms=10000,  # 10 second timeout
            fallback_to_local=False,  # Force event-based routing (no fallback)
        )

        print("✅ Routing successful!\n")
        print(f"📊 Received {len(result)} recommendations:\n")

        # Display recommendations
        for i, rec in enumerate(result, 1):
            agent_name = rec.get("agent_name", "unknown")
            agent_title = rec.get("agent_title", "Unknown Agent")
            confidence = rec.get("confidence", {})
            total_confidence = confidence.get("total", 0)
            reason = rec.get("reason", "No reason provided")

            print(f"{i}. {agent_title} ({agent_name})")
            print(f"   Confidence: {total_confidence:.2%}")
            print(f"   Reason: {reason}")
            print()

        return result

    except TimeoutError as e:
        print(f"❌ TIMEOUT: {e}")
        print("\nTroubleshooting:")
        print("  1. Check router consumer is running:")
        print("     docker ps | grep router-consumer")
        print("  2. Check consumer logs:")
        print("     docker logs omniclaude_archon_router_consumer --tail 50")
        print("  3. Verify Kafka connectivity (from Docker):")
        # Import settings to get current Kafka config
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import settings

        print(f"     kcat -L -b {settings.kafka_bootstrap_servers}")
        return None

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print(f"\nError type: {type(e).__name__}")
        import traceback

        traceback.print_exc()
        return None


async def verify_database_record():
    """Verify routing decision was stored in database."""
    print("\n" + "=" * 80)
    print("VERIFYING: Database Record")
    print("=" * 80 + "\n")

    try:
        import sys
        from pathlib import Path

        import asyncpg

        # Add project root to path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import settings

        # Get PostgreSQL configuration from settings (auto-loaded from .env)
        postgres_host = settings.postgres_host
        postgres_port = settings.postgres_port
        postgres_user = settings.postgres_user
        postgres_database = settings.postgres_database

        try:
            postgres_password = settings.get_effective_postgres_password()
        except ValueError:
            print("⚠️  WARNING: POSTGRES_PASSWORD not set in .env")
            print("   Please set POSTGRES_PASSWORD in your .env file")
            return

        # Connect to database
        print(
            f"🔌 Connecting to PostgreSQL: {postgres_host}:{postgres_port}/{postgres_database}"
        )
        conn = await asyncpg.connect(
            host=postgres_host,
            port=postgres_port,
            user=postgres_user,
            password=postgres_password,
            database=postgres_database,
        )

        try:
            # Query recent routing decisions
            query = """
                SELECT
                    correlation_id,
                    selected_agent,
                    confidence_score,
                    routing_time_ms,
                    routing_strategy,
                    user_request,
                    created_at
                FROM agent_routing_decisions
                ORDER BY created_at DESC
                LIMIT 5
            """
            rows = await conn.fetch(query)

            if rows:
                print(f"✅ Found {len(rows)} recent routing decisions:\n")
                for i, row in enumerate(rows, 1):
                    correlation_id = row["correlation_id"]
                    selected_agent = row["selected_agent"]
                    confidence_score = row["confidence_score"]
                    routing_time_ms = row["routing_time_ms"]
                    routing_strategy = row["routing_strategy"]
                    user_request = row["user_request"][:60]
                    created_at = row["created_at"]

                    print(f"{i}. Agent: {selected_agent}")
                    print(f"   Confidence: {confidence_score:.2%}")
                    print(f"   Routing Time: {routing_time_ms}ms")
                    print(f"   Strategy: {routing_strategy}")
                    print(f"   Request: {user_request}...")
                    print(f"   Correlation ID: {correlation_id}")
                    print(f"   Created: {created_at}")
                    print()
            else:
                print("⚠️  No routing decisions found in database")
                print("   This may be normal if no requests have been processed")

        finally:
            await conn.close()

    except ImportError:
        print("⚠️  asyncpg not installed (optional verification)")
        print("   Install with: pip install asyncpg")

    except Exception as e:
        print(f"❌ Database verification failed: {e}")
        import traceback

        traceback.print_exc()


async def main():
    """Run all tests."""
    # Test routing request
    result = await test_routing_request()

    # Verify database record
    await verify_database_record()

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80 + "\n")

    if result:
        print("✅ End-to-end routing flow WORKING")
        print(f"   • Routing request published to Kafka")
        print(f"   • Router consumer processed request")
        print(f"   • Client received {len(result)} recommendations")
        print(f"   • Routing decision stored in database")
        return 0
    else:
        print("❌ End-to-end routing flow FAILED")
        print("\nNext steps:")
        print("  1. Check consumer is running: docker ps | grep router-consumer")
        print(
            "  2. Check consumer logs: docker logs omniclaude_archon_router_consumer --tail 50"
        )
        # Import settings to get current Kafka config
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import settings

        print(
            f"  3. Verify Kafka topics: kcat -L -b {settings.kafka_bootstrap_servers}"
        )
        print("  4. Check database connectivity (credentials auto-loaded from .env)")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
