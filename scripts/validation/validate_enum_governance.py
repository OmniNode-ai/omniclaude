#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Enum Governance Validator for OmniClaude

This module wraps the omnibase_core enum governance validator to enforce:
- ENUM_001: Member casing enforcement (UPPER_SNAKE_CASE)
- ENUM_002: Literal type alias detection (suggest Enum conversion)
- ENUM_003: Duplicate enum value detection across files

Usage:
    # Validate default paths (src/omniclaude/)
    python scripts/validation/validate_enum_governance.py

    # Validate specific paths
    python scripts/validation/validate_enum_governance.py src/omniclaude/hooks/

    # Verbose output
    python scripts/validation/validate_enum_governance.py -v

Dependencies:
    - omnibase_core.validation.checker_enum_governance (from omnibase-core package)

See Also:
    - https://github.com/OmniNode/omnibase_core for validator documentation
    - src/omnibase_core/validation/checker_enum_governance.py for implementation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

# Import the omnibase_core enum governance validator
try:
    from omnibase_core.validation.checker_enum_governance import CheckerEnumGovernance
except ImportError as e:
    print(
        "Error: omnibase-core package not installed or CheckerEnumGovernance not available.",
        file=sys.stderr,
    )
    print(f"Import error: {e}", file=sys.stderr)
    print(
        "\nInstall omnibase-core with: uv add omnibase-core>=0.9.5",
        file=sys.stderr,
    )
    sys.exit(1)

# =============================================================================
# Constants
# =============================================================================

# Default directories to scan
DEFAULT_SCAN_PATHS: Final[list[str]] = ["src/omniclaude/"]

# Directories to exclude from scanning (passed to validator)
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


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point for the enum governance validator.

    Returns:
        Exit code: 0 if no violations, 1 if violations found or error occurred.
    """
    parser = argparse.ArgumentParser(
        description="Validate enum governance rules in Python files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Scan default paths (src/omniclaude/)
  %(prog)s src/omniclaude/hooks/     # Scan specific directory
  %(prog)s -v                        # Verbose output

Rules enforced:
  ENUM_001 - Enum member casing (UPPER_SNAKE_CASE required)
             Example: ACTIVE, IN_PROGRESS, HTTP_ERROR
             Bad: active, inProgress, HttpError

  ENUM_002 - Literal type aliases that should be Enums
             Flags Literal["a", "b", "c"] patterns with 3+ values
             that match status/type vocabulary

  ENUM_003 - Duplicate enum values across files
             Detects when multiple enums share the same string values

Excluded directories:
  lib/, _archive/, __pycache__, .git, .venv, .pytest_cache, etc.

This validator uses omnibase_core.validation.checker_enum_governance.
""",
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=DEFAULT_SCAN_PATHS,
        help="Paths to scan (files or directories). Default: src/omniclaude/",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output: show detailed progress",
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
        print("Enum Governance Validation (ONEX)")
        print("=" * 40)
        print()
        print(f"Scanning: {', '.join(str(p) for p in scan_paths)}")
        print()

    # Create and run the validator
    try:
        validator = CheckerEnumGovernance()
        result = validator.validate(scan_paths)
    except Exception as e:
        print(f"Error running validator: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1

    # Print results
    if not result.is_valid:
        # Print each issue
        for issue in result.issues:
            # Format: file:line: [severity] rule_name - message
            severity_str = (
                issue.severity.upper() if hasattr(issue, "severity") else "ERROR"
            )
            file_path = issue.file_path if hasattr(issue, "file_path") else "unknown"
            line_num = issue.line_number if hasattr(issue, "line_number") else 0
            rule_name = issue.rule_name if hasattr(issue, "rule_name") else issue.code
            message = issue.message if hasattr(issue, "message") else str(issue)

            print(f"{file_path}:{line_num}: [{severity_str}] {rule_name}")
            print(f"    {message}")

            # Print suggestion if available
            if hasattr(issue, "suggestion") and issue.suggestion:
                print(f"    Suggestion: {issue.suggestion}")
            print()

        if not args.quiet:
            print("-" * 40)
            print(f"Found {len(result.issues)} enum governance violation(s)")
            print()
            print("Fix suggestions:")
            print("  1. Rename enum members to UPPER_SNAKE_CASE")
            print("  2. Convert Literal type aliases to proper Enum classes")
            print("  3. Consolidate duplicate enum values into shared enums")

        return 1
    else:
        if not args.quiet:
            print("[PASS] All enum definitions follow governance rules")
            print()

            # Print validation metadata if available
            if hasattr(result, "metadata") and result.metadata:
                metadata = result.metadata
                # Handle both dict-like and Pydantic model metadata
                if hasattr(metadata, "files_checked"):
                    files_checked = metadata.files_checked
                    duration_ms = getattr(metadata, "duration_ms", 0)
                elif hasattr(metadata, "get"):
                    files_checked = metadata.get("files_checked", [])
                    duration_ms = metadata.get("duration_ms", 0)
                else:
                    files_checked = []
                    duration_ms = 0
                if files_checked:
                    print(f"Checked {len(files_checked)} files in {duration_ms}ms")

        return 0


if __name__ == "__main__":
    sys.exit(main())
