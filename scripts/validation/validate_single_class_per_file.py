#!/usr/bin/env python3
"""
Single Class Per File Validator for OmniClaude

Validates that Python files follow the single-class-per-file architecture pattern,
which improves code organization, discoverability, and maintainability.

Rules:
1. Each Python file should contain at most one public class (no underscore prefix)
2. Private classes (prefixed with _) are allowed alongside a public class
3. Enums are allowed as companion types (they define related constants)
4. Exceptions (ending in Error/Exception) are allowed as companions
5. Dataclasses used as data transfer objects are allowed as companions
6. Pydantic models (BaseModel) are allowed together (schemas/DTOs)
7. NamedTuples are allowed as companion types

Exclusions:
- __init__.py files (often have re-exports)
- Test files (test_*.py, *_test.py)
- Files in lib/, _archive/ directories

Adapted from omnibase_core architecture validation patterns.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

# =============================================================================
# Constants
# =============================================================================

# Default directories to scan
DEFAULT_SCAN_PATHS: Final[list[str]] = ["src/omniclaude/"]

# Directories to exclude from scanning
EXCLUDED_DIRS: Final[set[str]] = {
    "lib",
    "_archive",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# File patterns to exclude
EXCLUDED_FILE_PATTERNS: Final[list[str]] = [
    "__init__.py",
    "test_*.py",
    "*_test.py",
    "conftest.py",
]


# =============================================================================
# Data Classes
# =============================================================================


class ClassCategory(Enum):
    """Categories of class definitions for validation purposes."""

    PUBLIC = "public"
    PRIVATE = "private"
    ENUM = "enum"
    EXCEPTION = "exception"
    DATACLASS = "dataclass"
    PYDANTIC_MODEL = "pydantic_model"
    NAMED_TUPLE = "named_tuple"
    PROTOCOL = "protocol"
    TYPED_DICT = "typed_dict"


@dataclass(frozen=True)
class ClassInfo:
    """Information about a class definition in a file."""

    name: str
    line_number: int
    category: ClassCategory
    base_classes: tuple[str, ...]


@dataclass(frozen=True)
class FileViolation:
    """Represents a single-class-per-file violation."""

    file_path: Path
    public_classes: list[ClassInfo]
    all_classes: list[ClassInfo]

    @property
    def public_class_names(self) -> list[str]:
        """Get names of all public classes."""
        return [c.name for c in self.public_classes]


# =============================================================================
# AST Analysis
# =============================================================================


def _get_base_class_names(node: ast.ClassDef) -> tuple[str, ...]:
    """Extract base class names from a class definition."""
    base_names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            base_names.append(base.id)
        elif isinstance(base, ast.Attribute):
            # Handle qualified names like typing.Protocol
            parts: list[str] = []
            current = base
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value  # type: ignore[assignment]
            if isinstance(current, ast.Name):
                parts.append(current.id)
            base_names.append(".".join(reversed(parts)))
        elif isinstance(base, ast.Subscript):
            # Handle Generic[T], Protocol[T], etc.
            if isinstance(base.value, ast.Name):
                base_names.append(base.value.id)
            elif isinstance(base.value, ast.Attribute):
                parts = []
                current = base.value
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value  # type: ignore[assignment]
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                base_names.append(".".join(reversed(parts)))
    return tuple(base_names)


def _has_decorator(node: ast.ClassDef, decorator_name: str) -> bool:
    """Check if a class has a specific decorator."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == decorator_name:
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == decorator_name:
            return True
        if isinstance(decorator, ast.Call):
            if (
                isinstance(decorator.func, ast.Name)
                and decorator.func.id == decorator_name
            ):
                return True
            if (
                isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == decorator_name
            ):
                return True
    return False


def _categorize_class(node: ast.ClassDef) -> ClassCategory:
    """Determine the category of a class definition."""
    base_names = _get_base_class_names(node)

    # Check for private class (underscore prefix)
    if node.name.startswith("_"):
        return ClassCategory.PRIVATE

    # Check for Enum (inherits from Enum, IntEnum, StrEnum, Flag, IntFlag)
    enum_bases = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
    if any(base.split(".")[-1] in enum_bases for base in base_names):
        return ClassCategory.ENUM

    # Check for Exception (inherits from Exception/Error or name ends with Error/Exception)
    exception_bases = {"Exception", "BaseException", "Error"}
    if any(base.split(".")[-1] in exception_bases for base in base_names):
        return ClassCategory.EXCEPTION
    if node.name.endswith("Error") or node.name.endswith("Exception"):
        return ClassCategory.EXCEPTION

    # Check for Protocol (inherits from Protocol or typing.Protocol)
    if any("Protocol" in base for base in base_names):
        return ClassCategory.PROTOCOL

    # Check for TypedDict (inherits from TypedDict or typing.TypedDict)
    if any("TypedDict" in base for base in base_names):
        return ClassCategory.TYPED_DICT

    # Check for Pydantic BaseModel (inherits from BaseModel or pydantic.BaseModel)
    pydantic_bases = {"BaseModel", "pydantic.BaseModel"}
    if any(base.split(".")[-1] == "BaseModel" for base in base_names):
        return ClassCategory.PYDANTIC_MODEL

    # Check for NamedTuple (inherits from NamedTuple or typing.NamedTuple)
    if any("NamedTuple" in base for base in base_names):
        return ClassCategory.NAMED_TUPLE

    # Check for dataclass decorator
    if _has_decorator(node, "dataclass"):
        return ClassCategory.DATACLASS

    # Default to public class
    return ClassCategory.PUBLIC


def analyze_file(file_path: Path) -> list[ClassInfo]:
    """Analyze a Python file and extract class information.

    Args:
        file_path: Path to the Python file to analyze.

    Returns:
        List of ClassInfo objects for all top-level classes in the file.

    Raises:
        SyntaxError: If the file contains invalid Python syntax.
    """
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(file_path))

    classes: list[ClassInfo] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            category = _categorize_class(node)
            base_names = _get_base_class_names(node)
            classes.append(
                ClassInfo(
                    name=node.name,
                    line_number=node.lineno,
                    category=category,
                    base_classes=base_names,
                )
            )

    return classes


# =============================================================================
# Validation Logic
# =============================================================================


def _should_exclude_file(file_path: Path) -> bool:
    """Check if a file should be excluded from validation."""
    # Check excluded directories
    for part in file_path.parts:
        if part in EXCLUDED_DIRS:
            return True

    # Check excluded file patterns
    file_name = file_path.name
    for pattern in EXCLUDED_FILE_PATTERNS:
        if pattern.startswith("*"):
            if file_name.endswith(pattern[1:]):
                return True
        elif pattern.endswith("*"):
            if file_name.startswith(pattern[:-1]):
                return True
        elif file_name == pattern:
            return True

    return False


def validate_file(file_path: Path, strict: bool = False) -> FileViolation | None:
    """Validate a single file for the single-class-per-file rule.

    Args:
        file_path: Path to the Python file to validate.
        strict: If True, enforce exactly one class per file (no exceptions).

    Returns:
        FileViolation if the file violates the rule, None otherwise.
    """
    if _should_exclude_file(file_path):
        return None

    try:
        classes = analyze_file(file_path)
    except SyntaxError:
        # Skip files with syntax errors (they'll fail elsewhere)
        return None
    except UnicodeDecodeError:
        # Skip binary files or files with encoding issues
        return None

    if not classes:
        return None  # No classes, no violation

    if strict:
        # Strict mode: exactly one class per file
        if len(classes) > 1:
            return FileViolation(
                file_path=file_path,
                public_classes=classes,
                all_classes=classes,
            )
    else:
        # Normal mode: filter to only public classes
        public_classes = [c for c in classes if c.category == ClassCategory.PUBLIC]

        if len(public_classes) > 1:
            return FileViolation(
                file_path=file_path,
                public_classes=public_classes,
                all_classes=classes,
            )

    return None


def find_python_files(scan_paths: list[Path]) -> list[Path]:
    """Find all Python files in the given paths.

    Args:
        scan_paths: List of paths to scan (files or directories).

    Returns:
        List of Python file paths sorted alphabetically.
    """
    python_files: list[Path] = []

    for scan_path in scan_paths:
        if scan_path.is_file() and scan_path.suffix == ".py":
            python_files.append(scan_path)
        elif scan_path.is_dir():
            for py_file in scan_path.rglob("*.py"):
                if py_file.is_file():
                    python_files.append(py_file)

    return sorted(set(python_files))


def validate_paths(
    scan_paths: list[Path],
    strict: bool = False,
    verbose: bool = False,
) -> list[FileViolation]:
    """Validate all Python files in the given paths.

    Args:
        scan_paths: List of paths to scan.
        strict: If True, enforce exactly one class per file.
        verbose: If True, print progress information.

    Returns:
        List of FileViolation objects for files that violate the rule.
    """
    python_files = find_python_files(scan_paths)
    violations: list[FileViolation] = []

    for file_path in python_files:
        if verbose:
            print(f"  Scanning: {file_path}")

        violation = validate_file(file_path, strict=strict)
        if violation:
            violations.append(violation)

    return violations


# =============================================================================
# Output Formatting
# =============================================================================


def format_violation(violation: FileViolation, base_path: Path | None = None) -> str:
    """Format a violation for display.

    Args:
        violation: The violation to format.
        base_path: Optional base path to make paths relative.

    Returns:
        Formatted violation string.
    """
    file_path = violation.file_path
    if base_path:
        try:
            file_path = file_path.relative_to(base_path)
        except ValueError:
            pass  # Keep absolute path if not relative to base

    lines: list[str] = []
    lines.append(f"  {file_path}")

    # List public classes
    class_names = ", ".join(violation.public_class_names)
    lines.append(
        f"     Contains {len(violation.public_classes)} public classes: {class_names}"
    )

    # Show class details
    for cls in violation.public_classes:
        bases = f" ({', '.join(cls.base_classes)})" if cls.base_classes else ""
        lines.append(f"       - {cls.name}{bases} (line {cls.line_number})")

    # Suggestion
    if len(violation.public_classes) == 2:
        lines.append(
            f"     Consider: Move {violation.public_classes[1].name} to its own file"
        )
    else:
        lines.append("     Consider: Split into separate files, one class per file")

    return "\n".join(lines)


def format_summary(all_classes: list[ClassInfo]) -> str:
    """Format a summary of class categories found.

    Args:
        all_classes: List of all classes found.

    Returns:
        Formatted summary string.
    """
    by_category: dict[ClassCategory, int] = {}
    for cls in all_classes:
        by_category[cls.category] = by_category.get(cls.category, 0) + 1

    parts: list[str] = []
    for category in ClassCategory:
        count = by_category.get(category, 0)
        if count > 0:
            parts.append(f"{category.value}: {count}")

    return ", ".join(parts)


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point for the validator.

    Returns:
        Exit code: 0 if no violations, 1 if violations found.
    """
    parser = argparse.ArgumentParser(
        description="Validate single-class-per-file architecture in Python files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Scan default paths (src/omniclaude/)
  %(prog)s src/omniclaude/hooks/     # Scan specific directory
  %(prog)s --strict                  # No exceptions, exactly 1 class per file
  %(prog)s --verbose                 # Show all files being scanned

Allowed exceptions (in normal mode):
  - Private classes (prefixed with _)
  - Enums (inherit from Enum, IntEnum, StrEnum, etc.)
  - Exceptions (inherit from Exception or name ends with Error/Exception)
  - Protocols (inherit from Protocol)
  - TypedDicts (inherit from TypedDict)
  - Pydantic models (inherit from BaseModel)
  - NamedTuples (inherit from NamedTuple)
  - Dataclasses (decorated with @dataclass)

Excluded files:
  - __init__.py (re-exports)
  - test_*.py, *_test.py (test files)
  - Files in lib/, _archive/ directories
""",
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=DEFAULT_SCAN_PATHS,
        help="Paths to scan (files or directories). Default: src/omniclaude/",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: no exceptions, exactly one class per file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output: show all files being scanned",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Quiet mode: only show violations (no header/summary)",
    )

    args = parser.parse_args()

    # Convert paths to Path objects, resolving relative to cwd
    cwd = Path.cwd()
    scan_paths: list[Path] = []
    for path_str in args.paths:
        path = Path(path_str)
        if not path.is_absolute():
            path = cwd / path
        if path.exists():
            scan_paths.append(path)
        else:
            print(f"Warning: Path does not exist: {path}", file=sys.stderr)

    if not scan_paths:
        print("Error: No valid paths to scan", file=sys.stderr)
        return 1

    # Print header
    if not args.quiet:
        print("Single Class Per File Validation")
        print("=" * 35)
        print()
        mode = "strict" if args.strict else "normal"
        print(f"Mode: {mode}")
        print(f"Scanning: {', '.join(str(p) for p in scan_paths)}")
        print()

    # Run validation
    violations = validate_paths(scan_paths, strict=args.strict, verbose=args.verbose)

    # Print results
    if violations:
        for violation in violations:
            print(f"[FAIL] {violation.file_path}")
            print(format_violation(violation, base_path=cwd))
            print()

        if not args.quiet:
            print("-" * 35)
            print(f"Found {len(violations)} violation(s)")
            print()
            print("Fix suggestions:")
            print("  1. Move additional public classes to their own files")
            print("  2. Make helper classes private (prefix with _)")
            print("  3. Use composition instead of multiple classes")

        return 1
    else:
        if not args.quiet:
            print("[PASS] All files follow single-class-per-file pattern")
            print()

            # Count total files scanned
            python_files = find_python_files(scan_paths)
            excluded_count = sum(1 for f in python_files if _should_exclude_file(f))
            scanned_count = len(python_files) - excluded_count

            print(f"Scanned {scanned_count} files ({excluded_count} excluded)")

        return 0


if __name__ == "__main__":
    sys.exit(main())
