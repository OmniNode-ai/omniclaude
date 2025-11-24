#!/usr/bin/env python3
"""
Test script for PatternTracker integration.

Tests the pattern tracker in isolation to verify API communication.
"""

import asyncio
import sys
from pathlib import Path


# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from pattern_tracker import PatternTracker


async def test_pattern_tracker():
    """Test pattern tracker basic functionality."""
    print("=" * 60)
    print("Testing PatternTracker Integration")
    print("=" * 60)

    # Initialize tracker
    print("\n1. Initializing PatternTracker...")
    tracker = PatternTracker()
    print(f"   ✓ Tracker initialized (session: {tracker.session_id[:8]}...)")
    print(f"   ✓ API endpoint: {tracker.api_endpoint}")

    # Test pattern creation tracking
    print("\n2. Testing pattern creation tracking...")
    sample_code = '''
def calculate_sum(numbers):
    """Calculate sum of numbers."""
    return sum(numbers)
'''

    context = {
        "event_type": "pattern_created",
        "tool": "Write",
        "language": "python",
        "file_path": "/test/sample.py",
        "session_id": tracker.session_id,
    }

    print(f"   Sample code: {len(sample_code)} chars")
    print(f"   Context: {context['event_type']}, {context['language']}")

    try:
        pattern_id = await tracker.track_pattern_creation(sample_code, context)
        if pattern_id:
            print(f"   ✓ Pattern tracked successfully: {pattern_id[:16]}...")
        else:
            print("   ⚠ Pattern tracking returned None (API may be unavailable)")
    except Exception as e:
        print(f"   ✗ Pattern tracking failed: {e}")

    # Test with quality metrics
    print("\n3. Testing pattern tracking with quality metrics...")
    context_with_quality = {
        **context,
        "violations_found": 3,
        "quality_score": 0.7,
        "reason": "Code with naming violations",
    }

    try:
        pattern_id = await tracker.track_pattern_creation(
            sample_code, context_with_quality
        )
        if pattern_id:
            print(f"   ✓ Pattern with quality metrics tracked: {pattern_id[:16]}...")
        else:
            print("   ⚠ Pattern tracking returned None (API may be unavailable)")
    except Exception as e:
        print(f"   ✗ Pattern tracking failed: {e}")

    # Test quality score calculation
    print("\n4. Testing quality score calculation...")
    violations = [{"type": "naming"}, {"type": "naming"}, {"type": "naming"}]
    score = tracker.calculate_quality_score(violations)
    print(f"   ✓ Quality score for {len(violations)} violations: {score}")

    violations_empty = []
    score_perfect = tracker.calculate_quality_score(violations_empty)
    print(f"   ✓ Quality score for {len(violations_empty)} violations: {score_perfect}")

    print("\n" + "=" * 60)
    print("Pattern Tracker Test Complete")
    print("=" * 60)


def test_sync():
    """Test synchronous wrapper."""
    print("\n5. Testing synchronous wrapper...")
    tracker = PatternTracker()

    sample_code = "def test(): pass"
    context = {
        "event_type": "pattern_created",
        "tool": "Write",
        "language": "python",
        "file_path": "/test/sync.py",
    }

    try:
        pattern_id = tracker.track_pattern_creation_sync(sample_code, context)
        if pattern_id:
            print(f"   ✓ Sync pattern tracking: {pattern_id[:16]}...")
        else:
            print("   ⚠ Sync pattern tracking returned None (API may be unavailable)")
    except Exception as e:
        print(f"   ✗ Sync pattern tracking failed: {e}")


if __name__ == "__main__":
    # Run async tests
    asyncio.run(test_pattern_tracker())

    # Run sync test
    test_sync()
