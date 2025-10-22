#!/usr/bin/env python3
"""
Unit tests for WarningFixer

Tests automatic fixes for G12, G13, and G14 validation warnings.
"""

from pathlib import Path

import pytest

from agents.lib.warning_fixer import FixResult, WarningFixer, apply_automatic_fixes


class TestG12PydanticConfigFixes:
    """Test G12: Pydantic v2 ConfigDict fixes."""

    def test_add_configdict_import(self):
        """Test adding ConfigDict to existing pydantic import."""
        code = """from pydantic import BaseModel, Field

class ModelTestInput(BaseModel):
    name: str
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert result.fix_count > 0
        assert "ConfigDict" in result.fixed_code
        assert "Added ConfigDict import" in result.fixes_applied

    def test_add_model_config_input_model(self):
        """Test adding model_config to input model."""
        code = """from pydantic import BaseModel, Field, ConfigDict

class ModelTestInput(BaseModel):
    \"\"\"Input model for test.\"\"\"

    name: str
    value: int
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert result.fix_count > 0
        assert "model_config = ConfigDict" in result.fixed_code
        assert 'extra="forbid"' in result.fixed_code
        assert "validate_assignment=True" in result.fixed_code
        assert "str_strip_whitespace=True" in result.fixed_code

    def test_add_model_config_output_model(self):
        """Test adding model_config to output model."""
        code = """from pydantic import BaseModel, Field, ConfigDict

class ModelTestOutput(BaseModel):
    \"\"\"Output model for test.\"\"\"

    result: str
    success: bool
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert result.fix_count > 0
        assert "model_config = ConfigDict" in result.fixed_code
        assert 'extra="allow"' in result.fixed_code
        assert "validate_assignment=True" in result.fixed_code

    def test_skip_if_model_config_exists(self):
        """Test skipping models that already have model_config."""
        code = """from pydantic import BaseModel, Field, ConfigDict

class ModelTestInput(BaseModel):
    \"\"\"Input model for test.\"\"\"

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        # Should not add duplicate config
        assert result.fixed_code.count("model_config") == 1

    def test_fix_pydantic_v1_dict_method(self):
        """Test replacing .dict() with .model_dump()."""
        code = """
result = model.dict()
data = obj.dict(exclude={'field'})
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_dump()" in result.fixed_code
        assert ".dict()" not in result.fixed_code

    def test_fix_pydantic_v1_parse_obj(self):
        """Test replacing .parse_obj() with .model_validate()."""
        code = """
model = MyModel.parse_obj(data)
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert ".model_validate(" in result.fixed_code
        assert ".parse_obj(" not in result.fixed_code

    def test_fix_multiple_models(self):
        """Test fixing multiple models in same file."""
        code = """from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    name: str

class ModelOutput(BaseModel):
    result: str

class ModelConfig(BaseModel):
    setting: str
"""
        fixer = WarningFixer()
        result = fixer.fix_g12_pydantic_config(code)

        assert result.fix_count >= 3  # One config per model
        assert result.fixed_code.count("model_config") == 3


class TestG13TypeHintFixes:
    """Test G13: Type hint additions."""

    def test_add_typing_imports(self):
        """Test adding missing typing imports."""
        code = """import logging

def process_data(data):
    return data
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "from typing import" in result.fixed_code
        assert "Added typing imports" in result.fixes_applied

    def test_add_return_type_to_init(self):
        """Test adding -> None to __init__ method."""
        code = """from typing import Any

class MyClass:
    def __init__(self, value: int):
        self.value = value
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "def __init__(self, value: int) -> None:" in result.fixed_code

    def test_add_return_type_to_validate_method(self):
        """Test adding -> None to _validate methods."""
        code = """from typing import Any

class MyClass:
    def _validate_input(self, data: dict):
        pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "def _validate_input(self, data: dict) -> None:" in result.fixed_code

    def test_add_return_type_to_execute_method(self):
        """Test adding -> Dict[str, Any] to _execute methods."""
        code = """from typing import Any, Dict

class MyClass:
    def _execute_business_logic(self, input_data):
        return {}
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert (
            "def _execute_business_logic(self, input_data) -> Dict[str, Any]:"
            in result.fixed_code
        )

    def test_add_return_type_to_getter(self):
        """Test adding -> Any to _get methods."""
        code = """from typing import Any

class MyClass:
    def _get_value(self, key: str):
        return self.data.get(key)
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "def _get_value(self, key: str) -> Any:" in result.fixed_code

    def test_add_return_type_to_boolean_method(self):
        """Test adding -> bool to _is/_has methods."""
        code = """from typing import Any

class MyClass:
    def _is_valid(self, data):
        return True

    def _has_permission(self, user):
        return False
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        assert "def _is_valid(self, data) -> bool:" in result.fixed_code
        assert "def _has_permission(self, user) -> bool:" in result.fixed_code

    def test_skip_methods_with_existing_hints(self):
        """Test skipping methods that already have type hints."""
        code = """from typing import Any, Dict

class MyClass:
    def process(self, data: dict) -> Dict[str, Any]:
        return {}
"""
        fixer = WarningFixer()
        result = fixer.fix_g13_type_hints(code)

        # Should not modify existing hints
        assert "def process(self, data: dict) -> Dict[str, Any]:" in result.fixed_code


class TestG14ImportFixes:
    """Test G14: Import error fixes."""

    def test_fix_unterminated_docstring(self):
        """Test fixing unterminated docstring."""
        code = '''class MyClass:
    """
    This is a docstring
    that is not terminated

    def method(self):
        pass
'''
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code)

        # Should add closing quotes
        assert '"""' in result.fixed_code
        assert "unterminated docstrings" in result.fixes_applied[0].lower()

    def test_detect_effect_node_type(self):
        """Test detecting Effect node type."""
        code = """
class NodeTestEffect(NodeEffect):
    pass
"""
        fixer = WarningFixer()
        node_type = fixer._detect_node_type(code)

        assert node_type == "effect"

    def test_detect_compute_node_type(self):
        """Test detecting Compute node type."""
        code = """
class NodeTestCompute(NodeCompute):
    pass
"""
        fixer = WarningFixer()
        node_type = fixer._detect_node_type(code)

        assert node_type == "compute"

    def test_detect_node_type_from_file_path(self):
        """Test detecting node type from file path."""
        code = "class MyNode: pass"
        file_path = Path("/path/to/node_test_effect.py")

        fixer = WarningFixer()
        node_type = fixer._detect_node_type(code, file_path)

        assert node_type == "effect"

    def test_add_missing_imports_for_effect_node(self):
        """Test adding missing imports for Effect node."""
        code = """
class NodeTestEffect(NodeEffect):
    def process(self):
        pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code)

        # Should add required imports
        assert "from typing import" in result.fixed_code
        assert "from uuid import UUID" in result.fixed_code
        assert (
            "from omnibase_core.nodes.node_effect import NodeEffect"
            in result.fixed_code
        )

    def test_skip_existing_imports(self):
        """Test skipping imports that already exist."""
        code = """from typing import Any, Dict, List, Optional
from uuid import UUID
from omnibase_core.nodes.node_effect import NodeEffect

class NodeTestEffect(NodeEffect):
    pass
"""
        fixer = WarningFixer()
        result = fixer.fix_g14_imports(code)

        # Should not add duplicate imports
        assert result.fixed_code.count("from typing import") == 1
        assert result.fixed_code.count("from uuid import UUID") == 1

    def test_find_import_insertion_point_after_shebang(self):
        """Test finding correct insertion point after shebang."""
        lines = [
            "#!/usr/bin/env python3",
            '"""Module docstring."""',
            "",
            "import sys",
        ]

        fixer = WarningFixer()
        pos = fixer._find_import_insertion_point(lines)

        # Should insert after docstring
        assert pos == 3  # After blank line after docstring

    def test_find_import_insertion_point_multiline_docstring(self):
        """Test finding insertion point with multiline docstring."""
        lines = [
            "#!/usr/bin/env python3",
            '"""',
            "Module docstring",
            "with multiple lines",
            '"""',
            "",
            "import sys",
        ]

        fixer = WarningFixer()
        pos = fixer._find_import_insertion_point(lines)

        # Should insert after docstring end
        assert pos >= 5


class TestIntegrationFixes:
    """Test integrated fix application."""

    def test_fix_all_warnings_order(self):
        """Test that fixes are applied in correct order."""
        code = """from pydantic import BaseModel

class ModelTestInput(BaseModel):
    name: str

class MyNode:
    def __init__(self, value: int):
        self.value = value

    def process(self, data):
        model = ModelTestInput(name="test")
        return model.dict()
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Should apply all three types of fixes
        assert "G12" in result.warnings_fixed or "Pydantic" in str(result.fixes_applied)
        assert "G13" in result.warnings_fixed or "type" in str(result.fixes_applied)

        # Verify final code
        assert "model_config = ConfigDict" in result.fixed_code
        assert ".model_dump()" in result.fixed_code
        assert "def __init__(self, value: int) -> None:" in result.fixed_code

    def test_convenience_function(self):
        """Test convenience function for pipeline integration."""
        code = """from pydantic import BaseModel

class ModelTest(BaseModel):
    value: str
"""
        result = apply_automatic_fixes(code)

        assert isinstance(result, FixResult)
        assert result.fix_count > 0

    def test_fix_production_pattern(self):
        """Test fixing production-style code pattern."""
        code = """#!/usr/bin/env python3
\"\"\"
ONEX Effect Node: TestWriter

Writes test data to storage.
\"\"\"

from pydantic import BaseModel, Field

class ModelTestWriterInput(BaseModel):
    \"\"\"Input model for test writer.\"\"\"

    data: str = Field(..., description="Data to write")
    correlation_id: str = Field(..., description="Correlation ID")

class ModelTestWriterOutput(BaseModel):
    \"\"\"Output model for test writer.\"\"\"

    success: bool = Field(..., description="Write success")
    bytes_written: int = Field(..., description="Bytes written")
    correlation_id: str = Field(..., description="Correlation ID")

class NodeTestWriterEffect:
    def __init__(self, container):
        self.container = container

    async def process(self, input_data: ModelTestWriterInput):
        result = await self._execute_write(input_data)
        output = ModelTestWriterOutput(
            success=True,
            bytes_written=len(input_data.data),
            correlation_id=input_data.correlation_id
        )
        return output.dict()

    async def _execute_write(self, input_data):
        return {"status": "written"}
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Verify comprehensive fixes
        assert "ConfigDict" in result.fixed_code
        assert "model_config" in result.fixed_code
        assert ".model_dump()" in result.fixed_code
        assert "-> None:" in result.fixed_code  # __init__
        assert result.fix_count >= 4  # Multiple fixes applied

    def test_no_changes_for_compliant_code(self):
        """Test that compliant code is not modified."""
        code = """#!/usr/bin/env python3
from typing import Any, Dict
from pydantic import BaseModel, ConfigDict

class ModelTestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str

class MyNode:
    def __init__(self) -> None:
        pass

    def process(self, data: dict) -> Dict[str, Any]:
        return {}
"""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        # Should make minimal or no changes
        assert result.fix_count == 0 or result.fix_count < 2


class TestErrorHandling:
    """Test error handling in warning fixer."""

    def test_handle_very_large_file(self):
        """Test handling of very large files with safety limits."""
        # Create a file with many lines to test iteration limit
        lines = ["# Line {i}" for i in range(5000)]
        code = "\n".join(lines)
        fixer = WarningFixer()

        # Should complete without hanging
        result = fixer.fix_all_warnings(code)
        assert result.success

    def test_handle_many_blank_lines(self):
        """Test handling of many consecutive blank lines."""
        # Create code with excessive blank lines
        code = (
            '''#!/usr/bin/env python3
"""Module docstring."""

'''
            + ("\n" * 200)
            + """
import sys
"""
        )
        fixer = WarningFixer()

        # Should complete without hanging
        result = fixer.fix_all_warnings(code)
        assert result.success

    def test_handle_invalid_syntax(self):
        """Test graceful handling of invalid syntax."""
        code = """
class MyClass
    def method(self)
        pass
"""
        fixer = WarningFixer()

        # Should not crash
        result = fixer.fix_all_warnings(code)
        assert result.success  # May not fix syntax errors, but shouldn't crash

    def test_handle_empty_code(self):
        """Test handling empty code."""
        code = ""
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code)

        assert result.success
        assert result.fix_count == 0

    def test_handle_malformed_docstring(self):
        """Test handling malformed docstrings."""
        code = '''
class MyClass:
    """This docstring has weird formatting
    and multiple """ quotes """ inside
    """
    pass
'''
        fixer = WarningFixer()

        # Should not crash
        result = fixer.fix_all_warnings(code)
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
