#!/usr/bin/env python3
"""
Pydantic Pattern Validator for OmniClaude

Validates that Pydantic models follow established conventions:
1. Models must have frozen=True (immutability)
2. Models must use extra="forbid" or extra="ignore" (not "allow")
3. Fields must have explicit type annotations
4. Fields should avoid using Any type (warning)
5. Model classes should have docstrings

Uses AST parsing for reliable detection without importing modules.

Adapted from omnibase_core validation patterns.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final


class ViolationSeverity(StrEnum):
    """Severity levels for validation violations."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    """Represents a Pydantic pattern violation."""

    file_path: str
    line_number: int
    model_name: str
    severity: ViolationSeverity
    message: str


# Constants
DEFAULT_SCAN_PATHS: Final[list[str]] = ["src/omniclaude/"]
EXCLUDED_DIRS: Final[set[str]] = {"lib", "_archive", "__pycache__", ".git"}
ALLOWED_EXTRA_VALUES: Final[set[str]] = {"forbid", "ignore"}


class PydanticPatternChecker(ast.NodeVisitor):
    """AST visitor that checks Pydantic model patterns."""

    def __init__(self, file_path: str, source_lines: list[str]) -> None:
        """Initialize the checker.

        Args:
            file_path: Path to the file being checked.
            source_lines: Source code lines for context extraction.
        """
        self.file_path = file_path
        self.source_lines = source_lines
        self.violations: list[Violation] = []
        self._basemodel_aliases: set[str] = {"BaseModel"}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Track BaseModel imports to handle aliasing."""
        if node.module and "pydantic" in node.module:
            for alias in node.names:
                if alias.name == "BaseModel":
                    # Track the alias name (e.g., from pydantic import BaseModel as BM)
                    name = alias.asname if alias.asname else alias.name
                    self._basemodel_aliases.add(name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definitions to check for Pydantic model patterns."""
        if not self._is_pydantic_model(node):
            self.generic_visit(node)
            return

        # Check for docstring
        self._check_docstring(node)

        # Check for model_config with frozen=True and extra setting
        self._check_model_config(node)

        # Check field type annotations
        self._check_field_annotations(node)

        self.generic_visit(node)

    def _is_pydantic_model(self, node: ast.ClassDef) -> bool:
        """Check if the class inherits from BaseModel (directly or via alias)."""
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in self._basemodel_aliases:
                return True
            # Handle attribute access like pydantic.BaseModel
            if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                return True
        return False

    def _check_docstring(self, node: ast.ClassDef) -> None:
        """Check if the model class has a docstring."""
        docstring = ast.get_docstring(node)
        if not docstring:
            self.violations.append(
                Violation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    model_name=node.name,
                    severity=ViolationSeverity.WARNING,
                    message=f"Model '{node.name}' missing docstring",
                )
            )

    def _check_model_config(self, node: ast.ClassDef) -> None:
        """Check model_config for frozen=True and extra setting."""
        found_model_config = False
        found_frozen = False
        found_extra = False
        extra_value: str | None = None

        for item in node.body:
            # Check for model_config = ConfigDict(...)
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id == "model_config":
                    found_model_config = True
                    if item.value:
                        frozen, extra = self._extract_config_dict_values(item.value)
                        found_frozen = frozen is True
                        if extra is not None:
                            found_extra = True
                            extra_value = extra

            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "model_config":
                        found_model_config = True
                        if item.value:
                            frozen, extra = self._extract_config_dict_values(item.value)
                            found_frozen = frozen is True
                            if extra is not None:
                                found_extra = True
                                extra_value = extra

            # Check for inner Config class (older Pydantic v1 style)
            elif isinstance(item, ast.ClassDef) and item.name == "Config":
                found_model_config = True
                for config_item in item.body:
                    if isinstance(config_item, ast.Assign):
                        for target in config_item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == "frozen":
                                    value = self._get_constant_value(config_item.value)
                                    found_frozen = value is True
                                elif target.id == "extra":
                                    value = self._get_constant_value(config_item.value)
                                    if value is not None:
                                        found_extra = True
                                        extra_value = str(value)

        if not found_model_config:
            self.violations.append(
                Violation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    model_name=node.name,
                    severity=ViolationSeverity.WARNING,
                    message=f"Model '{node.name}' missing model_config",
                )
            )
            return

        if not found_frozen:
            self.violations.append(
                Violation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    model_name=node.name,
                    severity=ViolationSeverity.WARNING,
                    message=f"Model '{node.name}' missing frozen=True",
                )
            )

        if found_extra and extra_value and extra_value not in ALLOWED_EXTRA_VALUES:
            self.violations.append(
                Violation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    model_name=node.name,
                    severity=ViolationSeverity.ERROR,
                    message=f'Model \'{node.name}\' uses extra="{extra_value}" (should be "forbid" or "ignore")',
                )
            )

    def _extract_config_dict_values(
        self, node: ast.expr
    ) -> tuple[bool | None, str | None]:
        """Extract frozen and extra values from ConfigDict() call."""
        frozen: bool | None = None
        extra: str | None = None

        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "frozen":
                    value = self._get_constant_value(keyword.value)
                    frozen = value is True
                elif keyword.arg == "extra":
                    value = self._get_constant_value(keyword.value)
                    if value is not None:
                        extra = str(value)

        return frozen, extra

    def _get_constant_value(self, node: ast.expr) -> object:
        """Extract constant value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.NameConstant):  # Python 3.7 compatibility
            return node.value
        if isinstance(node, ast.Str):  # Python 3.7 compatibility
            return node.s
        return None

    def _check_field_annotations(self, node: ast.ClassDef) -> None:
        """Check that all fields have explicit type annotations."""
        for item in node.body:
            # Check for class-level assignments without annotations
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        # Skip private/dunder attributes and model_config
                        if (
                            target.id.startswith("_")
                            or target.id == "model_config"
                            or target.id == "__all__"
                        ):
                            continue

                        # Check if this might be a Field() assignment without annotation
                        if self._is_field_call(item.value):
                            self.violations.append(
                                Violation(
                                    file_path=self.file_path,
                                    line_number=item.lineno,
                                    model_name=node.name,
                                    severity=ViolationSeverity.ERROR,
                                    message=f"Field '{target.id}' in model '{node.name}' missing type annotation",
                                )
                            )

            # Check annotated assignments for Any type
            elif isinstance(item, ast.AnnAssign) and item.target:
                if isinstance(item.target, ast.Name):
                    # Skip model_config
                    if item.target.id == "model_config":
                        continue

                    # Check if annotation contains Any
                    if self._contains_any_type(item.annotation):
                        self.violations.append(
                            Violation(
                                file_path=self.file_path,
                                line_number=item.lineno,
                                model_name=node.name,
                                severity=ViolationSeverity.WARNING,
                                message=f"Field '{item.target.id}' in model '{node.name}' uses Any type",
                            )
                        )

    def _is_field_call(self, node: ast.expr) -> bool:
        """Check if the node is a Field() call."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "Field":
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == "Field":
                return True
        return False

    def _contains_any_type(self, node: ast.expr) -> bool:
        """Check if the type annotation contains Any."""
        if isinstance(node, ast.Name) and node.id == "Any":
            return True
        if isinstance(node, ast.Subscript):
            # Check container types like list[Any], dict[str, Any]
            return self._contains_any_type(node.slice)
        if isinstance(node, ast.Tuple):
            return any(self._contains_any_type(elt) for elt in node.elts)
        if isinstance(node, ast.BinOp):
            # Handle Union types with | operator (X | Any)
            return self._contains_any_type(node.left) or self._contains_any_type(
                node.right
            )
        if isinstance(node, ast.Attribute):
            # Handle typing.Any
            if node.attr == "Any":
                return True
        return False


def should_scan_file(file_path: Path, base_path: Path) -> bool:
    """Determine if a file should be scanned.

    Args:
        file_path: Path to the file to check.
        base_path: Base path for relative path calculation.

    Returns:
        True if the file should be scanned, False otherwise.
    """
    # Get relative path parts
    try:
        rel_path = file_path.relative_to(base_path)
    except ValueError:
        rel_path = file_path

    # Check if any excluded directory is in the path
    for part in rel_path.parts:
        if part in EXCLUDED_DIRS:
            return False

    return True


def scan_file(file_path: Path) -> list[Violation]:
    """Scan a single Python file for Pydantic pattern violations.

    Args:
        file_path: Path to the Python file.

    Returns:
        List of violations found in the file.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
        return []

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError as e:
        print(f"Warning: Syntax error in {file_path}: {e}", file=sys.stderr)
        return []

    source_lines = content.splitlines()
    checker = PydanticPatternChecker(str(file_path), source_lines)
    checker.visit(tree)

    return checker.violations


def scan_directory(path: Path, base_path: Path) -> list[Violation]:
    """Recursively scan a directory for Pydantic pattern violations.

    Args:
        path: Directory path to scan.
        base_path: Base path for relative path calculation.

    Returns:
        List of violations found in all Python files.
    """
    violations: list[Violation] = []

    for item in sorted(path.iterdir()):
        if item.is_dir():
            if item.name not in EXCLUDED_DIRS:
                violations.extend(scan_directory(item, base_path))
        elif item.is_file() and item.suffix == ".py":
            if should_scan_file(item, base_path):
                violations.extend(scan_file(item))

    return violations


def format_violation(violation: Violation) -> str:
    """Format a violation for display.

    Args:
        violation: The violation to format.

    Returns:
        Formatted string representation of the violation.
    """
    icon = "X" if violation.severity == ViolationSeverity.ERROR else "!"
    return f"  [{icon}] {violation.message}"


def main() -> int:
    """Main entry point for the validator.

    Returns:
        Exit code: 0 = no issues, 1 = errors found, 2 = warnings only (non-strict).
    """
    parser = argparse.ArgumentParser(
        description="Validate Pydantic model patterns in Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  No issues found
  1  Errors found
  2  Warnings only (non-strict mode)

Examples:
  %(prog)s                           # Scan default paths (src/omniclaude/)
  %(prog)s src/omniclaude/hooks/     # Scan specific directory
  %(prog)s --strict                  # Fail on warnings too
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=DEFAULT_SCAN_PATHS,
        help="Paths to scan (default: src/omniclaude/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings too (exit code 1)",
    )

    args = parser.parse_args()

    print("Pydantic Pattern Validation")
    print("=" * 27)
    print()

    all_violations: list[Violation] = []
    base_path = Path.cwd()

    for scan_path in args.paths:
        path = Path(scan_path)
        if not path.exists():
            print(f"Warning: Path does not exist: {scan_path}", file=sys.stderr)
            continue

        if path.is_file():
            all_violations.extend(scan_file(path))
        elif path.is_dir():
            all_violations.extend(scan_directory(path, base_path))

    # Group violations by file
    violations_by_file: dict[str, list[Violation]] = {}
    for v in all_violations:
        if v.file_path not in violations_by_file:
            violations_by_file[v.file_path] = []
        violations_by_file[v.file_path].append(v)

    # Count errors and warnings
    error_count = sum(
        1 for v in all_violations if v.severity == ViolationSeverity.ERROR
    )
    warning_count = sum(
        1 for v in all_violations if v.severity == ViolationSeverity.WARNING
    )

    # Print violations
    if violations_by_file:
        for file_path in sorted(violations_by_file.keys()):
            file_violations = violations_by_file[file_path]
            # Sort by line number
            file_violations.sort(key=lambda v: v.line_number)
            for v in file_violations:
                print(f"{v.file_path}:{v.line_number}")
                print(format_violation(v))
                print()

    # Print summary
    if error_count == 0 and warning_count == 0:
        print("No issues found.")
        return 0

    summary_parts = []
    if error_count > 0:
        summary_parts.append(f"{error_count} error(s)")
    if warning_count > 0:
        summary_parts.append(f"{warning_count} warning(s)")

    print(f"Found {', '.join(summary_parts)}")

    # Determine exit code
    if error_count > 0:
        return 1
    if warning_count > 0 and args.strict:
        return 1
    if warning_count > 0:
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
