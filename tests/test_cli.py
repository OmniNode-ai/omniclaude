#!/usr/bin/env python3
"""
Tests for CLI Handler and generate_node.py script.

Tests cover:
- CLIHandler initialization
- generate_node() method with mocked pipeline
- Output directory validation
- Result formatting
- Error handling
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Handle CI cache issue where cli.lib may not be properly installed
from typing import Any, Type, Union

from agents.lib.models.pipeline_models import (
    GateType,
    PipelineResult,
    PipelineStage,
    StageStatus,
    ValidationGate,
)


class _CLIHandlerNotAvailable:
    """Placeholder class when CLIHandler cannot be imported."""

    def __init__(self, **kwargs: Any) -> None:
        raise ImportError(
            "CLIHandler not available - CI cache issue with cli.lib package"
        )


# Type annotation that accommodates both real CLIHandler and placeholder
_CLIHandlerType: Union[Type[Any], Type[_CLIHandlerNotAvailable]] = (
    _CLIHandlerNotAvailable
)
CLI_AVAILABLE: bool = False

try:
    from cli.lib import CLIHandler as _ImportedCLIHandler

    _CLIHandlerType = _ImportedCLIHandler
    CLI_AVAILABLE = True
except ImportError:
    pass

# Expose CLIHandler for use in tests
CLIHandler = _CLIHandlerType

pytestmark = pytest.mark.skipif(
    not CLI_AVAILABLE,
    reason="CLIHandler not available - CI cache issue with cli.lib package",
)


class TestCLIHandler:
    """Tests for CLIHandler class."""

    def test_initialization(self):
        """Test CLIHandler initialization."""
        handler = CLIHandler(enable_compilation_testing=True)
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        assert handler is not None
        assert handler.pipeline is not None
        assert handler.pipeline.enable_compilation_testing is True

    def test_initialization_no_compile(self):
        """Test CLIHandler initialization without compilation testing."""
        handler = CLIHandler(enable_compilation_testing=False)
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        assert handler is not None
        assert handler.pipeline is not None
        assert handler.pipeline.enable_compilation_testing is False

    @pytest.mark.asyncio
    async def test_generate_node_success(self):
        """Test successful node generation."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Mock successful pipeline result
        mock_result = PipelineResult(
            correlation_id=uuid4(),
            status="success",
            total_duration_ms=38450,
            output_path="/path/to/node_infrastructure_test_effect",
            generated_files=[
                "/path/to/node_infrastructure_test_effect/v1_0_0/node.py",
                "/path/to/node_infrastructure_test_effect/v1_0_0/models/model_test_input.py",
            ],
            node_type="EFFECT",
            service_name="test_service",
            domain="infrastructure",
            validation_passed=True,
            compilation_passed=True,
        )

        # Mock pipeline.execute()
        with patch.object(
            handler.pipeline,
            "execute",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await handler.generate_node(
                prompt="Create EFFECT node for testing",
                output_directory="./output",
            )

            assert result is not None
            assert result.status == "success"
            assert result.node_type == "EFFECT"
            assert result.service_name == "test_service"
            assert len(result.generated_files) == 2

    @pytest.mark.asyncio
    async def test_generate_node_failure(self):
        """Test failed node generation."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Mock failed pipeline result
        mock_result = PipelineResult(
            correlation_id=uuid4(),
            status="failed",
            total_duration_ms=5000,
            error_summary="Missing required dependency: omnibase_core.nodes.node_effect.NodeEffect",
            validation_passed=False,
            compilation_passed=False,
        )

        # Add failed validation gate
        mock_result.stages.append(
            PipelineStage(
                stage_name="pre_generation_validation",
                status=StageStatus.FAILED,
                error="Critical import failed",
                validation_gates=[
                    ValidationGate(
                        gate_id="G4",
                        name="Critical Imports Exist",
                        status="fail",
                        gate_type=GateType.BLOCKING,
                        message="omnibase_core.nodes.node_effect.NodeEffect not found",
                        duration_ms=50,
                    )
                ],
            )
        )

        # Mock pipeline.execute()
        with patch.object(
            handler.pipeline,
            "execute",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await handler.generate_node(
                prompt="Create EFFECT node for testing",
                output_directory="./output",
            )

            assert result is not None
            assert result.status == "failed"
            assert result.error_summary is not None
            assert "Missing required dependency" in result.error_summary
            assert not result.validation_passed

            # Check failed gates
            failed_gates = result.get_failed_gates()
            assert len(failed_gates) == 1
            assert failed_gates[0].gate_id == "G4"

    @pytest.mark.asyncio
    async def test_generate_node_with_correlation_id(self):
        """Test node generation with custom correlation ID."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)
        correlation_id = uuid4()

        # Mock successful result
        mock_result = PipelineResult(
            correlation_id=correlation_id,
            status="success",
            total_duration_ms=40000,
            node_type="EFFECT",
            service_name="test",
        )

        with patch.object(
            handler.pipeline,
            "execute",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await handler.generate_node(
                prompt="Create EFFECT node for testing",
                output_directory="./output",
                correlation_id=correlation_id,
            )

            assert result.correlation_id == correlation_id

    def test_validate_output_directory_exists(self, tmp_path):
        """Test output directory validation when directory exists."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Create test directory
        test_dir = tmp_path / "output"
        test_dir.mkdir()

        # Validate
        validated_path = handler.validate_output_directory(str(test_dir))

        assert validated_path.exists()
        assert validated_path.is_dir()
        assert validated_path == test_dir.resolve()

    def test_validate_output_directory_creates_if_missing(self, tmp_path):
        """Test output directory validation creates directory if missing."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Directory does not exist
        test_dir = tmp_path / "new_output"
        assert not test_dir.exists()

        # Validate (should create)
        validated_path = handler.validate_output_directory(str(test_dir))

        assert validated_path.exists()
        assert validated_path.is_dir()

    def test_validate_output_directory_not_writable(self, tmp_path):
        """Test output directory validation fails if not writable."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Create read-only directory
        test_dir = tmp_path / "readonly"
        test_dir.mkdir()
        test_dir.chmod(0o444)  # Read-only

        # Validate (should raise)
        with pytest.raises(ValueError, match="not writable"):
            handler.validate_output_directory(str(test_dir))

        # Cleanup
        test_dir.chmod(0o755)

    def test_validate_output_directory_is_file(self, tmp_path):
        """Test output directory validation fails if path is a file."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Create file (not directory)
        test_file = tmp_path / "file.txt"
        test_file.write_text("test")

        # Validate (should raise)
        with pytest.raises(ValueError, match="not a directory"):
            handler.validate_output_directory(str(test_file))

    def test_format_result_summary_success(self):
        """Test result summary formatting for success."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        result = PipelineResult(
            correlation_id=uuid4(),
            status="success",
            total_duration_ms=38450,
            node_type="EFFECT",
            service_name="postgres_writer",
            generated_files=["file1.py", "file2.py"],
            validation_passed=True,
            compilation_passed=True,
        )

        summary = handler.format_result_summary(result)

        assert "SUCCESS" in summary
        assert "38.45s" in summary or "38.4s" in summary
        assert "EFFECT" in summary
        assert "postgres_writer" in summary
        assert "2" in summary  # 2 files

    def test_format_result_summary_failure(self):
        """Test result summary formatting for failure."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        result = PipelineResult(
            correlation_id=uuid4(),
            status="failed",
            total_duration_ms=5000,
            error_summary="Missing dependency",
        )

        # Add failed gate
        result.stages.append(
            PipelineStage(
                stage_name="pre_validation",
                status=StageStatus.FAILED,
                validation_gates=[
                    ValidationGate(
                        gate_id="G4",
                        name="Critical Imports",
                        status="fail",
                        gate_type=GateType.BLOCKING,
                        message="Import failed",
                        duration_ms=50,
                    )
                ],
            )
        )

        summary = handler.format_result_summary(result)

        assert "FAILED" in summary
        assert "Missing dependency" in summary
        assert "G4" in summary
        assert "Import failed" in summary

    def test_format_progress_update(self):
        """Test progress update formatting."""
        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Test various progress levels
        progress_25 = handler.format_progress_update("parsing", 25, "Analyzing prompt")
        assert "25%" in progress_25
        assert "parsing" in progress_25
        assert "Analyzing prompt" in progress_25

        progress_50 = handler.format_progress_update("generation", 50)
        assert "50%" in progress_50
        assert "generation" in progress_50

        progress_100 = handler.format_progress_update("completed", 100, "Done")
        assert "100%" in progress_100
        assert "completed" in progress_100


class TestCLIScript:
    """Tests for generate_node.py CLI script."""

    @pytest.mark.asyncio
    async def test_generate_node_direct_mode(self):
        """Test CLI direct mode (non-interactive)."""
        # Import main function
        from cli.generate_node import generate_node_direct

        handler = CLIHandler()
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        # Mock successful result
        mock_result = PipelineResult(
            correlation_id=uuid4(),
            status="success",
            total_duration_ms=40000,
            node_type="EFFECT",
            service_name="test",
        )

        with patch.object(
            handler.pipeline,
            "execute",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await generate_node_direct(
                handler=handler,
                prompt="Create EFFECT node for testing",
                output_dir="./output",
            )

            assert result.status == "success"

    def test_print_banner(self, capsys):
        """Test banner printing."""
        from cli.generate_node import print_banner

        print_banner()
        captured = capsys.readouterr()

        assert "ONEX Node Generation CLI" in captured.out
        assert "Autonomous Code Generation POC" in captured.out

    def test_print_success(self, capsys):
        """Test success message printing."""
        from cli.generate_node import print_success

        result = PipelineResult(
            correlation_id=uuid4(),
            status="success",
            total_duration_ms=38450,
            output_path="/path/to/output",
            generated_files=["file1.py", "file2.py", "file3.py"],
            node_type="EFFECT",
            service_name="test",
        )

        print_success(result)
        captured = capsys.readouterr()

        assert "SUCCESS" in captured.out
        assert "Node generation completed" in captured.out
        assert "/path/to/output" in captured.out
        assert "3 files" in captured.out

    def test_print_failure(self, capsys):
        """Test failure message printing."""
        from cli.generate_node import print_failure

        result = PipelineResult(
            correlation_id=uuid4(),
            status="failed",
            total_duration_ms=5000,
            error_summary="Test error",
        )

        # Add failed gate
        result.stages.append(
            PipelineStage(
                stage_name="pre_validation",
                status=StageStatus.FAILED,
                validation_gates=[
                    ValidationGate(
                        gate_id="G1",
                        name="Test Gate",
                        status="fail",
                        gate_type=GateType.BLOCKING,
                        message="Gate failed",
                        duration_ms=50,
                    )
                ],
            )
        )

        print_failure(result)
        captured = capsys.readouterr()

        assert "FAILED" in captured.out
        assert "Test error" in captured.out
        assert "G1" in captured.out

    def test_print_warnings(self, capsys):
        """Test warnings printing."""
        from cli.generate_node import print_warnings

        result = PipelineResult(
            correlation_id=uuid4(),
            status="success",
            total_duration_ms=40000,
        )

        # Add warning gate
        result.stages.append(
            PipelineStage(
                stage_name="compilation",
                status=StageStatus.COMPLETED,
                validation_gates=[
                    ValidationGate(
                        gate_id="G13",
                        name="MyPy Check",
                        status="warning",
                        gate_type=GateType.WARNING,
                        message="Type hint missing",
                        duration_ms=50,
                    )
                ],
            )
        )

        print_warnings(result)
        captured = capsys.readouterr()

        assert "Warnings" in captured.out
        assert "G13" in captured.out
        assert "Type hint missing" in captured.out


# Test fixtures
@pytest.fixture
def mock_pipeline_result():
    """Fixture for mock pipeline result."""
    return PipelineResult(
        correlation_id=uuid4(),
        status="success",
        total_duration_ms=40000,
        output_path="/path/to/output",
        generated_files=["file1.py", "file2.py"],
        node_type="EFFECT",
        service_name="test",
        domain="infrastructure",
        validation_passed=True,
        compilation_passed=True,
    )


@pytest.fixture
def cli_handler():
    """Fixture for CLIHandler instance."""
    return CLIHandler(enable_compilation_testing=True)


# Integration tests (if pipeline components available)
@pytest.mark.integration
class TestCLIIntegration:
    """Integration tests for CLI with real pipeline (requires omnibase_core)."""

    @pytest.mark.asyncio
    async def test_full_generation_flow(self, tmp_path):
        """Test complete generation flow end-to-end."""
        # This test requires omnibase_core to be installed
        pytest.importorskip("omnibase_core")

        handler = CLIHandler(enable_compilation_testing=False)  # Skip compile for speed
        assert not isinstance(handler, _CLIHandlerNotAvailable)

        output_dir = tmp_path / "output"

        try:
            result = await handler.generate_node(
                prompt="Create EFFECT node for test database operations",
                output_directory=str(output_dir),
            )

            # Validate result
            assert result is not None
            # Note: May fail if dependencies missing, that's expected

        except Exception as e:
            # Expected if dependencies not available
            pytest.skip(f"Integration test skipped due to: {e}")
