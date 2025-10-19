#!/usr/bin/env python3
"""Quick verification script for PatternTrackerSync."""

import sys

from lib.pattern_tracker_sync import PatternTrackerSync


def test_basic_tracking():
    """Test basic pattern tracking functionality."""
    print("=" * 60, file=sys.stderr)
    print("Testing PatternTrackerSync", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Create tracker
    tracker = PatternTrackerSync()

    # Example code snippet
    code = '''
def calculate_fibonacci(n: int) -> int:
    """Calculate fibonacci number at position n."""
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)
'''

    # Context with metadata
    context = {
        "event_type": "pattern_created",
        "file_path": "/test/fibonacci.py",
        "language": "python",
        "reason": "Code generation via Claude Code hook",
        "quality_score": 0.85,
        "violations_found": 2,  # Example: No memoization, recursive complexity
    }

    print("\n📝 Tracking pattern...", file=sys.stderr)
    pattern_id = tracker.track_pattern_creation(code, context)

    if pattern_id:
        print(f"\n✅ SUCCESS! Pattern tracked with ID: {pattern_id}", file=sys.stderr)
        print(f"   Context: {context['file_path']}", file=sys.stderr)
        print(f"   Quality: {context['quality_score']}", file=sys.stderr)
        return True
    else:
        print("\n❌ FAILED! Pattern was not tracked", file=sys.stderr)
        return False


def test_quality_calculation():
    """Test quality score calculation."""
    tracker = PatternTrackerSync()

    print("\n" + "=" * 60, file=sys.stderr)
    print("Testing Quality Score Calculation", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    test_cases = [
        ([], 1.0, "No violations"),
        (["violation1"], 0.9, "1 violation"),
        (["v1", "v2", "v3"], 0.7, "3 violations"),
        (
            ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"],
            0.0,
            "10 violations",
        ),
        (["v1"] * 15, 0.0, "15 violations (floor at 0.0)"),
    ]

    all_passed = True
    for violations, expected, description in test_cases:
        score = tracker.calculate_quality_score(violations)
        passed = score == expected
        all_passed = all_passed and passed
        status = "✅" if passed else "❌"
        print(
            f"{status} {description}: {score:.2f} (expected {expected:.2f})",
            file=sys.stderr,
        )

    return all_passed


if __name__ == "__main__":
    print("\n" + "=" * 60, file=sys.stderr)
    print("PatternTrackerSync Verification", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Run tests
    test1_passed = test_basic_tracking()
    test2_passed = test_quality_calculation()

    # Summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("Test Summary", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(
        f"Basic Tracking: {'✅ PASSED' if test1_passed else '❌ FAILED'}",
        file=sys.stderr,
    )
    print(
        f"Quality Calculation: {'✅ PASSED' if test2_passed else '❌ FAILED'}",
        file=sys.stderr,
    )

    if test1_passed and test2_passed:
        print("\n🎉 All tests passed!", file=sys.stderr)
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed", file=sys.stderr)
        sys.exit(1)
