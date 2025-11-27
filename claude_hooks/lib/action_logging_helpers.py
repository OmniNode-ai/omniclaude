#!/usr/bin/env python3
"""
Action Logging Helpers - Convenient wrappers for error and success logging

Provides easy-to-use functions for logging agent errors and successes to Kafka
from hooks and Python scripts. Automatically handles correlation IDs, timing,
and formatting.

Usage from hooks:
    # Error logging
    python3 -c "
    import sys
    sys.path.insert(0, '$HOOK_DIR/lib')
    from action_logging_helpers import log_error
    log_error(
        agent_name='polymorphic-agent',
        error_type='ToolExecutionError',
        error_message='Read tool failed',
        error_context={'file_path': '/path/to/file.py', 'error': 'FileNotFoundError'},
        correlation_id='$CORRELATION_ID'
    )
    "

    # Success logging
    python3 -c "
    import sys
    sys.path.insert(0, '$HOOK_DIR/lib')
    from action_logging_helpers import log_success
    log_success(
        agent_name='polymorphic-agent',
        success_type='TaskCompleted',
        success_message='Code generation completed',
        success_context={'files_created': 5, 'tests_passed': 12},
        correlation_id='$CORRELATION_ID'
    )
    "

Usage from Python:
    from action_logging_helpers import log_error, log_success

    # Log error
    log_error(
        agent_name="agent-researcher",
        error_type="DatabaseConnectionError",
        error_message="Failed to connect to PostgreSQL",
        error_context={"host": "192.168.86.200", "port": 5436},
        correlation_id="abc-123"
    )

    # Log success
    log_success(
        agent_name="agent-coder",
        success_type="CodeGenerationCompleted",
        success_message="Generated 3 ONEX nodes successfully",
        success_context={"nodes": ["NodeEffect", "NodeCompute", "NodeReducer"]},
        correlation_id="abc-123"
    )

Features:
- Automatic correlation ID generation if not provided
- JSON serialization of complex context objects
- Graceful degradation if Kafka unavailable
- Non-blocking async publishing
- Integration with execute_kafka.py for consistent logging
"""

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


def get_correlation_id() -> str:
    """
    Get or generate correlation ID.

    Returns:
        Correlation ID string
    """
    # Try to get from environment (set by hooks)
    corr_id = os.environ.get("CORRELATION_ID")
    if corr_id:
        return corr_id

    # Try to get from correlation_manager
    try:
        from correlation_manager import get_correlation_context

        context = get_correlation_context()
        if context and "correlation_id" in context:
            return str(context["correlation_id"])
    except Exception:
        pass

    # Generate new UUID
    return str(uuid4())


def get_agent_name() -> str:
    """
    Get agent name from environment or context.

    Returns:
        Agent name string (default: "polymorphic-agent")
    """
    # Try environment
    agent_name = os.environ.get("AGENT_NAME")
    if agent_name:
        return agent_name

    # Try correlation context
    try:
        from correlation_manager import get_correlation_context

        context = get_correlation_context()
        if context and "agent_name" in context:
            return str(context["agent_name"])
    except Exception:
        pass

    return "polymorphic-agent"


def get_action_log_timeout() -> float:
    """
    Get configurable timeout for action logging subprocess calls.

    Returns:
        Timeout in seconds (default: 10.0)
    """
    try:
        timeout_seconds = float(os.getenv("ACTION_LOG_TIMEOUT_SECONDS", "10"))
    except (TypeError, ValueError):
        timeout_seconds = 10.0

    return timeout_seconds


def log_error(
    agent_name: Optional[str] = None,
    error_type: str = "UnknownError",
    error_message: str = "",
    error_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
) -> bool:
    """
    Log an error event to Kafka via execute_kafka.py.

    Args:
        agent_name: Agent name (auto-detected if not provided)
        error_type: Type of error (e.g., "ToolExecutionError", "DatabaseConnectionError")
        error_message: Human-readable error message
        error_context: Additional context as dictionary (auto-serialized to JSON)
        correlation_id: Correlation ID (auto-generated if not provided)
        duration_ms: How long the failed operation took in milliseconds
        project_path: Absolute path to project directory
        project_name: Project name
        on_failure: Optional callback invoked if publishing fails

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        # With failure callback for debugging
        def handle_logging_failure(error: Exception):
            logger.warning(f"Failed to log error action: {error}")

        log_error(
            error_type="DatabaseConnectionError",
            error_message="Failed to connect to PostgreSQL",
            error_context={"host": "192.168.86.200"},
            on_failure=handle_logging_failure
        )
    """
    # Auto-detect agent name and correlation ID if not provided
    agent_name = agent_name or get_agent_name()
    correlation_id = correlation_id or get_correlation_id()

    # Build error details JSON
    error_details = {
        "error_type": error_type,
        "error_message": error_message,
        "error_context": error_context or {},
        "traceback": traceback.format_exc() if sys.exc_info()[0] else None,
    }

    # Call execute_kafka.py to publish error event
    try:
        skill_path = (
            Path.home()
            / ".claude"
            / "skills"
            / "agent-tracking"
            / "log-agent-action"
            / "execute_kafka.py"
        )

        if not skill_path.exists():
            print(
                f"Warning: execute_kafka.py not found at {skill_path}", file=sys.stderr
            )
            return False

        # Build command arguments
        cmd = [
            sys.executable,
            str(skill_path),
            "--agent",
            agent_name,
            "--action-type",
            "error",
            "--action-name",
            error_type,
            "--details",
            json.dumps(error_details),
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        # Add optional arguments
        if duration_ms is not None:
            cmd.extend(["--duration-ms", str(duration_ms)])
        if project_path:
            cmd.extend(["--project-path", project_path])
        if project_name:
            cmd.extend(["--project-name", project_name])

        # Execute (non-blocking)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=get_action_log_timeout(),
        )

        if result.returncode == 0:
            return True
        else:
            print(f"Error logging failed: {result.stderr}", file=sys.stderr)
            return False

    except Exception as e:
        if on_failure:
            on_failure(e)
        print(f"Failed to log error: {e}", file=sys.stderr)
        return False


def log_success(
    agent_name: Optional[str] = None,
    success_type: str = "TaskCompleted",
    success_message: str = "",
    success_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    quality_score: Optional[float] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
) -> bool:
    """
    Log a success event to Kafka via execute_kafka.py.

    Args:
        agent_name: Agent name (auto-detected if not provided)
        success_type: Type of success (e.g., "TaskCompleted", "WorkflowCompleted")
        success_message: Human-readable success message
        success_context: Additional context as dictionary (auto-serialized to JSON)
        correlation_id: Correlation ID (auto-generated if not provided)
        duration_ms: How long the successful operation took in milliseconds
        quality_score: Quality score (0.0 to 1.0)
        project_path: Absolute path to project directory
        project_name: Project name
        on_failure: Optional callback invoked if publishing fails

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        # With failure callback for debugging
        def handle_logging_failure(error: Exception):
            logger.warning(f"Failed to log success action: {error}")

        log_success(
            success_type="TaskCompleted",
            success_message="Generated 3 ONEX nodes successfully",
            success_context={"nodes": ["NodeEffect", "NodeCompute", "NodeReducer"]},
            quality_score=0.95,
            on_failure=handle_logging_failure
        )
    """
    # Auto-detect agent name and correlation ID if not provided
    agent_name = agent_name or get_agent_name()
    correlation_id = correlation_id or get_correlation_id()

    # Build success details JSON
    success_details: Dict[str, Any] = {
        "success_type": success_type,
        "success_message": success_message,
        "success_context": success_context or {},
    }

    if quality_score is not None:
        success_details["quality_score"] = quality_score

    # Call execute_kafka.py to publish success event
    try:
        skill_path = (
            Path.home()
            / ".claude"
            / "skills"
            / "agent-tracking"
            / "log-agent-action"
            / "execute_kafka.py"
        )

        if not skill_path.exists():
            print(
                f"Warning: execute_kafka.py not found at {skill_path}", file=sys.stderr
            )
            return False

        # Build command arguments
        cmd = [
            sys.executable,
            str(skill_path),
            "--agent",
            agent_name,
            "--action-type",
            "success",
            "--action-name",
            success_type,
            "--details",
            json.dumps(success_details),
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        # Add optional arguments
        if duration_ms is not None:
            cmd.extend(["--duration-ms", str(duration_ms)])
        if project_path:
            cmd.extend(["--project-path", project_path])
        if project_name:
            cmd.extend(["--project-name", project_name])

        # Execute (non-blocking)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=get_action_log_timeout(),
        )

        if result.returncode == 0:
            return True
        else:
            print(f"Success logging failed: {result.stderr}", file=sys.stderr)
            return False

    except Exception as e:
        if on_failure:
            on_failure(e)
        print(f"Failed to log success: {e}", file=sys.stderr)
        return False


def log_tool_call(
    tool_name: str,
    tool_parameters: Optional[Dict[str, Any]] = None,
    tool_result: Optional[Dict[str, Any]] = None,
    agent_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
) -> bool:
    """
    Log a tool call event to Kafka via execute_kafka.py.

    Args:
        tool_name: Name of the tool (e.g., "Read", "Write", "Bash")
        tool_parameters: Tool input parameters as dictionary
        tool_result: Tool execution result as dictionary
        agent_name: Agent name (auto-detected if not provided)
        correlation_id: Correlation ID (auto-generated if not provided)
        duration_ms: How long the tool call took in milliseconds
        project_path: Absolute path to project directory
        project_name: Project name
        on_failure: Optional callback invoked if publishing fails

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        # With failure callback for debugging
        def handle_logging_failure(error: Exception):
            logger.warning(f"Failed to log tool call: {error}")

        log_tool_call(
            tool_name="Read",
            tool_parameters={"file_path": "/path/to/file.py"},
            tool_result={"success": True, "lines_read": 100},
            duration_ms=50,
            on_failure=handle_logging_failure
        )
    """
    # Auto-detect agent name and correlation ID if not provided
    agent_name = agent_name or get_agent_name()
    correlation_id = correlation_id or get_correlation_id()

    # Build tool call details JSON
    tool_details = {
        "tool_name": tool_name,
        "tool_parameters": tool_parameters or {},
        "tool_result": tool_result or {},
    }

    # Call execute_kafka.py to publish tool call event
    try:
        skill_path = (
            Path.home()
            / ".claude"
            / "skills"
            / "agent-tracking"
            / "log-agent-action"
            / "execute_kafka.py"
        )

        if not skill_path.exists():
            print(
                f"Warning: execute_kafka.py not found at {skill_path}", file=sys.stderr
            )
            return False

        # Build command arguments
        cmd = [
            sys.executable,
            str(skill_path),
            "--agent",
            agent_name,
            "--action-type",
            "tool_call",
            "--action-name",
            tool_name,
            "--details",
            json.dumps(tool_details),
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        # Add optional arguments
        if duration_ms is not None:
            cmd.extend(["--duration-ms", str(duration_ms)])
        if project_path:
            cmd.extend(["--project-path", project_path])
        if project_name:
            cmd.extend(["--project-name", project_name])

        # Execute (non-blocking)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=get_action_log_timeout(),
        )

        if result.returncode == 0:
            return True
        else:
            print(f"Tool call logging failed: {result.stderr}", file=sys.stderr)
            return False

    except Exception as e:
        if on_failure:
            on_failure(e)
        print(f"Failed to log tool call: {e}", file=sys.stderr)
        return False


# Convenience function for logging decisions
def log_decision(
    decision_type: str,
    decision_details: Dict[str, Any],
    agent_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
) -> bool:
    """
    Log a decision event to Kafka via execute_kafka.py.

    Args:
        decision_type: Type of decision (e.g., "agent_selected", "route_chosen")
        decision_details: Decision details as dictionary
        agent_name: Agent name (auto-detected if not provided)
        correlation_id: Correlation ID (auto-generated if not provided)
        duration_ms: How long the decision took in milliseconds
        project_path: Absolute path to project directory
        project_name: Project name
        on_failure: Optional callback invoked if publishing fails

    Returns:
        bool: True if published successfully, False otherwise

    Example:
        # With failure callback for debugging
        def handle_logging_failure(error: Exception):
            logger.warning(f"Failed to log decision: {error}")

        log_decision(
            decision_type="agent_selected",
            decision_details={"agent": "agent-researcher", "confidence": 0.87},
            duration_ms=15,
            on_failure=handle_logging_failure
        )
    """
    # Auto-detect agent name and correlation ID if not provided
    agent_name = agent_name or get_agent_name()
    correlation_id = correlation_id or get_correlation_id()

    # Call execute_kafka.py to publish decision event
    try:
        skill_path = (
            Path.home()
            / ".claude"
            / "skills"
            / "agent-tracking"
            / "log-agent-action"
            / "execute_kafka.py"
        )

        if not skill_path.exists():
            print(
                f"Warning: execute_kafka.py not found at {skill_path}", file=sys.stderr
            )
            return False

        # Build command arguments
        cmd = [
            sys.executable,
            str(skill_path),
            "--agent",
            agent_name,
            "--action-type",
            "decision",
            "--action-name",
            decision_type,
            "--details",
            json.dumps(decision_details),
            "--correlation-id",
            correlation_id,
            "--debug-mode",
        ]

        # Add optional arguments
        if duration_ms is not None:
            cmd.extend(["--duration-ms", str(duration_ms)])
        if project_path:
            cmd.extend(["--project-path", project_path])
        if project_name:
            cmd.extend(["--project-name", project_name])

        # Execute (non-blocking)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=get_action_log_timeout(),
        )

        if result.returncode == 0:
            return True
        else:
            print(f"Decision logging failed: {result.stderr}", file=sys.stderr)
            return False

    except Exception as e:
        if on_failure:
            on_failure(e)
        print(f"Failed to log decision: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # Test the logging helpers
    print("Testing action logging helpers...")

    # Test error logging
    print("\n1. Testing error logging...")
    log_error(
        error_type="TestError",
        error_message="This is a test error",
        error_context={"test_key": "test_value"},
    )

    # Test success logging
    print("\n2. Testing success logging...")
    log_success(
        success_type="TestSuccess",
        success_message="This is a test success",
        success_context={"test_key": "test_value"},
        quality_score=0.95,
    )

    # Test tool call logging
    print("\n3. Testing tool call logging...")
    log_tool_call(
        tool_name="TestTool",
        tool_parameters={"param1": "value1"},
        tool_result={"result_key": "result_value"},
        duration_ms=125,
    )

    # Test decision logging
    print("\n4. Testing decision logging...")
    log_decision(
        decision_type="test_decision",
        decision_details={"option": "A", "confidence": 0.8},
    )

    print("\nAll tests completed. Check Kafka topic 'agent-actions' for logged events.")
