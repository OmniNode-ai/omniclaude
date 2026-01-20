#!/usr/bin/env python3
"""
Unit Tests for ActionLogger - Comprehensive validation of action logging functionality

Tests cover:
- ActionLogger initialization and correlation ID management
- Tool call logging (manual and context manager)
- Decision logging
- Error logging (with and without Slack notifications)
- Success logging
- Raw action logging
- Common kwargs propagation
- Graceful degradation when Kafka unavailable
"""

import asyncio
import os

# Import the module under test
import sys
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agents.lib.action_logger import (
    ActionLogger,
    log_action,
)


class TestActionLoggerInitialization:
    """Test ActionLogger initialization and basic configuration."""

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters provided."""
        correlation_id = str(uuid4())
        logger = ActionLogger(
            agent_name="test-agent",
            correlation_id=correlation_id,
            project_path="/test/path",
            project_name="test-project",
            working_directory="/test/working",
            debug_mode=True,
        )

        assert logger.agent_name == "test-agent"
        assert logger.correlation_id == correlation_id
        assert logger.project_path == "/test/path"
        assert logger.project_name == "test-project"
        assert logger.working_directory == "/test/working"
        assert logger.debug_mode is True

    def test_init_with_minimal_parameters(self):
        """Test initialization with minimal parameters (auto-generated correlation_id)."""
        logger = ActionLogger(agent_name="minimal-agent")

        assert logger.agent_name == "minimal-agent"
        assert logger.correlation_id is not None
        # Verify correlation_id is valid UUID
        UUID(logger.correlation_id)  # Raises ValueError if invalid
        assert logger.project_path == os.getcwd()
        assert logger.project_name == os.path.basename(os.getcwd())
        assert logger.working_directory == os.getcwd()
        assert logger.debug_mode is True

    def test_init_with_uuid_correlation_id(self):
        """Test initialization with UUID object as correlation_id."""
        correlation_id = uuid4()
        logger = ActionLogger(
            agent_name="uuid-agent",
            correlation_id=correlation_id,
        )

        assert logger.correlation_id == str(correlation_id)

    def test_get_common_kwargs(self):
        """Test _get_common_kwargs returns correct fields."""
        correlation_id = str(uuid4())
        logger = ActionLogger(
            agent_name="test-agent",
            correlation_id=correlation_id,
            project_path="/test/path",
            project_name="test-project",
            working_directory="/test/working",
            debug_mode=False,
        )

        kwargs = logger._get_common_kwargs()

        assert kwargs["correlation_id"] == correlation_id
        assert kwargs["project_path"] == "/test/path"
        assert kwargs["project_name"] == "test-project"
        assert kwargs["working_directory"] == "/test/working"
        assert kwargs["debug_mode"] is False


class TestToolCallLogging:
    """Test tool call logging functionality."""

    @pytest.mark.asyncio
    async def test_log_tool_call_success(self):
        """Test successful tool call logging."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_tool_call(
                tool_name="Read",
                tool_parameters={"file_path": "/test/file.py"},
                tool_result={"line_count": 100},
                duration_ms=45,
                success=True,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "test-agent"
            assert call_kwargs["tool_name"] == "Read"
            assert call_kwargs["tool_parameters"] == {"file_path": "/test/file.py"}
            assert call_kwargs["tool_result"] == {"line_count": 100}
            assert call_kwargs["duration_ms"] == 45
            assert call_kwargs["success"] is True
            assert "correlation_id" in call_kwargs

    @pytest.mark.asyncio
    async def test_log_tool_call_with_error(self):
        """Test tool call logging with error message."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_tool_call(
                tool_name="Write",
                tool_parameters={"file_path": "/test/file.py"},
                success=False,
                error_message="Permission denied",
            )

            assert success is True
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["success"] is False
            assert call_kwargs["error_message"] == "Permission denied"

    @pytest.mark.asyncio
    async def test_tool_call_context_manager_success(self):
        """Test tool call logging with context manager (success case)."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            async with logger.tool_call(
                "Read", {"file_path": "/test/file.py"}
            ) as action:
                # Simulate tool execution
                await asyncio.sleep(0.001)
                action.set_result({"line_count": 100})

            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["tool_name"] == "Read"
            assert call_kwargs["tool_result"] == {"line_count": 100}
            assert call_kwargs["success"] is True
            assert call_kwargs["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_tool_call_context_manager_with_exception(self):
        """Test tool call logging with context manager (exception case)."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with pytest.raises(ValueError, match="File not found"):
                async with logger.tool_call("Read", {"file_path": "/test/file.py"}):
                    # Simulate tool failure
                    raise ValueError("File not found")

            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["success"] is False
            assert "File not found" in call_kwargs["error_message"]


class TestDecisionLogging:
    """Test decision logging functionality."""

    @pytest.mark.asyncio
    async def test_log_decision_success(self):
        """Test successful decision logging."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_decision", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_decision(
                decision_name="select_agent",
                decision_context={"candidates": ["agent-a", "agent-b"]},
                decision_result={"selected": "agent-a", "confidence": 0.92},
                duration_ms=15,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "test-agent"
            assert call_kwargs["decision_name"] == "select_agent"
            assert call_kwargs["decision_context"] == {
                "candidates": ["agent-a", "agent-b"]
            }
            assert call_kwargs["decision_result"] == {
                "selected": "agent-a",
                "confidence": 0.92,
            }
            assert call_kwargs["duration_ms"] == 15


class TestErrorLogging:
    """Test error logging functionality with Slack notifications."""

    @pytest.mark.asyncio
    async def test_log_error_basic(self):
        """Test basic error logging without Slack."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_error(
                error_type="ImportError",
                error_message="Module 'foo' not found",
                error_context={"file": "/test/file.py", "line": 15},
                severity="warning",
                send_slack_notification=False,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "test-agent"
            assert call_kwargs["error_type"] == "ImportError"
            assert call_kwargs["error_message"] == "Module 'foo' not found"
            assert call_kwargs["error_context"] == {"file": "/test/file.py", "line": 15}

    @pytest.mark.asyncio
    async def test_log_error_with_slack_notification_disabled(self):
        """Test error logging with Slack explicitly disabled."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with patch("agents.lib.action_logger.SLACK_NOTIFIER_AVAILABLE", True):
                with patch(
                    "agents.lib.action_logger.get_slack_notifier"
                ) as mock_get_notifier:
                    mock_notifier = AsyncMock()
                    mock_get_notifier.return_value = mock_notifier

                    success = await logger.log_error(
                        error_type="DatabaseError",
                        error_message="Connection failed",
                        severity="critical",
                        send_slack_notification=False,  # Explicitly disabled
                    )

                    assert success is True
                    # Slack notifier should NOT be called when disabled
                    mock_notifier.send_error_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_error_with_slack_notification_enabled(self):
        """Test error logging with Slack notification enabled."""
        logger = ActionLogger(
            agent_name="test-agent", correlation_id="test-correlation-123"
        )

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with patch("agents.lib.action_logger.SLACK_NOTIFIER_AVAILABLE", True):
                with patch(
                    "agents.lib.action_logger.get_slack_notifier"
                ) as mock_get_notifier:
                    mock_notifier = AsyncMock()
                    mock_get_notifier.return_value = mock_notifier

                    success = await logger.log_error(
                        error_type="DatabaseConnectionError",
                        error_message="Failed to connect to PostgreSQL",
                        error_context={"host": "192.168.86.200", "port": 5436},
                        severity="critical",
                        send_slack_notification=True,
                    )

                    assert success is True
                    # Verify Slack notification was sent
                    mock_notifier.send_error_notification.assert_called_once()
                    call_args = mock_notifier.send_error_notification.call_args

                    # Verify exception object
                    error_obj = call_args.kwargs["error"]
                    assert error_obj.__class__.__name__ == "DatabaseConnectionError"
                    assert str(error_obj) == "Failed to connect to PostgreSQL"

                    # Verify context
                    context = call_args.kwargs["context"]
                    assert context["service"] == "test-agent"
                    assert context["correlation_id"] == "test-correlation-123"
                    assert context["severity"] == "critical"
                    assert context["host"] == "192.168.86.200"
                    assert context["port"] == 5436

    @pytest.mark.asyncio
    async def test_log_error_with_slack_notification_low_severity(self):
        """Test error logging with low severity doesn't trigger Slack."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with patch("agents.lib.action_logger.SLACK_NOTIFIER_AVAILABLE", True):
                with patch(
                    "agents.lib.action_logger.get_slack_notifier"
                ) as mock_get_notifier:
                    mock_notifier = AsyncMock()
                    mock_get_notifier.return_value = mock_notifier

                    success = await logger.log_error(
                        error_type="WarningError",
                        error_message="Minor issue",
                        severity="warning",  # Low severity
                        send_slack_notification=True,
                    )

                    assert success is True
                    # Slack should NOT be called for low severity
                    mock_notifier.send_error_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_error_slack_notification_failure_graceful(self):
        """Test that Slack notification failures don't break error logging."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with patch("agents.lib.action_logger.SLACK_NOTIFIER_AVAILABLE", True):
                with patch(
                    "agents.lib.action_logger.get_slack_notifier"
                ) as mock_get_notifier:
                    mock_notifier = AsyncMock()
                    # Simulate Slack failure
                    mock_notifier.send_error_notification.side_effect = Exception(
                        "Slack API error"
                    )
                    mock_get_notifier.return_value = mock_notifier

                    # Should still succeed even if Slack fails
                    success = await logger.log_error(
                        error_type="DatabaseError",
                        error_message="Connection failed",
                        severity="critical",
                        send_slack_notification=True,
                    )

                    assert success is True  # Kafka publish succeeded
                    mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_error_dynamic_exception_class_creation(self):
        """Test that dynamic exception class creation works correctly."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_error", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            with patch("agents.lib.action_logger.SLACK_NOTIFIER_AVAILABLE", True):
                with patch(
                    "agents.lib.action_logger.get_slack_notifier"
                ) as mock_get_notifier:
                    mock_notifier = AsyncMock()
                    mock_get_notifier.return_value = mock_notifier

                    # Test with custom error type name
                    custom_error_type = "CustomDatabaseConnectionError"
                    success = await logger.log_error(
                        error_type=custom_error_type,
                        error_message="Custom error message",
                        severity="error",
                        send_slack_notification=True,
                    )

                    assert success is True

                    # Verify dynamic class was created correctly
                    call_args = mock_notifier.send_error_notification.call_args
                    error_obj = call_args.kwargs["error"]

                    # Verify class name matches our custom error type
                    assert error_obj.__class__.__name__ == custom_error_type
                    assert str(error_obj) == "Custom error message"

                    # Verify it's an Exception subclass
                    assert isinstance(error_obj, Exception)


class TestSuccessLogging:
    """Test success logging functionality."""

    @pytest.mark.asyncio
    async def test_log_success(self):
        """Test successful success logging."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_success", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_success(
                success_name="task_completed",
                success_details={"files_processed": 5, "total_lines": 1000},
                duration_ms=250,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "test-agent"
            assert call_kwargs["success_name"] == "task_completed"
            assert call_kwargs["success_details"] == {
                "files_processed": 5,
                "total_lines": 1000,
            }
            assert call_kwargs["duration_ms"] == 250


class TestRawActionLogging:
    """Test raw action logging functionality."""

    @pytest.mark.asyncio
    async def test_log_raw_action(self):
        """Test raw action event logging."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_action_event", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            success = await logger.log_raw_action(
                action_type="custom_action",
                action_name="custom_operation",
                action_details={"custom_field": "custom_value"},
                duration_ms=100,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "test-agent"
            assert call_kwargs["action_type"] == "custom_action"
            assert call_kwargs["action_name"] == "custom_operation"
            assert call_kwargs["action_details"] == {"custom_field": "custom_value"}
            assert call_kwargs["duration_ms"] == 100


class TestConvenienceFunction:
    """Test standalone log_action convenience function."""

    @pytest.mark.asyncio
    async def test_log_action_convenience_function(self):
        """Test log_action standalone function."""
        with patch(
            "agents.lib.action_logger.publish_action_event", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            correlation_id = str(uuid4())
            success = await log_action(
                agent_name="standalone-agent",
                action_type="tool_call",
                action_name="Glob",
                action_details={"pattern": "**/*.py", "matches": 42},
                correlation_id=correlation_id,
                duration_ms=10,
            )

            assert success is True
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["agent_name"] == "standalone-agent"
            assert call_kwargs["action_type"] == "tool_call"
            assert call_kwargs["action_name"] == "Glob"
            assert call_kwargs["correlation_id"] == correlation_id


class TestToolCallContext:
    """Test ToolCallContext class directly."""

    @pytest.mark.asyncio
    async def test_tool_call_context_set_result(self):
        """Test ToolCallContext set_result method."""
        logger = ActionLogger(agent_name="test-agent")

        with patch(
            "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = True

            async with logger.tool_call(
                "Read", {"file_path": "/test/file.py"}
            ) as action:
                # Test set_result
                result = {"line_count": 100, "file_size": 5432}
                action.set_result(result)
                assert action.tool_result == result

            # Verify result was logged
            call_kwargs = mock_publish.call_args.kwargs
            assert call_kwargs["tool_result"] == result


class TestCorrelationIDManagement:
    """Test correlation ID management across logs."""

    @pytest.mark.asyncio
    async def test_correlation_id_propagation(self):
        """Test that correlation_id propagates to all log calls."""
        correlation_id = str(uuid4())
        logger = ActionLogger(agent_name="test-agent", correlation_id=correlation_id)

        with (
            patch(
                "agents.lib.action_logger.publish_tool_call", new_callable=AsyncMock
            ) as mock_tool,
            patch(
                "agents.lib.action_logger.publish_decision", new_callable=AsyncMock
            ) as mock_decision,
            patch(
                "agents.lib.action_logger.publish_error", new_callable=AsyncMock
            ) as mock_error,
            patch(
                "agents.lib.action_logger.publish_success",
                new_callable=AsyncMock,
            ) as mock_success,
        ):
            mock_tool.return_value = True
            mock_decision.return_value = True
            mock_error.return_value = True
            mock_success.return_value = True

            # Log different action types
            await logger.log_tool_call("Read", {})
            await logger.log_decision("decide", {})
            await logger.log_error("Error", "message", send_slack_notification=False)
            await logger.log_success("success", {})

            # Verify all have same correlation_id
            assert mock_tool.call_args.kwargs["correlation_id"] == correlation_id
            assert mock_decision.call_args.kwargs["correlation_id"] == correlation_id
            assert mock_error.call_args.kwargs["correlation_id"] == correlation_id
            assert mock_success.call_args.kwargs["correlation_id"] == correlation_id


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
