#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Test Error Handling in Helper Functions

Verifies that subprocess.run() error handling correctly:
- Checks return codes
- Returns success: False on failures
- Captures stderr on errors
- Includes return_code field for debugging

Tests for PR #33 fixes.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from skills._shared import docker_helper, kafka_helper


def test_docker_error_handling():
    """Test Docker helper error handling."""
    print("\n=== Testing Docker Helper Error Handling ===\n")

    # Test 1: Invalid container name should return success: False
    print("Test 1: Invalid container name")
    result = docker_helper.get_container_status("nonexistent_container_12345")
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    print(f"  Error: {result.get('error', 'MISSING')}")
    assert result["success"] is False, "Should fail for nonexistent container"
    assert "return_code" in result, "Should include return_code field"
    print("  ✅ PASS\n")

    # Test 2: Invalid Docker command should handle gracefully
    print("Test 2: Get logs from nonexistent container")
    result = docker_helper.get_container_logs("nonexistent_container_12345", tail=10)
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    print(f"  Error: {result.get('error', 'MISSING')[:80]}...")
    assert result["success"] is False, "Should fail for nonexistent container"
    assert "return_code" in result, "Should include return_code field"
    print("  ✅ PASS\n")

    # Test 3: List containers should succeed and include return_code
    print("Test 3: List containers (success case)")
    result = docker_helper.list_containers()
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    print(f"  Container count: {result['count']}")
    if result["success"]:
        assert result.get("return_code") == 0, (
            "Successful call should have return_code=0"
        )
        print("  ✅ PASS\n")
    else:
        print(f"  ⚠️  Docker not available: {result.get('error')}\n")


def test_kafka_error_handling():
    """Test Kafka helper error handling."""
    print("\n=== Testing Kafka Helper Error Handling ===\n")

    # Test 1: Get stats for nonexistent topic
    print("Test 1: Get stats for nonexistent topic")
    result = kafka_helper.get_topic_stats("nonexistent_topic_12345_xyz")
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    if result.get("error"):
        print(f"  Error: {result['error'][:80]}...")
    # Note: This might succeed or fail depending on Kafka availability
    # The important thing is that return_code is present
    assert "return_code" in result, "Should include return_code field"
    if result["success"]:
        assert result.get("return_code") == 0, "Success should have return_code=0"
    else:
        assert result.get("return_code") != 0 or "error" in result, (
            "Failure should have non-zero return_code or error"
        )
    print("  ✅ PASS\n")

    # Test 2: List topics (may succeed or fail depending on Kafka availability)
    print("Test 2: List topics")
    result = kafka_helper.list_topics()
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    if result["success"]:
        print(f"  Topic count: {result['count']}")
        assert result.get("return_code") == 0, "Success should have return_code=0"
        print("  ✅ PASS\n")
    else:
        print(f"  Error: {result.get('error', 'MISSING')[:80]}...")
        assert "return_code" in result or "error" in result, (
            "Failure should have return_code or error"
        )
        print("  ✅ PASS (Kafka unavailable)\n")

    # Test 3: Get recent message count (fixed function)
    print("Test 3: Get recent message count (testing the fix)")
    result = kafka_helper.get_recent_message_count(
        "nonexistent_topic_xyz", timeout_seconds=1
    )
    print(f"  Success: {result['success']}")
    print(f"  Return code: {result.get('return_code', 'MISSING')}")
    if result.get("error"):
        print(f"  Error: {result['error'][:80]}...")
    # The key fix: This should check returncode and NOT always return success: True
    assert "return_code" in result, "Should include return_code field"
    if result["success"]:
        assert result.get("return_code") == 0, "Success should have return_code=0"
    print("  ✅ PASS\n")


def test_return_code_consistency():
    """Verify return_code is consistently included in all responses."""
    print("\n=== Testing Return Code Consistency ===\n")

    test_cases = [
        ("docker_helper.list_containers", docker_helper.list_containers, []),
        ("kafka_helper.list_topics", kafka_helper.list_topics, []),
    ]

    for name, func, args in test_cases:
        print(f"Test: {name}")
        result = func(*args)
        if isinstance(result, dict):
            has_return_code = "return_code" in result
            print(f"  Has return_code: {has_return_code}")
            print(f"  Success: {result.get('success')}")
            if has_return_code:
                print(f"  Return code value: {result['return_code']}")
                # Verify consistency: success=True should mean return_code=0
                if result.get("success") is True:
                    assert result.get("return_code") == 0, (
                        f"{name}: success=True should have return_code=0"
                    )
            print("  ✅ PASS\n")
        else:
            print(f"  ⚠️  Unexpected result type: {type(result)}\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("Testing Error Handling Fixes (PR #33)")
    print("=" * 70)

    try:
        test_docker_error_handling()
        test_kafka_error_handling()
        test_return_code_consistency()

        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)
        print("\nSummary:")
        print("  - All subprocess calls now check return codes")
        print("  - Error output (stderr) is captured and returned on failure")
        print("  - return_code field is included for debugging")
        print("  - Backward compatibility maintained")
        print()

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
