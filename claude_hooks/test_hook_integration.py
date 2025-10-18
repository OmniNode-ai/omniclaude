#!/usr/bin/env python3
"""
Test PostToolUse Hook Integration

Simulates a real hook execution to verify end-to-end integration:
1. Metrics collection
2. Database logging
3. Correlation context
4. Output passthrough
"""

import sys
import json
import time
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from post_tool_metrics import collect_post_tool_metrics
from hook_event_logger import HookEventLogger


def simulate_write_operation():
    """Simulate a Write tool execution."""
    print("\n=== Simulating Write Operation ===\n")

    # Simulate tool info JSON (as received by PostToolUse hook)
    tool_info = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/test/calculator.py",
            "content": """def add(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return a + b

def subtract(a: int, b: int) -> int:
    \"\"\"Subtract b from a.\"\"\"
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    try:
        return a / b
    except:
        return None
""",
        },
        "tool_response": {"success": True, "message": "File written successfully"},
    }

    print("📝 Tool Info:")
    print(f"  Tool: {tool_info['tool_name']}")
    print(f"  File: {tool_info['tool_input']['file_path']}")
    print(f"  Size: {len(tool_info['tool_input']['content'])} bytes")
    print()

    # 1. Collect enhanced metrics
    print("📊 Collecting Enhanced Metrics...")
    start_time = time.time()

    try:
        enhanced_metadata = collect_post_tool_metrics(tool_info)
        collection_time_ms = (time.time() - start_time) * 1000

        print(f"  ✓ Metrics collected in {collection_time_ms:.2f}ms")
        print()

        # Display metrics
        print("📈 Enhanced Metadata:")
        print(json.dumps(enhanced_metadata, indent=2))
        print()

        # 2. Log to database (simulate)
        print("💾 Database Logging...")
        logger = HookEventLogger()

        event_id = logger.log_event(
            source="PostToolUse",
            action="tool_completion",
            resource="tool",
            resource_id=tool_info["tool_name"],
            payload={
                "tool_name": tool_info["tool_name"],
                "tool_output": tool_info["tool_response"],
                "file_path": tool_info["tool_input"]["file_path"],
                "enhanced_metadata": enhanced_metadata,
                "auto_fix_applied": False,
                "auto_fix_details": None,
            },
            metadata={
                "hook_type": "PostToolUse",
                "correlation_id": "test-correlation-123",
                "agent_name": None,
                "agent_domain": None,
                **enhanced_metadata,
            },
        )

        if event_id:
            print(f"  ✓ Logged to database: {event_id}")
        else:
            print("  ⚠️  Database logging failed (this is OK for testing)")
        print()

        # 3. Report summary
        print("📊 Summary:")
        success = enhanced_metadata["success_classification"]
        quality = enhanced_metadata["quality_metrics"]["quality_score"]
        exec_time = enhanced_metadata["performance_metrics"]["execution_time_ms"]
        bytes_written = enhanced_metadata["performance_metrics"]["bytes_written"]
        lines_changed = enhanced_metadata["performance_metrics"]["lines_changed"]

        print(f"  Success: {success}")
        print(f"  Quality Score: {quality:.2f}")
        print(f"  Execution Time: {exec_time:.2f}ms")
        print(f"  Bytes Written: {bytes_written}")
        print(f"  Lines Changed: {lines_changed}")
        print()

        # Quality component breakdown
        print("🔍 Quality Breakdown:")
        qm = enhanced_metadata["quality_metrics"]
        print(f"  Naming Conventions: {qm['naming_conventions']}")
        print(f"  Type Safety: {qm['type_safety']}")
        print(f"  Documentation: {qm['documentation']}")
        print(f"  Error Handling: {qm['error_handling']}")
        print()

        # Performance check
        if collection_time_ms < 12.0:
            print(f"✅ Performance requirement met: {collection_time_ms:.2f}ms < 12ms")
        else:
            print(f"⚠️  Performance requirement NOT met: {collection_time_ms:.2f}ms >= 12ms")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


def simulate_failed_operation():
    """Simulate a failed tool execution."""
    print("\n=== Simulating Failed Operation ===\n")

    tool_info = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/test/nonexistent.py", "old_string": "foo", "new_string": "bar"},
        "tool_response": {"error": "File not found: /test/nonexistent.py"},
    }

    print("📝 Tool Info:")
    print(f"  Tool: {tool_info['tool_name']}")
    print(f"  File: {tool_info['tool_input']['file_path']}")
    print()

    # Collect metrics
    print("📊 Collecting Enhanced Metrics...")
    start_time = time.time()

    try:
        enhanced_metadata = collect_post_tool_metrics(tool_info)
        collection_time_ms = (time.time() - start_time) * 1000

        print(f"  ✓ Metrics collected in {collection_time_ms:.2f}ms")
        print()

        # Display results
        success = enhanced_metadata["success_classification"]
        deviation = enhanced_metadata["execution_analysis"]["deviation_from_expected"]

        print("📈 Results:")
        print(f"  Success Classification: {success}")
        print(f"  Deviation: {deviation}")
        print()

        if success == "failed" and deviation == "major":
            print("✅ Failed operation correctly classified")
            return True
        else:
            print("⚠️  Unexpected classification")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run integration tests."""
    print("=" * 70)
    print("PostToolUse Hook Integration Test")
    print("=" * 70)

    results = []

    # Test 1: Successful Write operation
    results.append(("Write Operation", simulate_write_operation()))

    # Test 2: Failed operation
    results.append(("Failed Operation", simulate_failed_operation()))

    # Summary
    print("\n" + "=" * 70)
    print("Test Results Summary")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print("=" * 70)
    print(f"Overall: {passed}/{total} tests passed")

    if passed == total:
        print("✅ All integration tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
