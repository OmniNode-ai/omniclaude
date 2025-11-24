"""Unit tests for the naming validator."""

import sys
import tempfile
from pathlib import Path

import pytest


# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.validators.naming_validator import NamingValidator


class TestPythonNaming:
    """Test Python naming convention validation."""

    def test_valid_python_function_naming(self):
        """Test that valid snake_case functions pass validation."""
        validator = NamingValidator()

        code = """
def calculate_total(items):
    return sum(items)

def process_data():
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert (
            len(violations) == 0
        ), "Valid snake_case functions should not have violations"

    def test_invalid_python_function_naming_camelcase(self):
        """Test that camelCase functions are detected as violations."""
        validator = NamingValidator()

        code = """
def calculateTotal(items):
    return sum(items)
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 1, "camelCase function should be detected"
        assert violations[0].violation_type == "function"
        assert violations[0].name == "calculateTotal"
        assert violations[0].expected_format == "snake_case"
        assert "calculate_total" in violations[0].message

    def test_valid_python_class_naming(self):
        """Test that valid PascalCase classes pass validation."""
        validator = NamingValidator()

        code = """
class UserProfile:
    pass

class DataProcessor:
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert (
            len(violations) == 0
        ), "Valid PascalCase classes should not have violations"

    def test_invalid_python_class_naming_snake_case(self):
        """Test that snake_case classes are detected as violations."""
        validator = NamingValidator()

        code = """
class user_profile:
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 1, "snake_case class should be detected"
        assert violations[0].violation_type == "class"
        assert violations[0].name == "user_profile"
        assert violations[0].expected_format == "PascalCase"
        assert "UserProfile" in violations[0].message

    def test_python_multiple_violations(self):
        """Test detection of multiple violations in one file."""
        validator = NamingValidator()

        code = """
class user_profile:
    def calculateTotal(self, items):
        return sum(items)

def processData():
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 3, "Should detect class and function violations"

        # Check violation types
        violation_types = {v.violation_type for v in violations}
        assert "class" in violation_types
        assert "function" in violation_types


class TestTypeScriptNaming:
    """Test TypeScript naming convention validation."""

    def test_valid_typescript_function_naming(self):
        """Test that valid camelCase functions pass validation."""
        validator = NamingValidator()

        code = """
function calculateTotal(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}

function processData() {
    // implementation
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert (
            len(violations) == 0
        ), "Valid camelCase functions should not have violations"

    def test_invalid_typescript_function_naming_snake_case(self):
        """Test that snake_case functions are detected as violations."""
        validator = NamingValidator()

        code = """
function calculate_total(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 1, "snake_case function should be detected"
        assert violations[0].violation_type == "function"
        assert violations[0].name == "calculate_total"
        assert violations[0].expected_format == "camelCase"
        assert "calculateTotal" in violations[0].message

    def test_valid_typescript_class_naming(self):
        """Test that valid PascalCase classes pass validation."""
        validator = NamingValidator()

        code = """
class UserProfile {
    constructor(public name: string) {}
}

class DataProcessor {
    process() {}
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert (
            len(violations) == 0
        ), "Valid PascalCase classes should not have violations"

    def test_invalid_typescript_class_naming_snake_case(self):
        """Test that snake_case classes are detected as violations."""
        validator = NamingValidator()

        code = """
class user_profile {
    name: string;
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 1, "snake_case class should be detected"
        assert violations[0].violation_type == "class"
        assert violations[0].name == "user_profile"
        assert violations[0].expected_format == "PascalCase"
        assert "UserProfile" in violations[0].message

    def test_valid_typescript_interface_naming(self):
        """Test that valid PascalCase interfaces pass validation."""
        validator = NamingValidator()

        code = """
interface UserProfile {
    name: string;
    email: string;
}

interface DataProcessor {
    process(): void;
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert (
            len(violations) == 0
        ), "Valid PascalCase interfaces should not have violations"

    def test_invalid_typescript_interface_naming(self):
        """Test that non-PascalCase interfaces are detected as violations."""
        validator = NamingValidator()

        code = """
interface user_profile {
    name: string;
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 1, "snake_case interface should be detected"
        assert violations[0].violation_type == "interface"
        assert violations[0].expected_format == "PascalCase"


class TestCaseConversionHelpers:
    """Test case conversion helper methods."""

    def test_to_snake_case(self):
        """Test conversion to snake_case."""
        validator = NamingValidator()

        assert validator._to_snake_case("calculateTotal") == "calculate_total"
        assert validator._to_snake_case("UserProfile") == "user_profile"
        assert validator._to_snake_case("HTTPServer") == "http_server"
        assert validator._to_snake_case("already_snake_case") == "already_snake_case"

    def test_to_camel_case(self):
        """Test conversion to camelCase."""
        validator = NamingValidator()

        assert validator._to_camel_case("calculate_total") == "calculateTotal"
        assert validator._to_camel_case("user_profile") == "userProfile"
        assert validator._to_camel_case("already") == "already"
        assert validator._to_camel_case("http_server") == "httpServer"

    def test_to_pascal_case(self):
        """Test conversion to PascalCase."""
        validator = NamingValidator()

        assert validator._to_pascal_case("calculate_total") == "CalculateTotal"
        assert validator._to_pascal_case("user_profile") == "UserProfile"
        assert validator._to_pascal_case("http_server") == "HttpServer"
        assert validator._to_pascal_case("already") == "Already"

    def test_to_upper_snake_case(self):
        """Test conversion to UPPER_SNAKE_CASE."""
        validator = NamingValidator()

        assert validator._to_upper_snake_case("apiKey") == "API_KEY"
        assert validator._to_upper_snake_case("UserProfile") == "USER_PROFILE"
        assert validator._to_upper_snake_case("already_lower") == "ALREADY_LOWER"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_python_syntax(self):
        """Test that invalid Python syntax is handled gracefully."""
        validator = NamingValidator()

        code = """
def invalid syntax here
    this is not valid python
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Should not crash, should return empty violations
        assert isinstance(violations, list)

    def test_empty_file(self):
        """Test validation of empty file."""
        validator = NamingValidator()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("")
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 0, "Empty file should have no violations"

    def test_nonexistent_file(self):
        """Test validation of non-existent file."""
        validator = NamingValidator()

        violations = validator.validate_file("/nonexistent/file.py")

        assert len(violations) == 0, "Non-existent file should return empty violations"

    def test_private_methods_ignored(self):
        """Test that private methods (starting with _) are not flagged."""
        validator = NamingValidator()

        code = """
def _privateMethod():
    pass

def __dunderMethod__():
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Private methods starting with _ should be ignored
        assert len(violations) == 0, "Private methods should be ignored"


class TestOmninodeRepoDetection:
    """Test auto-detection for all actual Omninode repos."""

    def test_all_actual_repos_detection(self):
        """Verify auto-detection for all actual repos."""
        # Include repos (should enforce Omninode conventions)
        assert NamingValidator.is_omninode_repo("/workspace/omniagent/test.py") is True
        assert (
            NamingValidator.is_omninode_repo("/workspace/omniagent-main/test.py")
            is True
        )
        assert (
            NamingValidator.is_omninode_repo("/workspace/omnibase_core/test.py") is True
        )
        assert (
            NamingValidator.is_omninode_repo("/workspace/omnibase_infra/test.py")
            is True
        )
        assert (
            NamingValidator.is_omninode_repo("/workspace/omnibase_spi/test.py") is True
        )
        assert NamingValidator.is_omninode_repo("/workspace/omnimcp/test.py") is True
        assert NamingValidator.is_omninode_repo("/workspace/omnimemory/test.py") is True
        assert NamingValidator.is_omninode_repo("/workspace/omniplan/test.py") is True

        # Exclude repos (should use PEP 8)
        assert (
            NamingValidator.is_omninode_repo("/workspace/omninode_bridge/test.py")
            is False
        )
        assert NamingValidator.is_omninode_repo("/workspace/Archon/test.py") is False

        # Additional edge cases
        assert NamingValidator.is_omninode_repo("/some/other/repo/test.py") is False
        assert (
            NamingValidator.is_omninode_repo("/workspace/random_project/test.py")
            is False
        )

    def test_omninode_conventions_applied_correctly(self):
        """Verify Omninode repos get Omninode-specific validation."""
        validator = NamingValidator(language="python", validation_mode="auto")

        # Test with Omninode repo path - should require Model prefix
        code = """
from pydantic import BaseModel

class User(BaseModel):  # Should be ModelUser
    name: str
"""
        omninode_path = "/workspace/omnibase_core/models/user.py"
        violations = validator.validate_content(code, omninode_path)

        # Should detect violation for missing Model prefix
        assert (
            len(violations) > 0
        ), "Should detect Model prefix violation in Omninode repo"
        assert any(
            "Model" in str(v.message) for v in violations
        ), "Should mention Model prefix requirement"

    def test_pep8_conventions_for_excluded_repos(self):
        """Verify excluded repos get standard PEP 8 validation."""
        validator = NamingValidator(language="python", validation_mode="auto")

        # Test with Archon repo path - should allow classes without Model prefix
        code = """
from pydantic import BaseModel

class User(BaseModel):  # Should be allowed (standard PEP 8)
    name: str
"""
        archon_path = "/workspace/Archon/src/models/user.py"
        violations = validator.validate_content(code, archon_path)

        # Should NOT detect Model prefix violation in Archon
        model_violations = [v for v in violations if "Model" in str(v.message)]
        assert (
            len(model_violations) == 0
        ), "Should not require Model prefix in Archon repo"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
