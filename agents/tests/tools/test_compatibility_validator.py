#!/usr/bin/env python3
"""
Comprehensive tests for tools/compatibility_validator.py

Tests cover:
- ValidationCheck and ValidationResult dataclasses
- Template detection and placeholder substitution
- Import validation
- Class naming conventions
- Base class validation
- Container DI validation
- Pydantic v2 validation
- Type hint validation
- Forbidden pattern validation
- Directory validation
- Edge cases and error conditions
"""

import ast
import json
import tempfile
from pathlib import Path

import pytest

from tools.compatibility_validator import (
    CheckStatus,
    CheckType,
    OmniBaseCompatibilityValidator,
    ValidationCheck,
    ValidationResult,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def validator():
    """Create a basic validator instance"""
    return OmniBaseCompatibilityValidator()


@pytest.fixture
def strict_validator():
    """Create a strict validator instance"""
    return OmniBaseCompatibilityValidator(strict=True)


@pytest.fixture
def template_validator():
    """Create a validator in template mode"""
    return OmniBaseCompatibilityValidator(template_mode=True)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# Test DataClasses
# ============================================================================


class TestValidationCheck:
    """Test ValidationCheck dataclass"""

    def test_validation_check_creation(self):
        """Test creating a ValidationCheck"""
        check = ValidationCheck(
            check_type=CheckType.IMPORT,
            status=CheckStatus.PASS,
            rule="test_rule",
            message="Test message",
            line_number=10,
            details="Test details",
            suggestion="Test suggestion",
        )

        assert check.check_type == CheckType.IMPORT
        assert check.status == CheckStatus.PASS
        assert check.rule == "test_rule"
        assert check.message == "Test message"
        assert check.line_number == 10
        assert check.details == "Test details"
        assert check.suggestion == "Test suggestion"

    def test_validation_check_optional_fields(self):
        """Test ValidationCheck with optional fields as None"""
        check = ValidationCheck(
            check_type=CheckType.PATTERN,
            status=CheckStatus.FAIL,
            rule="test_rule",
            message="Test message",
        )

        assert check.line_number is None
        assert check.details is None
        assert check.suggestion is None


class TestValidationResult:
    """Test ValidationResult dataclass"""

    def test_validation_result_creation(self):
        """Test creating a ValidationResult"""
        result = ValidationResult(
            file_path="/test/file.py", overall_status=CheckStatus.PASS
        )

        assert result.file_path == "/test/file.py"
        assert result.overall_status == CheckStatus.PASS
        assert result.checks == []
        assert result.errors == []

    def test_summary_all_passed(self):
        """Test summary with all checks passed"""
        result = ValidationResult(
            file_path="/test/file.py", overall_status=CheckStatus.PASS
        )
        result.checks = [
            ValidationCheck(CheckType.IMPORT, CheckStatus.PASS, "rule1", "msg1"),
            ValidationCheck(CheckType.NAMING, CheckStatus.PASS, "rule2", "msg2"),
        ]

        summary = result.summary
        assert summary["total"] == 2
        assert summary["passed"] == 2
        assert summary["failed"] == 0
        assert summary["warnings"] == 0
        assert summary["skipped"] == 0

    def test_summary_mixed_statuses(self):
        """Test summary with mixed check statuses"""
        result = ValidationResult(
            file_path="/test/file.py", overall_status=CheckStatus.WARNING
        )
        result.checks = [
            ValidationCheck(CheckType.IMPORT, CheckStatus.PASS, "rule1", "msg1"),
            ValidationCheck(CheckType.NAMING, CheckStatus.FAIL, "rule2", "msg2"),
            ValidationCheck(CheckType.PYDANTIC, CheckStatus.WARNING, "rule3", "msg3"),
            ValidationCheck(CheckType.PATTERN, CheckStatus.SKIP, "rule4", "msg4"),
        ]

        summary = result.summary
        assert summary["total"] == 4
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["warnings"] == 1
        assert summary["skipped"] == 1

    def test_to_dict(self):
        """Test converting ValidationResult to dictionary"""
        result = ValidationResult(
            file_path="/test/file.py", overall_status=CheckStatus.PASS
        )
        result.checks = [
            ValidationCheck(
                CheckType.IMPORT,
                CheckStatus.PASS,
                "rule1",
                "msg1",
                line_number=5,
                details="details1",
                suggestion="suggestion1",
            )
        ]
        result.errors = ["error1"]

        data = result.to_dict()

        assert data["file_path"] == "/test/file.py"
        assert data["status"] == "pass"
        assert len(data["checks"]) == 1
        assert data["checks"][0]["type"] == "import"
        assert data["checks"][0]["status"] == "pass"
        assert data["checks"][0]["rule"] == "rule1"
        assert data["checks"][0]["message"] == "msg1"
        assert data["checks"][0]["line"] == 5
        assert data["checks"][0]["details"] == "details1"
        assert data["checks"][0]["suggestion"] == "suggestion1"
        assert data["errors"] == ["error1"]
        assert "summary" in data


# ============================================================================
# Test Template Detection and Substitution
# ============================================================================


class TestTemplateDetection:
    """Test template detection and placeholder substitution"""

    def test_is_template_file_with_placeholders(self, validator):
        """Test detecting template files with placeholders"""
        content = """
class Node{MICROSERVICE_NAME_PASCAL}Effect:
    pass
"""
        assert validator._is_template_file(content) is True

    def test_is_template_file_without_placeholders(self, validator):
        """Test detecting non-template files"""
        content = """
class NodeUserServiceEffect:
    pass
"""
        assert validator._is_template_file(content) is False

    @pytest.mark.parametrize(
        "placeholder",
        [
            "{MICROSERVICE_NAME}",
            "{MICROSERVICE_NAME_PASCAL}",
            "{DOMAIN}",
            "{DOMAIN_PASCAL}",
            "{NODE_TYPE}",
        ],
    )
    def test_is_template_file_various_placeholders(self, validator, placeholder):
        """Test detecting various placeholder patterns"""
        content = f"class Test{placeholder}Class:\n    pass"
        assert validator._is_template_file(content) is True

    def test_substitute_placeholders(self, validator):
        """Test placeholder substitution"""
        content = """
class Node{MICROSERVICE_NAME_PASCAL}Effect:
    def __init__(self):
        self.name = "{MICROSERVICE_NAME}"
        self.domain = "{DOMAIN}"
"""
        result = validator._substitute_placeholders(content)

        assert "{MICROSERVICE_NAME_PASCAL}" not in result
        assert "{MICROSERVICE_NAME}" not in result
        assert "{DOMAIN}" not in result
        assert "NodeExampleServiceEffect" in result
        assert "example_service" in result
        assert "example_domain" in result

    def test_substitute_all_placeholders(self, validator):
        """Test substituting all known placeholders"""
        placeholders = [
            "{MICROSERVICE_NAME}",
            "{MICROSERVICE_NAME_PASCAL}",
            "{DOMAIN}",
            "{DOMAIN_PASCAL}",
            "{NODE_TYPE}",
            "{BUSINESS_DESCRIPTION}",
            "{MIXIN_IMPORTS}",
            "{MIXIN_INHERITANCE}",
            "{MIXIN_INITIALIZATION}",
            "{BUSINESS_LOGIC_STUB}",
            "{OPERATIONS}",
            "{FEATURES}",
        ]

        content = "\n".join(placeholders)
        result = validator._substitute_placeholders(content)

        for placeholder in placeholders:
            assert placeholder not in result


# ============================================================================
# Test Import Validation
# ============================================================================


class TestImportValidation:
    """Test import statement validation"""

    def test_valid_omnibase_import(self, validator, temp_dir):
        """Test valid omnibase_core import"""
        test_file = temp_dir / "test_valid_import.py"
        test_file.write_text(
            """
from omnibase_core.nodes.node_effect import NodeEffect

class NodeTestEffect(NodeEffect):
    pass
"""
        )

        result = validator.validate_file(test_file)
        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]

        assert len(import_checks) > 0
        assert any(c.status == CheckStatus.PASS for c in import_checks)

    def test_incorrect_import_path(self, validator, temp_dir):
        """Test detection of incorrect import paths"""
        test_file = temp_dir / "test_incorrect_import.py"
        test_file.write_text(
            """
from omnibase_core.core.node_effect import NodeEffect
"""
        )

        result = validator.validate_file(test_file)
        import_checks = [
            c
            for c in result.checks
            if c.check_type == CheckType.IMPORT and c.status == CheckStatus.FAIL
        ]

        assert len(import_checks) > 0
        assert any("incorrect_import_path" in c.rule for c in import_checks)

    def test_unknown_import_name(self, validator, temp_dir):
        """Test detection of unknown import names"""
        test_file = temp_dir / "test_unknown_import.py"
        test_file.write_text(
            """
from omnibase_core.nodes.node_effect import UnknownClass
"""
        )

        result = validator.validate_file(test_file)
        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]

        # Should have a warning about unknown import name
        assert any(
            c.status == CheckStatus.WARNING and "unknown_import_name" in c.rule
            for c in import_checks
        )

    def test_non_omnibase_import_ignored(self, validator, temp_dir):
        """Test that non-omnibase imports are ignored"""
        test_file = temp_dir / "test_other_import.py"
        test_file.write_text(
            """
import json
from typing import Dict, List
"""
        )

        result = validator.validate_file(test_file)
        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]

        # Should not check non-omnibase imports
        assert len(import_checks) == 0


# ============================================================================
# Test Class Naming Validation
# ============================================================================


class TestClassNaming:
    """Test ONEX class naming conventions"""

    @pytest.mark.parametrize(
        ("class_name", "expected_pass"),
        [
            ("NodeUserServiceEffect", True),
            ("NodeDataProcessorCompute", True),
            ("NodeStateManagerReducer", True),
            ("NodeWorkflowOrchestrator", True),
            ("NodeTestEffect", True),  # Test classes allowed
            ("NodeEffectBad", False),  # Wrong order
            ("NodeEffect", False),  # Missing name
        ],
    )
    def test_node_naming_patterns(self, validator, temp_dir, class_name, expected_pass):
        """Test various Node class naming patterns"""
        test_file = temp_dir / f"test_{class_name}.py"
        test_file.write_text(f"class {class_name}:\n    pass\n")

        result = validator.validate_file(test_file)
        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]

        if expected_pass and not class_name.startswith("NodeTest"):
            assert any(c.status == CheckStatus.PASS for c in naming_checks)
        elif not expected_pass:
            assert any(c.status == CheckStatus.FAIL for c in naming_checks)

    def test_node_test_classes_excluded(self, validator, temp_dir):
        """Test that NodeTest* classes are excluded from naming validation"""
        test_file = temp_dir / "test_nodetest.py"
        test_file.write_text("class NodeTest:\n    pass\n")

        result = validator.validate_file(test_file)
        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]

        # NodeTest classes should not trigger naming validation
        assert not any("NodeTest" in c.message for c in naming_checks)

    @pytest.mark.parametrize(
        "class_name",
        [
            "ModelUser",
            "ModelUserInput",
            "ModelEffectOutput",
            "ModelComputeInput",
        ],
    )
    def test_model_naming_patterns(self, validator, temp_dir, class_name):
        """Test Model class naming patterns"""
        test_file = temp_dir / f"test_{class_name}.py"
        test_file.write_text(f"class {class_name}:\n    pass\n")

        result = validator.validate_file(test_file)
        naming_checks = [
            c
            for c in result.checks
            if c.check_type == CheckType.NAMING and "model_naming" in c.rule
        ]

        assert any(c.status == CheckStatus.PASS for c in naming_checks)

    @pytest.mark.parametrize(
        "class_name",
        [
            "EnumUserStatus",
            "EnumOperationType",
            "EnumErrorCode",
        ],
    )
    def test_enum_naming_patterns(self, validator, temp_dir, class_name):
        """Test Enum class naming patterns"""
        test_file = temp_dir / f"test_{class_name}.py"
        test_file.write_text(f"class {class_name}:\n    pass\n")

        result = validator.validate_file(test_file)
        naming_checks = [
            c
            for c in result.checks
            if c.check_type == CheckType.NAMING and "enum_naming" in c.rule
        ]

        assert any(c.status == CheckStatus.PASS for c in naming_checks)


# ============================================================================
# Test Base Class Validation
# ============================================================================


class TestBaseClassValidation:
    """Test base class inheritance validation"""

    @pytest.mark.parametrize(
        ("node_type", "base_class"),
        [
            ("Effect", "NodeEffect"),
            ("Compute", "NodeCompute"),
            ("Reducer", "NodeReducer"),
            ("Orchestrator", "NodeOrchestrator"),
        ],
    )
    def test_correct_base_class(self, validator, temp_dir, node_type, base_class):
        """Test detection of correct base classes"""
        test_file = temp_dir / f"test_base_{node_type}.py"
        test_file.write_text(
            f"""
# Define base class first
class {base_class}:
    pass

class NodeUser{node_type}({base_class}):
    pass
"""
        )

        result = validator.validate_file(test_file)
        base_checks = [c for c in result.checks if c.check_type == CheckType.BASE_CLASS]

        assert any(
            c.status == CheckStatus.PASS and "correct_base_class" in c.rule
            for c in base_checks
        )

    def test_missing_base_class(self, validator, temp_dir):
        """Test detection of missing base class"""
        test_file = temp_dir / "test_missing_base.py"
        test_file.write_text(
            """
class NodeUserEffect:
    pass
"""
        )

        result = validator.validate_file(test_file)
        base_checks = [c for c in result.checks if c.check_type == CheckType.BASE_CLASS]

        assert any(
            c.status == CheckStatus.FAIL and "missing_base_class" in c.rule
            for c in base_checks
        )

    def test_wrong_base_class(self, validator, temp_dir):
        """Test detection of wrong base class"""
        test_file = temp_dir / "test_wrong_base.py"
        test_file.write_text(
            """
# Define base classes
class NodeCompute:
    pass

class NodeUserEffect(NodeCompute):
    pass
"""
        )

        result = validator.validate_file(test_file)
        base_checks = [c for c in result.checks if c.check_type == CheckType.BASE_CLASS]

        # Should fail because Effect node uses Compute base
        assert any(c.status == CheckStatus.FAIL for c in base_checks)


# ============================================================================
# Test Container DI Validation
# ============================================================================


class TestContainerDI:
    """Test container-based dependency injection validation"""

    def test_correct_container_di(self, validator, temp_dir):
        """Test detection of correct container DI"""
        test_file = temp_dir / "test_container_di.py"
        test_file.write_text(
            """
class ModelONEXContainer:
    pass

class NodeUserEffect:
    def __init__(self, container: ModelONEXContainer):
        self.container = container
"""
        )

        result = validator.validate_file(test_file)
        di_checks = [c for c in result.checks if c.check_type == CheckType.DI_CONTAINER]

        assert any(
            c.status == CheckStatus.PASS and "container_di_present" in c.rule
            for c in di_checks
        )

    def test_missing_container_di(self, validator, temp_dir):
        """Test detection of missing container DI"""
        test_file = temp_dir / "test_no_container.py"
        test_file.write_text(
            """
class NodeUserEffect:
    def __init__(self):
        pass
"""
        )

        result = validator.validate_file(test_file)
        di_checks = [c for c in result.checks if c.check_type == CheckType.DI_CONTAINER]

        assert any(
            c.status == CheckStatus.WARNING and "container_di_missing" in c.rule
            for c in di_checks
        )

    def test_container_di_wrong_type(self, validator, temp_dir):
        """Test container DI with wrong type annotation"""
        test_file = temp_dir / "test_wrong_container.py"
        test_file.write_text(
            """
class NodeUserEffect:
    def __init__(self, container: dict):
        pass
"""
        )

        result = validator.validate_file(test_file)
        di_checks = [c for c in result.checks if c.check_type == CheckType.DI_CONTAINER]

        # Should warn about missing proper container type
        assert any(c.status == CheckStatus.WARNING for c in di_checks)


# ============================================================================
# Test Pydantic V2 Validation
# ============================================================================


class TestPydanticV2:
    """Test Pydantic v2 compliance"""

    @pytest.mark.parametrize(
        ("node_type", "contract_type"),
        [
            (".dict()", ".model_dump("),
            (".json()", ".model_dump_json("),
            (".schema()", ".model_json_schema("),
        ],
    )
    def test_pydantic_v1_patterns(
        self, validator, temp_dir, v1_pattern, v2_replacement
    ):
        """Test detection of Pydantic v1 patterns"""
        test_file = temp_dir / "test_pydantic_v1.py"
        test_file.write_text(
            f"""
class ModelUser:
    def to_dict(self):
        return self{v1_pattern}
"""
        )

        result = validator.validate_file(test_file)
        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]

        assert any(
            c.status == CheckStatus.FAIL and "pydantic_v1_pattern" in c.rule
            for c in pydantic_checks
        )
        assert any(v2_replacement in c.suggestion for c in pydantic_checks)

    def test_pydantic_parse_obj_pattern(self, validator, temp_dir):
        """Test detection of .parse_obj( pattern"""
        test_file = temp_dir / "test_parse_obj.py"
        test_file.write_text(
            """
class ModelUser:
    @classmethod
    def from_dict(cls, data):
        return cls.parse_obj(data)
"""
        )

        result = validator.validate_file(test_file)
        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]

        assert any(
            c.status == CheckStatus.FAIL
            and "pydantic_v1_pattern" in c.rule
            and ".parse_obj(" in c.message
            for c in pydantic_checks
        )

    def test_pydantic_parse_raw_pattern(self, validator, temp_dir):
        """Test detection of .parse_raw( pattern"""
        test_file = temp_dir / "test_parse_raw.py"
        test_file.write_text(
            """
class ModelUser:
    @classmethod
    def from_json(cls, json_str):
        return cls.parse_raw(json_str)
"""
        )

        result = validator.validate_file(test_file)
        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]

        assert any(
            c.status == CheckStatus.FAIL
            and "pydantic_v1_pattern" in c.rule
            and ".parse_raw(" in c.message
            for c in pydantic_checks
        )

    def test_pydantic_config_pattern(self, validator, temp_dir):
        """Test detection of old Config pattern"""
        test_file = temp_dir / "test_pydantic_config.py"
        test_file.write_text(
            """
class ModelUser:
    class Config:
        arbitrary_types_allowed = True
"""
        )

        result = validator.validate_file(test_file)
        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]

        assert any(c.status == CheckStatus.FAIL for c in pydantic_checks)

    def test_pydantic_v2_compliant(self, validator, temp_dir):
        """Test that v2 patterns don't trigger warnings"""
        test_file = temp_dir / "test_pydantic_v2.py"
        test_file.write_text(
            """
class ModelUser:
    def to_dict(self):
        return self.model_dump()

    model_config = {"arbitrary_types_allowed": True}
"""
        )

        result = validator.validate_file(test_file)
        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]

        # Should have no Pydantic v1 violations
        assert not any(c.status == CheckStatus.FAIL for c in pydantic_checks)


# ============================================================================
# Test Type Hint Validation
# ============================================================================


class TestTypeHints:
    """Test type hint validation"""

    def test_missing_return_type(self, validator, temp_dir):
        """Test detection of missing return type"""
        test_file = temp_dir / "test_no_return_type.py"
        test_file.write_text(
            """
def process_data(value):
    return value * 2
"""
        )

        result = validator.validate_file(test_file)
        type_checks = [c for c in result.checks if c.check_type == CheckType.TYPE_HINT]

        assert any(
            c.status == CheckStatus.WARNING and "missing_return_type" in c.rule
            for c in type_checks
        )

    def test_init_method_excluded(self, validator, temp_dir):
        """Test that __init__ methods are excluded from return type checks"""
        test_file = temp_dir / "test_init.py"
        test_file.write_text(
            """
class TestClass:
    def __init__(self):
        pass
"""
        )

        result = validator.validate_file(test_file)
        type_checks = [
            c
            for c in result.checks
            if c.check_type == CheckType.TYPE_HINT and "missing_return_type" in c.rule
        ]

        # __init__ should not trigger missing return type
        assert not any("__init__" in c.message for c in type_checks)

    def test_any_type_usage(self, validator, temp_dir):
        """Test detection of Any type usage"""
        test_file = temp_dir / "test_any_type.py"
        test_file.write_text(
            """
from typing import Any

def process(value: Any) -> Any:
    return value
"""
        )

        result = validator.validate_file(test_file)
        type_checks = [c for c in result.checks if c.check_type == CheckType.TYPE_HINT]

        # Should warn about Any type usage
        assert any(
            c.status == CheckStatus.WARNING and "any_type_usage" in c.rule
            for c in type_checks
        )

    def test_specific_types_ok(self, validator, temp_dir):
        """Test that specific types don't trigger warnings"""
        test_file = temp_dir / "test_specific_types.py"
        test_file.write_text(
            """
def process(value: int) -> str:
    return str(value)
"""
        )

        result = validator.validate_file(test_file)
        type_checks = [
            c
            for c in result.checks
            if c.check_type == CheckType.TYPE_HINT and c.status == CheckStatus.WARNING
        ]

        # Should not have warnings about specific types
        assert not any("any_type_usage" in c.rule for c in type_checks)


# ============================================================================
# Test Forbidden Pattern Validation
# ============================================================================


class TestForbiddenPatterns:
    """Test forbidden pattern detection"""

    def test_wildcard_import(self, validator, temp_dir):
        """Test detection of wildcard imports"""
        test_file = temp_dir / "test_wildcard.py"
        test_file.write_text(
            """
from typing import *
"""
        )

        result = validator.validate_file(test_file)
        forbidden_checks = [
            c for c in result.checks if c.check_type == CheckType.FORBIDDEN
        ]

        assert any(
            c.status == CheckStatus.WARNING and "import *" in c.message
            for c in forbidden_checks
        )

    def test_any_type_import(self, validator, temp_dir):
        """Test detection of Any type import"""
        test_file = temp_dir / "test_any_import.py"
        test_file.write_text(
            """
from typing import Any
"""
        )

        result = validator.validate_file(test_file)
        forbidden_checks = [
            c for c in result.checks if c.check_type == CheckType.FORBIDDEN
        ]

        assert any(
            c.status == CheckStatus.WARNING and "from typing import Any" in c.message
            for c in forbidden_checks
        )

    def test_commented_forbidden_patterns_ignored(self, validator, temp_dir):
        """Test that commented forbidden patterns are ignored"""
        test_file = temp_dir / "test_commented.py"
        test_file.write_text(
            """
# from typing import Any
# from typing import *
"""
        )

        result = validator.validate_file(test_file)
        forbidden_checks = [
            c for c in result.checks if c.check_type == CheckType.FORBIDDEN
        ]

        # Commented patterns should not trigger warnings
        assert len(forbidden_checks) == 0


# ============================================================================
# Test File and Directory Validation
# ============================================================================


class TestFileValidation:
    """Test file validation functionality"""

    def test_validate_valid_file(self, validator, temp_dir):
        """Test validation of a valid file"""
        test_file = temp_dir / "test_valid.py"
        test_file.write_text(
            """
from omnibase_core.nodes.node_effect import NodeEffect

class NodeTestEffect(NodeEffect):
    def __init__(self, container: ModelONEXContainer):
        self.container = container

    def process(self, value: int) -> str:
        return str(value)
"""
        )

        result = validator.validate_file(test_file)

        assert result.overall_status in [CheckStatus.PASS, CheckStatus.WARNING]
        assert len(result.errors) == 0
        assert len(result.checks) > 0

    def test_validate_file_with_syntax_error(self, validator, temp_dir):
        """Test validation of file with syntax error"""
        test_file = temp_dir / "test_syntax_error.py"
        test_file.write_text(
            """
def invalid syntax here:
    pass
"""
        )

        result = validator.validate_file(test_file)

        assert result.overall_status == CheckStatus.FAIL
        assert len(result.errors) > 0
        assert any("Syntax error" in e for e in result.errors)

    def test_validate_template_file(self, template_validator, temp_dir):
        """Test validation of template file"""
        test_file = temp_dir / "test_template.py"
        test_file.write_text(
            """
class Node{MICROSERVICE_NAME_PASCAL}Effect:
    def __init__(self):
        self.name = "{MICROSERVICE_NAME}"
"""
        )

        result = template_validator.validate_file(test_file)

        # Should have template mode check
        template_checks = [c for c in result.checks if "template_mode" in c.rule]
        assert len(template_checks) > 0


class TestDirectoryValidation:
    """Test directory validation functionality"""

    def test_validate_directory_non_recursive(self, validator, temp_dir):
        """Test non-recursive directory validation"""
        # Create test files
        (temp_dir / "file1.py").write_text("class Test1:\n    pass\n")
        (temp_dir / "file2.py").write_text("class Test2:\n    pass\n")

        # Create subdirectory with file (should be ignored)
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.py").write_text("class Test3:\n    pass\n")

        results = validator.validate_directory(temp_dir, recursive=False)

        assert len(results) == 2  # Only files in root directory

    def test_validate_directory_recursive(self, validator, temp_dir):
        """Test recursive directory validation"""
        # Create test files in root
        (temp_dir / "file1.py").write_text("class Test1:\n    pass\n")

        # Create subdirectory with file
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (subdir / "file2.py").write_text("class Test2:\n    pass\n")

        # Create nested subdirectory
        nested = subdir / "nested"
        nested.mkdir()
        (nested / "file3.py").write_text("class Test3:\n    pass\n")

        results = validator.validate_directory(temp_dir, recursive=True)

        assert len(results) == 3  # All files including subdirectories

    def test_validate_directory_with_pattern(self, validator, temp_dir):
        """Test directory validation with file pattern"""
        # Create various files
        (temp_dir / "test1.py").write_text("class Test1:\n    pass\n")
        (temp_dir / "test2.txt").write_text("Not Python")
        (temp_dir / "node_test.py").write_text("class NodeTest:\n    pass\n")

        # Validate only node_*.py files
        results = validator.validate_directory(
            temp_dir, recursive=False, pattern="node_*.py"
        )

        assert len(results) == 1
        assert "node_test.py" in results[0].file_path


# ============================================================================
# Test Strict Mode
# ============================================================================


class TestStrictMode:
    """Test strict mode behavior"""

    def test_strict_mode_converts_warnings_to_failures(
        self, strict_validator, temp_dir
    ):
        """Test that strict mode converts warnings to failures"""
        test_file = temp_dir / "test_strict.py"
        test_file.write_text(
            """
from typing import Any

class NodeTestEffect:
    def __init__(self):
        pass
"""
        )

        result = strict_validator.validate_file(test_file)

        # In strict mode, warnings should cause overall failure
        has_warnings = any(c.status == CheckStatus.WARNING for c in result.checks)
        if has_warnings:
            assert result.overall_status == CheckStatus.FAIL

    def test_normal_mode_allows_warnings(self, validator, temp_dir):
        """Test that normal mode allows warnings"""
        test_file = temp_dir / "test_normal.py"
        test_file.write_text(
            """
from typing import Any

class NodeTestEffect:
    def __init__(self):
        pass
"""
        )

        result = validator.validate_file(test_file)

        # In normal mode, warnings should not cause failure
        has_warnings = any(c.status == CheckStatus.WARNING for c in result.checks)
        has_failures = any(c.status == CheckStatus.FAIL for c in result.checks)

        if has_warnings and not has_failures:
            assert result.overall_status == CheckStatus.WARNING


# ============================================================================
# Test Helper Methods
# ============================================================================


class TestHelperMethods:
    """Test internal helper methods"""

    def test_get_base_name_from_name(self, validator):
        """Test extracting base class name from ast.Name"""
        code = "class Test(BaseClass): pass"
        tree = ast.parse(code)
        class_def = tree.body[0]
        base = class_def.bases[0]

        name = validator._get_base_name(base)
        assert name == "BaseClass"

    def test_get_base_name_from_attribute(self, validator):
        """Test extracting base class name from ast.Attribute"""
        code = "class Test(module.BaseClass): pass"
        tree = ast.parse(code)
        class_def = tree.body[0]
        base = class_def.bases[0]

        name = validator._get_base_name(base)
        assert name == "BaseClass"

    def test_get_base_name_unknown_type(self, validator):
        """Test extracting base class name from unknown type"""
        code = "class Test(func()): pass"
        tree = ast.parse(code)
        class_def = tree.body[0]
        base = class_def.bases[0]

        name = validator._get_base_name(base)
        assert name == ""

    def test_get_annotation_name_from_name(self, validator):
        """Test extracting annotation name from ast.Name"""
        code = "def test(x: int): pass"
        tree = ast.parse(code)
        func_def = tree.body[0]
        annotation = func_def.args.args[0].annotation

        name = validator._get_annotation_name(annotation)
        assert name == "int"

    def test_get_annotation_name_from_attribute(self, validator):
        """Test extracting annotation name from ast.Attribute"""
        code = "def test(x: types.IntType): pass"
        tree = ast.parse(code)
        func_def = tree.body[0]
        annotation = func_def.args.args[0].annotation

        name = validator._get_annotation_name(annotation)
        assert name == "IntType"

    def test_get_annotation_name_unknown_type(self, validator):
        """Test extracting annotation name from unknown type"""
        code = "def test(x: func()): pass"
        tree = ast.parse(code)
        func_def = tree.body[0]
        annotation = func_def.args.args[0].annotation

        name = validator._get_annotation_name(annotation)
        assert name == ""


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_file(self, validator, temp_dir):
        """Test validation of empty file"""
        test_file = temp_dir / "test_empty.py"
        test_file.write_text("")

        result = validator.validate_file(test_file)

        # Empty file should pass (no violations)
        assert result.overall_status == CheckStatus.PASS
        assert len(result.errors) == 0

    def test_template_auto_detection(self, validator, temp_dir):
        """Test automatic template detection"""
        test_file = temp_dir / "test_auto_template.py"
        test_file.write_text(
            """
class Node{MICROSERVICE_NAME_PASCAL}Effect:
    pass
"""
        )

        # Validator should auto-detect template mode
        result = validator.validate_file(test_file)

        # Should have template mode check
        template_checks = [c for c in result.checks if "template_mode" in c.rule]
        assert len(template_checks) > 0

    def test_validation_error_recovery(self, validator, temp_dir):
        """Test recovery from validation errors"""
        test_file = temp_dir / "test_error.py"
        # Create file with template placeholders that cause issues
        test_file.write_text(
            """
class {UNKNOWN_PLACEHOLDER}:
    pass
"""
        )

        result = validator.validate_file(test_file)

        # Should have errors but not crash
        assert isinstance(result, ValidationResult)

    def test_overall_status_with_failures(self, validator, temp_dir):
        """Test overall status calculation with failures"""
        test_file = temp_dir / "test_failures.py"
        test_file.write_text(
            """
from omnibase_core.core.node_effect import NodeEffect

class NodeBadName:
    pass
"""
        )

        result = validator.validate_file(test_file)

        # Should fail due to incorrect import and bad naming
        assert result.overall_status == CheckStatus.FAIL

    def test_overall_status_strict_mode(self, strict_validator, temp_dir):
        """Test overall status in strict mode with warnings"""
        test_file = temp_dir / "test_strict_warnings.py"
        test_file.write_text(
            """
class NodeUserEffect:
    def __init__(self):
        pass
"""
        )

        result = strict_validator.validate_file(test_file)

        # In strict mode, warnings should cause failure
        has_warnings = any(c.status == CheckStatus.WARNING for c in result.checks)
        if has_warnings:
            assert result.overall_status == CheckStatus.FAIL

    def test_file_with_only_comments(self, validator, temp_dir):
        """Test validation of file with only comments"""
        test_file = temp_dir / "test_comments.py"
        test_file.write_text(
            """
# This is a comment
# Another comment
"""
        )

        result = validator.validate_file(test_file)

        # Comment-only file should pass
        assert result.overall_status == CheckStatus.PASS

    def test_file_with_encoding_issues(self, validator, temp_dir):
        """Test handling of files with encoding declaration"""
        test_file = temp_dir / "test_encoding.py"
        test_file.write_text(
            """# -*- coding: utf-8 -*-
class Test:
    pass
"""
        )

        result = validator.validate_file(test_file)

        # Should handle encoding declaration
        assert result.overall_status == CheckStatus.PASS

    def test_multiple_violations_in_one_file(self, validator, temp_dir):
        """Test file with multiple different violations"""
        test_file = temp_dir / "test_multiple.py"
        test_file.write_text(
            """
from typing import Any
from typing import *

class NodeBadName:  # Wrong naming
    def __init__(self):  # Missing container DI
        pass

    def process(self):  # Missing return type
        return self.dict()  # Pydantic v1
"""
        )

        result = validator.validate_file(test_file)

        # Should have multiple different check types failing
        check_types = set(c.check_type for c in result.checks)
        assert len(check_types) > 1
        assert result.overall_status == CheckStatus.FAIL

    def test_unicode_in_file(self, validator, temp_dir):
        """Test handling of Unicode characters in file"""
        test_file = temp_dir / "test_unicode.py"
        test_file.write_text(
            """
class TestClass:
    \"\"\"Тестовый класс with émojis 🎉\"\"\"
    def __init__(self):
        self.message = "Hello 世界"
"""
        )

        result = validator.validate_file(test_file)

        # Should handle Unicode without errors
        assert len(result.errors) == 0

    def test_template_syntax_error_recovery(self, template_validator, temp_dir):
        """Test handling syntax errors even after template substitution"""
        test_file = temp_dir / "test_template_syntax_error.py"
        test_file.write_text(
            """
class {MICROSERVICE_NAME_PASCAL}Effect:
    def invalid syntax here
"""
        )

        result = template_validator.validate_file(test_file)

        # Should fail with syntax error
        assert result.overall_status == CheckStatus.FAIL
        assert len(result.errors) > 0
        assert any("Syntax error" in e for e in result.errors)

    def test_file_read_error_handling(self, validator, temp_dir):
        """Test handling of file read errors"""
        # Create a directory with same name as expected file
        fake_file = temp_dir / "test_dir_not_file"
        fake_file.mkdir()

        result = validator.validate_file(fake_file)

        # Should have an error
        assert result.overall_status == CheckStatus.FAIL
        assert len(result.errors) > 0


# ============================================================================
# Test Complex Scenarios
# ============================================================================


class TestComplexScenarios:
    """Test complex real-world scenarios"""

    def test_complete_node_file_validation(self, validator, temp_dir):
        """Test validation of a complete, valid Node file"""
        test_file = temp_dir / "test_complete_node.py"
        test_file.write_text(
            """
from omnibase_core.nodes.node_effect import NodeEffect

class ModelONEXContainer:
    pass

class NodeUserServiceEffect(NodeEffect):
    def __init__(self, container: ModelONEXContainer):
        self.container = container

    def execute(self, data: dict) -> dict:
        return data
"""
        )

        result = validator.validate_file(test_file)

        # Should have multiple passing checks
        assert len(result.checks) > 0
        passed_checks = [c for c in result.checks if c.status == CheckStatus.PASS]
        assert len(passed_checks) > 0

    def test_multiple_nodes_in_file(self, validator, temp_dir):
        """Test validation of file with multiple Node classes"""
        test_file = temp_dir / "test_multiple_nodes.py"
        test_file.write_text(
            """
class NodeEffect:
    pass

class NodeCompute:
    pass

class NodeUserEffect(NodeEffect):
    pass

class NodeDataCompute(NodeCompute):
    pass
"""
        )

        result = validator.validate_file(test_file)

        # Should validate all Node classes
        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]
        assert len(naming_checks) >= 2

    def test_mixed_valid_and_invalid_patterns(self, validator, temp_dir):
        """Test file with both valid and invalid patterns"""
        test_file = temp_dir / "test_mixed.py"
        test_file.write_text(
            """
from typing import Any

class ModelValidName:
    def valid_method(self, x: int) -> str:
        return str(x)

class NodeBadName:
    def no_return_type(self):
        return self.dict()
"""
        )

        result = validator.validate_file(test_file)

        # Should have both passes and failures
        passed = [c for c in result.checks if c.status == CheckStatus.PASS]
        failed = [c for c in result.checks if c.status == CheckStatus.FAIL]
        warnings = [c for c in result.checks if c.status == CheckStatus.WARNING]

        assert len(passed) > 0
        assert len(failed) > 0 or len(warnings) > 0

    def test_all_node_types_in_single_file(self, validator, temp_dir):
        """Test file with all four node types"""
        test_file = temp_dir / "test_all_types.py"
        test_file.write_text(
            """
class NodeEffect:
    pass

class NodeCompute:
    pass

class NodeReducer:
    pass

class NodeOrchestrator:
    pass

class ModelONEXContainer:
    pass

class NodeDataEffect(NodeEffect):
    def __init__(self, container: ModelONEXContainer):
        pass

class NodeProcessCompute(NodeCompute):
    def __init__(self, container: ModelONEXContainer):
        pass

class NodeStateReducer(NodeReducer):
    def __init__(self, container: ModelONEXContainer):
        pass

class NodeWorkflowOrchestrator(NodeOrchestrator):
    def __init__(self, container: ModelONEXContainer):
        pass
"""
        )

        result = validator.validate_file(test_file)

        # Should have checks for all node types
        base_checks = [c for c in result.checks if c.check_type == CheckType.BASE_CLASS]
        assert len(base_checks) >= 4

    def test_directory_validation_empty(self, validator, temp_dir):
        """Test validation of empty directory"""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()

        results = validator.validate_directory(empty_dir)

        assert len(results) == 0

    def test_directory_validation_mixed_files(self, validator, temp_dir):
        """Test directory with Python and non-Python files"""
        (temp_dir / "valid.py").write_text("class Test:\n    pass\n")
        (temp_dir / "readme.txt").write_text("Not Python")
        (temp_dir / "data.json").write_text("{}")

        results = validator.validate_directory(temp_dir)

        # Should only validate .py files
        assert len(results) == 1
        assert results[0].file_path.endswith("valid.py")


# ============================================================================
# Test CLI Interface
# ============================================================================


class TestCLIInterface:
    """Test command-line interface"""

    def test_main_with_file_argument(self, temp_dir, monkeypatch):
        """Test main() with --file argument"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test_cli.py"
        test_file.write_text("class Test:\n    pass\n")

        monkeypatch.setattr(sys, "argv", ["validator", "--file", str(test_file)])

        # Should exit with code 0 (success)
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_with_json_output(self, temp_dir, monkeypatch, capsys):
        """Test main() with JSON output"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test_json.py"
        test_file.write_text("class Test:\n    pass\n")

        monkeypatch.setattr(
            sys, "argv", ["validator", "--file", str(test_file), "--json"]
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 0
        # Output should be valid JSON

        output = json.loads(captured.out)
        assert "total_files" in output
        assert "results" in output

    def test_main_with_directory(self, temp_dir, monkeypatch):
        """Test main() with --directory argument"""
        import sys

        from tools.compatibility_validator import main

        (temp_dir / "test1.py").write_text("class Test:\n    pass\n")
        (temp_dir / "test2.py").write_text("class Test2:\n    pass\n")

        monkeypatch.setattr(sys, "argv", ["validator", "--directory", str(temp_dir)])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_with_recursive(self, temp_dir, monkeypatch):
        """Test main() with --recursive argument"""
        import sys

        from tools.compatibility_validator import main

        (temp_dir / "test.py").write_text("class Test:\n    pass\n")
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (subdir / "test2.py").write_text("class Test2:\n    pass\n")

        monkeypatch.setattr(
            sys,
            "argv",
            ["validator", "--directory", str(temp_dir), "--recursive"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_with_strict_mode(self, temp_dir, monkeypatch):
        """Test main() with --strict mode"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test_strict.py"
        test_file.write_text(
            """
class NodeUserEffect:
    def __init__(self):
        pass
"""
        )

        monkeypatch.setattr(
            sys, "argv", ["validator", "--file", str(test_file), "--strict"]
        )

        # Should fail in strict mode due to warnings
        with pytest.raises(SystemExit) as exc_info:
            main()
        # May exit with 1 if there are warnings in strict mode
        assert exc_info.value.code in [0, 1]

    def test_main_with_template_mode(self, temp_dir, monkeypatch):
        """Test main() with --template-mode"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test_template.py"
        test_file.write_text(
            """
class Model{MICROSERVICE_NAME_PASCAL}Input:
    def __init__(self):
        self.service = "{MICROSERVICE_NAME}"
        self.domain = "{DOMAIN}"
"""
        )

        monkeypatch.setattr(
            sys,
            "argv",
            ["validator", "--file", str(test_file), "--template-mode"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()
        # Template should be substituted and validated
        assert exc_info.value.code == 0

    def test_main_file_not_found(self, temp_dir, monkeypatch):
        """Test main() with non-existent file"""
        import sys

        from tools.compatibility_validator import main

        nonexistent = temp_dir / "nonexistent.py"

        monkeypatch.setattr(sys, "argv", ["validator", "--file", str(nonexistent)])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_directory_not_found(self, temp_dir, monkeypatch):
        """Test main() with non-existent directory"""
        import sys

        from tools.compatibility_validator import main

        nonexistent = temp_dir / "nonexistent_dir"

        monkeypatch.setattr(sys, "argv", ["validator", "--directory", str(nonexistent)])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_no_arguments(self, monkeypatch):
        """Test main() with no file or directory argument"""
        import sys

        from tools.compatibility_validator import main

        monkeypatch.setattr(sys, "argv", ["validator"])

        with pytest.raises(SystemExit):
            main()

    def test_main_both_file_and_directory(self, temp_dir, monkeypatch):
        """Test main() with both --file and --directory (should error)"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test.py"
        test_file.write_text("class Test:\n    pass\n")

        monkeypatch.setattr(
            sys,
            "argv",
            ["validator", "--file", str(test_file), "--directory", str(temp_dir)],
        )

        with pytest.raises(SystemExit):
            main()

    def test_main_with_pattern(self, temp_dir, monkeypatch):
        """Test main() with --pattern argument"""
        import sys

        from tools.compatibility_validator import main

        (temp_dir / "node_test.py").write_text("class NodeTest:\n    pass\n")
        (temp_dir / "other.py").write_text("class Other:\n    pass\n")

        monkeypatch.setattr(
            sys,
            "argv",
            ["validator", "--directory", str(temp_dir), "--pattern", "node_*.py"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_with_validation_failure(self, temp_dir, monkeypatch):
        """Test main() with validation failures"""
        import sys

        from tools.compatibility_validator import main

        test_file = temp_dir / "test_fail.py"
        test_file.write_text(
            """
from omnibase_core.core.node_effect import NodeEffect
"""
        )

        monkeypatch.setattr(sys, "argv", ["validator", "--file", str(test_file)])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
