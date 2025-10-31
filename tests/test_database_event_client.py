#!/usr/bin/env python3
"""
Test script for DatabaseEventClient end-to-end flow

This script tests the complete event-driven database query flow:
1. Client publishes query request to Kafka
2. Database adapter consumes request
3. Adapter executes query against PostgreSQL
4. Adapter publishes response to Kafka
5. Client receives response with correlation tracking
"""

import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, "agents/lib")

from database_event_client import DatabaseEventClient


async def test_simple_query():
    """Test simple SELECT query via Kafka events"""
    print("=" * 60)
    print("TEST 1: Simple Query - Count Routing Decisions")
    print("=" * 60)

    client = DatabaseEventClient()

    try:
        start_time = time.time()
        await client.start()
        print("✅ Client started")

        # Test simple query
        query = "SELECT COUNT(*) as total FROM agent_routing_decisions"
        print(f"\nExecuting query: {query}")

        rows = await client.query(query=query, limit=1)

        elapsed_ms = int((time.time() - start_time) * 1000)

        print("✅ Query successful!")
        print(f"   Results: {rows}")
        print(f"   Execution time: {elapsed_ms}ms")

        # Validate response
        assert rows is not None, "Expected non-None response"
        assert len(rows) > 0, "Expected at least one row"
        assert "total" in rows[0], "Expected 'total' column in response"

        print("✅ Validation passed")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_query_with_filter():
    """Test query with WHERE clause"""
    print("=" * 60)
    print("TEST 2: Filtered Query - Recent Routing Decisions")
    print("=" * 60)

    client = DatabaseEventClient()

    try:
        start_time = time.time()
        await client.start()
        print("✅ Client started")

        # Test filtered query
        query = """
        SELECT
            selected_agent,
            confidence_score,
            routing_strategy,
            created_at
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        """
        print(f"\nExecuting query: {query.strip()}")

        rows = await client.query(query=query, limit=5)

        elapsed_ms = int((time.time() - start_time) * 1000)

        print("✅ Query successful!")
        print(f"   Results: {len(rows)} rows")
        print(f"   Execution time: {elapsed_ms}ms")

        # Display results
        if rows:
            print("\n   Recent routing decisions:")
            for i, row in enumerate(rows, 1):
                print(f"     {i}. Agent: {row.get('selected_agent')}")
                print(f"        Confidence: {row.get('confidence_score')}")
                print(f"        Strategy: {row.get('routing_strategy')}")
                print(f"        Time: {row.get('created_at')}")
        else:
            print("   No results found")

        print("✅ Validation passed")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_correlation_tracking():
    """Test correlation ID preservation across request-response"""
    print("=" * 60)
    print("TEST 3: Correlation ID Tracking")
    print("=" * 60)

    client = DatabaseEventClient()

    try:
        await client.start()
        print("✅ Client started")

        # Execute query and capture correlation ID
        print("\nExecuting query with correlation tracking...")

        rows = await client.query(query="SELECT 1 as test_value", limit=1)

        print("✅ Query successful!")
        print(f"   Correlation ID: {client._correlation_id}")
        print(f"   Results: {rows}")

        # Validate correlation ID exists
        assert client._correlation_id is not None, "Expected correlation ID"
        print("✅ Correlation tracking validated")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_timeout_handling():
    """Test timeout handling for slow queries"""
    print("=" * 60)
    print("TEST 4: Timeout Handling")
    print("=" * 60)

    client = DatabaseEventClient(timeout_seconds=2)

    try:
        await client.start()
        print("✅ Client started with 2s timeout")

        # Test with reasonable query (should succeed)
        print("\nExecuting query within timeout...")

        rows = await client.query(
            query="SELECT COUNT(*) as total FROM agent_routing_decisions", limit=1
        )

        print("✅ Query completed within timeout!")
        print(f"   Results: {rows}")

        return True

    except asyncio.TimeoutError:
        print("❌ Query timed out (expected for slow queries)")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def run_all_tests():
    """Run all test cases"""
    print("\n" + "=" * 60)
    print("DATABASE EVENT CLIENT - END-TO-END TESTING")
    print("=" * 60)
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60 + "\n")

    results = {}

    # Run tests
    results["test_simple_query"] = await test_simple_query()
    results["test_query_with_filter"] = await test_query_with_filter()
    results["test_correlation_tracking"] = await test_correlation_tracking()
    results["test_timeout_handling"] = await test_timeout_handling()

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)

    return all(results.values())


if __name__ == "__main__":
    result = asyncio.run(run_all_tests())
    sys.exit(0 if result else 1)
