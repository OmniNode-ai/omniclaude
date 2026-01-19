#!/usr/bin/env python3
"""
Tests for Sequential Validation Gates (SV-001 to SV-004).

Comprehensive test coverage for:
- SV-001: Input Validation
- SV-002: Process Validation
- SV-003: Output Validation
- SV-004: Integration Testing

ONEX v2.0 Compliance:
- Test all pass/fail scenarios
- Validate performance targets
- Test dependency handling
- Verify error messages and metadata
"""


import pytest
from pydantic import BaseModel, Field

from agents.lib.models.model_quality_gate import EnumQualityGate
from agents.lib.validators.sequential_validators import (
    InputValidationValidator,
    IntegrationTestingValidator,
    OutputValidationValidator,
    ProcessValidationValidator,
)


# Test Pydantic models for schema validation
class TestInputSchema(BaseModel):
    """Test schema for input validation."""

    name: str = Field(..., min_length=1, max_length=100)
    age: int = Field(..., ge=0, le=150)
    email: str


class TestOutputSchema(BaseModel):
    """Test schema for output validation."""

    result: str
    count: int
    success: bool


class TestInputValidationValidator:
    """Test SV-001: Input Validation Validator."""

    @pytest.mark.asyncio
    async def test_valid_inputs_pass(self):
        """Test that valid inputs pass validation."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": "John Doe", "age": 30, "email": "john@example.com"},
            "required_fields": ["name", "age"],
        }

        result = await validator.validate(context)

        assert result.gate == EnumQualityGate.INPUT_VALIDATION
        assert result.status == "passed"
        assert result.metadata["validated_fields"] == 3
        assert result.metadata["required_fields"] == 2

    @pytest.mark.asyncio
    async def test_missing_required_fields_fail(self):
        """Test that missing required fields fail validation."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": "John Doe"},
            "required_fields": ["name", "age", "email"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "missing_fields" in result.metadata
        assert set(result.metadata["missing_fields"]) == {"age", "email"}
        assert any(
            "missing required fields" in issue.lower()
            for issue in result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_null_required_field_fails(self):
        """Test that null values in required fields fail."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": None, "age": 30},
            "required_fields": ["name", "age"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "null or empty" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_empty_string_required_field_fails(self):
        """Test that empty strings in required fields fail."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": "   ", "age": 30},
            "required_fields": ["name"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_schema_validation_pass(self):
        """Test schema validation with valid data."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": "John Doe", "age": 30, "email": "john@example.com"},
            "schema": TestInputSchema,
        }

        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_schema_validation_fail(self):
        """Test schema validation with invalid data."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"name": "John Doe", "age": 200, "email": "john@example.com"},
            "schema": TestInputSchema,
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "schema_errors" in result.metadata
        assert "schema_errors" in result.metadata

    @pytest.mark.asyncio
    async def test_type_constraints(self):
        """Test type constraint validation."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"age": "thirty"},  # String instead of int
            "constraints": {"age": {"type": int}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "incorrect type" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_numeric_min_max_constraints(self):
        """Test min/max constraints for numeric values."""
        validator = InputValidationValidator()

        # Test min constraint
        context = {
            "inputs": {"age": 5},
            "constraints": {"age": {"type": int, "min": 18, "max": 65}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "below minimum" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

        # Test max constraint
        context = {
            "inputs": {"age": 70},
            "constraints": {"age": {"type": int, "min": 18, "max": 65}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "above maximum" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_string_length_constraints(self):
        """Test min_length/max_length constraints for strings."""
        validator = InputValidationValidator()

        # Test min_length
        context = {
            "inputs": {"name": "Jo"},
            "constraints": {"name": {"min_length": 3, "max_length": 50}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "below minimum" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

        # Test max_length
        context = {
            "inputs": {"name": "J" * 100},
            "constraints": {"name": {"min_length": 3, "max_length": 50}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "above maximum" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_pattern_constraint(self):
        """Test regex pattern constraint."""
        validator = InputValidationValidator()

        context = {
            "inputs": {"email": "invalid-email"},
            "constraints": {
                "email": {
                    "pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
                }
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "does not match pattern" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_execution_with_timing(self):
        """Test that timing is tracked correctly."""
        validator = InputValidationValidator()

        context = {"inputs": {"test": "value"}, "required_fields": []}

        result = await validator.execute_with_timing(context)

        assert result.execution_time_ms >= 0
        assert result.execution_time_ms <= validator.gate.performance_target_ms * 2


class TestProcessValidationValidator:
    """Test SV-002: Process Validation Validator."""

    @pytest.mark.asyncio
    async def test_valid_process_pass(self):
        """Test that valid process passes validation."""
        validator = ProcessValidationValidator()

        context = {
            "current_stage": "execution",
            "completed_stages": ["initialization", "planning"],
            "expected_stages": ["initialization", "planning", "execution"],
            "workflow_pattern": "sequential_execution",
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["completed_stages_count"] == 2
        assert result.metadata["workflow_pattern"] == "sequential_execution"

    @pytest.mark.asyncio
    async def test_stage_order_violation_fails(self):
        """Test that incorrect stage order fails validation."""
        validator = ProcessValidationValidator()

        context = {
            "completed_stages": ["execution", "initialization"],  # Wrong order
            "expected_stages": ["initialization", "planning", "execution"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "order_violations" in result.metadata
        assert "order_violations" in result.metadata

    @pytest.mark.asyncio
    async def test_skipped_stage_fails(self):
        """Test that skipped stages fail validation (anti-YOLO)."""
        validator = ProcessValidationValidator()

        context = {
            "current_stage": "execution",
            "completed_stages": ["initialization"],  # Skipped "planning"
            "expected_stages": ["initialization", "planning", "execution"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "skipped_stages" in result.metadata
        assert "skipped_stages" in result.metadata
        assert "planning" in result.metadata["skipped_stages"]

    @pytest.mark.asyncio
    async def test_unknown_workflow_pattern_fails(self):
        """Test that unknown workflow patterns fail validation."""
        validator = ProcessValidationValidator()

        context = {
            "completed_stages": ["init"],
            "workflow_pattern": "unknown_pattern_xyz",
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "unknown" in issue.lower() for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_invalid_state_transitions_fail(self):
        """Test that invalid state transitions fail validation."""
        validator = ProcessValidationValidator()

        context = {
            "state_transitions": [
                {"from": "completed", "to": "pending"},  # Invalid
                {"from": "failed", "to": "in_progress"},  # Invalid
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "invalid_transitions" in result.metadata
        assert "invalid_transitions" in result.metadata

    @pytest.mark.asyncio
    async def test_valid_state_transitions_pass(self):
        """Test that valid state transitions pass validation."""
        validator = ProcessValidationValidator()

        context = {
            "state_transitions": [
                {"from": "pending", "to": "in_progress"},
                {"from": "in_progress", "to": "completed"},
            ]
        }

        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_current_stage_not_in_expected_fails(self):
        """Test that current stage not in expected stages fails."""
        validator = ProcessValidationValidator()

        context = {
            "current_stage": "unknown_stage",
            "expected_stages": ["init", "execute", "complete"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"


class TestOutputValidationValidator:
    """Test SV-003: Output Validation Validator."""

    @pytest.mark.asyncio
    async def test_valid_outputs_pass(self):
        """Test that valid outputs pass validation."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {"result": "success", "count": 10, "success": True},
            "expected_outputs": ["result", "count"],
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["validated_outputs"] == 3
        assert result.metadata["expected_outputs"] == 2

    @pytest.mark.asyncio
    async def test_missing_outputs_fail(self):
        """Test that missing expected outputs fail validation."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {"result": "success"},
            "expected_outputs": ["result", "count", "success"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "missing_outputs" in result.metadata
        assert "missing_outputs" in result.metadata
        assert set(result.metadata["missing_outputs"]) == {"count", "success"}

    @pytest.mark.asyncio
    async def test_null_expected_output_fails(self):
        """Test that null values in expected outputs fail."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {"result": None, "count": 10},
            "expected_outputs": ["result", "count"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert any(
            "null" in issue.lower() for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_schema_validation_pass(self):
        """Test output schema validation with valid data."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {"result": "success", "count": 10, "success": True},
            "schema": TestOutputSchema,
        }

        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_schema_validation_fail(self):
        """Test output schema validation with invalid data."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {
                "result": "success",
                "count": "ten",
                "success": True,
            },  # Invalid type
            "schema": TestOutputSchema,
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "schema_errors" in result.metadata

    @pytest.mark.asyncio
    async def test_generated_files_validation(self):
        """Test generated file existence validation."""
        import tempfile

        validator = OutputValidationValidator()

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        context = {
            "outputs": {},
            "generated_files": [tmp_path, "/nonexistent/file.txt"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "missing_files" in result.metadata
        assert "missing_files" in result.metadata

        # Cleanup
        import os

        os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_quality_metrics_validation(self):
        """Test quality metrics threshold validation."""
        validator = OutputValidationValidator()

        context = {
            "outputs": {"quality_score": 0.5, "performance_ms": 150},
            "quality_metrics": {
                "quality_score": {"min": 0.8},  # Failed
                "performance_ms": {"max": 100},  # Failed
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "validation failed" in result.message.lower()
        assert "failed_metrics" in result.metadata
        assert "failed_metrics" in result.metadata


class TestIntegrationTestingValidator:
    """Test SV-004: Integration Testing Validator."""

    @pytest.mark.asyncio
    async def test_valid_integration_pass(self):
        """Test that valid integration passes validation."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [
                {"target_agent": "agent1", "status": "success"},
                {"target_agent": "agent2", "status": "success"},
            ],
            "context_transfers": [
                {
                    "target_agent": "agent1",
                    "required_keys": ["task_id", "data"],
                    "context": {"task_id": "123", "data": "test"},
                }
            ],
            "messages": [
                {
                    "sender": "agent1",
                    "recipient": "agent2",
                    "message_type": "data",
                    "payload": {},
                }
            ],
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["delegations_count"] == 2
        assert result.metadata["messages_count"] == 1

    @pytest.mark.asyncio
    async def test_failed_delegations_fail(self):
        """Test that failed delegations fail validation."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [
                {"target_agent": "agent1", "status": "failed"},
                {"target_agent": "agent2", "status": "success"},
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "validation failed" in result.message.lower()
            or "testing failed" in result.message.lower()
        )
        assert "failed_delegations" in result.metadata
        assert "agent1" in result.metadata["failed_delegations"]

    @pytest.mark.asyncio
    async def test_incomplete_context_transfer_fails(self):
        """Test that incomplete context transfers fail validation."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [],
            "context_transfers": [
                {
                    "target_agent": "agent1",
                    "required_keys": ["task_id", "data", "config"],
                    "context": {"task_id": "123"},  # Missing "data" and "config"
                }
            ],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "validation failed" in result.message.lower()
            or "testing failed" in result.message.lower()
        )
        assert "incomplete_transfers" in result.metadata

    @pytest.mark.asyncio
    async def test_invalid_message_format_fails(self):
        """Test that invalid message format fails validation."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [],
            "messages": [
                {
                    "sender": "agent1",
                    "recipient": "agent2",
                },  # Missing message_type and payload
            ],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "validation failed" in result.message.lower()
            or "testing failed" in result.message.lower()
        )
        assert "invalid_messages" in result.metadata

    @pytest.mark.asyncio
    async def test_sequential_protocol_violation(self):
        """Test sequential coordination protocol validation."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [],
            "coordination_protocol": "sequential",
            "parallel_execution": True,  # Violates sequential protocol
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "validation failed" in result.message.lower()
            or "testing failed" in result.message.lower()
        )
        assert "protocol_violations" in result.metadata

    @pytest.mark.asyncio
    async def test_parallel_protocol_without_sync_points(self):
        """Test parallel protocol requires sync points."""
        validator = IntegrationTestingValidator()

        context = {
            "delegations": [],
            "coordination_protocol": "parallel",
            # Missing sync_points
        }

        result = await validator.validate(context)

        assert result.status == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
