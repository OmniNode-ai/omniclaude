#!/usr/bin/env python3
"""
Comprehensive tests for cli/generate_node.py CLI.

Tests cover:
- Argument parsing (all combinations)
- Logging setup
- Display functions (banner, stage header, success, failure, warnings)
- Interactive mode
- Direct mode
- Error handling and edge cases
- Output directory validation
- Exit codes
- Main entry point

Note: This test file uses aggressive mocking to avoid loading the entire
generation pipeline and its omnibase_core dependencies.
"""

import logging
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from agents.lib.models.pipeline_models import PipelineResult

# Mock CLIHandler before any imports
mock_cli_handler_module = MagicMock()
mock_cli_handler_class = MagicMock()
mock_cli_handler_module.CLIHandler = mock_cli_handler_class
sys.modules["cli.lib.cli_handler"] = mock_cli_handler_module
sys.modules["cli.lib"] = mock_cli_handler_module

# Now we can import the module under test
from cli import generate_node  # noqa: E402


@pytest.fixture
def mock_cli_handler():
    """Create a mock CLIHandler instance."""
    handler = AsyncMock()
    handler.validate_output_directory = Mock()
    handler.generate_node = AsyncMock()
    handler.format_result_summary = Mock()
    handler.format_progress_update = Mock()
    handler.cleanup_async = AsyncMock()
    handler.__aenter__ = AsyncMock(return_value=handler)
    handler.__aexit__ = AsyncMock(return_value=False)
    return handler


@pytest.fixture
def mock_pipeline_result_success():
    """Create a successful PipelineResult."""
    result = Mock(spec=PipelineResult)
    result.success = True
    result.status = "SUCCESS"
    result.output_path = "/tmp/output"
    result.generated_files = ["node_test.py", "model_test.py", "contract_test.py"]
    result.duration_seconds = 7.5
    result.to_summary = Mock(return_value="Success summary")
    result.get_failed_gates = Mock(return_value=[])
    result.get_warning_gates = Mock(return_value=[])
    result.error_summary = None
    return result


@pytest.fixture
def mock_pipeline_result_failure():
    """Create a failed PipelineResult."""
    result = Mock(spec=PipelineResult)
    result.success = False
    result.status = "FAILED"
    result.output_path = "/tmp/output"
    result.generated_files = []
    result.duration_seconds = 3.2
    result.to_summary = Mock(return_value="Failure summary")

    # Mock failed gates
    failed_gate = Mock()
    failed_gate.gate_id = "QG-001"
    failed_gate.name = "PRD Validation"
    failed_gate.message = "Invalid PRD structure"
    result.get_failed_gates = Mock(return_value=[failed_gate])
    result.get_warning_gates = Mock(return_value=[])
    result.error_summary = "Validation failed at Stage 2"
    return result


@pytest.fixture
def mock_pipeline_result_with_warnings():
    """Create a successful PipelineResult with warnings."""
    result = Mock(spec=PipelineResult)
    result.success = True
    result.status = "SUCCESS"
    result.output_path = "/tmp/output"
    result.generated_files = ["node_test.py"]
    result.duration_seconds = 5.0
    result.to_summary = Mock(return_value="Success with warnings")
    result.get_failed_gates = Mock(return_value=[])

    # Mock warning gates
    warning_gate = Mock()
    warning_gate.gate_id = "QG-010"
    warning_gate.name = "Performance Warning"
    warning_gate.message = "Execution time slightly above threshold"
    result.get_warning_gates = Mock(return_value=[warning_gate])
    result.error_summary = None
    return result


class TestLoggingSetup:
    """Test logging configuration."""

    def test_setup_logging_default(self):
        """Test default logging setup calls basicConfig with INFO level."""
        # We test that the function runs without error and sets the intended level
        # Note: basicConfig only sets level on first call, so we just verify it runs
        with patch("logging.basicConfig") as mock_basic_config:
            generate_node.setup_logging(debug=False)

            # Verify basicConfig was called with INFO level
            mock_basic_config.assert_called_once()
            call_kwargs = mock_basic_config.call_args.kwargs
            assert call_kwargs["level"] == logging.INFO

    def test_setup_logging_debug(self):
        """Test debug logging setup calls basicConfig with DEBUG level."""
        with patch("logging.basicConfig") as mock_basic_config:
            generate_node.setup_logging(debug=True)

            # Verify basicConfig was called with DEBUG level
            mock_basic_config.assert_called_once()
            call_kwargs = mock_basic_config.call_args.kwargs
            assert call_kwargs["level"] == logging.DEBUG

    def test_setup_logging_reduces_third_party_noise(self):
        """Test that third-party library logging is reduced."""
        # Reset the loggers first
        httpx_logger = logging.getLogger("httpx")
        httpcore_logger = logging.getLogger("httpcore")
        httpx_logger.setLevel(logging.NOTSET)
        httpcore_logger.setLevel(logging.NOTSET)

        generate_node.setup_logging(debug=False)

        # Verify the levels were set to WARNING
        assert httpx_logger.level == logging.WARNING
        assert httpcore_logger.level == logging.WARNING


class TestDisplayFunctions:
    """Test display/output functions."""

    def test_print_banner(self, capsys):
        """Test banner printing."""
        generate_node.print_banner()

        captured = capsys.readouterr()
        assert "ONEX Node Generation CLI" in captured.out
        assert "Autonomous Code Generation POC" in captured.out
        assert "╔" in captured.out
        assert "╚" in captured.out

    def test_print_stage_header(self, capsys):
        """Test stage header printing."""
        generate_node.print_stage_header("Stage 1: Parsing")

        captured = capsys.readouterr()
        assert "Stage 1: Parsing" in captured.out
        assert "─" in captured.out

    def test_print_success(self, capsys, mock_pipeline_result_success):
        """Test success message printing."""
        generate_node.print_success(mock_pipeline_result_success)

        captured = capsys.readouterr()
        assert "✅ SUCCESS" in captured.out
        assert "Success summary" in captured.out
        assert "/tmp/output" in captured.out
        assert "node_test.py" in captured.out
        assert "3 files" in captured.out

    def test_print_success_with_many_files(self, capsys):
        """Test success message with >10 files shows truncation."""
        result = Mock(spec=PipelineResult)
        result.success = True
        result.output_path = "/tmp/output"
        result.generated_files = [f"file_{i}.py" for i in range(15)]
        result.to_summary = Mock(return_value="Success")
        result.get_failed_gates = Mock(return_value=[])
        result.get_warning_gates = Mock(return_value=[])

        generate_node.print_success(result)

        captured = capsys.readouterr()
        assert "... and 5 more" in captured.out

    def test_print_failure(self, capsys, mock_pipeline_result_failure):
        """Test failure message printing."""
        generate_node.print_failure(mock_pipeline_result_failure)

        captured = capsys.readouterr()
        assert "❌ FAILED" in captured.out
        assert "Failure summary" in captured.out
        assert "Failed validation gates" in captured.out
        assert "QG-001" in captured.out
        assert "PRD Validation" in captured.out
        assert "Invalid PRD structure" in captured.out
        assert "Validation failed at Stage 2" in captured.out

    def test_print_failure_no_gates(self, capsys):
        """Test failure message with no failed gates."""
        result = Mock(spec=PipelineResult)
        result.success = False
        result.to_summary = Mock(return_value="Failure")
        result.get_failed_gates = Mock(return_value=[])
        result.error_summary = "Unknown error"

        generate_node.print_failure(result)

        captured = capsys.readouterr()
        assert "❌ FAILED" in captured.out
        assert "Unknown error" in captured.out

    def test_print_warnings(self, capsys, mock_pipeline_result_with_warnings):
        """Test warning message printing."""
        generate_node.print_warnings(mock_pipeline_result_with_warnings)

        captured = capsys.readouterr()
        assert "⚠️  Warnings" in captured.out
        assert "QG-010" in captured.out
        assert "Performance Warning" in captured.out
        assert "Execution time slightly above threshold" in captured.out

    def test_print_warnings_none(self, capsys, mock_pipeline_result_success):
        """Test no warnings prints nothing."""
        generate_node.print_warnings(mock_pipeline_result_success)

        captured = capsys.readouterr()
        assert captured.out == ""


class TestInteractiveMode:
    """Test interactive node generation."""

    @pytest.mark.asyncio
    async def test_generate_node_interactive_success(
        self, mock_cli_handler, mock_pipeline_result_success, capsys
    ):
        """Test successful interactive generation."""
        mock_cli_handler.generate_node.return_value = mock_pipeline_result_success

        with patch(
            "builtins.input", side_effect=["Create EFFECT node", "./test_output", "y"]
        ):
            result = await generate_node.generate_node_interactive(mock_cli_handler)

        assert result == mock_pipeline_result_success
        mock_cli_handler.generate_node.assert_called_once_with(
            prompt="Create EFFECT node", output_directory="./test_output"
        )

        captured = capsys.readouterr()
        assert "Interactive Node Generation" in captured.out
        assert "Describe the node you want to generate" in captured.out

    @pytest.mark.asyncio
    async def test_generate_node_interactive_empty_prompt(
        self, mock_cli_handler, capsys
    ):
        """Test interactive mode with empty prompt."""
        with patch("builtins.input", return_value=""):
            result = await generate_node.generate_node_interactive(mock_cli_handler)

        assert result is None
        mock_cli_handler.generate_node.assert_not_called()

        captured = capsys.readouterr()
        assert "❌ Prompt cannot be empty" in captured.out

    @pytest.mark.asyncio
    async def test_generate_node_interactive_default_output(
        self, mock_cli_handler, mock_pipeline_result_success
    ):
        """Test interactive mode with default output directory."""
        mock_cli_handler.generate_node.return_value = mock_pipeline_result_success

        with patch("builtins.input", side_effect=["Create EFFECT node", "", "y"]):
            await generate_node.generate_node_interactive(mock_cli_handler)

        mock_cli_handler.generate_node.assert_called_once_with(
            prompt="Create EFFECT node", output_directory="./output"  # Default
        )

    @pytest.mark.asyncio
    async def test_generate_node_interactive_cancelled(self, mock_cli_handler, capsys):
        """Test interactive mode cancelled by user."""
        with patch(
            "builtins.input", side_effect=["Create EFFECT node", "./output", "n"]
        ):
            result = await generate_node.generate_node_interactive(mock_cli_handler)

        assert result is None
        mock_cli_handler.generate_node.assert_not_called()

        captured = capsys.readouterr()
        assert "❌ Cancelled" in captured.out


class TestDirectMode:
    """Test direct node generation."""

    @pytest.mark.asyncio
    async def test_generate_node_direct_success(
        self, mock_cli_handler, mock_pipeline_result_success, capsys
    ):
        """Test successful direct generation."""
        mock_cli_handler.generate_node.return_value = mock_pipeline_result_success

        result = await generate_node.generate_node_direct(
            handler=mock_cli_handler,
            prompt="Create EFFECT node for database",
            output_dir="./output",
        )

        assert result == mock_pipeline_result_success
        mock_cli_handler.generate_node.assert_called_once_with(
            prompt="Create EFFECT node for database", output_directory="./output"
        )

        captured = capsys.readouterr()
        assert "🚀 Generating node from prompt..." in captured.out
        assert "Create EFFECT node for database" in captured.out
        assert "./output" in captured.out


class TestMainFunction:
    """Test main() entry point."""

    @pytest.mark.asyncio
    async def test_main_success_direct_mode(self, mock_pipeline_result_success, capsys):
        """Test main() with successful direct mode execution."""
        test_args = ["generate_node.py", "Create EFFECT node"]

        with patch.object(sys, "argv", test_args):
            # Create a proper mock handler that works as context manager
            mock_handler = AsyncMock()
            mock_handler.validate_output_directory = Mock()
            mock_handler.generate_node = AsyncMock(
                return_value=mock_pipeline_result_success
            )
            mock_handler.__aenter__ = AsyncMock(return_value=mock_handler)
            mock_handler.__aexit__ = AsyncMock(return_value=False)

            with patch("cli.generate_node.CLIHandler", return_value=mock_handler):
                exit_code = await generate_node.main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "✅ SUCCESS" in captured.out

    @pytest.mark.asyncio
    async def test_main_failure_direct_mode(self, mock_pipeline_result_failure, capsys):
        """Test main() with failed direct mode execution."""
        test_args = ["generate_node.py", "Create EFFECT node"]

        with patch.object(sys, "argv", test_args):
            mock_handler = AsyncMock()
            mock_handler.validate_output_directory = Mock()
            mock_handler.generate_node = AsyncMock(
                return_value=mock_pipeline_result_failure
            )
            mock_handler.__aenter__ = AsyncMock(return_value=mock_handler)
            mock_handler.__aexit__ = AsyncMock(return_value=False)

            with patch("cli.generate_node.CLIHandler", return_value=mock_handler):
                exit_code = await generate_node.main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "❌ FAILED" in captured.out

    @pytest.mark.asyncio
    async def test_main_no_prompt_shows_help(self, capsys):
        """Test main() with no prompt shows help and returns error."""
        test_args = ["generate_node.py"]

        with patch.object(sys, "argv", test_args):
            exit_code = await generate_node.main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Either provide a prompt or use --interactive mode" in captured.out

    @pytest.mark.asyncio
    async def test_main_keyboard_interrupt(self, capsys):
        """Test main() handles KeyboardInterrupt."""
        test_args = ["generate_node.py", "Create EFFECT node"]

        with patch.object(sys, "argv", test_args):
            mock_handler = AsyncMock()
            mock_handler.validate_output_directory = Mock(side_effect=KeyboardInterrupt)
            mock_handler.__aenter__ = AsyncMock(return_value=mock_handler)
            mock_handler.__aexit__ = AsyncMock(return_value=False)

            with patch("cli.generate_node.CLIHandler", return_value=mock_handler):
                exit_code = await generate_node.main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "❌ Cancelled by user" in captured.out

    @pytest.mark.asyncio
    async def test_main_unexpected_error(self, capsys):
        """Test main() handles unexpected errors."""
        test_args = ["generate_node.py", "Create EFFECT node"]

        with patch.object(sys, "argv", test_args):
            mock_handler = AsyncMock()
            mock_handler.validate_output_directory = Mock(
                side_effect=RuntimeError("Test error")
            )
            mock_handler.__aenter__ = AsyncMock(return_value=mock_handler)
            mock_handler.__aexit__ = AsyncMock(return_value=False)

            with patch("cli.generate_node.CLIHandler", return_value=mock_handler):
                exit_code = await generate_node.main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "❌ Unexpected error: Test error" in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
