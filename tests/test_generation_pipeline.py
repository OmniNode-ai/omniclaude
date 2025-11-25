#!/usr/bin/env python3
"""
Tests for Generation Pipeline - Autonomous Node Generation POC

Comprehensive test suite for pipeline orchestration and validation gates.
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.generation_pipeline import GenerationPipeline
from agents.lib.models.pipeline_models import (
    GateType,
    PipelineResult,
    PipelineStage,
    StageStatus,
    ValidationGate,
)


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_template_engine():
    """Mock template engine."""
    engine = MagicMock()
    engine.templates = {"EFFECT": MagicMock()}
    engine.generate_node = AsyncMock(
        return_value={
            "node_type": "EFFECT",
            "microservice_name": "test_service",
            "domain": "test_domain",
            "output_path": "/tmp/test_output/node_test_test_service_effect",
            "main_file": "/tmp/test_output/node_test_test_service_effect/v1_0_0/node.py",
            "generated_files": [
                "/tmp/test_output/node_test_test_service_effect/v1_0_0/node.py",
                "/tmp/test_output/node_test_test_service_effect/v1_0_0/models/model_test_service_input.py",
                "/tmp/test_output/node_test_test_service_effect/v1_0_0/models/model_test_service_output.py",
            ],
            "metadata": {
                "session_id": str(uuid4()),
                "correlation_id": str(uuid4()),
                "node_metadata": {},
                "confidence_score": 0.85,
                "quality_baseline": 0.8,
            },
            "context": {},
        }
    )
    return engine


@pytest.fixture
def pipeline(mock_template_engine):
    """Create pipeline instance with mocked template engine."""
    return GenerationPipeline(
        template_engine=mock_template_engine,
        enable_compilation_testing=False,  # Disable for faster tests
    )


@pytest.fixture
def pipeline_lite(mock_template_engine):
    """Lightweight pipeline for performance tests - disables heavy initialization."""
    return GenerationPipeline(
        template_engine=mock_template_engine,
        enable_compilation_testing=False,
        enable_intelligence_gathering=False,  # Skip intelligence gatherer init
    )


@pytest.fixture
def valid_prompt():
    """Valid test prompt."""
    return "Create EFFECT node for PostgreSQL database write operations"


@pytest.fixture
def invalid_prompt():
    """Invalid test prompt (too short)."""
    return "node"


# -------------------------------------------------------------------------
# Pipeline Models Tests
# -------------------------------------------------------------------------


def test_validation_gate_creation():
    """Test ValidationGate model creation."""
    gate = ValidationGate(
        gate_id="G1",
        name="Test Gate",
        status="pass",
        gate_type=GateType.BLOCKING,
        message="Test message",
        duration_ms=50,
    )

    assert gate.gate_id == "G1"
    assert gate.name == "Test Gate"
    assert gate.status == "pass"
    assert gate.gate_type == GateType.BLOCKING
    assert gate.duration_ms == 50


def test_pipeline_stage_creation():
    """Test PipelineStage model creation."""
    stage = PipelineStage(
        stage_name="test_stage", status=StageStatus.COMPLETED, duration_ms=1000
    )

    assert stage.stage_name == "test_stage"
    assert stage.status == StageStatus.COMPLETED
    assert stage.duration_ms == 1000
    assert len(stage.validation_gates) == 0


def test_pipeline_result_success():
    """Test PipelineResult success property."""
    result = PipelineResult(
        correlation_id=uuid4(),
        status="success",
        total_duration_ms=5000,
        stages=[],
        validation_passed=True,
        compilation_passed=True,
    )

    assert result.success is True
    assert result.duration_seconds == 5.0


def test_pipeline_result_failure():
    """Test PipelineResult failure property."""
    result = PipelineResult(
        correlation_id=uuid4(),
        status="failed",
        total_duration_ms=2000,
        stages=[],
        error_summary="Test error",
    )

    assert result.success is False
    assert result.error_summary == "Test error"


def test_pipeline_result_get_failed_gates():
    """Test PipelineResult get_failed_gates method."""
    gate1 = ValidationGate(
        gate_id="G1",
        name="Test 1",
        status="pass",
        gate_type=GateType.BLOCKING,
        duration_ms=10,
    )
    gate2 = ValidationGate(
        gate_id="G2",
        name="Test 2",
        status="fail",
        gate_type=GateType.BLOCKING,
        duration_ms=10,
        message="Failed",
    )

    stage = PipelineStage(
        stage_name="test",
        status=StageStatus.COMPLETED,
        validation_gates=[gate1, gate2],
    )

    result = PipelineResult(
        correlation_id=uuid4(),
        status="failed",
        total_duration_ms=1000,
        stages=[stage],
    )

    failed = result.get_failed_gates()
    assert len(failed) == 1
    assert failed[0].gate_id == "G2"


def test_pipeline_result_to_summary():
    """Test PipelineResult to_summary method."""
    result = PipelineResult(
        correlation_id=uuid4(),
        status="success",
        total_duration_ms=10000,
        stages=[],
        node_type="EFFECT",
        service_name="test_service",
        generated_files=["file1.py", "file2.py"],
    )

    summary = result.to_summary()
    assert "SUCCESS" in summary
    assert "10.00s" in summary
    assert "EFFECT" in summary
    assert "test_service" in summary
    assert "2" in summary  # File count


# -------------------------------------------------------------------------
# Validation Gates Tests
# -------------------------------------------------------------------------


def test_gate_g1_prompt_completeness_pass(pipeline):
    """Test G1 gate with complete prompt data."""
    parsed_data = {
        "node_type": "EFFECT",
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test description",
    }

    gate = pipeline._gate_g1_prompt_completeness_full(parsed_data)
    assert gate.status == "pass"
    assert gate.gate_id == "G1"


def test_gate_g1_prompt_completeness_fail(pipeline):
    """Test G1 gate with incomplete prompt data."""
    parsed_data = {
        "node_type": "EFFECT",
        # Missing service_name, domain, description
    }

    gate = pipeline._gate_g1_prompt_completeness_full(parsed_data)
    assert gate.status == "fail"
    assert "Missing required fields" in gate.message


def test_gate_g2_node_type_valid_pass(pipeline):
    """Test G2 gate with valid node type."""
    gate = pipeline._gate_g2_node_type_valid("EFFECT")
    assert gate.status == "pass"


def test_gate_g2_node_type_valid_fail(pipeline):
    """Test G2 gate with invalid node type."""
    gate = pipeline._gate_g2_node_type_valid("INVALID")
    assert gate.status == "fail"
    assert "Invalid node type" in gate.message


def test_gate_g3_service_name_valid_pass(pipeline):
    """Test G3 gate with valid service name."""
    gate = pipeline._gate_g3_service_name_valid("test_service")
    assert gate.status == "pass"


def test_gate_g3_service_name_valid_fail(pipeline):
    """Test G3 gate with invalid service name."""
    # Invalid: PascalCase
    gate = pipeline._gate_g3_service_name_valid("TestService")
    assert gate.status == "fail"

    # Invalid: starts with number
    gate = pipeline._gate_g3_service_name_valid("1test")
    assert gate.status == "fail"


def test_gate_g4_critical_imports_exist(pipeline):
    """Test G4 gate for critical imports."""
    gate = pipeline._gate_g4_critical_imports_exist()
    # Should pass if omnibase_core is installed
    # If not, should fail gracefully
    assert gate.gate_id == "G4"
    assert gate.status in ["pass", "fail"]


def test_gate_g5_templates_available_pass(pipeline):
    """Test G5 gate with available template."""
    gate = pipeline._gate_g5_templates_available("EFFECT")
    assert gate.status == "pass"


def test_gate_g5_templates_available_fail(pipeline):
    """Test G5 gate with unavailable template."""
    # Remove EFFECT template temporarily
    original = pipeline.template_engine.templates.get("EFFECT")
    pipeline.template_engine.templates.pop("EFFECT", None)

    gate = pipeline._gate_g5_templates_available("EFFECT")
    assert gate.status == "fail"

    # Restore
    if original:
        pipeline.template_engine.templates["EFFECT"] = original


def test_gate_g7_prompt_completeness_pass(pipeline):
    """Test G7 gate with good prompt."""
    gate = pipeline._gate_g7_prompt_completeness(
        "Create EFFECT node for database operations"
    )
    assert gate.status == "pass"


def test_gate_g7_prompt_completeness_warning(pipeline):
    """Test G7 gate with short prompt."""
    gate = pipeline._gate_g7_prompt_completeness("node")
    assert gate.status == "warning"


def test_gate_g8_context_completeness_pass(pipeline):
    """Test G8 gate with complete context."""
    parsed_data = {
        "node_type": "EFFECT",
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test",
        "operations": ["op1"],
        "features": ["feat1"],
    }

    gate = pipeline._gate_g8_context_completeness(parsed_data)
    assert gate.status == "pass"


def test_gate_g8_context_completeness_warning(pipeline):
    """Test G8 gate with incomplete context."""
    parsed_data = {
        "node_type": "EFFECT",
        "service_name": "test_service",
        # Missing domain, description, operations, features
    }

    gate = pipeline._gate_g8_context_completeness(parsed_data)
    assert gate.status == "warning"


def test_gate_g9_python_syntax_valid_pass(pipeline):
    """Test G9 gate with valid Python syntax."""
    code = """
class NodeTestEffect:
    def execute_effect(self, input_data):
        return input_data
"""
    gate = pipeline._gate_g9_python_syntax_valid(code, "test.py")
    assert gate.status == "pass"


def test_gate_g9_python_syntax_valid_fail(pipeline):
    """Test G9 gate with invalid Python syntax."""
    code = """
class NodeTestEffect(
    def execute_effect(self, input_data):  # Missing closing paren
        return input_data
"""
    gate = pipeline._gate_g9_python_syntax_valid(code, "test.py")
    assert gate.status == "fail"
    assert "Syntax error" in gate.message


def test_gate_g10_onex_naming_pass(pipeline):
    """Test G10 gate with correct ONEX naming."""
    code = """
class NodeTestServiceEffect(NodeEffect):
    pass
"""
    gate = pipeline._gate_g10_onex_naming(code, "EFFECT")
    assert gate.status == "pass"


def test_gate_g10_onex_naming_fail_prefix(pipeline):
    """Test G10 gate with incorrect ONEX naming (prefix)."""
    code = """
class EffectTestService(NodeEffect):  # WRONG: prefix instead of suffix
    pass
"""
    gate = pipeline._gate_g10_onex_naming(code, "EFFECT")
    assert gate.status == "fail"


def test_gate_g10_onex_naming_fail_missing(pipeline):
    """Test G10 gate with missing node class."""
    code = """
class SomeOtherClass:
    pass
"""
    gate = pipeline._gate_g10_onex_naming(code, "EFFECT")
    assert gate.status == "fail"


def test_gate_g11_import_resolution_pass(pipeline):
    """Test G11 gate with valid imports."""
    code = """
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.errors.model_onex_error import ModelOnexError
"""
    gate = pipeline._gate_g11_import_resolution(code)
    assert gate.status == "pass"


def test_gate_g11_import_resolution_fail(pipeline):
    """Test G11 gate with invalid imports."""
    code = """
from omnibase_core.core.node_effect import NodeEffect  # OLD PATH
"""
    gate = pipeline._gate_g11_import_resolution(code)
    assert gate.status == "fail"
    assert "Old import path" in gate.message


def test_gate_g12_pydantic_models_pass(pipeline):
    """Test G12 gate with valid Pydantic models."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(
            """
from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

    class Config:
        extra = "forbid"
"""
        )
        f.flush()

        gate = pipeline._gate_g12_pydantic_models([f.name])
        assert gate.status in ["pass", "warning"]

        # Cleanup
        Path(f.name).unlink()


def test_gate_g12_pydantic_models_warning(pipeline):
    """Test G12 gate with old Pydantic v1 patterns."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(
            """
from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

    def to_dict(self):
        return self.dict()  # OLD PYDANTIC V1
"""
        )
        f.flush()

        gate = pipeline._gate_g12_pydantic_models([f.name])
        assert gate.status == "warning"
        assert "Pydantic v1 pattern" in gate.message

        # Cleanup
        Path(f.name).unlink()


# -------------------------------------------------------------------------
# Helper Methods Tests
# -------------------------------------------------------------------------


def test_prompt_to_prd(pipeline):
    """Test prompt to PRD conversion."""
    prompt = "Create EFFECT node for database operations"
    prd = pipeline._prompt_to_prd(prompt)

    assert "Node Generation Request" in prd
    assert prompt in prd
    assert "## Overview" in prd
    assert "## Functional Requirements" in prd


def test_detect_node_type(pipeline):
    """Test node type detection from prompt keywords."""
    # Explicit node type mentions are detected with high confidence
    assert pipeline._detect_node_type("Create EFFECT node") == "EFFECT"
    assert pipeline._detect_node_type("Build a compute node") == "COMPUTE"
    assert (
        pipeline._detect_node_type("Create a reducer node for aggregation") == "REDUCER"
    )
    assert (
        pipeline._detect_node_type("orchestrator node for workflow") == "ORCHESTRATOR"
    )

    # Case insensitivity
    assert pipeline._detect_node_type("COMPUTE node for calculations") == "COMPUTE"
    assert pipeline._detect_node_type("effect node for database writes") == "EFFECT"

    # Action verb inference (when no explicit node type keyword present)
    assert (
        pipeline._detect_node_type("Process some data") == "COMPUTE"
    )  # "process" is COMPUTE indicator
    assert (
        pipeline._detect_node_type("Write to database") == "EFFECT"
    )  # "write" is EFFECT indicator
    assert (
        pipeline._detect_node_type("Aggregate the results") == "REDUCER"
    )  # "aggregate" is REDUCER indicator

    # Default to EFFECT when no node type indicators present
    assert pipeline._detect_node_type("Do something with data") == "EFFECT"


def test_extract_service_name_from_prompt(pipeline):
    """Test service name extraction from prompt."""

    # Mock analysis result
    mock_result = MagicMock()
    mock_result.parsed_prd.extracted_keywords = ["database", "postgresql"]

    # Test extraction from prompt
    name = pipeline._extract_service_name(
        "Create EFFECT node for PostgreSQL operations", mock_result
    )
    assert name == "postgresql"


def test_extract_domain_database(pipeline):
    """Test domain extraction for database prompts."""

    mock_result = MagicMock()

    domain = pipeline._extract_domain(
        "Create EFFECT node for PostgreSQL database", mock_result
    )
    assert domain == "infrastructure"


def test_extract_domain_api(pipeline):
    """Test domain extraction for API prompts."""

    mock_result = MagicMock()

    domain = pipeline._extract_domain(
        "Create EFFECT node for REST API endpoint", mock_result
    )
    assert domain == "api"


# -------------------------------------------------------------------------
# Stage Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_1_parse_prompt_success(pipeline, valid_prompt):
    """Test Stage 1 with valid prompt."""
    stage, result = await pipeline._stage_1_parse_prompt(valid_prompt)

    assert stage.status == StageStatus.COMPLETED
    assert stage.stage_name == "prompt_parsing"
    assert len(stage.validation_gates) == 2  # G7 and G8
    assert "parsed_data" in result
    assert "analysis_result" in result


@pytest.mark.asyncio
async def test_stage_3_pre_validation_success(pipeline):
    """Test Stage 3 with valid parsed data."""
    parsed_data = {
        "node_type": "EFFECT",
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test description",
        "operations": ["op1"],
        "features": ["feat1"],
        "confidence": 0.85,
    }

    stage = await pipeline._stage_3_pre_validation(parsed_data)

    assert stage.status == StageStatus.COMPLETED
    assert stage.stage_name == "pre_generation_validation"
    assert len(stage.validation_gates) == 6  # G1-G6


@pytest.mark.asyncio
async def test_stage_3_pre_validation_fail_invalid_node_type(pipeline):
    """Test Stage 3 failure with invalid node type."""
    parsed_data = {
        "node_type": "INVALID",  # Invalid for POC
        "service_name": "test_service",
        "domain": "test_domain",
        "description": "Test description",
        "operations": ["op1"],
        "features": ["feat1"],
        "confidence": 0.85,
    }

    stage = await pipeline._stage_3_pre_validation(parsed_data)

    assert stage.status == StageStatus.FAILED
    assert "Invalid node type" in stage.error


# -------------------------------------------------------------------------
# Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_execute_mock_success(pipeline, valid_prompt, temp_output_dir):
    """Test complete pipeline execution with mocked template engine."""
    # Create mock files that will be checked
    output_path = Path(temp_output_dir) / "node_infrastructure_postgresql_effect"
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "v1_0_0").mkdir(exist_ok=True)

    # Write mock node file
    node_file = output_path / "v1_0_0" / "node.py"
    node_file.write_text(
        """
from omnibase_core.nodes.node_effect import NodeEffect

class NodePostgresqlEffect(NodeEffect):
    async def execute_effect(self, input_data):
        return input_data
"""
    )

    # Update mock to return correct paths
    pipeline.template_engine.generate_node.return_value = {
        "node_type": "EFFECT",
        "microservice_name": "postgresql",
        "domain": "infrastructure",
        "output_path": str(output_path),
        "main_file": str(node_file),
        "generated_files": [str(node_file)],
        "metadata": {
            "session_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "node_metadata": {},
            "confidence_score": 0.85,
            "quality_baseline": 0.8,
        },
        "context": {},
    }

    # Execute pipeline
    result = await pipeline.execute(valid_prompt, temp_output_dir)

    assert result.status == "success"
    assert result.success is True
    assert result.node_type == "EFFECT"
    assert len(result.stages) >= 5  # At least 5 stages (excluding compilation)
    assert result.validation_passed is True


@pytest.mark.asyncio
async def test_pipeline_execute_rollback_on_error(
    pipeline, invalid_prompt, temp_output_dir
):
    """Test pipeline rollback on error."""
    # This should fail at G7 (prompt too short)
    result = await pipeline.execute(invalid_prompt, temp_output_dir)

    assert result.status == "failed"
    assert result.success is False
    assert result.error_summary is not None


# -------------------------------------------------------------------------
# Performance Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.slow
async def test_pipeline_performance_target(pipeline, valid_prompt, temp_output_dir):
    """Test pipeline meets performance target (<2 minutes)."""
    import time

    start_time = time.time()

    # Create mock files
    output_path = Path(temp_output_dir) / "node_infrastructure_test_effect"
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "v1_0_0").mkdir(exist_ok=True)

    node_file = output_path / "v1_0_0" / "node.py"
    node_file.write_text(
        """
from omnibase_core.nodes.node_effect import NodeEffect

class NodeTestEffect(NodeEffect):
    async def execute_effect(self, input_data):
        return input_data
"""
    )

    pipeline.template_engine.generate_node.return_value = {
        "node_type": "EFFECT",
        "microservice_name": "test",
        "domain": "infrastructure",
        "output_path": str(output_path),
        "main_file": str(node_file),
        "generated_files": [str(node_file)],
        "metadata": {
            "session_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "node_metadata": {},
            "confidence_score": 0.85,
            "quality_baseline": 0.8,
        },
        "context": {},
    }

    result = await pipeline.execute(valid_prompt, temp_output_dir)
    duration = time.time() - start_time

    # Should complete in <2 minutes (120 seconds)
    assert duration < 120
    assert result.success is True


def test_validation_gates_performance(pipeline_lite):
    """Test individual validation gates meet <200ms target.

    Uses pipeline_lite fixture for faster initialization and
    time.perf_counter() for more accurate timing measurements.
    """
    # G1
    start = time.perf_counter()
    pipeline_lite._gate_g1_prompt_completeness_full(
        {
            "node_type": "EFFECT",
            "service_name": "test",
            "domain": "test",
            "description": "test",
        }
    )
    duration_ms = (time.perf_counter() - start) * 1000
    assert duration_ms < 200

    # G2
    start = time.perf_counter()
    pipeline_lite._gate_g2_node_type_valid("EFFECT")
    duration_ms = (time.perf_counter() - start) * 1000
    assert duration_ms < 200

    # G3
    start = time.perf_counter()
    pipeline_lite._gate_g3_service_name_valid("test_service")
    duration_ms = (time.perf_counter() - start) * 1000
    assert duration_ms < 200


# -------------------------------------------------------------------------
# Run Tests
# -------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
