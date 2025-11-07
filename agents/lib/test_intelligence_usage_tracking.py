#!/usr/bin/env python3
"""
Test Intelligence Usage Tracking

Verifies that intelligence usage tracking is working correctly:
1. Intelligence retrieval is tracked
2. Data is stored in agent_intelligence_usage table
3. v_intelligence_effectiveness view returns meaningful data

Usage:
    python3 agents/lib/test_intelligence_usage_tracking.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    # Look for .env in project root (two levels up from this file)
    project_root = Path(__file__).parent.parent.parent
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        # Try current directory
        load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Install with: pip install python-dotenv")

# Add project root to path for centralized config import (before lib path)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import centralized configuration (must be before lib path to avoid shadowing)
try:
    from config import settings
except ImportError:
    print("⚠️  config.settings not available. Ensure config module is installed.")
    settings = None

# Add lib directory to path for imports
lib_path = Path(__file__).parent
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from intelligence_usage_tracker import IntelligenceUsageTracker


async def test_retrieval_tracking():
    """Test basic intelligence retrieval tracking."""
    print("\n=== Testing Intelligence Retrieval Tracking ===\n")

    # Ensure environment is loaded
    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

    try:
        # Generate test correlation ID
        correlation_id = uuid4()
        agent_name = "test-agent"

        print(f"Correlation ID: {correlation_id}")
        print(f"Agent Name: {agent_name}\n")

        # Test 1: Track pattern retrieval from execution_patterns
        print("Test 1: Tracking pattern retrieval from execution_patterns...")
        success = await tracker.track_retrieval(
            correlation_id=correlation_id,
            agent_name=agent_name,
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="Node State Management Pattern",
            collection_name="execution_patterns",
            confidence_score=0.95,
            query_time_ms=450,
            query_used="PATTERN_EXTRACTION",
            query_results_rank=1,
            intelligence_summary="ONEX pattern for state management",
            metadata={
                "source": "test",
                "parallel_query": False,
            },
        )

        if success:
            print("✅ Pattern retrieval tracked successfully")
        else:
            print("❌ Failed to track pattern retrieval")
            return False

        # Test 2: Track pattern retrieval from code_patterns
        print("\nTest 2: Tracking pattern retrieval from code_patterns...")
        success = await tracker.track_retrieval(
            correlation_id=correlation_id,
            agent_name=agent_name,
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="Async Event Bus Communication",
            collection_name="code_patterns",
            confidence_score=0.92,
            query_time_ms=380,
            query_used="PATTERN_EXTRACTION",
            query_results_rank=2,
            intelligence_summary="Real Python implementation of event bus",
            metadata={
                "source": "test",
                "parallel_query": False,
            },
        )

        if success:
            print("✅ Pattern retrieval tracked successfully")
        else:
            print("❌ Failed to track pattern retrieval")
            return False

        # Test 3: Track debug intelligence retrieval
        print("\nTest 3: Tracking debug intelligence retrieval...")
        success = await tracker.track_retrieval(
            correlation_id=correlation_id,
            agent_name=agent_name,
            intelligence_type="debug_intelligence",
            intelligence_source="postgres",
            intelligence_name="Similar Successful Workflow",
            confidence_score=0.88,
            query_time_ms=120,
            query_used="DEBUG_INTELLIGENCE_QUERY",
            query_results_rank=1,
            intelligence_summary="Successfully read file before editing",
            metadata={
                "source": "test",
                "success": True,
            },
        )

        if success:
            print("✅ Debug intelligence retrieval tracked successfully")
        else:
            print("❌ Failed to track debug intelligence retrieval")
            return False

        return True
    finally:
        # Ensure pool is properly closed
        await tracker.close()


async def test_application_tracking():
    """Test intelligence application tracking."""
    print("\n=== Testing Intelligence Application Tracking ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

    try:
        # Generate test correlation ID
        correlation_id = uuid4()
        agent_name = "test-agent"

        # First, track retrieval
        print("Step 1: Tracking pattern retrieval...")
        await tracker.track_retrieval(
            correlation_id=correlation_id,
            agent_name=agent_name,
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="File Operation Pattern",
            collection_name="code_patterns",
            confidence_score=0.90,
            query_time_ms=200,
        )
        print("✅ Pattern retrieval tracked")

        # Then, track application
        print("\nStep 2: Tracking pattern application...")
        success = await tracker.track_application(
            correlation_id=correlation_id,
            intelligence_name="File Operation Pattern",
            was_applied=True,
            application_details={
                "applied_to": "file_read_operation",
                "success": True,
            },
            contributed_to_success=True,
            quality_impact=0.85,
        )

        if success:
            print("✅ Pattern application tracked successfully")
        else:
            print("❌ Failed to track pattern application")
            return False

        return True
    finally:
        # Ensure pool is properly closed
        await tracker.close()


async def test_usage_stats():
    """Test retrieving usage statistics."""
    print("\n=== Testing Usage Statistics Retrieval ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

    try:
        # Get overall stats
        print("Fetching overall usage statistics...")
        stats = await tracker.get_usage_stats()

        if "error" in stats:
            print(f"❌ Error fetching stats: {stats['error']}")
            return False

        print("\n📊 Overall Usage Statistics:")
        print(f"  Total Retrievals: {stats.get('total_retrievals', 0)}")
        print(f"  Times Applied: {stats.get('times_applied', 0)}")
        print(f"  Application Rate: {stats.get('application_rate_percent', 0)}%")

        # Handle NULL values from database
        avg_confidence = stats.get("avg_confidence")
        avg_confidence_str = (
            f"{avg_confidence:.2f}" if avg_confidence is not None else "N/A"
        )
        print(f"  Avg Confidence: {avg_confidence_str}")

        avg_quality = stats.get("avg_quality_impact")
        avg_quality_str = f"{avg_quality:.2f}" if avg_quality is not None else "N/A"
        print(f"  Avg Quality Impact: {avg_quality_str}")

        print(f"  Success Contributions: {stats.get('success_contributions', 0)}")

        avg_query_time = stats.get("avg_query_time_ms")
        avg_query_time_str = (
            f"{avg_query_time:.0f}ms" if avg_query_time is not None else "N/A"
        )
        print(f"  Avg Query Time: {avg_query_time_str}")

        if stats.get("total_retrievals", 0) > 0:
            print("\n✅ Usage statistics retrieved successfully")
            return True
        else:
            print("\n⚠️  No usage statistics found (may be expected for fresh install)")
            return True
    finally:
        # Ensure pool is properly closed
        await tracker.close()


async def test_pool_lifecycle():
    """Test connection pool lifecycle (create and cleanup)."""
    print("\n=== Testing Connection Pool Lifecycle ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

    try:
        # Test pool creation
        print("Step 1: Creating connection pool...")
        pool = await tracker._get_pool()
        if pool is None:
            print("❌ Failed to create connection pool")
            return False
        print("✅ Connection pool created successfully")

        # Test reusing existing pool
        print("\nStep 2: Verifying pool reuse...")
        pool2 = await tracker._get_pool()
        if pool is not pool2:
            print("❌ Pool not reused (created new instance)")
            return False
        print("✅ Pool reused successfully")

        # Test pool cleanup
        print("\nStep 3: Closing connection pool...")
        await tracker.close()
        if tracker._pool is not None:
            print("❌ Pool not properly closed")
            return False
        print("✅ Connection pool closed successfully")

        # Test pool recreation after close
        print("\nStep 4: Recreating pool after close...")
        pool3 = await tracker._get_pool()
        if pool3 is None:
            print("❌ Failed to recreate pool after close")
            return False
        print("✅ Pool recreated successfully")

        # Final cleanup
        await tracker.close()

        return True

    except Exception as e:
        print(f"❌ Error during pool lifecycle test: {e}")
        return False


async def test_database_view():
    """Test v_intelligence_effectiveness view."""
    print("\n=== Testing v_intelligence_effectiveness View ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    # Check if settings is available
    if settings is None:
        print("❌ config.settings not available")
        print("   Ensure config module is installed and in PYTHONPATH")
        return False

    try:
        import asyncpg

        # Connect to database using centralized settings with asyncpg
        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_database,
            user=settings.postgres_user,
            password=settings.get_effective_postgres_password(),
        )

        try:
            # Query view
            results = await conn.fetch(
                """
                SELECT
                    intelligence_type,
                    intelligence_name,
                    times_retrieved,
                    times_applied,
                    application_rate_percent,
                    avg_confidence,
                    avg_quality_impact,
                    success_contributions
                FROM v_intelligence_effectiveness
                ORDER BY times_applied DESC
                LIMIT 10
            """
            )

            if results:
                print(
                    f"✅ Found {len(results)} intelligence items in effectiveness view\n"
                )
                print("Top Intelligence Items by Application Rate:")
                print("-" * 80)
                for row in results:
                    print(f"  {row['intelligence_type']}: {row['intelligence_name']}")
                    print(
                        f"    Retrieved: {row['times_retrieved']}, "
                        f"Applied: {row['times_applied']}, "
                        f"Rate: {row['application_rate_percent']}%"
                    )

                    # Handle NULL values from database
                    row_confidence = row["avg_confidence"]
                    row_confidence_str = (
                        f"{row_confidence:.2f}" if row_confidence is not None else "N/A"
                    )

                    row_quality = row["avg_quality_impact"]
                    row_quality_str = (
                        f"{row_quality:.2f}" if row_quality is not None else "N/A"
                    )

                    print(
                        f"    Confidence: {row_confidence_str}, "
                        f"Quality Impact: {row_quality_str}, "
                        f"Success Contributions: {row['success_contributions']}"
                    )
                    print()
                return True
            else:
                print("⚠️  No data in v_intelligence_effectiveness view yet")
                print("    Run manifest injection to populate intelligence usage data")
                return True

        finally:
            await conn.close()

    except Exception as e:
        print(f"❌ Error querying view: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 80)
    print("Intelligence Usage Tracking Test Suite")
    print("=" * 80)

    # Check prerequisites
    if not os.getenv("POSTGRES_PASSWORD"):
        print("\n❌ POSTGRES_PASSWORD not set")
        print("   Run: source .env")
        sys.exit(1)

    # Run tests
    tests = [
        ("Connection Pool Lifecycle", test_pool_lifecycle),
        ("Intelligence Retrieval Tracking", test_retrieval_tracking),
        ("Intelligence Application Tracking", test_application_tracking),
        ("Usage Statistics Retrieval", test_usage_stats),
        ("Database View Query", test_database_view),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n❌ Test '{test_name}' raised exception: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
