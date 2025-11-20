#!/usr/bin/env python3
"""
Test Summary Generator - Display test coverage statistics.

Usage:
    python3 test_summary.py

Created: 2025-11-20
"""

import sys
from pathlib import Path


def count_test_functions(file_path):
    """Count test functions in a file."""
    content = file_path.read_text()
    return content.count("def test_")


def count_test_classes(file_path):
    """Count test classes in a file."""
    content = file_path.read_text()
    return content.count("class Test")


def main():
    """Generate test summary."""
    tests_dir = Path(__file__).parent
    test_files = sorted(tests_dir.glob("test_*.py"))

    print("=" * 70)
    print("System Status Skills - Test Coverage Summary")
    print("=" * 70)
    print()

    total_files = 0
    total_classes = 0
    total_functions = 0

    categories = {
        "Unit Tests": [],
        "Integration Tests": [],
        "Security Tests": [],
        "Other Tests": [],
    }

    # Categorize tests
    for test_file in test_files:
        name = test_file.stem

        if name in [
            "test_validators",
            "test_timeframe_parser",
            "test_helper_modules",
            "test_input_validation",
        ]:
            categories["Unit Tests"].append(test_file)
        elif name in [
            "test_sql_security",
            "test_sql_injection_prevention",
            "test_ssrf_protection",
        ]:
            categories["Security Tests"].append(test_file)
        elif name.startswith("test_check_") or name in [
            "test_generate_status_report",
            "test_diagnose_issues",
        ]:
            categories["Integration Tests"].append(test_file)
        else:
            categories["Other Tests"].append(test_file)

    # Print by category
    for category, files in categories.items():
        if not files:
            continue

        print(f"{category}:")
        print("-" * 70)

        for test_file in files:
            classes = count_test_classes(test_file)
            functions = count_test_functions(test_file)

            total_files += 1
            total_classes += classes
            total_functions += functions

            print(f"  {test_file.stem:40} {classes:2} classes, {functions:3} tests")

        print()

    # Summary
    print("=" * 70)
    print(f"Total Test Files:     {total_files}")
    print(f"Total Test Classes:   {total_classes}")
    print(f"Total Test Functions: {total_functions}")
    print("=" * 70)
    print()

    # Coverage targets
    print("Coverage Targets:")
    print("-" * 70)
    print("  Critical Paths (SQL, Input Validation):  90%+")
    print("  Error Handling:                          70%+")
    print("  Main Execution Paths:                    60%+")
    print("  Overall Target:                          60-70%")
    print()

    print("Run tests with:")
    print("  ./run_tests.sh              # All tests")
    print("  ./run_tests.sh --cov        # With coverage report")
    print("  pytest -v                   # Verbose output")
    print()


if __name__ == "__main__":
    main()
