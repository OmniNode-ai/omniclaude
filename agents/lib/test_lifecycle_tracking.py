#!/usr/bin/env python3
"""
Test script for agent lifecycle completion tracking.

Tests the new mark_agent_completed() method to verify it properly updates
the agent_manifest_injections table with completion timestamps.

Usage:
    python3 test_lifecycle_tracking.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

# Add lib directory to path for imports
lib_path = Path(__file__).parent
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector  # noqa: E402


async def test_lifecycle_tracking():
    """Test agent lifecycle completion tracking."""
    print("=" * 70)
    print("AGENT LIFECYCLE TRACKING TEST")
    print("=" * 70)
    print()

    # Set database password for remote host (outside Docker)
    os.environ["POSTGRES_PASSWORD"] = "omninode_remote_2024_secure"

    # Set agent name (fixes "unknown" issue)
    agent_name = "test-lifecycle-agent"
    os.environ["AGENT_NAME"] = agent_name
    print(f"✓ Set AGENT_NAME environment variable: {agent_name}")

    # Generate correlation ID
    correlation_id = uuid4()
    print(f"✓ Generated correlation ID: {correlation_id}")
    print()

    # Test 1: Create manifest injector
    print("TEST 1: Creating ManifestInjector with agent_name")
    async with ManifestInjector(
        agent_name=agent_name,
        enable_intelligence=True,  # Enable to ensure record is stored
        enable_storage=True,
        query_timeout_ms=2000,  # Short timeout for testing
    ) as injector:
        print("  ✓ ManifestInjector created")
        print(f"  ✓ Agent name: {injector.agent_name}")
        print(f"  ✓ Storage enabled: {injector.enable_storage}")
        print()

        # Test 2: Generate manifest (this creates the record)
        print("TEST 2: Generating manifest (creates database record)")
        try:
            await injector.generate_dynamic_manifest_async(str(correlation_id))
            print("  ✓ Manifest generated successfully")
            print(f"  ✓ Correlation ID set: {injector._current_correlation_id}")
            print()
        except Exception as e:
            print(f"  ✗ Manifest generation failed: {e}")
            print()

        # Test 3: Mark as completed (success case)
        print("TEST 3: Marking agent as completed (success=True)")
        success = injector.mark_agent_completed(success=True)
        if success:
            print("  ✓ Agent marked as completed successfully")
        else:
            print("  ✗ Failed to mark agent as completed")
        print()

    # Test 4: Verify database record
    print("TEST 4: Verifying database record")
    try:
        import psycopg2

        # Connect to database
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "omninode-bridge-postgres"),
            port=int(os.environ.get("POSTGRES_PORT", "5436")),
            dbname=os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get("POSTGRES_PASSWORD", "omninode_remote_2024_secure"),
        )

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                correlation_id,
                agent_name,
                created_at,
                completed_at,
                executed_at,
                agent_execution_success,
                EXTRACT(EPOCH FROM (completed_at - created_at)) AS duration_seconds
            FROM agent_manifest_injections
            WHERE correlation_id = %s
            """,
            (str(correlation_id),),
        )

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            print("  ✓ Database record found:")
            print(f"    Correlation ID: {row[0]}")
            print(f"    Agent Name: {row[1]}")
            print(f"    Created At: {row[2]}")
            print(f"    Completed At: {row[3]}")
            print(f"    Executed At: {row[4]}")
            print(f"    Success: {row[5]}")
            print(f"    Duration: {row[6]:.2f}s" if row[6] else "    Duration: N/A")
            print()

            # Validate all lifecycle fields are set
            if all([row[3], row[4], row[5] is not None]):
                print("  ✅ SUCCESS: All lifecycle fields populated correctly!")
            else:
                print("  ✗ FAILURE: Some lifecycle fields missing")
                print(f"    completed_at: {'SET' if row[3] else 'NULL'}")
                print(f"    executed_at: {'SET' if row[4] else 'NULL'}")
                print(
                    f"    agent_execution_success: {'SET' if row[5] is not None else 'NULL'}"
                )
        else:
            print(f"  ✗ No database record found for correlation_id={correlation_id}")

    except Exception as e:
        print(f"  ✗ Database verification failed: {e}")
        import traceback

        traceback.print_exc()

    print()
    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


async def test_error_case():
    """Test error handling when marking agent as failed."""
    print()
    print("=" * 70)
    print("ERROR CASE TEST")
    print("=" * 70)
    print()

    # Set database password for remote host (outside Docker)
    os.environ["POSTGRES_PASSWORD"] = "omninode_remote_2024_secure"

    agent_name = "test-lifecycle-agent-error"
    os.environ["AGENT_NAME"] = agent_name
    correlation_id = uuid4()

    async with ManifestInjector(
        agent_name=agent_name,
        enable_intelligence=True,  # Enable to ensure record is stored
        enable_storage=True,
        query_timeout_ms=2000,  # Short timeout for testing
    ) as injector:
        # Generate manifest
        await injector.generate_dynamic_manifest_async(str(correlation_id))

        # Simulate error and mark as failed
        print("TEST: Marking agent as failed with error message")
        error_message = "Test error: Something went wrong"
        success = injector.mark_agent_completed(
            success=False, error_message=error_message
        )

        if success:
            print("  ✓ Agent marked as failed successfully")

            # Verify database record
            import psycopg2

            conn = psycopg2.connect(
                host=os.environ.get("POSTGRES_HOST", "omninode-bridge-postgres"),
                port=int(os.environ.get("POSTGRES_PORT", "5436")),
                dbname=os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
                user=os.environ.get("POSTGRES_USER", "postgres"),
                password=os.environ.get(
                    "POSTGRES_PASSWORD", "omninode_remote_2024_secure"
                ),
            )

            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    agent_execution_success,
                    warnings
                FROM agent_manifest_injections
                WHERE correlation_id = %s
                """,
                (str(correlation_id),),
            )

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                print(f"  ✓ Success flag: {row[0]} (should be False)")
                print(f"  ✓ Warnings: {row[1]}")

                if row[0] is False and error_message in str(row[1]):
                    print("  ✅ SUCCESS: Error case handled correctly!")
                else:
                    print("  ✗ FAILURE: Error not recorded properly")
            else:
                print("  ✗ No record found")
        else:
            print("  ✗ Failed to mark agent as failed")

    print()


if __name__ == "__main__":
    # Run tests
    asyncio.run(test_lifecycle_tracking())
    asyncio.run(test_error_case())
