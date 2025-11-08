#!/usr/bin/env python3
"""
Unit Tests for ManifestInjector._format_action_logging().

Tests the action logging section formatting to ensure:
1. Section exists and is properly formatted
2. Correlation ID is correctly injected
3. Agent name is correctly injected
4. ActionLogger initialization code is present
5. All required examples are included

Run tests:
    pytest agents/lib/test_manifest_injector.py -v

Created: 2025-11-07
Correlation ID: def1bf03-d307-405f-98dd-869cde43179a
"""

import sys
from pathlib import Path as PathLib

import pytest

# Add project root to path for proper imports
project_root = PathLib(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


class TestFormatActionLogging:
    """Unit tests for ManifestInjector._format_action_logging() method."""

    def test_format_action_logging_section_exists(self):
        """Verify ACTION LOGGING REQUIREMENTS section is generated."""
        # Create injector with test values
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID directly (simulating what would happen during manifest generation)
        injector._current_correlation_id = "test-correlation-123"

        # Call _format_action_logging with empty data (data from action_logging section)
        result = injector._format_action_logging(action_logging_data={})

        # Verify section header exists
        assert (
            "ACTION LOGGING REQUIREMENTS:" in result
        ), "ACTION LOGGING REQUIREMENTS section header should exist"

        # Verify result is not empty
        assert len(result) > 0, "Formatted action logging section should not be empty"

        # Verify it has substantial content (multiple lines)
        lines = result.split("\n")
        assert len(lines) > 10, f"Expected substantial content, got {len(lines)} lines"

    def test_format_action_logging_correlation_id_injection(self):
        """Verify correlation ID is injected correctly."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set specific correlation ID
        test_correlation_id = "test-correlation-abc-123"
        injector._current_correlation_id = test_correlation_id

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify correlation ID appears in output
        assert (
            test_correlation_id in result
        ), f"Correlation ID '{test_correlation_id}' should appear in formatted output"

        # Verify it appears in the expected location (near the top)
        lines = result.split("\n")
        found_in_first_10_lines = any(
            test_correlation_id in line for line in lines[:10]
        )
        assert (
            found_in_first_10_lines
        ), "Correlation ID should appear in first 10 lines of output"

        # Verify it's in the proper format (Correlation ID: <value>)
        assert (
            f"Correlation ID: {test_correlation_id}" in result
        ), "Correlation ID should be displayed in format 'Correlation ID: <value>'"

    def test_format_action_logging_agent_name_injection(self):
        """Verify agent name is injected correctly."""
        # Create injector with specific agent name
        test_agent_name = "debug-agent-test"
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name=test_agent_name
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify agent name appears in output
        assert (
            test_agent_name in result
        ), f"Agent name '{test_agent_name}' should appear in formatted output"

        # Verify it appears in initialization code
        assert (
            f'agent_name="{test_agent_name}"' in result
        ), "Agent name should appear in ActionLogger initialization code"

    def test_format_action_logging_initialization_code(self):
        """Verify ActionLogger initialization code is present."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify import statement
        assert (
            "from agents.lib.action_logger import ActionLogger" in result
        ), "ActionLogger import statement should be present"

        # Verify initialization code exists
        assert (
            "logger = ActionLogger(" in result
        ), "ActionLogger initialization code should be present"

        # Verify initialization parameters
        assert (
            "agent_name=" in result
        ), "agent_name parameter should be in initialization"
        assert (
            "correlation_id=" in result
        ), "correlation_id parameter should be in initialization"
        assert (
            "project_name=" in result
        ), "project_name parameter should be in initialization"

    def test_format_action_logging_includes_examples(self):
        """Verify all required usage examples are included."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify tool call example
        assert "logger.tool_call" in result, "Tool call example should be present"

        # Verify decision logging example
        assert (
            "logger.log_decision" in result
        ), "Decision logging example should be present"

        # Verify error logging example
        assert "logger.log_error" in result, "Error logging example should be present"

        # Verify success logging example
        assert (
            "logger.log_success" in result
        ), "Success logging example should be present"

    def test_format_action_logging_includes_infrastructure_details(self):
        """Verify infrastructure details (Kafka topic, performance notes) are included."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify Kafka topic is mentioned
        assert (
            "agent-actions" in result
        ), "Kafka topic 'agent-actions' should be mentioned"

        # Verify performance notes
        assert "Performance:" in result, "Performance information should be included"

        # Verify benefits are mentioned
        assert "Benefits:" in result, "Benefits should be mentioned"

    def test_format_action_logging_with_custom_project_name(self):
        """Verify custom project name can be passed via action_logging_data."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format with custom project name
        custom_project = "custom-project-name"
        result = injector._format_action_logging(
            action_logging_data={"project_name": custom_project}
        )

        # Verify custom project name appears
        assert (
            f'project_name="{custom_project}"' in result
        ), f"Custom project name '{custom_project}' should appear in initialization code"

    def test_format_action_logging_with_no_correlation_id(self):
        """Verify graceful handling when correlation ID is not set."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Don't set correlation ID (leave as None)
        injector._current_correlation_id = None

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Should still generate output with fallback value
        assert len(result) > 0, "Should generate output even without correlation ID"

        # Should use auto-generated placeholder
        assert (
            "auto-generated" in result
        ), "Should use 'auto-generated' as fallback when correlation ID is None"

    def test_format_action_logging_with_no_agent_name(self):
        """Verify graceful handling when agent name is not set."""
        # Create injector without agent name
        injector = ManifestInjector(
            enable_intelligence=False,
            enable_storage=False,
            agent_name=None,  # No agent name
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Should still generate output with fallback value
        assert len(result) > 0, "Should generate output even without agent name"

        # Should use placeholder
        assert (
            "your-agent-name" in result
        ), "Should use 'your-agent-name' as fallback when agent name is None"

    def test_format_action_logging_output_structure(self):
        """Verify the output has proper structure and formatting."""
        # Create injector
        injector = ManifestInjector(
            enable_intelligence=False, enable_storage=False, agent_name="test-agent"
        )

        # Set correlation ID
        injector._current_correlation_id = "test-123"

        # Format action logging
        result = injector._format_action_logging(action_logging_data={})

        # Verify sections are present in logical order
        lines = result.split("\n")

        # Find key section markers
        header_idx = None
        correlation_idx = None
        init_idx = None
        tool_call_idx = None
        decision_idx = None
        error_idx = None
        success_idx = None

        for i, line in enumerate(lines):
            if "ACTION LOGGING REQUIREMENTS:" in line:
                header_idx = i
            elif "Correlation ID:" in line:
                correlation_idx = i
            elif "Initialize ActionLogger:" in line:
                init_idx = i
            elif "Log tool calls" in line:
                tool_call_idx = i
            elif "Log decisions:" in line:
                decision_idx = i
            elif "Log errors:" in line:
                error_idx = i
            elif "Log successes:" in line:
                success_idx = i

        # Verify all sections found
        assert header_idx is not None, "Header should be present"
        assert correlation_idx is not None, "Correlation ID section should be present"
        assert init_idx is not None, "Initialization section should be present"
        assert tool_call_idx is not None, "Tool call section should be present"
        assert decision_idx is not None, "Decision section should be present"
        assert error_idx is not None, "Error section should be present"
        assert success_idx is not None, "Success section should be present"

        # Verify logical ordering
        assert header_idx < correlation_idx, "Header should come before correlation ID"
        assert (
            correlation_idx < init_idx
        ), "Correlation ID should come before initialization"
        assert init_idx < tool_call_idx, "Initialization should come before examples"
        assert (
            tool_call_idx < decision_idx < error_idx < success_idx
        ), "Examples should be in order: tool_call, decision, error, success"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
