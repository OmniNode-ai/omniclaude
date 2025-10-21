"""Integration tests for the quality enforcement system."""

import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.validators.naming_validator import NamingValidator


class TestEndToEndPython:
    """End-to-end integration tests for Python validation."""

    def test_complete_validation_pipeline_python(self):
        """Test complete enforcement pipeline for Python with multiple violations."""
        validator = NamingValidator()

        code = '''
def calculateTotal(items):
    """Calculate total of items."""
    return sum(items)

class user_profile:
    """User profile class."""
    pass

def process_data():
    """This one is correct."""
    pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Should detect 2 violations: calculateTotal and user_profile
        assert len(violations) >= 2, "Should detect function and class violations"

        # Check that violations have correct types
        violation_types = {v.violation_type for v in violations}
        assert "function" in violation_types
        assert "class" in violation_types

        # Check that suggestions are provided
        func_violation = next(v for v in violations if v.violation_type == "function")
        assert "calculate_total" in func_violation.message

        class_violation = next(v for v in violations if v.violation_type == "class")
        assert "UserProfile" in class_violation.message

    def test_clean_code_no_violations(self):
        """Test that clean code passes without violations."""
        validator = NamingValidator()

        code = '''
def calculate_total(items):
    """Calculate total of items."""
    return sum(items)

class UserProfile:
    """User profile class."""
    def __init__(self, name):
        self.name = name

def process_data():
    """Process data."""
    pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 0, "Clean code should have no violations"


class TestEndToEndTypeScript:
    """End-to-end integration tests for TypeScript validation."""

    def test_complete_validation_pipeline_typescript(self):
        """Test complete enforcement pipeline for TypeScript with multiple violations."""
        validator = NamingValidator()

        code = """
function calculate_total(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}

class user_profile {
    constructor(public name: string) {}
}

interface data_processor {
    process(): void;
}

function processData() {
    // This one is correct
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Should detect violations: calculate_total, user_profile, data_processor
        assert (
            len(violations) >= 3
        ), "Should detect function, class, and interface violations"

        # Check violation types
        violation_types = {v.violation_type for v in violations}
        assert "function" in violation_types
        assert "class" in violation_types
        assert "interface" in violation_types

    def test_clean_typescript_code(self):
        """Test that clean TypeScript code passes without violations."""
        validator = NamingValidator()

        code = """
function calculateTotal(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}

class UserProfile {
    constructor(public name: string) {}
}

interface DataProcessor {
    process(): void;
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == 0, "Clean TypeScript code should have no violations"


class TestPerformance:
    """Performance tests to ensure validation meets performance budget."""

    def test_performance_budget_small_file(self):
        """Ensure validation completes within performance budget for small files."""
        validator = NamingValidator()

        code = """
def calculateTotal(items):
    return sum(items)

class user_profile:
    pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            start = time.time()
            violations = validator.validate_file(f.name)
            elapsed = time.time() - start

        # Should complete in much less than 100ms (design target)
        assert (
            elapsed < 0.1
        ), f"Validation took {elapsed*1000:.2f}ms, exceeds 100ms budget"
        assert len(violations) > 0, "Should detect violations"

    def test_performance_budget_medium_file(self):
        """Ensure validation completes within budget for medium-sized files."""
        validator = NamingValidator()

        # Generate a medium-sized file with multiple violations
        code_blocks = []
        for i in range(50):
            code_blocks.append(
                f"""
def processData{i}():
    pass

class data_processor_{i}:
    pass
"""
            )

        code = "\n".join(code_blocks)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            start = time.time()
            violations = validator.validate_file(f.name)
            elapsed = time.time() - start

        # Should still complete in reasonable time
        assert elapsed < 0.5, f"Validation took {elapsed*1000:.2f}ms, exceeds 500ms"
        assert len(violations) > 0, "Should detect violations"


class TestMultiLanguage:
    """Test validation across different file types."""

    def test_javascript_validation(self):
        """Test JavaScript file validation."""
        validator = NamingValidator()

        code = """
function calculate_total(items) {
    return items.reduce((a, b) => a + b, 0);
}

class user_profile {
    constructor(name) {
        this.name = name;
    }
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) >= 2, "Should detect JavaScript violations"

    def test_tsx_validation(self):
        """Test TSX file validation."""
        validator = NamingValidator()

        code = """
interface user_props {
    name: string;
}

function user_component(props: user_props) {
    return <div>{props.name}</div>;
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsx", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) >= 2, "Should detect TSX violations"


class TestRealWorldScenarios:
    """Test real-world scenarios and complex cases."""

    def test_mixed_valid_invalid_code(self):
        """Test file with mix of valid and invalid names."""
        validator = NamingValidator()

        code = """
# Valid code
def calculate_total(items):
    return sum(items)

class UserProfile:
    pass

# Invalid code
def processData():
    pass

class api_handler:
    pass

# More valid code
def format_string(text):
    return text.strip()
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Should detect exactly 2 violations: processData and api_handler
        assert len(violations) == 2, f"Expected 2 violations, found {len(violations)}"

        violation_names = {v.name for v in violations}
        assert "processData" in violation_names
        assert "api_handler" in violation_names

    def test_nested_classes_and_methods(self):
        """Test validation of nested classes and methods."""
        validator = NamingValidator()

        code = """
class OuterClass:
    def validMethod(self):
        pass

    class inner_class:
        def anotherMethod(self):
            pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        # Should detect violations in nested structures
        assert len(violations) >= 2, "Should detect violations in nested code"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
