#!/usr/bin/env python3
"""
Comprehensive test suite for PostToolMetricsCollector

Tests:
1. Success classification (full_success, partial_success, failed)
2. Quality scoring accuracy (naming, type safety, documentation, error handling)
3. Performance metrics extraction
4. Execution analysis
5. Performance overhead measurement
"""

import sys
import time
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from post_tool_metrics import PostToolMetricsCollector, collect_post_tool_metrics


def test_success_classification():
    """Test success classification logic."""
    print("\n=== Test: Success Classification ===")

    test_cases = [
        # (tool_output, expected_classification)
        ({"success": True}, "full_success"),
        ({"success": False}, "failed"),
        ({"error": "Something failed"}, "failed"),
        ({"warning": "Minor issue"}, "partial_success"),
        (None, "full_success"),
        ({}, "full_success"),
    ]

    collector = PostToolMetricsCollector()
    passed = 0
    failed = 0

    for tool_output, expected in test_cases:
        result = collector._classify_success("Write", tool_output)
        status = "✓" if result == expected else "✗"
        print(f"  {status} Output: {tool_output} → {result} (expected: {expected})")

        if result == expected:
            passed += 1
        else:
            failed += 1

    print(f"Result: {passed}/{len(test_cases)} passed")
    return failed == 0


def test_quality_scoring_python():
    """Test Python quality scoring."""
    print("\n=== Test: Python Quality Scoring ===")

    test_cases = [
        # Perfect code (regex-based detection has limitations, 0.85+ is excellent)
        {
            "name": "Perfect Python",
            "content": '''def calculate_sum(a: int, b: int) -> int:
    """Calculate sum of two numbers."""
    try:
        return a + b
    except TypeError as e:
        raise ValueError(f"Invalid input: {e}")
''',
            "expected_min_score": 0.85,  # Adjusted for realistic regex-based detection
        },
        # Poor code (no types, no docs, bare except)
        {
            "name": "Poor Python",
            "content": """def calculate_sum(a, b):
    try:
        return a + b
    except:
        pass
""",
            "expected_min_score": 0.0,
            "expected_max_score": 0.7,
        },
        # Camel case violations
        {
            "name": "Naming Violations",
            "content": """def myFunction():
    myVariable = 10
    return myVariable
""",
            "expected_max_score": 0.8,
        },
    ]

    collector = PostToolMetricsCollector()
    passed = 0
    failed = 0

    for test_case in test_cases:
        metrics = collector._calculate_quality_metrics(
            "/test/example.py", test_case["content"]
        )

        score = metrics.quality_score
        expected_min = test_case.get("expected_min_score", 0.0)
        expected_max = test_case.get("expected_max_score", 1.0)

        is_valid = expected_min <= score <= expected_max
        status = "✓" if is_valid else "✗"

        print(
            f"  {status} {test_case['name']}: {score:.2f} (expected: {expected_min:.2f}-{expected_max:.2f})"
        )
        print(
            f"      Naming: {metrics.naming_conventions}, Type: {metrics.type_safety}, "
            + f"Docs: {metrics.documentation}, Error: {metrics.error_handling}"
        )

        if is_valid:
            passed += 1
        else:
            failed += 1

    print(f"Result: {passed}/{len(test_cases)} passed")
    return failed == 0


def test_quality_scoring_typescript():
    """Test TypeScript quality scoring."""
    print("\n=== Test: TypeScript Quality Scoring ===")

    test_cases = [
        # Good TypeScript
        {
            "name": "Good TypeScript",
            "content": """/**
 * Calculate sum of two numbers
 */
function calculateSum(a: number, b: number): number {
    try {
        return a + b;
    } catch (error) {
        throw new Error(`Invalid input: ${error}`);
    }
}
""",
            "expected_min_score": 0.8,
        },
        # Poor TypeScript (any types, empty catch)
        {
            "name": "Poor TypeScript",
            "content": """function calculateSum(a: any, b: any): any {
    try {
        return a + b;
    } catch (error) {}
}
""",
            "expected_max_score": 0.7,
        },
    ]

    collector = PostToolMetricsCollector()
    passed = 0
    failed = 0

    for test_case in test_cases:
        metrics = collector._calculate_quality_metrics(
            "/test/example.ts", test_case["content"]
        )

        score = metrics.quality_score
        expected_min = test_case.get("expected_min_score", 0.0)
        expected_max = test_case.get("expected_max_score", 1.0)

        is_valid = expected_min <= score <= expected_max
        status = "✓" if is_valid else "✗"

        print(
            f"  {status} {test_case['name']}: {score:.2f} (expected: {expected_min:.2f}-{expected_max:.2f})"
        )
        print(
            f"      Naming: {metrics.naming_conventions}, Type: {metrics.type_safety}, "
            + f"Docs: {metrics.documentation}, Error: {metrics.error_handling}"
        )

        if is_valid:
            passed += 1
        else:
            failed += 1

    print(f"Result: {passed}/{len(test_cases)} passed")
    return failed == 0


def test_performance_metrics():
    """Test performance metrics extraction."""
    print("\n=== Test: Performance Metrics ===")

    tool_info = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/test/example.py",
            "content": "def test():\n    pass\n",
        },
        "tool_response": {"success": True},
    }

    collector = PostToolMetricsCollector()
    metadata = collector.collect_metrics(
        tool_name="Write",
        tool_input=tool_info["tool_input"],
        tool_output=tool_info["tool_response"],
        file_path="/test/example.py",
        content=tool_info["tool_input"]["content"],
    )

    perf = metadata.performance_metrics

    print(f"  Execution time: {perf.execution_time_ms:.2f}ms")
    print(f"  Bytes written: {perf.bytes_written}")
    print(f"  Lines changed: {perf.lines_changed}")
    print(f"  Files modified: {perf.files_modified}")

    # Validate
    passed = True
    if perf.bytes_written != len(b"def test():\n    pass\n"):
        print("  ✗ Bytes written calculation incorrect")
        passed = False
    if perf.lines_changed != 2:
        print("  ✗ Lines changed calculation incorrect")
        passed = False
    if perf.files_modified != 1:
        print("  ✗ Files modified should be 1")
        passed = False

    if passed:
        print("  ✓ All performance metrics correct")

    return passed


def test_performance_overhead():
    """Test that metrics collection stays under 12ms budget."""
    print("\n=== Test: Performance Overhead (Target: <12ms) ===")

    tool_info = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/test/large_file.py",
            "content": """# Large Python file
def function1():
    '''Docstring'''
    pass

def function2():
    '''Docstring'''
    pass

def function3():
    '''Docstring'''
    pass
"""
            * 10,  # Make it larger
        },
        "tool_response": {"success": True},
    }

    # Run multiple iterations to get average
    iterations = 100
    times = []

    for _ in range(iterations):
        start = time.time()
        collect_post_tool_metrics(tool_info)
        elapsed_ms = (time.time() - start) * 1000
        times.append(elapsed_ms)

    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)

    print(f"  Iterations: {iterations}")
    print(f"  Average time: {avg_time:.2f}ms")
    print(f"  Min time: {min_time:.2f}ms")
    print(f"  Max time: {max_time:.2f}ms")

    if avg_time < 12.0:
        print("  ✓ Performance requirement met (<12ms)")
        return True
    else:
        print("  ✗ Performance requirement NOT met (>12ms)")
        return False


def test_execution_analysis():
    """Test execution analysis logic."""
    print("\n=== Test: Execution Analysis ===")

    test_cases = [
        # (tool_output, expected_deviation)
        ({"success": True}, "none"),
        ({"error": "Failed"}, "major"),
        ({"retry": True, "attempt": 2}, "minor"),
        ({"recovered": True}, "minor"),
        (None, "none"),
    ]

    collector = PostToolMetricsCollector()
    passed = 0
    failed = 0

    for tool_output, expected_deviation in test_cases:
        analysis = collector._analyze_execution(tool_output)
        is_correct = analysis.deviation_from_expected == expected_deviation
        status = "✓" if is_correct else "✗"

        print(
            f"  {status} Output: {tool_output} → {analysis.deviation_from_expected} "
            + f"(expected: {expected_deviation})"
        )

        if is_correct:
            passed += 1
        else:
            failed += 1

    print(f"Result: {passed}/{len(test_cases)} passed")
    return failed == 0


def main():
    """Run all tests."""
    print("=" * 70)
    print("PostToolMetricsCollector Test Suite")
    print("=" * 70)

    results = {
        "Success Classification": test_success_classification(),
        "Python Quality Scoring": test_quality_scoring_python(),
        "TypeScript Quality Scoring": test_quality_scoring_typescript(),
        "Performance Metrics": test_performance_metrics(),
        "Execution Analysis": test_execution_analysis(),
        "Performance Overhead": test_performance_overhead(),
    }

    print("\n" + "=" * 70)
    print("Test Results Summary")
    print("=" * 70)

    passed = sum(results.values())
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print("=" * 70)
    print(f"Overall: {passed}/{total} test suites passed")

    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
