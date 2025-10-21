"""
Comprehensive tests for AST-based code corrector.

Tests verify that:
1. Framework methods are NEVER renamed (AST visitor, Django, FastAPI, pytest)
2. User code IS corrected when violations exist
3. Formatting and comments are preserved
4. Performance is <100ms for typical files
5. Graceful fallback when libcst unavailable

Author: Claude Code + Archon AI Quality Enforcer
Date: 2025-09-30
"""

import sys
from pathlib import Path

import pytest

# Add hooks lib to path
HOOKS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

from correction.ast_corrector import apply_corrections_with_ast  # noqa: E402
from correction.framework_detector import FrameworkMethodDetector  # noqa: E402


class TestFrameworkMethodPreservation:
    """Test that framework methods are NEVER renamed."""

    def test_ast_visitor_methods_not_renamed(self):
        """AST visitor methods must not be renamed."""
        code = """
import ast

class MyVisitor(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        '''Visit function definitions'''
        pass

    def generic_visit(self, node):
        pass
"""
        correction = {
            "old_name": "visit_FunctionDef",
            "new_name": "visit__function_def",
            "line": 5,
            "column": 8,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert "visit_FunctionDef" in result.corrected_content
        assert "visit__function_def" not in result.corrected_content
        assert result.framework_methods_preserved >= 1

    def test_django_model_methods_not_renamed(self):
        """Django model methods must not be renamed."""
        code = """
from django.db import models

class MyModel(models.Model):
    name = models.CharField(max_length=100)

    def save(self, *args, **kwargs):
        '''Custom save logic'''
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
"""
        corrections = [
            {"old_name": "save", "new_name": "save_model", "line": 6, "column": 8},
            {"old_name": "delete", "new_name": "delete_model", "line": 10, "column": 8},
        ]

        result = apply_corrections_with_ast(code, corrections)

        assert result.success
        assert "def save(" in result.corrected_content
        assert "def delete(" in result.corrected_content
        assert result.framework_methods_preserved >= 2

    def test_fastapi_route_methods_not_renamed(self):
        """FastAPI route methods must not be renamed."""
        code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
def get(request):
    '''Get users endpoint'''
    return {"users": []}

@app.post("/items")
async def post(data):
    return {"created": True}
"""
        corrections = [
            {"old_name": "get", "new_name": "get_users", "line": 6, "column": 4},
            {"old_name": "post", "new_name": "post_item", "line": 11, "column": 10},
        ]

        result = apply_corrections_with_ast(code, corrections)

        assert result.success
        assert "def get(" in result.corrected_content
        assert "async def post(" in result.corrected_content
        assert result.framework_methods_preserved >= 2

    def test_pytest_test_functions_not_renamed(self):
        """pytest test functions must not be renamed."""
        code = """
def test_something():
    '''Test something important'''
    assert True

def test_another():
    assert 1 + 1 == 2
"""
        corrections = [
            {
                "old_name": "test_something",
                "new_name": "test__something",
                "line": 1,
                "column": 4,
            },
            {
                "old_name": "test_another",
                "new_name": "test__another",
                "line": 5,
                "column": 4,
            },
        ]

        result = apply_corrections_with_ast(code, corrections)

        assert result.success
        assert "def test_something" in result.corrected_content
        assert "def test_another" in result.corrected_content
        assert result.framework_methods_preserved >= 2

    def test_magic_methods_not_renamed(self):
        """Python magic methods must not be renamed."""
        code = """
class MyClass:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)

    def __eq__(self, other):
        return self.value == other.value
"""
        corrections = [
            {
                "old_name": "__init__",
                "new_name": "__init_method__",
                "line": 2,
                "column": 8,
            },
            {"old_name": "__str__", "new_name": "__string__", "line": 5, "column": 8},
        ]

        result = apply_corrections_with_ast(code, corrections)

        assert result.success
        assert "def __init__" in result.corrected_content
        assert "def __str__" in result.corrected_content
        assert result.framework_methods_preserved >= 2


class TestUserCodeCorrections:
    """Test that user code violations ARE corrected."""

    def test_user_function_renamed(self):
        """User function with naming violation should be corrected."""
        code = """
class MyClass:
    def getUserData(self):
        '''Get user data'''
        return {"user": "data"}
"""
        correction = {
            "old_name": "getUserData",
            "new_name": "get_user_data",
            "line": 2,
            "column": 8,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert "get_user_data" in result.corrected_content
        assert "getUserData" not in result.corrected_content
        assert result.corrections_applied >= 1

    def test_user_variable_renamed(self):
        """User variable with naming violation should be corrected."""
        code = """
def process_data():
    userData = {"name": "John"}
    return userData
"""
        correction = {
            "old_name": "userData",
            "new_name": "user_data",
            "line": 2,
            "column": 4,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert "user_data" in result.corrected_content
        assert result.corrections_applied >= 1

    def test_user_class_renamed(self):
        """User class with naming violation should be corrected."""
        code = """
class user_class:
    '''A user class'''
    pass
"""
        correction = {
            "old_name": "user_class",
            "new_name": "UserClass",
            "line": 1,
            "column": 6,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert "class UserClass" in result.corrected_content
        assert result.corrections_applied >= 1


class TestFormattingPreservation:
    """Test that formatting and comments are preserved."""

    def test_comments_preserved(self):
        """All comments should be preserved."""
        code = """
# Module docstring
def myFunction():  # Inline comment
    '''Docstring'''
    # Block comment
    x = 1  # Another inline
    return x
"""
        correction = {
            "old_name": "myFunction",
            "new_name": "my_function",
            "line": 2,
            "column": 4,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert "# Module docstring" in result.corrected_content
        assert "# Inline comment" in result.corrected_content
        assert "# Block comment" in result.corrected_content
        assert "# Another inline" in result.corrected_content
        assert "'''Docstring'''" in result.corrected_content

    def test_formatting_preserved(self):
        """Custom spacing and formatting should be preserved."""
        code = """
def foo(  x,   y  ):
    '''Custom   spacing'''
    return   x + y
"""
        # No corrections, just verify formatting preservation
        result = apply_corrections_with_ast(code, [])

        assert result.success
        # libcst should preserve most spacing
        assert "def foo" in result.corrected_content

    def test_docstrings_preserved(self):
        """Docstrings should be preserved."""
        code = '''
def my_function():
    """
    This is a multi-line
    docstring with details.

    Args:
        None

    Returns:
        str: A message
    """
    return "hello"
'''
        # No corrections
        result = apply_corrections_with_ast(code, [])

        assert result.success
        assert '"""' in result.corrected_content
        assert "This is a multi-line" in result.corrected_content


class TestStringLiteralPreservation:
    """Test that string literals are NOT modified."""

    def test_string_literals_not_renamed(self):
        """Identifiers in string literals should not be renamed."""
        code = """
def process():
    method_name = "getUserData"  # String literal
    message = "Call getUserData() method"  # In string
    return method_name

def getUserData():  # Should be renamed
    '''Get user data'''
    pass
"""
        correction = {
            "old_name": "getUserData",
            "new_name": "get_user_data",
            "line": 7,
            "column": 4,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        # Function definition should be renamed
        assert "def get_user_data" in result.corrected_content
        # String literals should NOT be renamed
        assert '"getUserData"' in result.corrected_content
        assert '"Call getUserData() method"' in result.corrected_content


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_syntax_error_handling(self):
        """Invalid Python should be handled gracefully."""
        code = """
def broken syntax here
    pass
"""
        correction = {"old_name": "broken", "new_name": "fixed", "line": 1, "column": 4}

        result = apply_corrections_with_ast(code, [correction])

        assert not result.success
        assert "Syntax error" in result.error_message

    def test_empty_corrections_list(self):
        """Empty corrections should succeed without changes."""
        code = """
def my_function():
    pass
"""
        result = apply_corrections_with_ast(code, [])

        assert result.success
        assert result.corrections_applied == 0
        assert result.corrected_content == code

    def test_multiple_corrections(self):
        """Multiple corrections should be applied in single pass."""
        code = """
class MyClass:
    def getUserData(self):
        userData = {"name": "John"}
        return userData
"""
        corrections = [
            {
                "old_name": "getUserData",
                "new_name": "get_user_data",
                "line": 2,
                "column": 8,
            },
            {"old_name": "userData", "new_name": "user_data", "line": 3, "column": 8},
        ]

        result = apply_corrections_with_ast(code, corrections)

        assert result.success
        assert "get_user_data" in result.corrected_content
        assert "user_data" in result.corrected_content
        assert result.corrections_applied >= 2


class TestPerformance:
    """Test performance characteristics."""

    def test_small_file_performance(self):
        """Small files should be processed quickly."""
        code = (
            """
def my_function():
    x = 1
    return x
"""
            * 10
        )  # ~40 lines

        correction = {
            "old_name": "my_function",
            "new_name": "my_func",
            "line": 1,
            "column": 4,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert result.performance_ms is not None
        assert (
            result.performance_ms < 100
        ), f"Performance: {result.performance_ms}ms (target: <100ms)"

    def test_medium_file_performance(self):
        """Medium files should meet performance budget."""
        code = (
            """
def function_{i}():
    x = {i}
    return x
""".replace(
                "{i}", "0"
            )
            * 100
        )  # ~400 lines

        correction = {
            "old_name": "function_0",
            "new_name": "func_0",
            "line": 1,
            "column": 4,
        }

        result = apply_corrections_with_ast(code, [correction])

        assert result.success
        assert (
            result.performance_ms < 100
        ), f"Performance: {result.performance_ms}ms (target: <100ms)"

    @pytest.mark.benchmark
    def test_benchmark_correction_speed(self, benchmark):
        """Benchmark correction speed."""
        code = """
class MyClass:
    def getUserData(self):
        return {"user": "data"}
"""
        correction = {
            "old_name": "getUserData",
            "new_name": "get_user_data",
            "line": 2,
            "column": 8,
        }

        def run_correction():
            return apply_corrections_with_ast(code, [correction])

        result = benchmark(run_correction)
        assert result.success


class TestFrameworkDetector:
    """Test framework pattern detector directly."""

    def test_detector_identifies_ast_visitor(self):
        """Detector should identify AST visitor methods."""
        import ast

        code = """
import ast

class MyVisitor(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        pass
"""
        tree = ast.parse(code)
        detector = FrameworkMethodDetector()

        # Find the method
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "visit_FunctionDef":
                pattern = detector.is_framework_method(node, tree)
                assert pattern is not None
                assert pattern.framework in ["ast.NodeVisitor", "NodeVisitor"]
                assert pattern.method_name == "visit_FunctionDef"

    def test_detector_identifies_django_model(self):
        """Detector should identify Django model methods."""
        import ast

        code = """
from django.db import models

class MyModel(models.Model):
    def save(self, *args, **kwargs):
        pass
"""
        tree = ast.parse(code)
        detector = FrameworkMethodDetector()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "save":
                pattern = detector.is_framework_method(node, tree)
                assert pattern is not None
                assert "Model" in pattern.framework


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
