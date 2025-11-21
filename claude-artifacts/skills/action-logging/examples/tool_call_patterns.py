#!/usr/bin/env python3
"""
Tool Call Logging Patterns

Common patterns for logging tool calls with ActionLogger.
"""

import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "agents" / "lib"))

from action_logger import ActionLogger


async def pattern_examples():
    """Demonstrate common tool call logging patterns."""

    logger = ActionLogger(agent_name="agent-tool-examples", correlation_id=str(uuid4()))

    # Pattern 1: Context Manager (Recommended)
    print("Pattern 1: Context Manager")
    async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
        # Your tool execution
        await asyncio.sleep(0.01)
        result = "file content here"

        # Set result
        action.set_result({"line_count": len(result.splitlines()), "success": True})
    print("✓ Logged with automatic timing\n")

    # Pattern 2: Manual Timing
    print("Pattern 2: Manual Timing")
    start_time = time.time()

    # Your tool execution
    await asyncio.sleep(0.02)
    result = "output data"

    duration_ms = int((time.time() - start_time) * 1000)

    await logger.log_tool_call(
        tool_name="Write",
        tool_parameters={"file_path": "/tmp/output.txt"},
        tool_result={"success": True, "bytes_written": len(result)},
        duration_ms=duration_ms,
    )
    print("✓ Logged with manual timing\n")

    # Pattern 3: Error Handling in Context Manager
    print("Pattern 3: Error Handling")
    try:
        async with logger.tool_call("Bash", {"command": "ls /missing"}) as action:
            # Simulate error
            raise FileNotFoundError("/missing does not exist")
    except FileNotFoundError:
        pass  # Error automatically logged by context manager
    print("✓ Error automatically logged\n")

    # Pattern 4: Batch Operations
    print("Pattern 4: Batch Operations")
    files = ["file1.py", "file2.py", "file3.py"]

    for file_path in files:
        async with logger.tool_call(
            "Glob", {"pattern": "*.py", "file": file_path}
        ) as action:
            await asyncio.sleep(0.005)
            action.set_result({"matches": 10, "file": file_path})

    print(f"✓ Logged {len(files)} tool calls\n")

    # Pattern 5: Conditional Logging
    print("Pattern 5: Conditional Success/Failure")
    operation_succeeded = False

    async with logger.tool_call("Edit", {"file_path": "/path/to/file.py"}) as action:
        await asyncio.sleep(0.01)

        # Determine success
        operation_succeeded = True

        action.set_result(
            {
                "success": operation_succeeded,
                "lines_changed": 5 if operation_succeeded else 0,
            }
        )

    print("✓ Logged with conditional result\n")

    print("All patterns demonstrated!")


if __name__ == "__main__":
    asyncio.run(pattern_examples())
