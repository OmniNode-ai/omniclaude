"""
Framework Method Pattern Detector

Identifies framework methods that should NOT be renamed to preserve framework contracts.

Supported Frameworks:
- Python AST Visitor Pattern (ast.NodeVisitor, ast.NodeTransformer)
- Django (models.Model, views.View, rest_framework)
- FastAPI (route decorators, dependency injection)
- Testing Frameworks (pytest, unittest)
- Python Magic Methods (__init__, __str__, etc.)

Author: Claude Code + Archon AI Quality Enforcer
Date: 2025-09-30
"""

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FrameworkPattern:
    """Represents a detected framework pattern."""

    framework: str  # e.g., "ast.NodeVisitor", "Django", "FastAPI"
    pattern_type: str  # e.g., "inheritance", "decorator", "magic_method"
    method_name: str  # e.g., "visit_FunctionDef", "save", "get"
    reason: str  # Human-readable explanation


class FrameworkMethodDetector:
    """
    Detect framework methods that should not be renamed.

    This prevents false positives where naming convention corrections
    would break framework contracts (e.g., renaming visit_FunctionDef
    to visit__function_def breaks Python AST visitor pattern).
    """

    # Framework base classes to detect
    FRAMEWORK_BASE_CLASSES = {
        # Python AST visitor pattern
        "ast.NodeVisitor",
        "ast.NodeTransformer",
        "NodeVisitor",
        "NodeTransformer",
        # Django ORM
        "models.Model",
        "Model",
        "django.db.models.Model",
        "django.db.models.base.Model",
        # Django views
        "View",
        "django.views.View",
        "django.views.generic.View",
        # Django REST framework
        "APIView",
        "rest_framework.views.APIView",
        "ViewSet",
        "rest_framework.viewsets.ViewSet",
        # Testing frameworks
        "unittest.TestCase",
        "TestCase",
    }

    # Framework decorators that indicate framework methods
    FRAMEWORK_DECORATORS = {
        # FastAPI
        "app.get",
        "app.post",
        "app.put",
        "app.delete",
        "app.patch",
        "app.options",
        "app.head",
        "router.get",
        "router.post",
        "router.put",
        "router.delete",
        "router.patch",
        # Django
        "csrf_exempt",
        "login_required",
        "permission_required",
        # pytest
        "pytest.fixture",
        "pytest.mark",
    }

    # Known framework method names by pattern
    FRAMEWORK_METHOD_PATTERNS = {
        # AST visitor pattern (visit_* methods)
        "ast.NodeVisitor": {"visit_", "generic_visit"},
        # Django model methods
        "models.Model": {
            "save",
            "delete",
            "clean",
            "clean_fields",
            "full_clean",
            "get_absolute_url",
            "get_deferred_fields",
            "refresh_from_db",
        },
        # Django view methods
        "View": {
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "head",
            "options",
            "dispatch",
        },
        # Django REST framework
        "APIView": {
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "list",
            "create",
            "retrieve",
            "update",
            "destroy",
        },
        # unittest
        "unittest.TestCase": {
            "setUp",
            "tearDown",
            "setUpClass",
            "tearDownClass",
            "setUpModule",
            "tearDownModule",
        },
    }

    def __init__(self):
        """Initialize the framework detector."""
        self.detected_patterns: list[FrameworkPattern] = []

    def is_framework_method(
        self, func_node: ast.FunctionDef, tree: ast.Module, file_path: str = ""
    ) -> FrameworkPattern | None:
        """
        Check if a function is a framework method that should not be renamed.

        Args:
            func_node: AST FunctionDef node to check
            tree: Full module AST for context
            file_path: Optional file path for logging

        Returns:
            FrameworkPattern if framework method detected, None otherwise
        """
        method_name = func_node.name

        # 1. Check for Python magic methods
        if method_name.startswith("__") and method_name.endswith("__"):
            pattern = FrameworkPattern(
                framework="Python",
                pattern_type="magic_method",
                method_name=method_name,
                reason="Python protocol/magic method (e.g., __init__, __str__)",
            )
            self.detected_patterns.append(pattern)
            return pattern

        # 2. Check for pytest test functions
        if method_name.startswith("test_"):
            parent_class = self._get_parent_class(func_node, tree)
            if parent_class is None:  # Top-level function
                pattern = FrameworkPattern(
                    framework="pytest",
                    pattern_type="naming_convention",
                    method_name=method_name,
                    reason="pytest test discovery pattern (test_* functions)",
                )
                self.detected_patterns.append(pattern)
                return pattern

        # 3. Check for framework decorators (FastAPI, Django, pytest)
        decorator_pattern = self._check_framework_decorators(func_node)
        if decorator_pattern:
            self.detected_patterns.append(decorator_pattern)
            return decorator_pattern

        # 4. Check for framework method via inheritance
        parent_class = self._get_parent_class(func_node, tree)
        if parent_class:
            inheritance_pattern = self._check_framework_inheritance(func_node, parent_class, tree)
            if inheritance_pattern:
                self.detected_patterns.append(inheritance_pattern)
                return inheritance_pattern

        return None

    def _check_framework_decorators(self, func_node: ast.FunctionDef) -> FrameworkPattern | None:
        """Check if function has framework decorators."""
        for decorator in func_node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)

            # Check against known framework decorators
            for fw_decorator in self.FRAMEWORK_DECORATORS:
                if fw_decorator in decorator_name:
                    return FrameworkPattern(
                        framework=self._infer_framework_from_decorator(fw_decorator),
                        pattern_type="decorator",
                        method_name=func_node.name,
                        reason=f"Decorated with @{decorator_name} (framework route/fixture)",
                    )

        return None

    def _check_framework_inheritance(
        self, func_node: ast.FunctionDef, class_node: ast.ClassDef, tree: ast.Module
    ) -> FrameworkPattern | None:
        """Check if function is a framework method via class inheritance."""
        # Get base class names
        base_classes = self._get_base_class_names(class_node)

        # Check each base class
        for base_class in base_classes:
            if base_class in self.FRAMEWORK_BASE_CLASSES:
                # Check if method name matches framework pattern
                framework_methods = self._get_framework_methods_for_base(base_class)

                method_name = func_node.name
                for pattern in framework_methods:
                    # Check for exact match or prefix match (e.g., visit_*)
                    if method_name == pattern or (
                        pattern.endswith("_") and method_name.startswith(pattern)
                    ):
                        return FrameworkPattern(
                            framework=base_class,
                            pattern_type="inheritance",
                            method_name=method_name,
                            reason=f"Overrides {base_class}.{method_name} (framework contract)",
                        )

        return None

    def _get_framework_methods_for_base(self, base_class: str) -> set[str]:
        """Get framework method patterns for a given base class."""
        # Check exact match first
        for framework_key, methods in self.FRAMEWORK_METHOD_PATTERNS.items():
            if base_class.endswith(framework_key) or framework_key in base_class:
                return methods

        return set()

    def _get_parent_class(
        self, func_node: ast.FunctionDef, tree: ast.Module
    ) -> ast.ClassDef | None:
        """Find the parent class of a function definition."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if func_node in node.body:
                    return node
        return None

    def _get_base_class_names(self, class_node: ast.ClassDef) -> list[str]:
        """Extract base class names from ClassDef node."""
        base_names = []

        for base in class_node.bases:
            base_name = self._get_base_name(base)
            if base_name:
                base_names.append(base_name)

        return base_names

    def _get_base_name(self, base: ast.expr) -> str | None:
        """Extract name from base class expression."""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            # Handle module.Class format
            parts: list[str] = []
            current: ast.expr = base
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return None

    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name from decorator node."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            # Handle @app.get format
            parts: list[str] = []
            current: ast.expr = decorator
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        elif isinstance(decorator, ast.Call):
            # Handle @decorator() format
            return self._get_decorator_name(decorator.func)
        return ""

    def _infer_framework_from_decorator(self, decorator: str) -> str:
        """Infer framework name from decorator pattern."""
        if "app." in decorator or "router." in decorator:
            return "FastAPI"
        elif "pytest" in decorator:
            return "pytest"
        elif any(
            django_dec in decorator
            for django_dec in ["csrf_exempt", "login_required", "permission_required"]
        ):
            return "Django"
        return "Unknown"

    def get_detected_patterns(self) -> list[FrameworkPattern]:
        """Get all detected framework patterns."""
        return self.detected_patterns

    def clear_patterns(self):
        """Clear detected patterns (for reuse)."""
        self.detected_patterns = []


# Convenience functions


def is_framework_method(func_node: ast.FunctionDef, tree: ast.Module, file_path: str = "") -> bool:
    """
    Convenience function to check if a method is a framework method.

    Args:
        func_node: Function AST node
        tree: Full module AST
        file_path: Optional file path

    Returns:
        True if framework method, False otherwise
    """
    detector = FrameworkMethodDetector()
    result = detector.is_framework_method(func_node, tree, file_path)
    return result is not None


def get_framework_pattern(
    func_node: ast.FunctionDef, tree: ast.Module, file_path: str = ""
) -> FrameworkPattern | None:
    """
    Get framework pattern information for a method.

    Args:
        func_node: Function AST node
        tree: Full module AST
        file_path: Optional file path

    Returns:
        FrameworkPattern if detected, None otherwise
    """
    detector = FrameworkMethodDetector()
    return detector.is_framework_method(func_node, tree, file_path)
