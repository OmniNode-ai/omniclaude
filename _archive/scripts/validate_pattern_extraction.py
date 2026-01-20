#!/usr/bin/env python3
"""
Validation script for pattern metadata extraction from Qdrant.

Tests that the _query_patterns_direct_qdrant() method correctly extracts:
- file_path → file
- confidence_score → confidence
- node_types
- use_cases
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"Loaded environment from {env_path}")
else:
    print(f"Warning: .env file not found at {env_path}")

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.lib.manifest_injector import ManifestInjector


async def validate_pattern_extraction():
    """Validate that pattern extraction includes all required metadata."""
    print("=" * 70)
    print("Pattern Metadata Extraction Validation")
    print("=" * 70)
    print()

    # Initialize manifest injector
    injector = ManifestInjector()

    # Query patterns directly from Qdrant
    print("Querying Qdrant for patterns...")
    correlation_id = "validation-test"
    collections = ["code_generation_patterns"]

    result = await injector._query_patterns_direct_qdrant(
        correlation_id=correlation_id,
        collections=collections,
        limit_per_collection=5,  # Just get a few for testing
    )

    patterns = result.get("patterns", [])
    print(f"Retrieved {len(patterns)} patterns")
    print()

    if not patterns:
        print("❌ No patterns found - check Qdrant connection and data")
        return False

    # Validate first pattern has all required fields
    print("Validating first pattern structure...")
    print("-" * 70)

    first_pattern = patterns[0]
    required_fields = {
        "name": str,
        "file_path": str,
        "node_types": list,
        "confidence": (int, float),
        "use_cases": list,
        "description": str,
    }

    all_valid = True
    for field_name, expected_type in required_fields.items():
        value = first_pattern.get(field_name)

        if value is None:
            print(f"❌ {field_name}: MISSING (None)")
            all_valid = False
        elif not isinstance(value, expected_type):
            print(
                f"❌ {field_name}: WRONG TYPE (expected {expected_type}, got {type(value)})"
            )
            all_valid = False
        elif isinstance(value, str) and value == "":
            print(f"⚠️  {field_name}: EMPTY STRING ('{value}')")
            # Don't fail on empty strings, just warn
        elif isinstance(value, (int, float)) and value == 0.0:
            print(f"⚠️  {field_name}: ZERO VALUE ({value})")
            # Don't fail on zero, just warn
        elif isinstance(value, list) and len(value) == 0:
            print(f"⚠️  {field_name}: EMPTY ARRAY ({value})")
            # Don't fail on empty arrays, just warn
        else:
            # Show actual value for non-empty fields
            display_value = value
            if isinstance(value, str) and len(value) > 50:
                display_value = value[:50] + "..."
            elif isinstance(value, list):
                display_value = f"[{len(value)} items]"
            print(f"✅ {field_name}: {display_value}")

    print()
    print("-" * 70)
    print("First pattern details:")
    print(f"  Name: {first_pattern.get('name', 'N/A')}")
    print(f"  File: {first_pattern.get('file_path', 'N/A')}")
    print(f"  Confidence: {first_pattern.get('confidence', 0.0)}")
    print(f"  Node Types: {first_pattern.get('node_types', [])}")
    print(f"  Use Cases: {first_pattern.get('use_cases', [])}")
    print()

    # Show summary of all patterns
    print("-" * 70)
    print(f"Summary of all {len(patterns)} patterns:")
    print()

    # Count patterns with populated fields
    with_file = sum(1 for p in patterns if p.get("file_path", ""))
    with_confidence = sum(1 for p in patterns if p.get("confidence", 0.0) > 0.0)
    with_node_types = sum(1 for p in patterns if p.get("node_types", []))
    with_use_cases = sum(1 for p in patterns if p.get("use_cases", []))

    print(f"  Patterns with file_path: {with_file}/{len(patterns)}")
    print(f"  Patterns with confidence > 0: {with_confidence}/{len(patterns)}")
    print(f"  Patterns with node_types: {with_node_types}/{len(patterns)}")
    print(f"  Patterns with use_cases: {with_use_cases}/{len(patterns)}")
    print()

    # Determine overall success
    print("=" * 70)
    if all_valid:
        print("✅ VALIDATION PASSED - All required fields present")
        return True
    else:
        print("❌ VALIDATION FAILED - Missing or invalid fields")
        return False


if __name__ == "__main__":
    success = asyncio.run(validate_pattern_extraction())
    sys.exit(0 if success else 1)
