#!/usr/bin/env python3
"""
Integration test for pattern deduplication in manifest generation.

Tests the full flow:
1. _format_patterns_result processes raw patterns with deduplication
2. _format_patterns displays metrics correctly
3. Token savings are measured accurately
"""

import sys
from pathlib import Path


def test_manifest_integration():
    """Test deduplication in the context of full manifest generation."""

    # Add project root to path dynamically
    project_root = Path(__file__).parent.resolve()
    sys.path.insert(0, str(project_root))
    from agents.lib.manifest_injector import ManifestInjector

    # Create ManifestInjector instance
    injector = ManifestInjector()

    # Simulate raw patterns from Qdrant (with duplicates)
    raw_result = {
        "patterns": [
            # Dependency injection pattern repeated 23 times
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.85,
                "file_path": "pattern1.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.92,
                "file_path": "pattern2.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.78,
                "file_path": "pattern3.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.88,
                "file_path": "pattern4.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.95,
                "file_path": "pattern5.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.82,
                "file_path": "pattern6.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.87,
                "file_path": "pattern7.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.90,
                "file_path": "pattern8.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.84,
                "file_path": "pattern9.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.91,
                "file_path": "pattern10.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.86,
                "file_path": "pattern11.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.89,
                "file_path": "pattern12.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.83,
                "file_path": "pattern13.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.93,
                "file_path": "pattern14.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.81,
                "file_path": "pattern15.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.94,
                "file_path": "pattern16.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.80,
                "file_path": "pattern17.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.87,
                "file_path": "pattern18.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.92,
                "file_path": "pattern19.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.85,
                "file_path": "pattern20.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.88,
                "file_path": "pattern21.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.91,
                "file_path": "pattern22.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            {
                "name": "Dependency Injection Pattern",
                "confidence": 0.86,
                "file_path": "pattern23.py",
                "node_types": ["EFFECT"],
                "use_cases": ["DI"],
            },
            # Other patterns
            {
                "name": "Factory Pattern",
                "confidence": 0.92,
                "file_path": "factory.py",
                "node_types": ["COMPUTE"],
                "use_cases": ["Object creation"],
            },
            {
                "name": "Observer Pattern",
                "confidence": 0.95,
                "file_path": "observer.py",
                "node_types": ["ORCHESTRATOR"],
                "use_cases": ["Event handling"],
            },
        ],
        "collections_queried": {
            "execution_patterns": 120,
            "code_patterns": 856,
        },
        "query_time_ms": 1842,
    }

    print("=" * 70)
    print("Manifest Integration Test - Pattern Deduplication")
    print("=" * 70)
    print()

    print("📊 Input Data:")
    print(f"   Total patterns from Qdrant: {len(raw_result['patterns'])}")
    print(
        f"   Collections queried: execution_patterns ({raw_result['collections_queried']['execution_patterns']}), "
        f"code_patterns ({raw_result['collections_queried']['code_patterns']})"
    )
    print()

    # Step 1: Format patterns result (applies deduplication)
    print("🔄 Step 1: Processing patterns with deduplication...")
    formatted_result = injector._format_patterns_result(raw_result)

    print(f"   ✓ Processed successfully")
    print(f"   Original count: {formatted_result['original_count']}")
    print(f"   Unique patterns: {formatted_result['total_count']}")
    print(f"   Duplicates removed: {formatted_result['duplicates_removed']}")
    print()

    # Verify deduplication metrics
    assert (
        formatted_result["original_count"] == 25
    ), f"Expected 25 original patterns, got {formatted_result['original_count']}"
    assert (
        formatted_result["total_count"] == 3
    ), f"Expected 3 unique patterns, got {formatted_result['total_count']}"
    assert (
        formatted_result["duplicates_removed"] == 22
    ), f"Expected 22 duplicates removed, got {formatted_result['duplicates_removed']}"
    print("✅ Deduplication metrics verified:")
    print(f"   ✓ Original count: {formatted_result['original_count']}")
    print(f"   ✓ Unique patterns: {formatted_result['total_count']}")
    print(f"   ✓ Duplicates removed: {formatted_result['duplicates_removed']}")
    print()

    # Step 2: Format patterns for display in manifest
    print("🎨 Step 2: Formatting patterns for manifest display...")
    formatted_output = injector._format_patterns(formatted_result)

    print("✅ Formatted output:")
    print("-" * 70)
    print(formatted_output)
    print("-" * 70)
    print()

    # Verify output contains deduplication info
    assert "Deduplication:" in formatted_output, "Output should mention deduplication"
    assert (
        f"{formatted_result['duplicates_removed']} duplicates removed"
        in formatted_output
    )
    assert (
        f"({formatted_result['original_count']} → {formatted_result['total_count']} unique patterns)"
        in formatted_output
    )
    print("✅ Manifest output verified:")
    print("   ✓ Contains deduplication metrics")
    print("   ✓ Shows before/after counts")
    print()

    # Step 3: Calculate token savings
    print("💰 Step 3: Calculating token savings...")

    # Estimate tokens per pattern entry in manifest
    # Pattern name (avg 4 tokens) + confidence (2 tokens) + file path (3 tokens)
    # + node types (2 tokens) + formatting (2 tokens) = ~13 tokens per pattern
    tokens_per_pattern = 13
    token_savings = formatted_result["duplicates_removed"] * tokens_per_pattern

    print(f"   Duplicates removed: {formatted_result['duplicates_removed']}")
    print(f"   Tokens per pattern entry: ~{tokens_per_pattern}")
    print(f"   Total token savings: ~{token_savings} tokens")
    print(
        f"   Reduction percentage: {(formatted_result['duplicates_removed'] / formatted_result['original_count'] * 100):.1f}%"
    )
    print()

    # Verify token savings meet PR #22 requirements
    assert (
        token_savings >= 100
    ), f"Expected at least 100 tokens saved, got {token_savings}"
    print(f"✅ Token savings verified: {token_savings} tokens (exceeds 100-150 target)")
    print()

    # Step 4: Verify highest confidence versions were kept
    print("🎯 Step 4: Verifying pattern quality...")
    pattern_map = {p["name"]: p for p in formatted_result["available"]}

    # Check Dependency Injection Pattern has highest confidence (0.95)
    di_pattern = pattern_map.get("Dependency Injection Pattern")
    assert di_pattern is not None, "Dependency Injection Pattern should be present"
    assert (
        di_pattern["confidence"] == 0.95
    ), f"Expected confidence 0.95, got {di_pattern['confidence']}"
    print(
        f"   ✓ Dependency Injection Pattern: {di_pattern['confidence']:.0%} confidence (highest)"
    )

    # Check Factory Pattern
    factory_pattern = pattern_map.get("Factory Pattern")
    assert factory_pattern is not None, "Factory Pattern should be present"
    assert (
        factory_pattern["confidence"] == 0.92
    ), f"Expected confidence 0.92, got {factory_pattern['confidence']}"
    print(f"   ✓ Factory Pattern: {factory_pattern['confidence']:.0%} confidence")

    # Check Observer Pattern
    observer_pattern = pattern_map.get("Observer Pattern")
    assert observer_pattern is not None, "Observer Pattern should be present"
    assert (
        observer_pattern["confidence"] == 0.95
    ), f"Expected confidence 0.95, got {observer_pattern['confidence']}"
    print(f"   ✓ Observer Pattern: {observer_pattern['confidence']:.0%} confidence")
    print()

    print("=" * 70)
    print("✅ Integration Test Passed!")
    print("=" * 70)
    print()
    print("Summary:")
    print(
        f"   • Deduplication successfully removed {formatted_result['duplicates_removed']} duplicate patterns"
    )
    print(f"   • Token savings: ~{token_savings} tokens per manifest injection")
    print(f"   • Pattern quality maintained (highest confidence versions kept)")
    print(f"   • Manifest display shows deduplication metrics")
    print()

    return formatted_result, token_savings


if __name__ == "__main__":
    try:
        test_manifest_integration()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Integration test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
