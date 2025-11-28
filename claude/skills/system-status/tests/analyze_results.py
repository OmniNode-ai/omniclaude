#!/usr/bin/env python3
"""Analyze test results and categorize failures."""

import os
import re
import sys
from collections import defaultdict


# Read the test results file
if not os.path.exists("test_results_full.txt"):
    print("Error: test_results_full.txt not found")
    sys.exit(1)

with open("test_results_full.txt", "r") as f:
    content = f.read()

# Extract test results
test_pattern = r"(test_\w+\.py)::(Test\w+)::(test_\w+) (PASSED|FAILED|ERROR)"
tests = re.findall(test_pattern, content)

# Categorize results
by_file = defaultdict(lambda: {"passed": [], "failed": [], "errors": []})
by_error_type = defaultdict(list)

for file, test_class, test_name, result in tests:
    full_name = f"{test_class}::{test_name}"
    if result == "PASSED":
        by_file[file]["passed"].append(full_name)
    elif result == "FAILED":
        by_file[file]["failed"].append(full_name)
    elif result == "ERROR":
        by_file[file]["errors"].append(full_name)

# Extract error types from failures
error_pattern = r"(ImportError|AttributeError|SystemExit|AssertionError|Failed): (.+)"
errors = re.findall(error_pattern, content)

for error_type, message in errors:
    by_error_type[error_type].append(message[:100])  # First 100 chars

# Print summary
print("# Test Results by File\n")
for file in sorted(by_file.keys()):
    data = by_file[file]
    total = len(data["passed"]) + len(data["failed"]) + len(data["errors"])
    passed = len(data["passed"])
    failed = len(data["failed"])
    errored = len(data["errors"])

    status = "✅" if failed == 0 and errored == 0 else "❌"
    print(
        f"{status} **{file}**: {passed}/{total} passed ({failed} failed, {errored} errors)"
    )

print("\n# Error Type Summary\n")
for error_type, messages in sorted(
    by_error_type.items(), key=lambda x: len(x[1]), reverse=True
):
    print(f"- **{error_type}**: {len(messages)} occurrences")
    # Show unique error messages
    unique_msgs = list(set(messages))[:3]
    for msg in unique_msgs:
        print(f"  - {msg}")

print("\n# Statistics\n")
total_tests = sum(
    len(data["passed"]) + len(data["failed"]) + len(data["errors"])
    for data in by_file.values()
)
total_passed = sum(len(data["passed"]) for data in by_file.values())
total_failed = sum(len(data["failed"]) for data in by_file.values())
total_errors = sum(len(data["errors"]) for data in by_file.values())
pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0

print(f"- Total Tests: {total_tests}")
print(f"- Passed: {total_passed} ({pass_rate:.1f}%)")
print(f"- Failed: {total_failed}")
print(f"- Errors: {total_errors}")
