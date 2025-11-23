#!/usr/bin/env python3
"""
Test script for agent_actions unique constraint (PR #33 CRITICAL fix)

Tests:
1. Migration applies successfully
2. Unique constraint prevents duplicates
3. Concurrent insertions are handled correctly
4. ON CONFLICT DO NOTHING works as expected
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest


# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings


@pytest.fixture
async def db_pool():
    """Create database connection pool for testing."""
    pool = await asyncpg.create_pool(
        settings.get_postgres_dsn(),
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_unique_constraint_exists(db_pool):
    """Test that the unique constraint exists in the database."""
    async with db_pool.acquire() as conn:
        # Check if constraint exists
        result = await conn.fetchrow(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'agent_actions'
              AND constraint_name = 'unique_action_per_correlation_timestamp'
              AND constraint_type = 'UNIQUE'
            """
        )

        assert (
            result is not None
        ), "Unique constraint 'unique_action_per_correlation_timestamp' not found"
        print("✅ Unique constraint exists in database")


@pytest.mark.asyncio
async def test_duplicate_prevention(db_pool):
    """Test that duplicate insertions are prevented."""
    correlation_id = uuid.uuid4()
    action_name = "test_action"
    timestamp = datetime.now(timezone.utc)

    async with db_pool.acquire() as conn:
        # Clean up any existing test data
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )

        # Insert first record
        insert_sql = """
            INSERT INTO agent_actions (
                correlation_id,
                agent_name,
                action_type,
                action_name,
                action_details,
                debug_mode,
                duration_ms,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT ON CONSTRAINT unique_action_per_correlation_timestamp
            DO NOTHING
            RETURNING id
        """

        result1 = await conn.fetchrow(
            insert_sql,
            correlation_id,
            "test_agent",
            "tool_call",
            action_name,
            json.dumps({"test": "data"}),
            True,
            100,
            timestamp,
        )

        assert result1 is not None, "First insert should succeed"
        print(f"✅ First insert succeeded with id: {result1['id']}")

        # Try to insert duplicate (same correlation_id, action_name, timestamp)
        result2 = await conn.fetchrow(
            insert_sql,
            correlation_id,
            "test_agent",
            "tool_call",
            action_name,
            json.dumps({"test": "data"}),
            True,
            100,
            timestamp,
        )

        assert result2 is None, "Duplicate insert should be skipped"
        print("✅ Duplicate insert was correctly prevented (ON CONFLICT DO NOTHING)")

        # Verify only one record exists
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
            correlation_id,
        )

        assert count == 1, f"Expected 1 record, found {count}"
        print("✅ Only one record exists in database (duplicates prevented)")

        # Clean up
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )


@pytest.mark.asyncio
async def test_concurrent_insertions(db_pool):
    """Test that concurrent insertions are handled correctly."""
    correlation_id = uuid.uuid4()
    action_name = "concurrent_test_action"
    timestamp = datetime.now(timezone.utc)

    async def insert_record(pool, cid, ts):
        """Insert a record (simulates concurrent consumer)."""
        async with pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO agent_actions (
                    correlation_id,
                    agent_name,
                    action_type,
                    action_name,
                    action_details,
                    debug_mode,
                    duration_ms,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT ON CONSTRAINT unique_action_per_correlation_timestamp
                DO NOTHING
                RETURNING id
                """,
                cid,
                "test_agent",
                "tool_call",
                action_name,
                json.dumps({"test": "concurrent"}),
                True,
                100,
                ts,
            )
            return result

    # Clean up any existing test data
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )

    # Launch 10 concurrent insertions (same correlation_id, action_name, timestamp)
    tasks = [insert_record(db_pool, correlation_id, timestamp) for _ in range(10)]

    results = await asyncio.gather(*tasks)

    # Count successful insertions
    successful = sum(1 for r in results if r is not None)
    duplicates = sum(1 for r in results if r is None)

    print(
        f"✅ Concurrent test: {successful} succeeded, {duplicates} duplicates prevented"
    )

    # Verify only one record exists
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
            correlation_id,
        )

        assert (
            count == 1
        ), f"Expected 1 record after concurrent insertions, found {count}"
        print("✅ Concurrent insertions handled correctly (only 1 record in DB)")

        # Clean up
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )


@pytest.mark.asyncio
async def test_different_timestamps_allowed(db_pool):
    """Test that same action with different timestamps is allowed."""
    correlation_id = uuid.uuid4()
    action_name = "timestamp_test_action"
    timestamp1 = datetime.now(timezone.utc)
    timestamp2 = datetime.now(timezone.utc).replace(
        microsecond=timestamp1.microsecond + 1000
    )

    async with db_pool.acquire() as conn:
        # Clean up any existing test data
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )

        insert_sql = """
            INSERT INTO agent_actions (
                correlation_id,
                agent_name,
                action_type,
                action_name,
                action_details,
                debug_mode,
                duration_ms,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT ON CONSTRAINT unique_action_per_correlation_timestamp
            DO NOTHING
            RETURNING id
        """

        # Insert first record
        result1 = await conn.fetchrow(
            insert_sql,
            correlation_id,
            "test_agent",
            "tool_call",
            action_name,
            json.dumps({"test": "data"}),
            True,
            100,
            timestamp1,
        )

        # Insert second record with different timestamp (should succeed)
        result2 = await conn.fetchrow(
            insert_sql,
            correlation_id,
            "test_agent",
            "tool_call",
            action_name,
            json.dumps({"test": "data"}),
            True,
            100,
            timestamp2,
        )

        assert result1 is not None, "First insert should succeed"
        assert (
            result2 is not None
        ), "Second insert with different timestamp should succeed"
        print("✅ Same action with different timestamps allowed (both inserted)")

        # Verify two records exist
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = $1",
            correlation_id,
        )

        assert (
            count == 2
        ), f"Expected 2 records with different timestamps, found {count}"
        print("✅ Two records exist (different timestamps)")

        # Clean up
        await conn.execute(
            "DELETE FROM agent_actions WHERE correlation_id = $1", correlation_id
        )


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("Testing agent_actions unique constraint (PR #33 CRITICAL fix)")
    print("=" * 70 + "\n")

    # Create connection pool
    pool = await asyncpg.create_pool(
        settings.get_postgres_dsn(),
        min_size=2,
        max_size=10,
        command_timeout=30,
    )

    try:
        print("Test 1: Checking unique constraint exists...")
        await test_unique_constraint_exists(pool)
        print()

        print("Test 2: Testing duplicate prevention...")
        await test_duplicate_prevention(pool)
        print()

        print("Test 3: Testing concurrent insertions...")
        await test_concurrent_insertions(pool)
        print()

        print("Test 4: Testing different timestamps allowed...")
        await test_different_timestamps_allowed(pool)
        print()

        print("=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
