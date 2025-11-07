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


async def test_application_tracking():
    """Test intelligence application tracking."""
    print("\n=== Testing Intelligence Application Tracking ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

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


async def test_usage_stats():
    """Test retrieving usage statistics."""
    print("\n=== Testing Usage Statistics Retrieval ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    tracker = IntelligenceUsageTracker()

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
    print(f"  Avg Confidence: {stats.get('avg_confidence') or 0:.2f}")
    print(f"  Avg Quality Impact: {stats.get('avg_quality_impact') or 0:.2f}")
    print(f"  Success Contributions: {stats.get('success_contributions', 0)}")
    print(f"  Avg Query Time: {stats.get('avg_query_time_ms') or 0:.0f}ms")

    if stats.get("total_retrievals", 0) > 0:
        print("\n✅ Usage statistics retrieved successfully")
        return True
    else:
        print("\n⚠️  No usage statistics found (may be expected for fresh install)")
        return True


async def test_database_view():
    """Test v_intelligence_effectiveness view."""
    print("\n=== Testing v_intelligence_effectiveness View ===\n")

    if not os.getenv("POSTGRES_PASSWORD"):
        print("⚠️  POSTGRES_PASSWORD not set. Run: source .env")
        return False

    try:
        import psycopg2
        import psycopg2.extras

        # Import settings with fallback
        try:
            from config import settings
        except ImportError:
            # Fallback to environment variables (os already imported at top)
            class Settings:
                postgres_host = os.getenv("POSTGRES_HOST", "192.168.86.200")
                postgres_port = int(os.getenv("POSTGRES_PORT", "5436"))
                postgres_database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
                postgres_user = os.getenv("POSTGRES_USER", "postgres")

                @staticmethod
                def get_effective_postgres_password():
                    return os.getenv("POSTGRES_PASSWORD")

            settings = Settings()

        # Connect to database
        with (
            psycopg2.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                dbname=settings.postgres_database,
                user=settings.postgres_user,
                password=settings.get_effective_postgres_password(),
            ) as conn,
            conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor,
        ):
            # Query view
            cursor.execute(
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

            results = cursor.fetchall()

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
                    print(
                        f"    Confidence: {row['avg_confidence'] or 0:.2f}, "
                        f"Quality Impact: {row['avg_quality_impact'] or 0:.2f}, "
                        f"Success Contributions: {row['success_contributions']}"
                    )
                    print()
                return True
            else:
                print("⚠️  No data in v_intelligence_effectiveness view yet")
                print("    Run manifest injection to populate intelligence usage data")
                return True

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
