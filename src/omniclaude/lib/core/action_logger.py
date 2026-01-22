#!/usr/bin/env python3
"""
Agent Action Logger - Convenient wrapper for action event publishing

Provides an easy-to-use interface for logging agent actions (tool calls, decisions, errors).
Automatically handles correlation IDs, timing, and formatting. Includes optional Slack
notifications for critical errors.

Usage:
    from action_logger import ActionLogger

    # Initialize logger
    logger = ActionLogger(
        agent_name="agent-researcher",
        correlation_id="abc-123"
    )

    # Log tool call
    await logger.log_tool_call(
        tool_name="Read",
        tool_parameters={"file_path": "/path/to/file.py"},
        tool_result={"line_count": 100},
        duration_ms=45
    )

    # Or use context manager for automatic timing
    async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
        # Tool execution happens here
        result = await read_file("/path/to/file.py")
        action.set_result({"line_count": len(result)})

    # Log error with Slack notification (if configured)
    await logger.log_error(
        error_type="DatabaseConnectionError",
        error_message="Failed to connect to PostgreSQL",
        error_context={"host": "192.168.86.200", "port": 5436},
        severity="critical"  # 'error' or 'critical' triggers Slack notification
    )

Features:
- Automatic timing with context manager
- Correlation ID management
- Error handling and logging
- Graceful degradation if Kafka unavailable
- Optional Slack notifications for critical errors (opt-in via SLACK_WEBHOOK_URL)
- Intelligent throttling (max 1 notification per error type per 5 minutes)
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from .action_event_publisher import (
    publish_action_event,
    publish_decision,
    publish_error,
    publish_success,
    publish_tool_call,
)

# Import Slack notifier for error notifications
try:
    from omniclaude.lib.slack_notifier import get_slack_notifier

    SLACK_NOTIFIER_AVAILABLE = True
except ImportError:
    try:
        from agents.lib.slack_notifier import get_slack_notifier

        SLACK_NOTIFIER_AVAILABLE = True
    except ImportError:
        SLACK_NOTIFIER_AVAILABLE = False
        logging.warning("SlackNotifier not available - error notifications disabled")

# Import Prometheus metrics
try:
    from omniclaude.lib.prometheus_metrics import (
        action_log_counter,
        action_log_duration,
        action_log_errors_counter,
        record_action_log,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    try:
        from agents.lib.prometheus_metrics import (
            action_log_counter,
            action_log_duration,
            action_log_errors_counter,
            record_action_log,
        )

        PROMETHEUS_AVAILABLE = True
    except ImportError:
        PROMETHEUS_AVAILABLE = False
        logging.debug("Prometheus metrics not available - metrics disabled")

logger = logging.getLogger(__name__)


class ToolCallContext:
    """Context manager for tool call logging with automatic timing."""

    def __init__(
        self,
        action_logger: "ActionLogger",
        tool_name: str,
        tool_parameters: dict[str, Any] | None = None,
    ):
        self.action_logger = action_logger
        self.tool_name = tool_name
        self.tool_parameters = tool_parameters or {}
        self.tool_result: dict[str, Any] | None = None
        self.start_time: float | None = None
        self.success = True
        self.error_message: str | None = None

    async def __aenter__(self):
        """Start timing when entering context."""
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Log action when exiting context."""
        duration_ms = int((time.time() - (self.start_time or time.time())) * 1000)

        # If exception occurred, mark as failure
        if exc_type is not None:
            self.success = False
            self.error_message = str(exc_val)

        # Log the tool call
        await self.action_logger.log_tool_call(
            tool_name=self.tool_name,
            tool_parameters=self.tool_parameters,
            tool_result=self.tool_result,
            duration_ms=duration_ms,
            success=self.success,
            error_message=self.error_message,
        )

        # Don't suppress exception
        return False

    def set_result(self, result: dict[str, Any]):
        """Set tool result (call this from within the context)."""
        self.tool_result = result


class ActionLogger:
    """Convenient wrapper for logging agent actions."""

    def __init__(
        self,
        agent_name: str,
        correlation_id: str | UUID | None = None,
        project_path: str | None = None,
        project_name: str | None = None,
        working_directory: str | None = None,
        debug_mode: bool = True,
    ):
        """
        Initialize action logger.

        Args:
            agent_name: Agent executing actions
            correlation_id: Correlation ID for tracing (auto-generated if not provided)
            project_path: Path to project directory
            project_name: Name of project
            working_directory: Current working directory
            debug_mode: Whether to enable debug mode logging
        """
        self.agent_name = agent_name
        self.correlation_id = str(correlation_id) if correlation_id else str(uuid4())
        self.project_path = project_path or os.getcwd()
        self.project_name = project_name or os.path.basename(self.project_path)
        self.working_directory = working_directory or os.getcwd()
        self.debug_mode = debug_mode

        logger.debug(
            f"ActionLogger initialized: agent={agent_name}, correlation_id={self.correlation_id}"
        )

    def _get_common_kwargs(self) -> dict[str, Any]:
        """Get common kwargs for all action events."""
        return {
            "correlation_id": self.correlation_id,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "working_directory": self.working_directory,
            "debug_mode": self.debug_mode,
        }

    async def log_tool_call(
        self,
        tool_name: str,
        tool_parameters: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> bool:
        """
        Log a tool call action.

        Args:
            tool_name: Name of tool (Read, Write, Edit, Bash, etc.)
            tool_parameters: Tool input parameters
            tool_result: Tool execution result
            duration_ms: Execution time
            success: Whether tool succeeded
            error_message: Error message if failed

        Returns:
            bool: True if logged successfully
        """
        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE and duration_ms is not None:
            record_action_log(
                agent_name=self.agent_name,
                action_type="tool_call",
                duration=duration_ms / 1000.0,  # Convert ms to seconds
                status="success" if success else "failure",
            )

        return await publish_tool_call(
            agent_name=self.agent_name,
            tool_name=tool_name,
            tool_parameters=tool_parameters,
            tool_result=tool_result,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            **self._get_common_kwargs(),
        )

    @asynccontextmanager
    async def tool_call(
        self,
        tool_name: str,
        tool_parameters: dict[str, Any] | None = None,
    ):
        """
        Context manager for logging tool call with automatic timing.

        Usage:
            async with logger.tool_call("Read", {"file_path": "..."}) as action:
                result = await read_file("...")
                action.set_result({"line_count": len(result)})

        Args:
            tool_name: Name of tool
            tool_parameters: Tool parameters

        Yields:
            ToolCallContext: Context with set_result() method
        """
        context = ToolCallContext(self, tool_name, tool_parameters)
        async with context:
            yield context

    async def log_decision(
        self,
        decision_name: str,
        decision_context: dict[str, Any] | None = None,
        decision_result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """
        Log a decision action.

        Args:
            decision_name: Name of decision
            decision_context: Decision context
            decision_result: Decision result
            duration_ms: Decision time

        Returns:
            bool: True if logged successfully
        """
        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE and duration_ms is not None:
            record_action_log(
                agent_name=self.agent_name,
                action_type="decision",
                duration=duration_ms / 1000.0,
                status="success",
            )

        return await publish_decision(
            agent_name=self.agent_name,
            decision_name=decision_name,
            decision_context=decision_context,
            decision_result=decision_result,
            duration_ms=duration_ms,
            **self._get_common_kwargs(),
        )

    async def log_error(
        self,
        error_type: str,
        error_message: str,
        error_context: dict[str, Any] | None = None,
        severity: str = "error",
        send_slack_notification: bool = True,
    ) -> bool:
        """
        Log an error action with optional Slack notification.

        Args:
            error_type: Error type
            error_message: Error message
            error_context: Additional context
            severity: Error severity (debug, info, warning, error, critical)
            send_slack_notification: Whether to send Slack notification (default: True)

        Returns:
            bool: True if logged successfully

        Note:
            Slack notifications are only sent if:
            - send_slack_notification=True
            - Severity is 'error' or 'critical'
            - SLACK_WEBHOOK_URL is configured
            - Notification passes throttling check
        """
        # Record Prometheus metrics for errors
        if PROMETHEUS_AVAILABLE:
            action_log_errors_counter.labels(
                agent_name=self.agent_name, error_type=error_type
            ).inc()

        # Publish error event to Kafka
        kafka_success = await publish_error(
            agent_name=self.agent_name,
            error_type=error_type,
            error_message=error_message,
            error_context=error_context,
            **self._get_common_kwargs(),
        )

        # Send Slack notification for critical errors
        if (
            send_slack_notification
            and SLACK_NOTIFIER_AVAILABLE
            and severity in ("error", "critical")
        ):
            try:
                # Create exception-like object for notification
                # (since log_error takes strings, not exceptions)
                class LoggedError(Exception):
                    """Wrapper for string-based errors to send to Slack."""

                    pass

                # Create dynamic exception class with the desired name
                # IMPORTANT: Use type() to create class with desired __name__
                # DO NOT try to modify error_obj.__class__.__name__ directly - it's readonly!
                # Attempting error_obj.__class__.__name__ = error_type raises TypeError
                error_cls = type(error_type, (LoggedError,), {})
                error_obj = error_cls(error_message)

                # Build notification context
                notification_context = {
                    "service": self.agent_name,
                    "operation": "agent_action",
                    "correlation_id": self.correlation_id,
                    "project": self.project_name,
                    "severity": severity,
                    "error_type": error_type,  # Include error type for debugging
                    "error_class": error_obj.__class__.__name__,  # Verify class name
                }

                # Add error_context fields to notification context
                if error_context:
                    notification_context.update(error_context)

                # Get notifier and send
                notifier = get_slack_notifier()
                notification_success = await notifier.send_error_notification(
                    error=error_obj, context=notification_context
                )

                if notification_success:
                    logger.debug(
                        f"Slack notification sent successfully: {error_type} "
                        f"(correlation_id: {self.correlation_id})"
                    )
                else:
                    logger.warning(
                        f"Slack notification failed to send: {error_type} "
                        f"(correlation_id: {self.correlation_id})"
                    )

            except Exception as slack_error:
                # Never fail main flow due to notification errors
                # Log at WARNING level so failures are visible
                logger.warning(
                    f"Failed to send Slack notification for {error_type}: {slack_error}",
                    exc_info=True,
                )

        return kafka_success

    async def log_success(
        self,
        success_name: str,
        success_details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """
        Log a success action.

        Args:
            success_name: Success name
            success_details: Success details
            duration_ms: Operation time

        Returns:
            bool: True if logged successfully
        """
        return await publish_success(
            agent_name=self.agent_name,
            success_name=success_name,
            success_details=success_details,
            duration_ms=duration_ms,
            **self._get_common_kwargs(),
        )

    async def log_raw_action(
        self,
        action_type: str,
        action_name: str,
        action_details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """
        Log a raw action event (for custom action types).

        Args:
            action_type: Action type
            action_name: Action name
            action_details: Action details
            duration_ms: Duration

        Returns:
            bool: True if logged successfully
        """
        return await publish_action_event(
            agent_name=self.agent_name,
            action_type=action_type,
            action_name=action_name,
            action_details=action_details,
            duration_ms=duration_ms,
            **self._get_common_kwargs(),
        )


# Convenience function for one-off logging
async def log_action(
    agent_name: str,
    action_type: str,
    action_name: str,
    action_details: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    duration_ms: int | None = None,
    **kwargs,
) -> bool:
    """
    Convenience function for logging a single action without creating a logger instance.

    Args:
        agent_name: Agent name
        action_type: Action type
        action_name: Action name
        action_details: Action details
        correlation_id: Correlation ID
        duration_ms: Duration
        **kwargs: Additional fields

    Returns:
        bool: True if logged successfully
    """
    return await publish_action_event(
        agent_name=agent_name,
        action_type=action_type,
        action_name=action_name,
        action_details=action_details,
        correlation_id=correlation_id,
        duration_ms=duration_ms,
        **kwargs,
    )


if __name__ == "__main__":
    # Test action logger
    async def test():
        logging.basicConfig(level=logging.DEBUG)

        # Test with logger instance
        logger = ActionLogger(
            agent_name="agent-researcher",
            correlation_id="test-correlation-123",
            project_name="omniclaude",
        )

        # Test tool call with context manager
        async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
            # Simulate file reading
            await asyncio.sleep(0.05)  # 50ms
            action.set_result({"line_count": 100, "file_size_bytes": 5432})

        print("✓ Tool call logged with context manager")

        # Test manual tool call logging
        await logger.log_tool_call(
            tool_name="Write",
            tool_parameters={"file_path": "/path/to/output.py", "content_length": 2048},
            tool_result={"success": True},
            duration_ms=30,
        )

        print("✓ Tool call logged manually")

        # Test decision logging
        await logger.log_decision(
            decision_name="select_agent",
            decision_context={"candidates": ["agent-a", "agent-b"]},
            decision_result={"selected": "agent-a", "confidence": 0.92},
            duration_ms=15,
        )

        print("✓ Decision logged")

        # Test error logging (without Slack notification)
        await logger.log_error(
            error_type="ImportError",
            error_message="Module 'foo' not found",
            error_context={"file": "/path/to/file.py", "line": 15},
            severity="warning",  # Won't trigger Slack
            send_slack_notification=False,
        )

        print("✓ Error logged (without Slack)")

        # Test critical error logging (with Slack notification if configured)
        await logger.log_error(
            error_type="DatabaseConnectionError",
            error_message="Failed to connect to PostgreSQL at 192.168.86.200:5436",
            error_context={
                "host": "192.168.86.200",
                "port": 5436,
                "database": "omninode_bridge",
                "retry_count": 3,
            },
            severity="critical",  # Will trigger Slack if SLACK_WEBHOOK_URL is set
        )

        print("✓ Critical error logged (with Slack notification if configured)")

        # Test success logging
        await logger.log_success(
            success_name="task_completed",
            success_details={"files_processed": 5},
            duration_ms=250,
        )

        print("✓ Success logged")

        # Test one-off convenience function
        await log_action(
            agent_name="agent-test",
            action_type="tool_call",
            action_name="Glob",
            action_details={"pattern": "**/*.py", "matches": 42},
            correlation_id="one-off-test",
            duration_ms=10,
        )

        print("✓ One-off action logged")

        print("\nAll tests passed! Check Kafka topic 'agent-actions' for events.")

    asyncio.run(test())
