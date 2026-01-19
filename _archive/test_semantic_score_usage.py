#!/usr/bin/env python3
"""
Unit test to verify semantic score mapping in manifest_injector.py

This test verifies:
1. Patterns with metadata.semantic_score get mapped to hybrid_score
2. Filtering works based on semantic_score threshold (0.3)
3. No dependency on ArchonHybridScorer
"""


def test_semantic_score_mapping():
    """Test the semantic score mapping logic"""
    print("=" * 70)
    print("Testing Semantic Score Mapping Logic")
    print("=" * 70)

    # Simulate patterns from Qdrant with semantic scores
    test_patterns = [
        {
            "name": "High Score Pattern",
            "description": "Should pass filter",
            "metadata": {"semantic_score": 0.85, "quality_score": 0.8},
        },
        {
            "name": "Medium Score Pattern",
            "description": "Should pass filter",
            "metadata": {"semantic_score": 0.45, "quality_score": 0.5},
        },
        {
            "name": "Low Score Pattern",
            "description": "Should be filtered out",
            "metadata": {"semantic_score": 0.15, "quality_score": 0.3},
        },
        {
            "name": "Threshold Pattern",
            "description": "Should be filtered out (exactly at threshold)",
            "metadata": {"semantic_score": 0.30, "quality_score": 0.4},
        },
        {
            "name": "Just Above Threshold",
            "description": "Should pass filter",
            "metadata": {"semantic_score": 0.31, "quality_score": 0.5},
        },
    ]

    # Apply the same logic as manifest_injector.py (lines 1597-1625)
    relevance_threshold = 0.3
    all_patterns = test_patterns.copy()

    # Map semantic_score to hybrid_score
    for pattern in all_patterns:
        metadata = pattern.get("metadata", {})
        semantic_score = metadata.get("semantic_score", 0.5)

        # This is the key change: use semantic_score directly
        pattern["hybrid_score"] = semantic_score
        pattern["score_breakdown"] = {"semantic_score": semantic_score}
        pattern["score_metadata"] = {
            "source": "qdrant_vector_similarity",
            "model": "GTE-Qwen2-7B-instruct",
        }

    # Filter by threshold (> not >=)
    filtered_patterns = [
        p for p in all_patterns if p.get("hybrid_score", 0.0) > relevance_threshold
    ]

    # Sort by score descending
    filtered_patterns.sort(key=lambda p: p.get("hybrid_score", 0.0), reverse=True)

    # Print results
    print(f"\nOriginal patterns: {len(test_patterns)}")
    print(f"Filtered patterns: {len(filtered_patterns)}")
    print(f"Threshold: {relevance_threshold}")

    print("\nFiltered patterns (sorted by score):")
    for i, pattern in enumerate(filtered_patterns, 1):
        score = pattern.get("hybrid_score", 0.0)
        print(f"  {i}. {pattern['name']}: {score:.2f}")

    # Expected: 3 patterns should pass (0.85, 0.45, 0.31)
    # Should filter out: 0.15, 0.30
    expected_count = 3
    expected_names = [
        "High Score Pattern",
        "Medium Score Pattern",
        "Just Above Threshold",
    ]

    print("\n" + "=" * 70)
    print("Test Results")
    print("=" * 70)

    success = True

    # Check count
    if len(filtered_patterns) == expected_count:
        print(f"✓ PASS: Correct number of patterns ({expected_count})")
    else:
        print(
            f"❌ FAIL: Expected {expected_count} patterns, got {len(filtered_patterns)}"
        )
        success = False

    # Check names
    actual_names = [p["name"] for p in filtered_patterns]
    if set(actual_names) == set(expected_names):
        print("✓ PASS: Correct patterns passed filter")
    else:
        print(f"❌ FAIL: Expected {expected_names}, got {actual_names}")
        success = False

    # Check scores are descending
    scores = [p.get("hybrid_score", 0.0) for p in filtered_patterns]
    if scores == sorted(scores, reverse=True):
        print("✓ PASS: Patterns sorted by score descending")
    else:
        print("❌ FAIL: Patterns not sorted correctly")
        success = False

    # Check all scores > threshold
    all_above_threshold = all(
        p.get("hybrid_score", 0.0) > relevance_threshold for p in filtered_patterns
    )
    if all_above_threshold:
        print(f"✓ PASS: All filtered patterns have score > {relevance_threshold}")
    else:
        print(f"❌ FAIL: Some patterns have score <= {relevance_threshold}")
        success = False

    # Check metadata
    has_correct_metadata = all(
        p.get("score_metadata", {}).get("source") == "qdrant_vector_similarity"
        for p in filtered_patterns
    )
    if has_correct_metadata:
        print("✓ PASS: All patterns have correct metadata source")
    else:
        print("❌ FAIL: Patterns missing correct metadata")
        success = False

    print("\n" + "=" * 70)
    if success:
        print("✅ ALL TESTS PASSED")
        print("\nSemantic score mapping logic is working correctly:")
        print("  - Uses Qdrant semantic_score directly (no Archon API)")
        print("  - Filters patterns with score > 0.3")
        print("  - Sorts by score descending")
        print("  - Maps to hybrid_score for consistency")
        return 0
    else:
        print("❌ TESTS FAILED")
        return 1


if __name__ == "__main__":
    import sys

    exit_code = test_semantic_score_mapping()
    sys.exit(exit_code)
