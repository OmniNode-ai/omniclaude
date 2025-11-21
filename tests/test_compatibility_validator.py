#!/usr/bin/env python3
"""
Tests for OmniBase Core Compatibility Validator

Tests all validation checks:
- Import path validation
- ONEX naming conventions
- Pydantic v2 compliance
- Base class inheritance
- Container-based DI
- Type hint validation
- Forbidden pattern detection
"""

import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest


# Add parent directory to path to import tools module
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.compatibility_validator import (
    CheckStatus,
    CheckType,
    OmniBaseCompatibilityValidator,
)


@pytest.fixture
def validator():
    """Create validator instance"""
    return OmniBaseCompatibilityValidator(strict=False)


@pytest.fixture
def strict_validator():
    """Create strict validator instance"""
    return OmniBaseCompatibilityValidator(strict=True)


@pytest.fixture
def temp_file():
    """Create temporary file for testing"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        yield Path(f.name)
    Path(f.name).unlink(missing_ok=True)


class TestImportValidation:
    """Test import path validation"""

    def test_valid_imports(self, validator, temp_file):
        """Test that valid omnibase_core imports pass"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect
            from omnibase_core.errors.model_onex_error import ModelOnexError
            from omnibase_core.models.container.model_onex_container import ModelONEXContainer

            class TestNode:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]
        assert len(import_checks) > 0
        assert all(c.status == CheckStatus.PASS for c in import_checks)

    def test_incorrect_import_paths(self, validator, temp_file):
        """Test that incorrect import paths are detected"""
        code = dedent(
            """
            from omnibase_core.core.node_effect import ModelEffectInput

            class TestNode:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]
        assert any(c.status == CheckStatus.FAIL for c in import_checks)
        failed_check = next(c for c in import_checks if c.status == CheckStatus.FAIL)
        assert "incorrect" in failed_check.message.lower()

    def test_unknown_module_import(self, validator, temp_file):
        """Test that unknown modules are detected"""
        code = dedent(
            """
            from omnibase_core.nonexistent.module import Something

            class TestNode:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        import_checks = [c for c in result.checks if c.check_type == CheckType.IMPORT]
        # Should either fail or warn about unknown import
        assert any(
            c.status in [CheckStatus.FAIL, CheckStatus.WARNING] for c in import_checks
        )


class TestONEXNaming:
    """Test ONEX naming convention validation"""

    def test_valid_node_naming(self, validator, temp_file):
        """Test valid ONEX node naming"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect

            class NodeUserServiceEffect(NodeEffect):
                pass

            class NodeDataProcessorCompute:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]
        assert len(naming_checks) > 0
        assert all(c.status == CheckStatus.PASS for c in naming_checks)

    def test_invalid_node_naming(self, validator, temp_file):
        """Test invalid ONEX node naming"""
        code = dedent(
            """
            class NodeInvalid:
                pass

            class NodeNoType:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]
        assert any(c.status == CheckStatus.FAIL for c in naming_checks)

    def test_model_naming(self, validator, temp_file):
        """Test Model class naming"""
        code = dedent(
            """
            from pydantic import BaseModel

            class ModelUserInput(BaseModel):
                pass

            class ModelServiceConfig(BaseModel):
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        naming_checks = [c for c in result.checks if c.check_type == CheckType.NAMING]
        assert len(naming_checks) > 0
        assert all(c.status == CheckStatus.PASS for c in naming_checks)


class TestBaseClassValidation:
    """Test base class inheritance validation"""

    def test_correct_base_class(self, validator, temp_file):
        """Test that correct base class inheritance is detected"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect

            class NodeUserServiceEffect(NodeEffect):
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        base_class_checks = [
            c for c in result.checks if c.check_type == CheckType.BASE_CLASS
        ]
        assert len(base_class_checks) > 0
        assert all(c.status == CheckStatus.PASS for c in base_class_checks)

    def test_missing_base_class(self, validator, temp_file):
        """Test that missing base class is detected"""
        code = dedent(
            """
            class NodeUserServiceEffect:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        base_class_checks = [
            c for c in result.checks if c.check_type == CheckType.BASE_CLASS
        ]
        assert any(c.status == CheckStatus.FAIL for c in base_class_checks)

    def test_wrong_base_class(self, validator, temp_file):
        """Test that wrong base class is detected"""
        code = dedent(
            """
            from omnibase_core.nodes.node_compute import NodeCompute

            class NodeUserServiceEffect(NodeCompute):  # Wrong base class
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        base_class_checks = [
            c for c in result.checks if c.check_type == CheckType.BASE_CLASS
        ]
        assert any(c.status == CheckStatus.FAIL for c in base_class_checks)


class TestContainerDI:
    """Test container-based dependency injection validation"""

    def test_container_di_present(self, validator, temp_file):
        """Test that container DI is detected"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect
            from omnibase_core.models.container.model_onex_container import ModelONEXContainer

            class NodeUserServiceEffect(NodeEffect):
                def __init__(self, container: ModelONEXContainer):
                    super().__init__(container)
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        di_checks = [c for c in result.checks if c.check_type == CheckType.DI_CONTAINER]
        assert len(di_checks) > 0
        assert all(c.status == CheckStatus.PASS for c in di_checks)

    def test_container_di_missing(self, validator, temp_file):
        """Test that missing container DI is detected"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect

            class NodeUserServiceEffect(NodeEffect):
                def __init__(self):
                    pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        di_checks = [c for c in result.checks if c.check_type == CheckType.DI_CONTAINER]
        assert any(c.status == CheckStatus.WARNING for c in di_checks)


class TestPydanticV2:
    """Test Pydantic v2 compliance validation"""

    def test_pydantic_v1_dict_method(self, validator, temp_file):
        """Test that Pydantic v1 .dict() is detected"""
        code = dedent(
            """
            from pydantic import BaseModel

            class MyModel(BaseModel):
                name: str

            m = MyModel(name="test")
            data = m.dict()
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]
        assert len(pydantic_checks) > 0
        assert any(c.status == CheckStatus.FAIL for c in pydantic_checks)
        assert any(
            ".model_dump(" in c.suggestion for c in pydantic_checks if c.suggestion
        )

    def test_pydantic_v1_json_method(self, validator, temp_file):
        """Test that Pydantic v1 .json() is detected"""
        code = dedent(
            """
            from pydantic import BaseModel

            class MyModel(BaseModel):
                name: str

            m = MyModel(name="test")
            json_str = m.json()
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]
        assert any(c.status == CheckStatus.FAIL for c in pydantic_checks)

    def test_pydantic_v2_compliant(self, validator, temp_file):
        """Test that Pydantic v2 code passes"""
        code = dedent(
            """
            from pydantic import BaseModel

            class MyModel(BaseModel):
                name: str

            m = MyModel(name="test")
            data = m.model_dump()
            json_str = m.model_dump_json()
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        pydantic_checks = [
            c for c in result.checks if c.check_type == CheckType.PYDANTIC
        ]
        # Should have no failed checks
        assert not any(c.status == CheckStatus.FAIL for c in pydantic_checks)


class TestTypeHints:
    """Test type hint validation"""

    def test_any_type_detection(self, validator, temp_file):
        """Test that Any types are detected"""
        code = dedent(
            """
            from typing import Any

            def process_data(data: Any) -> Any:
                return data
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        type_hint_checks = [
            c for c in result.checks if c.check_type == CheckType.TYPE_HINT
        ]
        assert any(c.status == CheckStatus.WARNING for c in type_hint_checks)
        assert any("Any" in c.message for c in type_hint_checks)

    def test_missing_return_type(self, validator, temp_file):
        """Test that missing return types are detected"""
        code = dedent(
            """
            def process_data(data: str):
                return data.upper()
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        type_hint_checks = [
            c for c in result.checks if c.check_type == CheckType.TYPE_HINT
        ]
        assert any(c.status == CheckStatus.WARNING for c in type_hint_checks)


class TestForbiddenPatterns:
    """Test forbidden pattern detection"""

    def test_wildcard_imports(self, validator, temp_file):
        """Test that wildcard imports are detected"""
        code = dedent(
            """
            from typing import *
            from pathlib import *

            class MyClass:
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        forbidden_checks = [
            c for c in result.checks if c.check_type == CheckType.FORBIDDEN
        ]
        assert len(forbidden_checks) >= 2  # Should catch both wildcard imports


class TestTemplateMode:
    """Test template mode functionality"""

    def test_template_detection(self, validator, temp_file):
        """Test that templates are auto-detected"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect

            class Node{MICROSERVICE_NAME_PASCAL}Effect(NodeEffect):
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        # Should detect template mode
        pattern_checks = [c for c in result.checks if c.check_type == CheckType.PATTERN]
        assert any("template_mode" in c.rule for c in pattern_checks)

    def test_template_substitution(self, validator, temp_file):
        """Test that template placeholders are substituted"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect
            from omnibase_core.models.container.model_onex_container import ModelONEXContainer

            class Node{MICROSERVICE_NAME_PASCAL}Effect(NodeEffect):
                def __init__(self, container: ModelONEXContainer):
                    super().__init__(container)
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        # Should successfully parse after substitution
        assert result.overall_status != CheckStatus.FAIL or len(result.errors) == 0


class TestStrictMode:
    """Test strict mode behavior"""

    def test_strict_mode_warnings_become_errors(self, strict_validator, temp_file):
        """Test that warnings become failures in strict mode"""
        code = dedent(
            """
            from typing import Any

            def process(data):
                return data
        """
        )
        temp_file.write_text(code)

        result = strict_validator.validate_file(temp_file)

        # In strict mode, warnings should cause overall failure
        if any(c.status == CheckStatus.WARNING for c in result.checks):
            assert result.overall_status == CheckStatus.FAIL


class TestValidationResult:
    """Test ValidationResult functionality"""

    def test_summary_statistics(self, validator, temp_file):
        """Test that summary statistics are correct"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect
            from typing import Any

            class NodeTestEffect(NodeEffect):
                def process(self, data: Any) -> Any:
                    return data
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)
        summary = result.summary

        assert "total" in summary
        assert "passed" in summary
        assert "failed" in summary
        assert "warnings" in summary
        assert summary["total"] == sum(
            [
                summary["passed"],
                summary["failed"],
                summary["warnings"],
                summary["skipped"],
            ]
        )

    def test_to_dict_serialization(self, validator, temp_file):
        """Test that results can be serialized to dict"""
        code = dedent(
            """
            from omnibase_core.nodes.node_effect import NodeEffect

            class NodeTestEffect(NodeEffect):
                pass
        """
        )
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)
        result_dict = result.to_dict()

        assert "file_path" in result_dict
        assert "status" in result_dict
        assert "checks" in result_dict
        assert "summary" in result_dict
        assert isinstance(result_dict["checks"], list)


class TestDirectoryValidation:
    """Test directory validation"""

    def test_validate_directory(self, validator):
        """Test validating multiple files in directory"""
        templates_dir = Path("agents/templates")
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        results = validator.validate_directory(templates_dir, recursive=False)

        assert len(results) > 0
        assert all(isinstance(r.file_path, str) for r in results)

    def test_validate_recursive(self, validator):
        """Test recursive directory validation"""
        agents_dir = Path("agents")
        if not agents_dir.exists():
            pytest.skip("Agents directory not found")

        results = validator.validate_directory(
            agents_dir, recursive=True, pattern="*.py"
        )

        assert len(results) > 0


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_file(self, validator, temp_file):
        """Test validation of empty file"""
        temp_file.write_text("")

        result = validator.validate_file(temp_file)

        # Empty file should not cause errors
        assert result.overall_status in [CheckStatus.PASS, CheckStatus.WARNING]

    def test_syntax_error_file(self, validator, temp_file):
        """Test validation of file with syntax errors"""
        code = "def invalid syntax here"
        temp_file.write_text(code)

        result = validator.validate_file(temp_file)

        assert result.overall_status == CheckStatus.FAIL
        assert len(result.errors) > 0
        assert any("syntax" in error.lower() for error in result.errors)

    def test_non_python_content(self, validator, temp_file):
        """Test validation of non-Python content"""
        content = "This is not Python code at all!"
        temp_file.write_text(content)

        result = validator.validate_file(temp_file)

        assert result.overall_status == CheckStatus.FAIL
        assert len(result.errors) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
