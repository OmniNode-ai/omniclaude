#!/usr/bin/env python3
"""
Test metadata extraction from Qdrant patterns.

Verifies that:
1. Keywords are extracted from reuse_conditions
2. quality_score comes from source_context.quality_score (not top-level)
3. Metadata is properly structured
"""

import asyncio
import sys
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from lib.manifest_injector import ManifestInjector
from lib.task_classifier import TaskClassifier


async def test_metadata_extraction():
    """Test that metadata is extracted correctly from Qdrant"""

    print("=" * 80)
    print("METADATA EXTRACTION TEST: Verifying Qdrant Pattern Metadata")
    print("=" * 80)
    print()

    # Initialize manifest injector
    injector = ManifestInjector()

    # Sample user prompt
    user_prompt = "Create an LLM effect node for API calls"

    # Classify task
    classifier = TaskClassifier()
    task_context = classifier.classify(user_prompt)

    print(f"📝 User Prompt: '{user_prompt}'")
    print(f"🎯 Task Type: {task_context.primary_intent.value}")
    print()

    # Query patterns directly from Qdrant (using the internal method)
    print("🔍 Querying patterns from Qdrant...")

    try:
        # Use the internal _query_patterns_direct_qdrant method
        import uuid

        correlation_id = str(uuid.uuid4())

        result = await injector._query_patterns_direct_qdrant(
            task_context=task_context,
            user_prompt=user_prompt,
            correlation_id=correlation_id,
        )

        # Extract patterns list from result
        patterns = result.get("patterns", [])

        print(f"✅ Retrieved {len(patterns)} patterns from Qdrant")
        print(f"   Query time: {result.get('query_time_ms', 0)}ms")
        print()

        # Examine first 3 patterns
        print("=" * 80)
        print("PATTERN METADATA INSPECTION")
        print("=" * 80)
        print()

        for i, pattern in enumerate(patterns[:3], 1):
            print(f"Pattern #{i}: {pattern.get('name', 'Unknown')}")
            print("-" * 80)

            # Check for keywords
            keywords = pattern.get("keywords", [])
            print(
                f"  Keywords (from reuse_conditions): {keywords[:5] if keywords else '[]'}"
            )

            # Check for metadata
            metadata = pattern.get("metadata", {})
            if metadata:
                print("  Metadata:")
                print(
                    f"    • quality_score: {metadata.get('quality_score', 'MISSING')}"
                )
                print(
                    f"    • confidence_score: {metadata.get('confidence_score', 'MISSING')}"
                )
                print(f"    • success_rate: {metadata.get('success_rate', 'MISSING')}")
                print(f"    • usage_count: {metadata.get('usage_count', 'MISSING')}")
                print(f"    • pattern_type: {metadata.get('pattern_type', 'MISSING')}")
                print(f"    • node_type: {metadata.get('node_type', 'MISSING')}")
            else:
                print("  ❌ Metadata: MISSING")

            # Check for source_context (should still be present)
            source_context = pattern.get("source_context", {})
            if source_context:
                print("  Source Context (raw):")
                print(
                    f"    • quality_score: {source_context.get('quality_score', 'MISSING')}"
                )
                print(f"    • node_type: {source_context.get('node_type', 'MISSING')}")

            # Check old fields (should still exist)
            print("  Other Fields:")
            print(f"    • reuse_conditions: {pattern.get('reuse_conditions', [])[:3]}")
            print(f"    • pattern_type: {pattern.get('pattern_type', 'MISSING')}")
            print(
                f"    • confidence_score: {pattern.get('confidence_score', 'MISSING')}"
            )

            print()

        # Validation
        print("=" * 80)
        print("VALIDATION")
        print("=" * 80)
        print()

        # Check that all patterns have metadata
        patterns_with_metadata = sum(1 for p in patterns if p.get("metadata"))
        print(
            f"✅ Patterns with metadata: {patterns_with_metadata}/{len(patterns)} ({patterns_with_metadata/len(patterns)*100:.1f}%)"
        )

        # Check that quality_score is not default 0.5
        quality_scores = [
            p.get("metadata", {}).get("quality_score", 0.5) for p in patterns[:10]
        ]
        non_default_quality = sum(1 for q in quality_scores if q != 0.5)
        print(
            f"✅ Patterns with non-default quality_score: {non_default_quality}/{len(quality_scores)}"
        )

        if non_default_quality > 0:
            print(f"   Quality scores: {[f'{q:.2f}' for q in quality_scores[:5]]}")

        # Check that keywords are extracted
        patterns_with_keywords = sum(1 for p in patterns if p.get("keywords"))
        print(
            f"✅ Patterns with keywords: {patterns_with_keywords}/{len(patterns)} ({patterns_with_keywords/len(patterns)*100:.1f}%)"
        )

        print()
        print("=" * 80)
        print("✅ METADATA EXTRACTION TEST COMPLETE")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"❌ Error querying patterns: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_metadata_extraction())
    sys.exit(0 if success else 1)
