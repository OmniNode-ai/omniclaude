#!/usr/bin/env python3
import asyncio

from agents.lib.performance_optimization import (
    create_performance_indexes,
    optimize_database_performance,
)


async def test_performance_optimization():
    try:
        print("Testing performance optimization...")

        # Test database optimization analysis
        optimizations = await optimize_database_performance()
        print("✓ Database optimization analysis completed")
        print(f"✓ Found {len(optimizations.get('table_sizes', []))} tables analyzed")

        if "missing_indexes" in optimizations:
            print(f"✓ Found {len(optimizations['missing_indexes'])} missing indexes")

        if "slow_queries" in optimizations:
            print(f"✓ Found {len(optimizations['slow_queries'])} slow queries")

        # Test creating performance indexes
        created_indexes = await create_performance_indexes()
        print(f"✓ Created {len(created_indexes)} performance indexes")

        for index in created_indexes[:5]:  # Show first 5
            print(f"  - {index}")

    except Exception as e:
        print(f"✗ Performance optimization test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_performance_optimization())
