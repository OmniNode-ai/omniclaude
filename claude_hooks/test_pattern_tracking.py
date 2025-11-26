#!/usr/bin/env python3
"""
Test script for pattern tracking end-to-end functionality.

This simulates the PostToolUse hook workflow to test data flow
from Claude Code hooks to Phase 4 APIs.
"""

import os
import sys
import tempfile
import uuid

from config import settings

from .pattern_tracker import get_tracker


def test_pattern_tracking():
    """Test end-to-end pattern tracking functionality."""
    print("=== Pattern Tracking End-to-End Test ===")

    try:
        # Import pattern tracker (already imported above)

        print("✓ Pattern tracker imported successfully")

        # Test pattern creation
        test_code = """
def calculate_fibonacci(n):
    \"\"\"Calculate Fibonacci sequence up to n.\"\"\"
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)

# Test function
result = calculate_fibonacci(10)
print(f"Result: {result}")
"""

        context = {
            "event_type": "pattern_created",
            "tool": "Write",
            "language": "python",
            "file_path": "/test/fibonacci.py",
            "session_id": "test-session-123",
        }

        metadata = {
            "author": "claude-code",
            "test": True,
            "purpose": "end-to-end validation",
        }

        # Get tracker and test pattern creation
        tracker = get_tracker()
        print(f"✓ Pattern tracker initialized (session: {tracker.session_id})")

        # Test the async method using asyncio.run()
        import asyncio

        pattern_id = asyncio.run(
            tracker.track_pattern_creation(
                code=test_code, context=context, metadata=metadata
            )
        )

        print("✓ Pattern creation tracked successfully")
        print(f"  - Pattern ID: {pattern_id}")
        print(f"  - Session ID: {tracker.session_id}")

        # Verify pattern ID format
        if pattern_id and len(pattern_id) == 64:  # SHA256 hex
            print("✓ Pattern ID format is correct (SHA256)")
        else:
            print(f"⚠ Pattern ID format unexpected: {pattern_id}")

        return True

    except Exception as e:
        print(f"✗ Pattern tracking test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_hook_simulation():
    """Test the actual PostToolUse hook workflow."""
    print("\n=== Hook Simulation Test ===")

    try:
        # Create a temporary Python file to trigger the hook
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            test_content = '''def test_function():
    """Test function for pattern tracking."""
    return "Pattern tracking test successful"

if __name__ == "__main__":
    print(test_function())
'''
            f.write(test_content)
            temp_file_path = f.name

        print(f"✓ Created test file: {temp_file_path}")

        # Simulate the PostToolUse workflow
        from post_tool_use_enforcer import load_config, track_pattern_for_file

        config = load_config()
        print("✓ Loaded configuration")

        # Test pattern tracking
        success = track_pattern_for_file(temp_file_path, config)

        if success:
            print("✓ Pattern tracking via hook simulation succeeded")
        else:
            print("✗ Pattern tracking via hook simulation failed")

        # Clean up
        os.unlink(temp_file_path)
        print("✓ Cleaned up test file")

        return success

    except Exception as e:
        print(f"✗ Hook simulation test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_direct_api():
    """Test direct API call to Phase 4 endpoint."""
    print("\n=== Direct API Test ===")

    try:
        import httpx

        # Test payload matching LineageTrackRequest schema
        test_payload = {
            "event_type": "pattern_created",
            "pattern_id": f"test-direct-api-{uuid.uuid4().hex[:8]}",
            "pattern_type": "code",
            "pattern_version": "1.0.0",
            "tool_name": "Write",
            "file_path": "/test/direct_api.py",
            "language": "python",
            "pattern_data": {
                "code": "print('Direct API test')",
                "session_id": "test-session-direct",
                "correlation_id": "corr-direct-001",
                "timestamp": "2025-10-04T13:20:00Z",
                "context": {"tool": "Write"},
                "metadata": {"test": True},
            },
            "triggered_by": "test-script",
            "reason": "Direct API test",
        }

        # Make direct API call
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{settings.archon_intelligence_url}/api/pattern-traceability/lineage/track",
                json=test_payload,
            )

            print(f"✓ API call completed with status: {response.status_code}")

            if response.status_code == 200:
                print("✓ Direct API call successful")
                print(f"  Response: {response.json()}")
                return True
            else:
                print(f"✗ API call failed: {response.text}")
                return False

    except Exception as e:
        print(f"✗ Direct API test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("Starting Pattern Tracking End-to-End Tests\n")

    results = {
        "pattern_tracking": test_pattern_tracking(),
        "hook_simulation": test_hook_simulation(),
        "direct_api": test_direct_api(),
    }

    print("\n=== Test Results Summary ===")
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name.replace('_', ' ').title()}: {status}")

    total_passed = sum(results.values())
    total_tests = len(results)

    print(f"\nOverall: {total_passed}/{total_tests} tests passed")

    if total_passed == total_tests:
        print("🎉 All tests passed! Pattern tracking is working end-to-end.")
        return 0
    else:
        print("⚠ Some tests failed. Check the output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
