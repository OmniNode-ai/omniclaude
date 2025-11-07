#!/usr/bin/env python3
"""
Test pattern deduplication logic in ManifestInjector.

Tests the _deduplicate_patterns method to ensure:
1. Duplicates are correctly identified by name
2. Highest confidence version is kept
3. Metrics are accurately tracked
4. Token savings are measurable
"""

import sys
from typing import Any, Dict, List


def test_deduplicate_patterns():
    """Test the deduplication logic with realistic pattern data."""

    # Import the ManifestInjector class
    sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
    from agents.lib.manifest_injector import ManifestInjector

    # Create test data with duplicates (simulating the PR #22 issue)
    test_patterns: List[Dict[str, Any]] = [
        # Dependency injection pattern repeated 23 times (as mentioned in PR #22)
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.85,
            "file_path": "pattern1.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.92,
            "file_path": "pattern2.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.78,
            "file_path": "pattern3.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.88,
            "file_path": "pattern4.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.95,
            "file_path": "pattern5.py",
        },  # Highest
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.82,
            "file_path": "pattern6.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.87,
            "file_path": "pattern7.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.90,
            "file_path": "pattern8.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.84,
            "file_path": "pattern9.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.91,
            "file_path": "pattern10.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.86,
            "file_path": "pattern11.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.89,
            "file_path": "pattern12.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.83,
            "file_path": "pattern13.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.93,
            "file_path": "pattern14.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.81,
            "file_path": "pattern15.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.94,
            "file_path": "pattern16.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.80,
            "file_path": "pattern17.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.87,
            "file_path": "pattern18.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.92,
            "file_path": "pattern19.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.85,
            "file_path": "pattern20.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.88,
            "file_path": "pattern21.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.91,
            "file_path": "pattern22.py",
        },
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.86,
            "file_path": "pattern23.py",
        },
        # Other unique patterns
        {"name": "Factory Pattern", "confidence": 0.88, "file_path": "factory1.py"},
        {
            "name": "Factory Pattern",
            "confidence": 0.92,
            "file_path": "factory2.py",
        },  # Duplicate with higher confidence
        {"name": "Observer Pattern", "confidence": 0.95, "file_path": "observer.py"},
        {"name": "Singleton Pattern", "confidence": 0.90, "file_path": "singleton.py"},
        {"name": "Strategy Pattern", "confidence": 0.87, "file_path": "strategy.py"},
    ]

    print(f"📊 Test Data:")
    print(f"   Total patterns: {len(test_patterns)}")
    print(f"   Expected duplicates: 23 (22 for Dependency Injection + 1 for Factory)")
    print(
        f"   Expected unique patterns: 5 (Dependency Injection, Factory, Observer, Singleton, Strategy)"
    )
    print()

    # Create ManifestInjector instance
    injector = ManifestInjector()

    # Test deduplication
    print("🔍 Running deduplication...")
    deduplicated, duplicates_removed = injector._deduplicate_patterns(test_patterns)

    print(f"✅ Deduplication complete!")
    print(f"   Patterns before: {len(test_patterns)}")
    print(f"   Patterns after: {len(deduplicated)}")
    print(f"   Duplicates removed: {duplicates_removed}")
    print()

    # Verify results
    print("🧪 Verification:")

    # Check that we have 5 unique patterns
    assert (
        len(deduplicated) == 5
    ), f"Expected 5 unique patterns, got {len(deduplicated)}"
    print("   ✓ Correct number of unique patterns (5)")

    # Check that 23 duplicates were removed (22 from DI + 1 from Factory)
    assert (
        duplicates_removed == 23
    ), f"Expected 23 duplicates removed, got {duplicates_removed}"
    print("   ✓ Correct number of duplicates removed (23)")

    # Check that highest confidence versions were kept
    pattern_map = {p["name"]: p for p in deduplicated}

    # Dependency Injection should have confidence 0.95 (highest)
    assert pattern_map["Dependency Injection Pattern"]["confidence"] == 0.95
    print("   ✓ Dependency Injection Pattern: kept highest confidence (0.95)")

    # Factory Pattern should have confidence 0.92 (highest)
    assert pattern_map["Factory Pattern"]["confidence"] == 0.92
    print("   ✓ Factory Pattern: kept highest confidence (0.92)")

    # Check that patterns are sorted by confidence (highest first)
    confidences = [p["confidence"] for p in deduplicated]
    assert confidences == sorted(
        confidences, reverse=True
    ), "Patterns should be sorted by confidence (highest first)"
    print("   ✓ Patterns sorted by confidence (highest first)")

    print()
    print("📈 Deduplication Results:")
    for i, pattern in enumerate(deduplicated, 1):
        print(
            f"   {i}. {pattern['name']} ({pattern['confidence']:.0%} confidence) - {pattern['file_path']}"
        )

    # Calculate token savings
    # Assuming each duplicate pattern takes ~5-7 tokens on average
    # (pattern name + confidence + file path + formatting)
    avg_tokens_per_pattern = 6
    token_savings = duplicates_removed * avg_tokens_per_pattern

    print()
    print("💰 Token Savings Estimation:")
    print(f"   Duplicates removed: {duplicates_removed}")
    print(f"   Avg tokens per pattern: {avg_tokens_per_pattern}")
    print(f"   Estimated token savings: {token_savings} tokens")
    print(f"   Reduction: {(duplicates_removed / len(test_patterns) * 100):.1f}%")

    return deduplicated, duplicates_removed


def test_edge_cases():
    """Test edge cases for deduplication."""
    sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
    from agents.lib.manifest_injector import ManifestInjector

    injector = ManifestInjector()

    print("\n🔬 Testing Edge Cases:")

    # Test 1: Empty list
    result, count = injector._deduplicate_patterns([])
    assert result == []
    assert count == 0
    print("   ✓ Empty list handled correctly")

    # Test 2: Single pattern (no duplicates)
    single = [{"name": "Pattern A", "confidence": 0.9}]
    result, count = injector._deduplicate_patterns(single)
    assert len(result) == 1
    assert count == 0
    print("   ✓ Single pattern (no duplicates) handled correctly")

    # Test 3: All patterns are identical
    identical = [{"name": "Same Pattern", "confidence": 0.8}] * 10
    result, count = injector._deduplicate_patterns(identical)
    assert len(result) == 1
    assert count == 9
    print("   ✓ All identical patterns handled correctly (10 → 1, 9 removed)")

    # Test 4: No duplicates
    unique = [
        {"name": "Pattern A", "confidence": 0.9},
        {"name": "Pattern B", "confidence": 0.8},
        {"name": "Pattern C", "confidence": 0.7},
    ]
    result, count = injector._deduplicate_patterns(unique)
    assert len(result) == 3
    assert count == 0
    print("   ✓ No duplicates handled correctly")

    print()


if __name__ == "__main__":
    print("=" * 70)
    print("Pattern Deduplication Test Suite")
    print("=" * 70)
    print()

    try:
        # Run main test
        test_deduplicate_patterns()

        # Run edge case tests
        test_edge_cases()

        print("=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
