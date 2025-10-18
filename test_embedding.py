#!/usr/bin/env python3
import asyncio
from agents.lib.embedding_search import find_similar_errors, recommend_stfs_for_error, get_error_patterns_analysis


async def test_embedding_search():
    try:
        print("Testing embedding-based similarity search...")

        # Test finding similar errors
        similar_errors = await find_similar_errors(
            error_text="Task breakdown validation failed", error_type="VALIDATION_ERROR", limit=5
        )
        print(f"✓ Found {len(similar_errors)} similar errors")

        for error in similar_errors:
            print(f"  - {error.error_type}: {error.message[:50]}... (similarity: {error.similarity_score:.3f})")

        # Test STF recommendations
        recommendations = await recommend_stfs_for_error(
            error_text="Task breakdown validation failed", error_type="VALIDATION_ERROR", limit=3
        )
        print(f"✓ Found {len(recommendations)} STF recommendations")

        for rec in recommendations:
            print(f"  - {rec['stf_name']}: confidence={rec['confidence']:.3f}, success_rate={rec['success_rate']:.3f}")

        # Test error pattern analysis
        patterns = await get_error_patterns_analysis(days=7, min_frequency=1)
        print(f"✓ Found {len(patterns)} error patterns")

        for pattern in patterns[:3]:
            print(f"  - {pattern['error_type']}: {pattern['message'][:50]}... (freq: {pattern['frequency']})")

    except Exception as e:
        print(f"✗ Embedding search test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_embedding_search())
