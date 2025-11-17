#!/usr/bin/env python3
"""
Basic Action Logging Usage Example

Copy-paste ready code for integrating action logging into agents.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

# Add project root and agents/lib to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root / "agents" / "lib"))
sys.path.insert(0, str(project_root))

# Load environment from .env file
from dotenv import load_dotenv

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ Loaded .env from {env_path}")
    print(
        f"  KAFKA_BOOTSTRAP_SERVERS={os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'not set')}"
    )
else:
    print(f"⚠️  .env not found at {env_path}, using defaults")

from action_logger import ActionLogger


async def example_agent():
    """Example agent with action logging."""

    # 1. Initialize logger at agent startup
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    logger = ActionLogger(
        agent_name="agent-example",
        correlation_id=str(uuid4()),  # Get from agent context in production
        project_name="omniclaude",
        project_path=str(project_root),
        working_directory=os.getcwd(),
        debug_mode=True,
    )

    print(f"Agent started (correlation_id: {logger.correlation_id})")

    # 2. Log tool call with context manager (automatic timing)
    async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
        # Your tool execution here
        await asyncio.sleep(0.02)  # Simulate work

        # Set result before exiting context
        action.set_result({"line_count": 100, "file_size_bytes": 5432, "success": True})

    print("✓ Tool call logged")

    # 3. Log decision
    await logger.log_decision(
        decision_name="select_agent",
        decision_context={
            "user_request": "Design a REST API",
            "candidates": ["agent-api", "agent-frontend"],
        },
        decision_result={
            "selected": "agent-api",
            "confidence": 0.92,
            "reasoning": "API keywords detected",
        },
        duration_ms=15,
    )

    print("✓ Decision logged")

    # 4. Log error
    try:
        raise ValueError("Example error")
    except ValueError as e:
        await logger.log_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_context={"file": __file__, "operation": "example_operation"},
        )

    print("✓ Error logged")

    # 5. Log success
    await logger.log_success(
        success_name="task_completed",
        success_details={"files_processed": 5, "quality_score": 0.95},
        duration_ms=250,
    )

    print("✓ Success logged")
    print(f"\nAll actions logged! Correlation ID: {logger.correlation_id}")


if __name__ == "__main__":
    asyncio.run(example_agent())
