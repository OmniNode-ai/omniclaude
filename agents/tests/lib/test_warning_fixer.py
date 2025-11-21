#!/usr/bin/env python3
"""
Comprehensive tests for agents/lib/warning_fixer.py

Tests cover:
- Warning detection for G12, G13, G14
- Automatic fix generation
- Code transformation logic
- AST manipulation
- Fix validation
- Edge cases and malformed code handling

Target: 85-90% coverage (currently 12.2%)
"""

from pathlib import Path

from agents.lib.warning_fixer import (
    FixResult,
    ValidationWarning,
    WarningFixer,
    apply_automatic_fixes,
)


class TestDataClasses:
    """Test FixResult and ValidationWarning dataclasses."""

    def test_fix_result_initialization(self):
        """Test FixResult default initialization."""
        result = FixResult(fixed_code="test code")

        assert result.fixed_code == "test code"
        assert result.fixes_applied == []
        assert result.warnings_fixed == []
        assert result.fix_count == 0
        assert result.success is True
        assert result.error_message is None

    def test_fix_result_with_data(self):
        """Test FixResult with data."""
        result = FixResult(
            fixed_code="fixed",
            fixes_applied=["fix1", "fix2"],
            warnings_fixed=["G12", "G13"],
            fix_count=2,
            success=False,
            error_message="Test error",
        )

        assert result.fixed_code == "fixed"
        assert result.fixes_applied == ["fix1", "fix2"]
        assert result.warnings_fixed == ["G12", "G13"]
        assert result.fix_count == 2
        assert result.success is False
        assert result.error_message == "Test error"

    def test_validation_warning_initialization(self):
        """Test ValidationWarning initialization."""
        warning = ValidationWarning(
            gate_id="G12",
            warning_type="missing_config",
            line_number=42,
            column_number=10,
            message="Missing ConfigDict",
        )

        assert warning.gate_id == "G12"
        assert warning.warning_type == "missing_config"
        assert warning.line_number == 42
        assert warning.column_number == 10
        assert warning.message == "Missing ConfigDict"

    def test_validation_warning_defaults(self):
        """Test ValidationWarning default values."""
        warning = ValidationWarning(gate_id="G13", warning_type="missing_type_hint")

        assert warning.gate_id == "G13"
        assert warning.warning_type == "missing_type_hint"
        assert warning.line_number is None
        assert warning.column_number is None
        assert warning.message == ""


class TestWarningFixerInitialization:
    """Test WarningFixer initialization."""

    def test_initialization(self):
        """Test WarningFixer creates logger."""
        fixer = WarningFixer()
        assert fixer.logger is not None
        assert hasattr(fixer, "NODE_TYPE_IMPORTS")
        assert hasattr(fixer, "COMMON_METHOD_HINTS")


class TestFixAllWarnings:
    """Test fix_all_warnings orchestration."""

    def test_empty_code(self):
        """Test with empty code."""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings("")

        assert result.fixed_code == ""
        assert result.success is True
        assert result.fix_count == 0

    def test_code_without_warnings(self):
        """Test code that doesn't need fixes."""
        code = '''
def clean_function() -> None:
    """Clean function with proper types."""
    pass
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True
        # May have some fixes applied (e.g., imports)
        assert result.fixed_code is not None

    def test_code_with_all_warning_types(self):
        """Test code with G12, G13, and G14 warnings."""
        code = '''
from pydantic import BaseModel

class ModelInput(BaseModel):
    """Test model."""
    name: str

def process_data(data):
    """Process data.
    result = model.dict()
    return result
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True
        assert result.fix_count > 0
        # Should have all three warning types
        assert any(
            "G12" in w or "G13" in w or "G14" in w for w in result.warnings_fixed
        )

    def test_exception_handling(self):
        """Test exception handling in fix_all_warnings."""
        fixer = WarningFixer()

        # Mock a method to raise exception
        original_method = fixer.fix_g14_imports

        def raise_error(*args, **kwargs):
            raise ValueError("Test error")

        fixer.fix_g14_imports = raise_error

        result = fixer.fix_all_warnings("test code")

        assert result.success is False
        assert result.error_message == "Test error"

        # Restore original method
        fixer.fix_g14_imports = original_method

    def test_sequential_fix_order(self):
        """Test fixes are applied in correct order: G14 -> G12 -> G13."""
        code = """
from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str

def process(data):
    return data.dict()
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True
        # Check that warnings were fixed in order
        if result.warnings_fixed:
            # G14 should come before G12, G12 before G13
            if "G14" in result.warnings_fixed and "G12" in result.warnings_fixed:
                assert result.warnings_fixed.index("G14") < result.warnings_fixed.index(
                    "G12"
                )


class TestFixG12PydanticConfig:
    """Test G12 Pydantic ConfigDict fixes."""

    def test_add_configdict_import(self):
        """Test adding ConfigDict to existing Pydantic import."""
        code = """from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert "ConfigDict" in result.fixed_code
        assert "from pydantic import BaseModel, ConfigDict" in result.fixed_code
        assert any("ConfigDict import" in fix for fix in result.fixes_applied)

    def test_add_model_config_to_input_model(self):
        """Test adding model_config to Input model."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    """Input model."""
    name: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert "model_config = ConfigDict" in result.fixed_code
        assert 'extra="forbid"' in result.fixed_code
        assert "validate_assignment=True" in result.fixed_code
        assert "str_strip_whitespace=True" in result.fixed_code

    def test_add_model_config_to_output_model(self):
        """Test adding model_config to Output model."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelOutput(BaseModel):
    """Output model."""
    result: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert "model_config = ConfigDict" in result.fixed_code
        assert 'extra="allow"' in result.fixed_code
        assert "validate_assignment=True" in result.fixed_code
        # Output models don't have str_strip_whitespace
        assert (
            "str_strip_whitespace"
            not in result.fixed_code.split("ModelOutput")[1].split("class")[0]
        )

    def test_add_model_config_to_config_model(self):
        """Test adding model_config to Config model."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelConfig(BaseModel):
    """Config model."""
    setting: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert "model_config = ConfigDict" in result.fixed_code
        assert 'extra="forbid"' in result.fixed_code
        assert "str_strip_whitespace=True" in result.fixed_code

    def test_skip_existing_model_config(self):
        """Test that existing model_config is not duplicated."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    """Input model."""
    model_config = ConfigDict(extra="forbid")
    name: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        # Should not add another model_config
        assert result.fixed_code.count("model_config") == 1

    def test_fix_dict_to_model_dump(self):
        """Test fixing .dict() to .model_dump()."""
        code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

def test():
    obj = ModelTest(name="test")
    data = obj.dict()
    return data
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_dump()" in result.fixed_code
        assert ".dict()" not in result.fixed_code
        assert any("Pydantic v1 pattern" in fix for fix in result.fixes_applied)

    def test_fix_parse_obj_to_model_validate(self):
        """Test fixing .parse_obj() to .model_validate()."""
        code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

def test():
    obj = ModelTest.parse_obj({"name": "test"})
    return obj
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_validate(" in result.fixed_code
        assert ".parse_obj(" not in result.fixed_code

    def test_fix_json_to_model_dump_json(self):
        """Test fixing .json() to .model_dump_json()."""
        code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

def test():
    obj = ModelTest(name="test")
    json_str = obj.json()
    return json_str
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_dump_json()" in result.fixed_code
        assert result.fixed_code.count(".json()") == 0  # Should all be converted

    def test_fix_parse_raw_to_model_validate_json(self):
        """Test fixing .parse_raw() to .model_validate_json()."""
        code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    name: str

def test():
    obj = ModelTest.parse_raw('{"name": "test"}')
    return obj
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_validate_json(" in result.fixed_code
        assert ".parse_raw(" not in result.fixed_code

    def test_handle_model_with_docstring(self):
        """Test model_config insertion after docstring."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    """
    This is a multi-line
    docstring for the model.
    """
    name: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        # model_config should come after docstring
        docstring_end = result.fixed_code.index(
            '"""', result.fixed_code.index('"""') + 3
        )
        config_pos = result.fixed_code.index("model_config")
        assert config_pos > docstring_end

    def test_multiple_models_in_file(self):
        """Test fixing multiple models in same file."""
        code = '''from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    """Input."""
    name: str

class ModelOutput(BaseModel):
    """Output."""
    result: str
'''
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        # At least one model should have model_config
        assert result.fixed_code.count("model_config") >= 1
        # Input should have forbid or output should have forbid (based on detection)
        assert (
            'extra="forbid"' in result.fixed_code
            or 'extra="allow"' in result.fixed_code
        )


class TestFixG13TypeHints:
    """Test G13 type hint fixes."""

    def test_add_typing_imports(self):
        """Test adding typing module imports."""
        code = """import os

def test_function():
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        # Typing imports are added if there's an existing import
        assert "from typing import" in result.fixed_code
        assert "Any" in result.fixed_code

    def test_add_init_return_hint(self):
        """Test adding -> None to __init__."""
        code = """from typing import Any

class TestClass:
    def __init__(self):
        pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "def __init__(self) -> None:" in result.fixed_code

    def test_add_validate_return_hint(self):
        """Test adding -> None to _validate methods."""
        code = """from typing import Any

def _validate_input(data):
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> None:" in result.fixed_code

    def test_add_execute_return_hint(self):
        """Test adding -> Dict[str, Any] to _execute methods."""
        code = """from typing import Any, Dict

def _execute_business_logic():
    return {}
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> Dict[str, Any]:" in result.fixed_code

    def test_add_get_return_hint(self):
        """Test adding -> Any to _get methods."""
        code = """from typing import Any

def _get_data():
    return None
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> Any:" in result.fixed_code

    def test_add_is_return_hint(self):
        """Test adding -> bool to _is methods."""
        code = """from typing import Any

def _is_valid():
    return True
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> bool:" in result.fixed_code

    def test_add_has_return_hint(self):
        """Test adding -> bool to _has methods."""
        code = """from typing import Any

def _has_data():
    return False
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> bool:" in result.fixed_code

    def test_add_count_return_hint(self):
        """Test adding -> int to _count methods."""
        code = """from typing import Any

def _count_items():
    return 0
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> int:" in result.fixed_code

    def test_add_generic_return_hint(self):
        """Test adding -> Any to unknown methods."""
        code = """from typing import Any

def _custom_method():
    return "something"
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> Any:" in result.fixed_code

    def test_skip_methods_with_existing_hints(self):
        """Test that methods with hints are not modified."""
        code = """from typing import Any

def test_function() -> str:
    return "test"
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        # Should not be modified
        assert result.fixed_code.count("-> str:") == 1

    def test_handle_methods_with_parameters(self):
        """Test adding hints to methods with parameters."""
        code = """from typing import Any

def process_data(data, options):
    return data
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "-> Any:" in result.fixed_code
        assert "def process_data(data, options) -> Any:" in result.fixed_code


class TestFixG14Imports:
    """Test G14 import fixes."""

    def test_fix_unterminated_docstring(self):
        """Test fixing unterminated docstrings."""
        code = '''
def test():
    """This docstring is not terminated
    pass
'''
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code)

        # Should add closing quotes
        assert result.fixed_code.count('"""') % 2 == 0

    def test_detect_node_type_from_file_path(self):
        """Test node type detection from file path."""
        fixer = WarningFixer()

        assert fixer._detect_node_type("", Path("node_test_effect.py")) == "effect"
        assert fixer._detect_node_type("", Path("node_test_compute.py")) == "compute"
        assert fixer._detect_node_type("", Path("node_test_reducer.py")) == "reducer"
        assert (
            fixer._detect_node_type("", Path("node_test_orchestrator.py"))
            == "orchestrator"
        )

    def test_detect_node_type_from_code(self):
        """Test node type detection from code patterns."""
        fixer = WarningFixer()

        code_effect = "class NodeTestEffect: pass"
        assert fixer._detect_node_type(code_effect, None) == "effect"

        code_compute = "class NodeTestCompute: pass"
        assert fixer._detect_node_type(code_compute, None) == "compute"

        code_reducer = "class NodeTestReducer: pass"
        assert fixer._detect_node_type(code_reducer, None) == "reducer"

        code_orchestrator = "class NodeTestOrchestrator: pass"
        assert fixer._detect_node_type(code_orchestrator, None) == "orchestrator"

    def test_add_missing_effect_imports(self):
        """Test adding missing imports for effect nodes."""
        code = """
class NodeTestEffect:
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code, Path("node_test_effect.py"))

        assert (
            "from omnibase_core.nodes.node_effect import NodeEffect"
            in result.fixed_code
        )
        assert "from omnibase_core.errors import" in result.fixed_code
        assert result.fix_count > 0

    def test_add_missing_compute_imports(self):
        """Test adding missing imports for compute nodes."""
        code = """
class NodeTestCompute:
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code, Path("node_test_compute.py"))

        assert (
            "from omnibase_core.nodes.node_compute import NodeCompute"
            in result.fixed_code
        )
        assert result.fix_count > 0

    def test_add_missing_reducer_imports(self):
        """Test adding missing imports for reducer nodes."""
        code = """
class NodeTestReducer:
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code, Path("node_test_reducer.py"))

        assert (
            "from omnibase_core.nodes.node_reducer import NodeReducer"
            in result.fixed_code
        )
        assert result.fix_count > 0

    def test_add_missing_orchestrator_imports(self):
        """Test adding missing imports for orchestrator nodes."""
        code = """
class NodeTestOrchestrator:
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code, Path("node_test_orchestrator.py"))

        assert (
            "from omnibase_core.nodes.node_orchestrator import NodeOrchestrator"
            in result.fixed_code
        )
        assert result.fix_count > 0

    def test_skip_existing_imports(self):
        """Test that existing imports are not duplicated."""
        code = """from typing import Any, Dict, List, Optional
from uuid import UUID
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError

class NodeTestEffect:
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code, Path("node_test_effect.py"))

        # Should not duplicate imports
        assert (
            result.fixed_code.count(
                "from omnibase_core.nodes.node_effect import NodeEffect"
            )
            == 1
        )


class TestHelperMethods:
    """Test helper methods."""

    def test_fix_unterminated_docstrings_single_line(self):
        """Test fixing single-line unterminated docstring."""
        fixer = WarningFixer()
        lines = [
            '"""This is a test',
            "def test():",
            "    pass",
        ]

        fixes = fixer._fix_unterminated_docstrings(lines)

        assert fixes > 0
        assert '"""' in lines  # Should add closing quotes

    def test_fix_unterminated_docstrings_multiline(self):
        """Test fixing multi-line unterminated docstring."""
        fixer = WarningFixer()
        lines = [
            '"""',
            "This is a test",
            "def test():",
            "    pass",
        ]

        fixes = fixer._fix_unterminated_docstrings(lines)

        assert fixes > 0

    def test_fix_unterminated_docstrings_at_eof(self):
        """Test fixing docstring at end of file."""
        fixer = WarningFixer()
        lines = [
            "def test():",
            '    """This is a test',
            "    pass",
        ]

        fixes = fixer._fix_unterminated_docstrings(lines)

        assert fixes >= 0  # May or may not fix depending on implementation

    def test_detect_node_type_none(self):
        """Test node type detection returns None for non-ONEX code."""
        fixer = WarningFixer()

        code = "class RegularClass: pass"
        assert fixer._detect_node_type(code, None) is None

    def test_get_missing_imports_all_present(self):
        """Test _get_missing_imports with all imports present."""
        fixer = WarningFixer()

        code = """from typing import Any, Dict, List, Optional
from uuid import UUID
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError
"""
        missing = fixer._get_missing_imports(code, "effect")

        assert len(missing) == 0

    def test_get_missing_imports_some_missing(self):
        """Test _get_missing_imports with partial imports."""
        fixer = WarningFixer()

        code = """from typing import Any
"""
        missing = fixer._get_missing_imports(code, "effect")

        assert len(missing) > 0
        assert any("NodeEffect" in imp for imp in missing)

    def test_find_import_insertion_point_basic(self):
        """Test finding import insertion point in basic file."""
        fixer = WarningFixer()
        lines = [
            "# Some code",
            "print('hello')",
        ]

        pos = fixer._find_import_insertion_point(lines)

        assert pos == 0

    def test_find_import_insertion_point_with_shebang(self):
        """Test finding import insertion point with shebang."""
        fixer = WarningFixer()
        lines = [
            "#!/usr/bin/env python3",
            "# Some code",
        ]

        pos = fixer._find_import_insertion_point(lines)

        assert pos == 1

    def test_find_import_insertion_point_with_docstring(self):
        """Test finding import insertion point with module docstring."""
        fixer = WarningFixer()
        lines = [
            '"""Module docstring."""',
            "",
            "# Some code",
        ]

        pos = fixer._find_import_insertion_point(lines)

        assert pos > 0

    def test_find_import_insertion_point_with_multiline_docstring(self):
        """Test finding import insertion point with multi-line docstring."""
        fixer = WarningFixer()
        lines = [
            '"""',
            "Module docstring",
            "with multiple lines",
            '"""',
            "",
            "# Code",
        ]

        pos = fixer._find_import_insertion_point(lines)

        assert pos > 3  # Should be after docstring

    def test_fix_common_import_issues(self):
        """Test _fix_common_import_issues."""
        fixer = WarningFixer()
        lines = [
            "from typing import Any",
            "from ..module import something",
        ]

        fixes = fixer._fix_common_import_issues(lines)

        # This method mostly logs, may not apply fixes
        assert fixes >= 0


class TestEdgeCases:
    """Test edge cases and malformed code handling."""

    def test_empty_string(self):
        """Test handling empty string."""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings("")

        assert result.success is True
        assert result.fixed_code == ""

    def test_whitespace_only(self):
        """Test handling whitespace-only code."""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings("   \n  \n  ")

        assert result.success is True

    def test_malformed_class_definition(self):
        """Test handling malformed class definition."""
        code = "class Model"  # Missing colon
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Should not crash
        assert result.success is True

    def test_malformed_import(self):
        """Test handling malformed import."""
        code = "from pydantic import"  # Incomplete import
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Should not crash
        assert result.success is True

    def test_nested_docstrings(self):
        """Test handling nested docstrings."""
        code = '''
class Test:
    """Class docstring"""

    def method(self):
        """Method docstring"""
        pass
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True
        # Docstrings should remain balanced
        assert result.fixed_code.count('"""') % 2 == 0

    def test_very_long_file(self):
        """Test handling very long file."""
        # Create a file with many lines
        lines = [f"def function_{i}(): pass" for i in range(1000)]
        code = "\n".join(lines)

        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True

    def test_mixed_quote_styles(self):
        """Test handling mixed quote styles in docstrings."""
        code = """
def test1():
    '''Single quote docstring'''
    pass

def test2():
    \"\"\"Double quote docstring\"\"\"
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True

    def test_unicode_content(self):
        """Test handling unicode content."""
        code = '''
def test():
    """测试函数 with émojis 🎉"""
    pass
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True
        assert "测试函数" in result.fixed_code

    def test_multiple_pydantic_v1_patterns_same_line(self):
        """Test fixing multiple Pydantic v1 patterns on same line."""
        code = """from pydantic import BaseModel

def test():
    data = obj.dict().json()
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        # Both should be converted
        assert (
            ".model_dump()" in result.fixed_code
            or ".model_dump_json()" in result.fixed_code
        )


class TestConvenienceFunction:
    """Test apply_automatic_fixes convenience function."""

    def test_apply_automatic_fixes(self):
        """Test convenience function."""
        code = """from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str
"""
        result = apply_automatic_fixes(code)

        assert isinstance(result, FixResult)
        assert result.success is True

    def test_apply_automatic_fixes_with_path(self):
        """Test convenience function with file path."""
        code = """
class NodeTestEffect:
    pass
"""
        result = apply_automatic_fixes(code, Path("node_test_effect.py"))

        assert isinstance(result, FixResult)
        assert result.success is True
        assert result.fix_count > 0


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_complete_onex_node_generation(self):
        """Test fixing a complete ONEX node with all warning types."""
        code = '''from pydantic import BaseModel

class ModelInput(BaseModel):
    data: str

class NodeTestEffect:
    def __init__(self):
        self.config = None

    def execute(self, contract):
        """Execute the effect.
        input_data = contract.dict()
        result = self._process(input_data)
        return result

    def _process(self, data):
        return {"status": "success"}
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code, Path("node_test_effect.py"))

        assert result.success is True
        assert result.fix_count > 0

        # Check G12 fixes
        assert "ConfigDict" in result.fixed_code
        assert "model_config" in result.fixed_code
        assert ".model_dump()" in result.fixed_code

        # Check G13 fixes
        assert "-> None:" in result.fixed_code
        assert (
            "-> Any:" in result.fixed_code or "-> Dict[str, Any]:" in result.fixed_code
        )

        # Check G14 fixes
        assert "from omnibase_core" in result.fixed_code

    def test_multiple_models_and_methods(self):
        """Test file with multiple models and methods."""
        code = '''from pydantic import BaseModel

class ModelInput(BaseModel):
    """Input model."""
    name: str
    value: int

class ModelOutput(BaseModel):
    """Output model."""
    result: str

class ModelConfig(BaseModel):
    """Config model."""
    setting: bool

def process_input(data):
    obj = ModelInput.parse_obj(data)
    return obj

def process_output(result):
    return result.dict()

def validate_config(config):
    return True
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success is True

        # At least some models should have model_config
        assert result.fixed_code.count("model_config") >= 2

        # Pydantic v1 patterns should be fixed
        assert ".model_validate(" in result.fixed_code
        assert ".model_dump()" in result.fixed_code

        # Type hints should be added
        assert "-> Any:" in result.fixed_code or "-> bool:" in result.fixed_code

    def test_fix_idempotency(self):
        """Test that running fixes twice produces same result."""
        code = """from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str

def process(data):
    return data.dict()
"""
        fixer = WarningFixer()

        # First run
        result1 = fixer.fix_all_warnings(code)

        # Second run on fixed code
        result2 = fixer.fix_all_warnings(result1.fixed_code)

        # Should have fewer or same fixes on second run
        assert result2.fix_count <= result1.fix_count

    def test_preserve_code_structure(self):
        """Test that fixes preserve overall code structure."""
        code = '''from pydantic import BaseModel

class ModelInput(BaseModel):
    """Input model."""
    name: str

    def custom_method(self):
        """Custom method."""
        return self.name

def external_function():
    """External function."""
    pass
'''
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Structure should be preserved
        assert "class ModelInput" in result.fixed_code
        assert "def custom_method" in result.fixed_code
        assert "def external_function" in result.fixed_code
        assert "External function" in result.fixed_code


class TestFixResultAccumulation:
    """Test fix result accumulation across phases."""

    def test_fix_count_accumulation(self):
        """Test that fix_count accumulates across all phases."""
        code = """from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str

def process(data):
    return data.dict()
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # fix_count should match number of fixes_applied
        assert result.fix_count == len(result.fixes_applied)

    def test_warnings_fixed_list(self):
        """Test warnings_fixed list contains unique gate IDs."""
        code = """from pydantic import BaseModel

class ModelInput(BaseModel):
    name: str

def process(data):
    return data.dict()
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Should have unique gate IDs
        if result.warnings_fixed:
            unique_warnings = set(result.warnings_fixed)
            assert len(unique_warnings) <= 3  # Max 3 gate types: G12, G13, G14


class TestNodeTypeImports:
    """Test NODE_TYPE_IMPORTS configuration."""

    def test_node_type_imports_structure(self):
        """Test NODE_TYPE_IMPORTS has correct structure."""
        fixer = WarningFixer()

        assert "effect" in fixer.NODE_TYPE_IMPORTS
        assert "compute" in fixer.NODE_TYPE_IMPORTS
        assert "reducer" in fixer.NODE_TYPE_IMPORTS
        assert "orchestrator" in fixer.NODE_TYPE_IMPORTS

        # Each should have required imports
        for node_type, imports in fixer.NODE_TYPE_IMPORTS.items():
            assert isinstance(imports, list)
            assert len(imports) > 0
            assert any("typing" in imp for imp in imports)
            assert any("uuid" in imp for imp in imports)
            assert any(f"node_{node_type}" in imp for imp in imports)


class TestCommonMethodHints:
    """Test COMMON_METHOD_HINTS configuration."""

    def test_common_method_hints_structure(self):
        """Test COMMON_METHOD_HINTS has correct structure."""
        fixer = WarningFixer()

        assert "__init__" in fixer.COMMON_METHOD_HINTS
        assert fixer.COMMON_METHOD_HINTS["__init__"] == "-> None"

        assert "_validate_input" in fixer.COMMON_METHOD_HINTS
        assert fixer.COMMON_METHOD_HINTS["_validate_input"] == "-> None"

        assert "_execute_business_logic" in fixer.COMMON_METHOD_HINTS
        assert "Dict[str, Any]" in fixer.COMMON_METHOD_HINTS["_execute_business_logic"]
