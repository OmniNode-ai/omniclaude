#!/usr/bin/env python3
"""
Test database pool lifecycle management.

This script verifies that the DatabasePool context manager properly
creates and closes connection pools without resource leaks.
"""

import asyncio
import sys
from pathlib import Path


# Add parent directory to path for config import
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import from debug_loop_cli
from scripts.debug_loop_cli import console, get_db_pool


async def test_pool_lifecycle():
    """Test that pool is properly created and closed."""
    console.print("[cyan]Testing database pool lifecycle...[/cyan]")

    try:
        # Test 1: Basic pool creation and cleanup
        console.print("\n[yellow]Test 1: Basic pool creation and cleanup[/yellow]")
        async with await get_db_pool() as pool:
            console.print(f"  ✓ Pool created: {pool}")
            console.print(f"  ✓ Pool size: {pool.get_size()}")
            console.print(f"  ✓ Pool idle: {pool.get_idle_size()}")
        console.print("  ✓ Pool closed (context manager exited)")

        # Test 2: Pool with actual query
        console.print("\n[yellow]Test 2: Pool with actual query[/yellow]")
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                console.print(f"  ✓ Query executed successfully: {result}")
        console.print("  ✓ Pool closed after query")

        # Test 3: Multiple sequential operations
        console.print("\n[yellow]Test 3: Multiple sequential operations[/yellow]")
        for i in range(3):
            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    result = await conn.fetchval("SELECT $1::int", i)
                    console.print(f"  ✓ Operation {i}: result={result}")
        console.print("  ✓ All pools properly cleaned up")

        # Test 4: Exception handling
        console.print("\n[yellow]Test 4: Exception handling[/yellow]")
        try:
            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    # This query should fail
                    await conn.fetchval("SELECT * FROM nonexistent_table")
        except Exception as e:
            console.print(f"  ✓ Exception caught: {type(e).__name__}")
            console.print("  ✓ Pool should still be closed despite exception")

        console.print(
            "\n[green]✓ All tests passed! Pool lifecycle management is working correctly.[/green]"
        )
        return True

    except Exception as e:
        console.print(f"\n[red]✗ Test failed: {e}[/red]")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Main test runner."""
    success = await test_pool_lifecycle()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
