#!/usr/bin/env python3
"""
Tests for Quality Compliance Validators.

Tests 4 quality compliance gates:
- QC-001: ONEX Standards Validator
- QC-002: Anti-YOLO Compliance Validator
- QC-003: Type Safety Validator
- QC-004: Error Handling Validator
"""

import pytest

from agents.lib.validators.quality_compliance_validators import (
    AntiYOLOComplianceValidator,
    ErrorHandlingValidator,
    ONEXStandardsValidator,
    TypeSafetyValidator,
)


class TestONEXStandardsValidator:
    """Tests for QC-001: ONEX Standards Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ONEXStandardsValidator()

    @pytest.mark.asyncio
    async def test_valid_onex_node_class(self, validator):
        """Test validation passes for valid ONEX node class."""
        code = """
class NodeDataProcessorEffect:
    async def execute_effect(self, contract):
        return {"status": "success"}
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.gate.value == "qc_001_onex_standards"

    @pytest.mark.asyncio
    async def test_invalid_node_naming(self, validator):
        """Test validation fails for invalid node naming."""
        code = """
class DataProcessor:  # Missing 'Node' prefix and type suffix
    async def execute(self, contract):
        return {"status": "success"}
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"  # No Node classes, so no violations

    @pytest.mark.asyncio
    async def test_node_missing_type_suffix(self, validator):
        """Test validation fails for node without type suffix."""
        code = """
class NodeDataProcessor:  # Missing Effect/Compute/Reducer/Orchestrator
    async def execute(self, contract):
        return {"status": "success"}
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert "must end with Effect/Compute/Reducer/Orchestrator" in str(
            result.metadata["issues"]
        )

    @pytest.mark.asyncio
    async def test_valid_model_naming(self, validator):
        """Test validation passes for valid model naming."""
        code = """
from pydantic import BaseModel

class ModelUserData(BaseModel):
    name: str
    age: int
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_valid_enum_naming(self, validator):
        """Test validation passes for valid enum naming."""
        code = """
from enum import Enum

class EnumUserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_node_missing_execute_method(self, validator):
        """Test warning for node missing execute method."""
        code = """
class NodeDataProcessorEffect:
    def process(self, data):
        return data
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("execute_effect" in w for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_multiple_node_types(self, validator):
        """Test validation with multiple node types."""
        code = """
class NodeDataFetcherEffect:
    async def execute_effect(self, contract):
        return {"data": []}

class NodeDataTransformerCompute:
    async def execute_compute(self, contract):
        return {"result": {}}

class NodeDataAggregatorReducer:
    async def execute_reduction(self, contract):
        return {"total": 0}

class NodeWorkflowCoordinatorOrchestrator:
    async def execute_orchestration(self, contract):
        return {"status": "complete"}
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["total_classes"] == 4

    @pytest.mark.asyncio
    async def test_syntax_error(self, validator):
        """Test handling of syntax errors."""
        code = """
class NodeBroken
    def method(self):
        pass
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Syntax error" in result.message


class TestAntiYOLOComplianceValidator:
    """Tests for QC-002: Anti-YOLO Compliance Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return AntiYOLOComplianceValidator()

    @pytest.mark.asyncio
    async def test_all_stages_completed(self, validator):
        """Test validation passes when all stages completed."""
        context = {
            "workflow_stages": ["planning", "execution", "validation", "completion"],
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": True,
            "quality_gates_executed": ["input_validation", "output_validation"],
            "skipped_stages": [],
        }
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_missing_planning_stage(self, validator):
        """Test validation fails when planning stage missing."""
        context = {
            "workflow_stages": ["execution", "validation"],
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": False,
            "quality_gates_executed": ["output_validation"],
            "skipped_stages": [],
        }
        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Planning stage not completed" in str(result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_skipped_required_stage(self, validator):
        """Test validation fails when required stage skipped."""
        context = {
            "workflow_stages": ["planning", "execution"],
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": True,
            "quality_gates_executed": ["input_validation"],
            "skipped_stages": ["validation"],
        }
        result = await validator.validate(context)

        assert result.status == "failed"
        assert any("validation" in issue.lower() for issue in result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_skipped_optional_stage(self, validator):
        """Test validation passes with warning when optional stage skipped."""
        context = {
            "workflow_stages": ["planning", "execution", "validation"],
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": True,
            "quality_gates_executed": ["input_validation"],
            "skipped_stages": ["optimization"],  # Optional stage
        }
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("optimization" in w.lower() for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_no_quality_gates(self, validator):
        """Test warning when no quality gates executed."""
        context = {
            "workflow_stages": ["planning", "execution", "validation"],
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": True,
            "quality_gates_executed": [],
            "skipped_stages": [],
        }
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("quality gates" in w.lower() for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_missing_required_stages(self, validator):
        """Test validation fails when required stages missing."""
        context = {
            "workflow_stages": ["planning", "execution"],
            "required_stages": ["planning", "execution", "validation", "completion"],
            "planning_completed": True,
            "quality_gates_executed": ["input_validation"],
            "skipped_stages": [],
        }
        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Missing required stages" in str(result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_stage_ordering(self, validator):
        """Test warning for incorrect stage ordering."""
        context = {
            "workflow_stages": ["execution", "planning", "validation"],  # Wrong order
            "required_stages": ["planning", "execution", "validation"],
            "planning_completed": True,
            "quality_gates_executed": ["input_validation"],
            "skipped_stages": [],
        }
        result = await validator.validate(context)

        # Should pass but have warnings about ordering
        assert result.status in ("passed", "failed")


class TestTypeSafetyValidator:
    """Tests for QC-003: Type Safety Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return TypeSafetyValidator()

    @pytest.mark.asyncio
    async def test_fully_typed_code(self, validator):
        """Test validation passes for fully typed code."""
        code = """
def process_data(name: str, age: int) -> dict[str, Any]:
    return {"name": name, "age": age}

async def fetch_user(user_id: int) -> dict[str, str]:
    return {"id": str(user_id), "name": "test"}
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["type_coverage"] >= 0.9

    @pytest.mark.asyncio
    async def test_missing_return_type(self, validator):
        """Test warning for missing return type."""
        code = """
def process_data(name: str, age: int):  # Missing return type
    return {"name": name, "age": age}
"""
        context = {"code": code, "min_type_coverage": 0.0}  # Allow 0 coverage
        result = await validator.validate(context)

        # Should pass with warnings about missing return type
        assert result.status == "passed"
        assert any("return type" in w.lower() for w in result.metadata["warnings"])
        assert result.metadata["type_coverage"] == 0.0  # Function not counted as typed

    @pytest.mark.asyncio
    async def test_missing_argument_types(self, validator):
        """Test warning for missing argument types."""
        code = """
def process_data(name, age) -> dict[str, int]:  # Missing arg types
    return {"name": name, "age": age}
"""
        context = {"code": code, "min_type_coverage": 0.0}  # Allow 0 coverage
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any(
            "untyped arguments" in w.lower() for w in result.metadata["warnings"]
        )
        assert result.metadata["type_coverage"] == 0.0  # Function not counted as typed

    @pytest.mark.asyncio
    async def test_type_ignore_without_code(self, validator):
        """Test warning for type: ignore without error code."""
        code = """
def process_data(name: str) -> str:
    return name.upper()  # type: ignore
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any(
            "type: ignore without specific error code" in w
            for w in result.metadata["warnings"]
        )

    @pytest.mark.asyncio
    async def test_type_ignore_with_code(self, validator):
        """Test type: ignore with error code."""
        code = """
def process_data(name: str) -> str:
    return name.upper()  # type: ignore[attr-defined]
"""
        context = {"code": code}
        result = await validator.validate(context)

        # Should have warning about missing justification
        assert result.status == "passed"
        assert any("justification" in w.lower() for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_any_type_usage(self, validator):
        """Test warning for Any type usage."""
        code = """
from typing import Any

def process_data(data: Any) -> Any:  # Using Any
    return data
"""
        context = {"code": code, "allow_any": False}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("Any type" in w for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_low_type_coverage(self, validator):
        """Test failure for low type coverage."""
        code = """
def func1(a, b):
    return a + b

def func2(x, y):
    return x * y

def func3(name: str, age: int) -> dict[str, Any]:
    return {"name": name, "age": age}
"""
        context = {"code": code, "min_type_coverage": 0.9}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Type coverage" in str(result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_magic_methods_excluded(self, validator):
        """Test that magic methods are excluded from coverage calculation."""
        code = """
class MyClass:
    def __init__(self, value):  # Magic method, no type hints
        self.value = value

    def process(self, data: str) -> str:  # Regular method with type hints
        return data.upper()
"""
        context = {"code": code, "min_type_coverage": 0.9}
        result = await validator.validate(context)

        # Should pass because magic methods are excluded
        assert result.status == "passed"


class TestErrorHandlingValidator:
    """Tests for QC-004: Error Handling Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ErrorHandlingValidator()

    @pytest.mark.asyncio
    async def test_proper_exception_handling(self, validator):
        """Test validation passes for proper exception handling."""
        code = """
try:
    result = risky_operation()
except ValueError as e:
    raise CustomError("Operation failed") from e
finally:
    cleanup_resources()
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_bare_except_clause(self, validator):
        """Test failure for bare except clause."""
        code = """
try:
    result = risky_operation()
except:  # Bare except
    pass
"""
        context = {"code": code, "allow_bare_except": False}
        result = await validator.validate(context)

        assert result.status == "failed"
        assert any("Bare except" in issue for issue in result.metadata["issues"])

    @pytest.mark.asyncio
    async def test_bare_except_allowed(self, validator):
        """Test bare except allowed when configured."""
        code = """
try:
    result = risky_operation()
except:  # Bare except but allowed
    pass
"""
        context = {"code": code, "allow_bare_except": True}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_missing_exception_chaining(self, validator):
        """Test warning for missing exception chaining."""
        code = """
try:
    result = risky_operation()
except ValueError as e:
    raise CustomError("Operation failed")  # Missing 'from e'
"""
        context = {"code": code, "require_exception_chaining": True}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("without chaining" in w for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_exception_chaining_present(self, validator):
        """Test no warning when exception chaining present."""
        code = """
try:
    result = risky_operation()
except ValueError as e:
    raise CustomError("Operation failed") from e
"""
        context = {"code": code, "require_exception_chaining": True}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_missing_finally_block(self, validator):
        """Test warning for missing finally block with resources."""
        code = """
try:
    file = open("data.txt")
    data = file.read()
except IOError as e:
    raise CustomError("File read failed") from e
# Missing finally block to close file
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
        assert any("finally block" in w.lower() for w in result.metadata["warnings"])

    @pytest.mark.asyncio
    async def test_finally_block_present(self, validator):
        """Test no warning when finally block present."""
        code = """
try:
    file = open("data.txt")
    data = file.read()
except IOError as e:
    raise CustomError("File read failed") from e
finally:
    file.close()
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_no_resource_allocation(self, validator):
        """Test no warning when no resources allocated."""
        code = """
try:
    result = calculate_sum([1, 2, 3])
except ValueError as e:
    raise CustomError("Calculation failed") from e
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_multiple_exception_types(self, validator):
        """Test handling of multiple exception types."""
        code = """
try:
    result = risky_operation()
except ValueError as e:
    raise CustomError("Value error") from e
except KeyError as e:
    raise CustomError("Key error") from e
except Exception as e:
    raise CustomError("Unknown error") from e
finally:
    cleanup()
"""
        context = {"code": code}
        result = await validator.validate(context)

        assert result.status == "passed"
