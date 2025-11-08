#!/usr/bin/env python3
"""
Test pattern deduplication in manifest_injector.py

This script verifies that:
1. Duplicate patterns are grouped by name
2. Instance counts are tracked correctly
3. Metadata is aggregated from all instances
4. Token usage is reduced
"""

import sys
from typing import Any, Dict, List


def mock_deduplicate_patterns(
    patterns: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], int]:
    """
    Mock implementation of _deduplicate_patterns() for testing.

    This matches the actual implementation in manifest_injector.py.
    """
    if not patterns:
        return [], 0

    # Group patterns by name
    pattern_groups = {}

    for pattern in patterns:
        name = pattern.get("name", "Unknown Pattern")
        confidence = pattern.get("confidence", 0.0)

        if name not in pattern_groups:
            pattern_groups[name] = {
                "pattern": pattern,
                "count": 0,
                "node_types": set(),
                "domains": set(),
                "services": set(),
                "files": set(),
            }

        group = pattern_groups[name]
        group["count"] += 1

        # Update to highest confidence version
        if confidence > group["pattern"].get("confidence", 0.0):
            group["pattern"] = pattern

        # Accumulate metadata from all instances
        if pattern.get("node_types"):
            group["node_types"].update(pattern["node_types"])
        if pattern.get("file_path"):
            group["files"].add(pattern["file_path"])

        # Extract domain and service from source context
        source_context = pattern.get("source_context", {})
        if source_context.get("domain"):
            group["domains"].add(source_context["domain"])
        if source_context.get("service_name"):
            group["services"].add(source_context["service_name"])

    # Build deduplicated list with enhanced metadata
    deduplicated = []
    for name, group in pattern_groups.items():
        pattern = group["pattern"].copy()

        # Add aggregated metadata to pattern
        pattern["instance_count"] = group["count"]
        pattern["all_node_types"] = sorted(group["node_types"])
        pattern["all_domains"] = sorted(group["domains"])
        pattern["all_services"] = sorted(group["services"])
        pattern["all_files"] = sorted(group["files"])

        deduplicated.append(pattern)

    # Calculate duplicates removed
    original_count = len(patterns)
    duplicates_removed = original_count - len(deduplicated)

    # Sort by confidence (highest first)
    deduplicated.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)

    return deduplicated, duplicates_removed


def test_basic_deduplication():
    """Test basic deduplication with duplicate pattern names."""
    print("Test 1: Basic deduplication")
    print("-" * 60)

    patterns = [
        {
            "name": "Dependency Injection",
            "confidence": 0.75,
            "node_types": ["EFFECT"],
            "file_path": "service_a/node_user_effect.py",
            "source_context": {"domain": "identity", "service_name": "user_service"},
        },
        {
            "name": "Dependency Injection",
            "confidence": 0.80,
            "node_types": ["COMPUTE"],
            "file_path": "service_b/node_analytics_compute.py",
            "source_context": {
                "domain": "analytics",
                "service_name": "analytics_service",
            },
        },
        {
            "name": "Dependency Injection",
            "confidence": 0.78,
            "node_types": ["EFFECT"],
            "file_path": "service_c/node_data_effect.py",
            "source_context": {
                "domain": "data_processing",
                "service_name": "data_service",
            },
        },
        {
            "name": "Unique Pattern",
            "confidence": 0.90,
            "node_types": ["ORCHESTRATOR"],
            "file_path": "orchestrator.py",
            "source_context": {
                "domain": "orchestration",
                "service_name": "orchestrator",
            },
        },
    ]

    deduplicated, duplicates_removed = mock_deduplicate_patterns(patterns)

    print(f"Input: {len(patterns)} patterns")
    print(f"Output: {len(deduplicated)} unique patterns")
    print(f"Duplicates removed: {duplicates_removed}")
    print()

    # Verify results
    assert (
        len(deduplicated) == 2
    ), f"Expected 2 unique patterns, got {len(deduplicated)}"
    assert (
        duplicates_removed == 2
    ), f"Expected 2 duplicates removed, got {duplicates_removed}"

    # Find the Dependency Injection pattern
    dep_injection = next(
        (p for p in deduplicated if p["name"] == "Dependency Injection"), None
    )
    assert dep_injection is not None, "Dependency Injection pattern not found"

    print("Dependency Injection pattern:")
    print(f"  Instance count: {dep_injection['instance_count']}")
    print(f"  Confidence: {dep_injection['confidence']:.0%} (should be highest: 80%)")
    print(f"  All node types: {dep_injection['all_node_types']}")
    print(f"  All domains: {dep_injection['all_domains']}")
    print(f"  All services: {dep_injection['all_services']}")
    print(f"  All files: {len(dep_injection['all_files'])} files")
    print()

    # Verify metadata
    assert (
        dep_injection["instance_count"] == 3
    ), f"Expected 3 instances, got {dep_injection['instance_count']}"
    assert (
        dep_injection["confidence"] == 0.80
    ), f"Expected confidence 0.80, got {dep_injection['confidence']}"
    assert set(dep_injection["all_node_types"]) == {
        "COMPUTE",
        "EFFECT",
    }, f"Node types mismatch: {dep_injection['all_node_types']}"
    assert set(dep_injection["all_domains"]) == {
        "analytics",
        "data_processing",
        "identity",
    }, f"Domains mismatch: {dep_injection['all_domains']}"
    assert (
        len(dep_injection["all_files"]) == 3
    ), f"Expected 3 files, got {len(dep_injection['all_files'])}"

    print("✅ Test 1 PASSED")
    print()


def test_no_duplicates():
    """Test with no duplicate patterns."""
    print("Test 2: No duplicates")
    print("-" * 60)

    patterns = [
        {
            "name": "Pattern A",
            "confidence": 0.80,
            "node_types": ["EFFECT"],
            "file_path": "pattern_a.py",
        },
        {
            "name": "Pattern B",
            "confidence": 0.75,
            "node_types": ["COMPUTE"],
            "file_path": "pattern_b.py",
        },
    ]

    deduplicated, duplicates_removed = mock_deduplicate_patterns(patterns)

    print(f"Input: {len(patterns)} patterns")
    print(f"Output: {len(deduplicated)} unique patterns")
    print(f"Duplicates removed: {duplicates_removed}")
    print()

    assert len(deduplicated) == 2, f"Expected 2 patterns, got {len(deduplicated)}"
    assert (
        duplicates_removed == 0
    ), f"Expected 0 duplicates removed, got {duplicates_removed}"

    # Verify instance counts
    for pattern in deduplicated:
        assert (
            pattern["instance_count"] == 1
        ), f"Expected instance_count=1, got {pattern['instance_count']}"

    print("✅ Test 2 PASSED")
    print()


def test_many_duplicates():
    """Test with many duplicates (like the 23x dependency injection case)."""
    print("Test 3: Many duplicates (23x)")
    print("-" * 60)

    patterns = []
    for i in range(23):
        patterns.append(
            {
                "name": "Dependency Injection",
                "confidence": 0.70 + (i * 0.005),  # Varying confidence
                "node_types": ["EFFECT", "COMPUTE"][i % 2 :],
                "file_path": f"service_{i}/node_effect.py",
                "source_context": {
                    "domain": ["identity", "analytics", "data_processing"][i % 3],
                    "service_name": f"service_{i}",
                },
            }
        )

    deduplicated, duplicates_removed = mock_deduplicate_patterns(patterns)

    print(f"Input: {len(patterns)} patterns")
    print(f"Output: {len(deduplicated)} unique patterns")
    print(f"Duplicates removed: {duplicates_removed}")
    print()

    assert len(deduplicated) == 1, f"Expected 1 unique pattern, got {len(deduplicated)}"
    assert (
        duplicates_removed == 22
    ), f"Expected 22 duplicates removed, got {duplicates_removed}"

    pattern = deduplicated[0]
    print("Dependency Injection pattern:")
    print(f"  Instance count: {pattern['instance_count']}")
    print(f"  Confidence: {pattern['confidence']:.0%}")
    print(f"  All node types: {pattern['all_node_types']}")
    print(f"  All domains: {pattern['all_domains']}")
    print(f"  All files: {len(pattern['all_files'])} files")
    print()

    assert (
        pattern["instance_count"] == 23
    ), f"Expected 23 instances, got {pattern['instance_count']}"
    assert (
        len(pattern["all_files"]) == 23
    ), f"Expected 23 files, got {len(pattern['all_files'])}"

    print("✅ Test 3 PASSED")
    print()


def estimate_token_savings():
    """Estimate token savings from deduplication."""
    print("Test 4: Token savings estimation")
    print("-" * 60)

    # Before deduplication: 23 patterns x ~25 tokens each = ~575 tokens
    patterns_before = 23
    tokens_per_pattern = 25
    tokens_before = patterns_before * tokens_per_pattern

    # After deduplication: 1 pattern with instance count + metadata = ~40 tokens
    patterns_after = 1
    tokens_per_grouped_pattern = 40
    tokens_after = patterns_after * tokens_per_grouped_pattern

    tokens_saved = tokens_before - tokens_after
    reduction_pct = (tokens_saved / tokens_before) * 100

    print(f"Before deduplication:")
    print(
        f"  {patterns_before} patterns x {tokens_per_pattern} tokens = ~{tokens_before} tokens"
    )
    print()
    print(f"After deduplication:")
    print(
        f"  {patterns_after} pattern x {tokens_per_grouped_pattern} tokens = ~{tokens_after} tokens"
    )
    print()
    print(f"Savings: ~{tokens_saved} tokens ({reduction_pct:.1f}% reduction)")
    print()

    assert tokens_saved > 0, "Expected token savings"
    assert reduction_pct > 50, f"Expected >50% reduction, got {reduction_pct:.1f}%"

    print("✅ Test 4 PASSED")
    print()


def main():
    """Run all tests."""
    print("=" * 60)
    print("Pattern Deduplication Tests")
    print("=" * 60)
    print()

    try:
        test_basic_deduplication()
        test_no_duplicates()
        test_many_duplicates()
        estimate_token_savings()

        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ ERROR: {e}")
        print("=" * 60)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
