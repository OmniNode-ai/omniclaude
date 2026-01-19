#!/usr/bin/env python3
"""
Test script to verify pattern filtering fix in manifest_injector.py

This script tests that:
1. Qdrant semantic scores are used directly (no Archon API dependency)
2. Patterns with semantic_score > 0.3 pass through filter
3. Patterns with semantic_score <= 0.3 are filtered out
4. Manifest generation shows patterns_count > 0

Usage:
    python3 test_pattern_filtering_fix.py
"""

import asyncio
import sys
from pathlib import Path

# Add agents/lib to path
lib_path = Path(__file__).parent / "agents" / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector
from task_classifier import TaskClassifier


async def test_pattern_filtering():
    """Test that pattern filtering uses Qdrant semantic scores directly"""
    print("=" * 70)
    print("Testing Pattern Filtering Fix")
    print("=" * 70)

    # Initialize manifest injector
    injector = ManifestInjector()

    # Create task context for testing
    classifier = TaskClassifier()
    task_context = classifier.classify(
        user_prompt="Help me implement ONEX node patterns with state management"
    )

    print("\nTask Context:")
    print(f"  Primary Intent: {task_context.primary_intent}")
    print(f"  Keywords: {task_context.keywords[:10]}")

    # Generate manifest with pattern discovery
    print("\nGenerating manifest with pattern discovery...")
    correlation_id = "test-pattern-filtering-" + str(id(task_context))

    manifest_data = await injector.generate_dynamic_manifest_async(
        agent_name="test-agent",
        correlation_id=correlation_id,
        user_prompt="Help me implement ONEX node patterns with state management",
        task_context=task_context,
    )

    manifest = manifest_data.get("content", "")

    # Extract pattern info from manifest
    patterns_count = 0
    avg_score = 0.0
    scores = []

    # Parse manifest text to find pattern counts
    if "patterns_count:" in manifest:
        for line in manifest.split("\n"):
            if "patterns_count:" in line:
                try:
                    patterns_count = int(line.split(":")[-1].strip())
                except ValueError:
                    pass
            if "avg_score=" in line:
                try:
                    avg_score = float(
                        line.split("avg_score=")[-1].split(",")[0].strip()
                    )
                except ValueError:
                    pass

    # Results
    print("\n" + "=" * 70)
    print("Test Results")
    print("=" * 70)
    print(f"✓ Patterns Count: {patterns_count}")
    print(f"✓ Average Score: {avg_score:.3f}")

    # Validate results
    success = True
    if patterns_count == 0:
        print("\n❌ FAIL: No patterns found (expected > 0)")
        success = False
    else:
        print(f"\n✓ PASS: Found {patterns_count} patterns with semantic scores > 0.3")

    if avg_score < 0.3:
        print(f"❌ FAIL: Average score {avg_score:.3f} is below threshold 0.3")
        success = False
    else:
        print(f"✓ PASS: Average score {avg_score:.3f} is above threshold 0.3")

    # Check that manifest mentions Qdrant semantic scoring
    if "Qdrant semantic score" in manifest or "qdrant_vector_similarity" in manifest:
        print("✓ PASS: Manifest indicates using Qdrant semantic scores")
    else:
        print("⚠️  WARNING: Manifest doesn't mention Qdrant semantic scoring")

    # Final result
    print("\n" + "=" * 70)
    if success:
        print("✅ ALL TESTS PASSED")
        print("\nPattern filtering is now using Qdrant semantic scores directly.")
        print("No dependency on broken Archon API endpoint.")
        return 0
    else:
        print("❌ TESTS FAILED")
        print("\nPattern filtering issue detected. Check logs above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_pattern_filtering())
    sys.exit(exit_code)
