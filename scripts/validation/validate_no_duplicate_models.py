#!/usr/bin/env python3
"""
Duplicate Model Filename Validator for OmniClaude

Detects duplicate Python filenames across different directories in src/omniclaude/.
This prevents import ambiguity and naming conflicts in the codebase.

Example: If both `src/omniclaude/hooks/schemas.py` and `src/omniclaude/models/schemas.py`
exist, this script will flag them as duplicates.

Exclusions:
- __init__.py (expected to exist in every package)
- conftest.py (pytest configuration files)
- test_*.py files (test files may have duplicates)
- Files in lib/ directory (utility modules)
- Files in _archive/ directory (archived code)

Usage:
    python scripts/validation/validate_no_duplicate_models.py
    python scripts/validation/validate_no_duplicate_models.py --help

Exit Codes:
    0 - No duplicate filenames found
    1 - Duplicate filenames detected

Adapted from omnibase_core validation patterns for OMN-1558.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Final

# Constants
SRC_DIR: Final[str] = "src/omniclaude"

# Files to always exclude (expected duplicates)
EXCLUDED_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "__init__.py",
        "conftest.py",
    }
)

# Directory patterns to exclude
EXCLUDED_DIR_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "lib",
        "_archive",
        "__pycache__",
        ".pytest_cache",
    }
)


def is_excluded_directory(path: Path) -> bool:
    """Check if any parent directory matches exclusion patterns."""
    for part in path.parts:
        if part in EXCLUDED_DIR_PATTERNS:
            return True
    return False


def is_test_file(filename: str) -> bool:
    """Check if filename is a test file."""
    return filename.startswith("test_") or filename.endswith("_test.py")


def collect_python_files(root_dir: Path) -> dict[str, list[Path]]:
    """Collect all Python files grouped by filename.

    Args:
        root_dir: Root directory to scan

    Returns:
        Dictionary mapping filename to list of full paths
    """
    files_by_name: dict[str, list[Path]] = defaultdict(list)

    if not root_dir.exists():
        return files_by_name

    for py_file in root_dir.rglob("*.py"):
        # Skip excluded directories
        if is_excluded_directory(py_file.relative_to(root_dir)):
            continue

        filename = py_file.name

        # Skip excluded filenames
        if filename in EXCLUDED_FILENAMES:
            continue

        # Skip test files
        if is_test_file(filename):
            continue

        files_by_name[filename].append(py_file)

    return files_by_name


def find_duplicates(files_by_name: dict[str, list[Path]]) -> dict[str, list[Path]]:
    """Find filenames that appear in multiple directories.

    Args:
        files_by_name: Dictionary mapping filename to list of paths

    Returns:
        Dictionary containing only filenames with duplicates
    """
    return {
        filename: paths for filename, paths in files_by_name.items() if len(paths) > 1
    }


def print_report(duplicates: dict[str, list[Path]], root_dir: Path) -> None:
    """Print a formatted report of duplicate filenames.

    Args:
        duplicates: Dictionary of duplicate filenames and their paths
        root_dir: Root directory for relative path display
    """
    print("Duplicate Model Check")
    print("=====================")
    print()

    if not duplicates:
        print("No duplicate filenames found.")
        print()
        return

    for filename in sorted(duplicates.keys()):
        paths = duplicates[filename]
        print(f"DUPLICATE: {filename}")
        for path in sorted(paths):
            try:
                rel_path = path.relative_to(root_dir.parent)
            except ValueError:
                rel_path = path
            print(f"   - {rel_path}")
        print()

    print(f"Found {len(duplicates)} duplicate filename(s)")


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for duplicates found)
    """
    parser = argparse.ArgumentParser(
        description="Detect duplicate Python filenames in src/omniclaude/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                  Check for duplicate filenames
  %(prog)s --help           Show this help message

Exclusions:
  - __init__.py, conftest.py (common files)
  - test_*.py, *_test.py (test files)
  - Files in lib/ directory
  - Files in _archive/ directory
""",
    )
    parser.parse_args()

    # Determine project root
    script_path = Path(__file__).resolve()
    # Navigate from scripts/validation/ to project root
    project_root = script_path.parent.parent.parent
    src_dir = project_root / SRC_DIR

    if not src_dir.exists():
        print(f"Error: Source directory not found: {src_dir}", file=sys.stderr)
        return 1

    # Collect and analyze files
    files_by_name = collect_python_files(src_dir)
    duplicates = find_duplicates(files_by_name)

    # Print report
    print_report(duplicates, src_dir)

    # Return appropriate exit code
    return 1 if duplicates else 0


if __name__ == "__main__":
    sys.exit(main())
