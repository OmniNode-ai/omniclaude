#!/usr/bin/env python3
"""
Action Logging Integration Example

Demonstrates how to integrate action logging into agent code.
This shows the recommended patterns for logging all agent actions.

Usage:
    python action_logging_example.py
"""

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4


# Add agents/lib to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from action_logger import ActionLogger, log_action


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def example_agent_with_action_logging():
    """
    Example agent that demonstrates comprehensive action logging.
    """
    # Initialize action logger for this agent execution
    action_logger = ActionLogger(
        agent_name="agent-researcher",
        correlation_id=str(uuid4()),
        project_name="omniclaude",
        project_path=str(Path(__file__).parent.parent.parent.resolve()),
        working_directory=os.getcwd(),
        debug_mode=True,
    )

    logger.info(f"Agent started (correlation_id: {action_logger.correlation_id})")

    # Example 1: Log file read with context manager (automatic timing)
    logger.info("Example 1: File read with context manager")
    project_root = Path(__file__).parent.parent.parent.resolve()
    readme_path = str(project_root / "README.md")

    async with action_logger.tool_call(
        "Read",
        tool_parameters={
            "file_path": readme_path,
            "offset": 0,
            "limit": 100,
        },
    ) as action:
        # Simulate file reading
        await asyncio.sleep(0.02)  # 20ms

        # Simulate reading file
        file_path = readme_path
        if Path(file_path).exists():
            with open(file_path, "r") as f:
                content = f.read()

            action.set_result(
                {
                    "line_count": len(content.splitlines()),
                    "file_size_bytes": len(content),
                    "success": True,
                }
            )
            logger.info("✓ Read action logged with context manager")
        else:
            action.set_result({"success": False, "error": "File not found"})

    # Example 2: Log file write manually (with timing)
    logger.info("Example 2: File write with manual timing")
    start_time = time.time()

    # Simulate file writing with secure temp file
    temp_file = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".txt", prefix="test_output_"
    )
    temp_file_path = temp_file.name
    temp_file.close()

    await asyncio.sleep(0.03)  # 30ms

    duration_ms = int((time.time() - start_time) * 1000)

    await action_logger.log_tool_call(
        tool_name="Write",
        tool_parameters={"file_path": temp_file_path, "content_length": 2048},
        tool_result={"success": True, "bytes_written": 2048},
        duration_ms=duration_ms,
        success=True,
    )

    # Cleanup temp file
    try:
        os.unlink(temp_file_path)
    except Exception:
        pass

    logger.info("✓ Write action logged manually")

    # Example 3: Log agent decision
    logger.info("Example 3: Agent decision logging")
    start_time = time.time()

    # Simulate decision-making
    candidates = ["agent-api-architect", "agent-frontend-specialist"]
    await asyncio.sleep(0.01)  # 10ms
    selected_agent = "agent-api-architect"
    confidence = 0.92

    duration_ms = int((time.time() - start_time) * 1000)

    await action_logger.log_decision(
        decision_name="select_specialized_agent",
        decision_context={
            "user_request": "Design a REST API for user management",
            "candidates": candidates,
            "routing_strategy": "fuzzy_match",
        },
        decision_result={
            "selected_agent": selected_agent,
            "confidence": confidence,
            "reasoning": "API design keywords detected",
        },
        duration_ms=duration_ms,
    )
    logger.info("✓ Decision action logged")

    # Example 4: Log bash command execution
    logger.info("Example 4: Bash command execution")
    # Use secure temp directory for bash command examples
    temp_dir = tempfile.mkdtemp(prefix="bash_test_")
    async with action_logger.tool_call(
        "Bash",
        tool_parameters={
            "command": f"ls -la {temp_dir}",
            "working_directory": temp_dir,
        },
    ) as action:
        # Simulate bash execution
        await asyncio.sleep(0.05)  # 50ms

        action.set_result(
            {"exit_code": 0, "stdout_length": 1024, "stderr_length": 0, "success": True}
        )

        # Cleanup temp directory
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass

        logger.info("✓ Bash action logged")

    # Example 5: Log error
    logger.info("Example 5: Error logging")
    try:
        # Simulate an error
        raise ImportError("Module 'nonexistent_module' not found")
    except ImportError as e:
        await action_logger.log_error(
            error_type="ImportError",
            error_message=str(e),
            error_context={
                "file": __file__,
                "line": 150,
                "attempted_import": "nonexistent_module",
            },
        )
        logger.info("✓ Error action logged")

    # Example 6: Log task success
    logger.info("Example 6: Success logging")
    await action_logger.log_success(
        success_name="agent_task_completed",
        success_details={
            "files_processed": 5,
            "actions_taken": 10,
            "quality_score": 0.95,
        },
        duration_ms=250,
    )
    logger.info("✓ Success action logged")

    # Example 7: Log multiple tool calls in sequence
    logger.info("Example 7: Multiple tool calls in sequence")
    # Use secure temp directory for glob pattern examples
    glob_temp_dir = tempfile.mkdtemp(prefix="glob_test_")
    for i in range(3):
        async with action_logger.tool_call(
            "Glob", tool_parameters={"pattern": f"**/*.py", "path": glob_temp_dir}
        ) as action:
            await asyncio.sleep(0.01)
            action.set_result({"matches": 10 + i, "success": True})
        logger.info(f"✓ Glob action {i+1} logged")

    # Cleanup temp directory
    try:
        os.rmdir(glob_temp_dir)
    except Exception:
        pass

    logger.info(f"Agent completed (correlation_id: {action_logger.correlation_id})")
    logger.info("All actions logged successfully!")


async def example_one_off_action():
    """
    Example of using the convenience function for one-off action logging.
    """
    logger.info("\nExample 8: One-off action logging")

    project_root = Path(__file__).parent.parent.parent.resolve()
    await log_action(
        agent_name="agent-quick-task",
        action_type="tool_call",
        action_name="Grep",
        action_details={
            "pattern": "TODO",
            "file_path": f"{project_root}/**/*.py",
            "matches": 42,
        },
        correlation_id=str(uuid4()),
        duration_ms=15,
        project_name="omniclaude",
    )

    logger.info("✓ One-off action logged")


async def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Action Logging Integration Example")
    logger.info("=" * 60)

    # Run example agent with comprehensive logging
    await example_agent_with_action_logging()

    # Run one-off example
    await example_one_off_action()

    logger.info("\n" + "=" * 60)
    logger.info("Example completed successfully!")
    logger.info("=" * 60)
    logger.info("\nNext steps:")
    logger.info("1. Check Kafka topic 'agent-actions' for published events")
    logger.info(
        "2. Verify consumer is running: docker ps | grep agent-actions-consumer"
    )
    logger.info(
        "3. Query database: SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT 20;"
    )


if __name__ == "__main__":
    asyncio.run(main())
