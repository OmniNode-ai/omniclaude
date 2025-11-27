#!/usr/bin/env python3
"""
Test script for PatternTracker integration.

Tests the pattern tracker in isolation to verify API communication.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

from .pattern_tracker import PatternTracker


async def test_pattern_tracker() -> None:
    """Test pattern tracker basic functionality."""
    print("=" * 60)
    print("Testing PatternTracker Integration")
    print("=" * 60)

    # Initialize tracker
    print("\n1. Initializing PatternTracker...")
    tracker = PatternTracker()
    print(f"   ✓ Tracker initialized (session: {tracker.session_id[:8]}...)")
    print(f"   ✓ API endpoint: {tracker.config.intelligence_url}")

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

    # Test quality score calculation (using inline calculation since PatternTracker doesn't have this method)
    print("\n4. Testing quality score calculation...")
    violations: List[Dict[str, Any]] = [
        {"type": "naming"},
        {"type": "naming"},
        {"type": "naming"},
    ]

    def calculate_quality_score(violations_list: List[Dict[str, Any]]) -> float:
        """Calculate quality score based on violations count."""
        if not violations_list:
            return 1.0
        return max(0.0, 1.0 - (len(violations_list) * 0.1))

    score = calculate_quality_score(violations)
    print(f"   ✓ Quality score for {len(violations)} violations: {score}")

    violations_empty: List[Dict[str, Any]] = []
    score_perfect = calculate_quality_score(violations_empty)
    print(f"   ✓ Quality score for {len(violations_empty)} violations: {score_perfect}")

    print("\n" + "=" * 60)
    print("Pattern Tracker Test Complete")
    print("=" * 60)


def test_sync() -> None:
    """Test synchronous wrapper using async run."""
    print("\n5. Testing synchronous wrapper...")
    tracker = PatternTracker()

    sample_code = "def test(): pass"
    context: Dict[str, Any] = {
        "event_type": "pattern_created",
        "tool": "Write",
        "language": "python",
        "file_path": "/test/sync.py",
    }

    try:
        # PatternTracker uses async, so we run it in an event loop
        pattern_id = asyncio.run(tracker.track_pattern_creation(sample_code, context))
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
