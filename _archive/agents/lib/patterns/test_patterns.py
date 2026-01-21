#!/usr/bin/env python3
"""
Quick test script for Pattern Library

Demonstrates pattern matching and code generation capabilities.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/lib/patterns/test_patterns.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio

from agents.lib.patterns.pattern_matcher import PatternMatcher
from agents.lib.patterns.pattern_registry import PatternRegistry


async def test_patterns():
    """Test pattern matching and code generation"""

    # Initialize pattern components
    matcher = PatternMatcher()
    registry = PatternRegistry()

    # Test capabilities
    test_capabilities = [
        {
            "name": "create_user",
            "type": "create",
            "description": "Create a new user record in the database",
            "required": True,
        },
        {
            "name": "transform_csv_to_json",
            "type": "transformation",
            "description": "Transform CSV data to JSON format",
            "required": False,
        },
        {
            "name": "aggregate_sales_data",
            "type": "aggregation",
            "description": "Aggregate sales data by region and calculate totals",
            "required": True,
        },
        {
            "name": "orchestrate_order_workflow",
            "type": "orchestration",
            "description": "Orchestrate multi-step order processing workflow",
            "required": True,
        },
    ]

    print("=" * 80)
    print("Pattern Library Test - Phase 5 Code Generation")
    print("=" * 80)

    for capability in test_capabilities:
        print(f"\n\nTesting capability: {capability['name']}")
        print("-" * 80)

        # Match patterns
        matches = matcher.match_patterns(capability, max_matches=2)

        if not matches:
            print("  ❌ No patterns matched")
            continue

        print(f"  ✅ Found {len(matches)} pattern matches:")

        for i, match in enumerate(matches, 1):
            print(f"\n  Match {i}:")
            print(f"    Pattern Type: {match.pattern_type.value}")
            print(f"    Confidence: {match.confidence:.2%}")
            print(f"    Matched Keywords: {', '.join(match.matched_keywords)}")
            print(f"    Suggested Method: {match.suggested_method_name}")

        # Generate code using best match
        best_match = matches[0]
        print(f"\n  Generating code using {best_match.pattern_type.value} pattern...")

        context = {
            "has_event_bus": True,
            "service_name": "test_service",
            **best_match.context,
        }

        generated_code = registry.generate_code_for_pattern(
            pattern_match=best_match, capability=capability, context=context
        )

        if generated_code:
            lines = generated_code.strip().split("\n")
            preview_lines = lines[:10]  # Show first 10 lines
            print(f"\n  Generated Code Preview ({len(lines)} lines total):")
            print("  " + "\n  ".join(preview_lines))
            if len(lines) > 10:
                print(f"  ... ({len(lines) - 10} more lines)")

        # Show required imports and mixins
        imports = registry.get_required_imports_for_pattern(best_match.pattern_type)
        mixins = registry.get_required_mixins_for_pattern(best_match.pattern_type)

        print(f"\n  Required Imports ({len(imports)}):")
        for imp in imports[:3]:  # Show first 3
            print(f"    - {imp}")
        if len(imports) > 3:
            print(f"    ... ({len(imports) - 3} more)")

        print(f"\n  Required Mixins ({len(mixins)}):")
        for mixin in mixins:
            print(f"    - {mixin}")

    print("\n\n" + "=" * 80)
    print("Test completed successfully!")
    print("=" * 80)

    # Show pattern statistics
    stats = registry.get_cache_stats()
    print("\nPattern Registry Statistics:")
    print(f"  Total Patterns: {stats['pattern_count']}")
    print(
        f"  Registered Patterns: {', '.join([p.value for p in stats['patterns_registered']])}"
    )

    # Show pattern priorities
    priorities = registry.get_pattern_priorities()
    print("\nPattern Priorities:")
    for pattern_type, priority in sorted(
        priorities.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {pattern_type.value}: {priority}")


if __name__ == "__main__":
    asyncio.run(test_patterns())
