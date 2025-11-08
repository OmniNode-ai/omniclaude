#!/usr/bin/env python3
"""
Test Script for Agent Execution Logging

Tests that polymorphic agents properly log their execution to the
agent_execution_logs database table with correct agent names and correlation IDs.

Usage:
    python test_execution_logging.py
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Add agents lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from agents.parallel_execution.agent_coder import CoderAgent
from agents.parallel_execution.agent_debug_intelligence import DebugIntelligenceAgent
from agents.parallel_execution.agent_model import AgentTask


async def test_debug_agent_logging():
    """Test debug intelligence agent execution logging."""
    print("\n" + "=" * 80)
    print("TEST 1: Debug Intelligence Agent Execution Logging")
    print("=" * 80)

    # Create agent
    agent = DebugIntelligenceAgent()

    # Create test task with correlation_id
    correlation_id = str(uuid4())
    task = AgentTask(
        task_id="test-debug-001",
        description="Debug a sample error for testing",
        agent_name="debug-intelligence",
        input_data={
            "code": "def broken_function():\n    return x + 1  # x is not defined",
            "file_path": "test.py",
            "language": "python",
            "error": "NameError: name 'x' is not defined",
        },
        correlation_id=correlation_id,
        session_id=str(uuid4()),
    )

    print(f"✓ Created task: {task.task_id}")
    print(f"✓ Correlation ID: {correlation_id}")
    print(f"✓ Agent: {task.agent_name}")

    # Execute agent (should log to database)
    print("\n→ Executing agent...")
    try:
        result = await agent.execute(task)
        print(f"✓ Agent execution completed: success={result.success}")
        print(f"✓ Execution time: {result.execution_time_ms:.2f}ms")

        if result.success:
            confidence = result.output_data.get("root_cause_confidence", 0)
            print(f"✓ Root cause confidence: {confidence:.2f}")

        print("\n✅ TEST 1 PASSED: Debug agent execution logged successfully")
        return (True, correlation_id)

    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback

        traceback.print_exc()
        return (False, correlation_id)


async def test_coder_agent_logging():
    """Test coder agent execution logging."""
    print("\n" + "=" * 80)
    print("TEST 2: Coder Agent Execution Logging")
    print("=" * 80)

    # Create agent
    agent = CoderAgent()

    # Create test task with correlation_id
    correlation_id = str(uuid4())
    task = AgentTask(
        task_id="test-coder-001",
        description="Generate a simple ONEX Effect node",
        agent_name="contract-driven-generator",
        input_data={
            "node_type": "Effect",
            "node_name": "TestNode",
            "pre_gathered_context": {},
        },
        correlation_id=correlation_id,
        session_id=str(uuid4()),
    )

    print(f"✓ Created task: {task.task_id}")
    print(f"✓ Correlation ID: {correlation_id}")
    print(f"✓ Agent: {task.agent_name}")

    # Execute agent (should log to database)
    print("\n→ Executing agent...")
    try:
        result = await agent.execute(task)
        print(f"✓ Agent execution completed: success={result.success}")
        print(f"✓ Execution time: {result.execution_time_ms:.2f}ms")

        if result.success:
            lines = result.output_data.get("lines_generated", 0)
            quality = result.output_data.get("quality_score", 0)
            print(f"✓ Generated {lines} lines of code")
            print(f"✓ Quality score: {quality:.2f}")

        print("\n✅ TEST 2 PASSED: Coder agent execution logged successfully")
        return (True, correlation_id)

    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        import traceback

        traceback.print_exc()
        return (False, correlation_id)


async def verify_database_records(correlation_ids):
    """Verify that execution records were created in the database."""
    print("\n" + "=" * 80)
    print("TEST 3: Database Record Verification")
    print("=" * 80)

    # Defensive check: ensure correlation_ids is not empty
    if not correlation_ids:
        print("❌ No correlation IDs provided to verify!")
        print(
            "   This indicates that previous tests failed to collect correlation IDs."
        )
        return False

    # Filter out None values (in case tests failed before returning IDs)
    valid_ids = [cid for cid in correlation_ids if cid is not None]
    if not valid_ids:
        print("❌ All correlation IDs are None!")
        print("   This indicates that previous tests failed before generating IDs.")
        return False

    print(f"✓ Verifying {len(valid_ids)} correlation IDs")

    try:
        # Import database helpers
        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from db import get_pg_pool

        pool = await get_pg_pool()
        if not pool:
            print("⚠️ Database pool unavailable - skipping verification")
            return None

        async with pool.acquire() as conn:
            # Query for records with test correlation IDs
            query = """
                SELECT
                    execution_id,
                    correlation_id,
                    agent_name,
                    status,
                    duration_ms,
                    quality_score,
                    created_at
                FROM agent_execution_logs
                WHERE correlation_id = ANY($1::text[])
                ORDER BY created_at DESC
            """

            records = await conn.fetch(query, valid_ids)

            if not records:
                print("❌ No execution records found in database!")
                print(
                    f"   Searched for {len(valid_ids)} correlation IDs: {', '.join(valid_ids[:2])}..."
                )
                return False

            print(f"✓ Found {len(records)} execution records")
            print("\nRecords:")
            for rec in records:
                print(f"  • Agent: {rec['agent_name']}")
                print(f"    Correlation ID: {rec['correlation_id']}")
                print(f"    Status: {rec['status']}")
                print(f"    Duration: {rec['duration_ms']}ms")
                if rec["quality_score"]:
                    print(f"    Quality: {rec['quality_score']:.2f}")
                print()

            # Check for proper agent names (not "unknown")
            unknown_count = sum(1 for rec in records if rec["agent_name"] == "unknown")
            if unknown_count > 0:
                print(f"⚠️ Warning: {unknown_count} records have agent_name='unknown'")
                return False

            print("✅ TEST 3 PASSED: All records have proper agent names")
            return True

    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: Database verification error: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("AGENT EXECUTION LOGGING TEST SUITE")
    print("=" * 80)
    print("\nThis test verifies that polymorphic agents properly log their execution")
    print("to the agent_execution_logs database table.")
    print("\nTests:")
    print("  1. Debug Intelligence Agent - execution logging")
    print("  2. Coder Agent - execution logging")
    print("  3. Database Record Verification - proper agent names")

    correlation_ids = []
    results = []

    # Test 1: Debug agent
    test1_passed, test1_correlation_id = await test_debug_agent_logging()
    results.append(("Debug Agent", test1_passed))
    correlation_ids.append(test1_correlation_id)

    # Test 2: Coder agent
    test2_passed, test2_correlation_id = await test_coder_agent_logging()
    results.append(("Coder Agent", test2_passed))
    correlation_ids.append(test2_correlation_id)

    # Test 3: Database verification
    # Pass captured correlation IDs to verify database records
    test3_passed = await verify_database_records(correlation_ids)
    if test3_passed is not None:
        results.append(("Database Verification", test3_passed))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")

    all_passed = all(r[1] for r in results)
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
