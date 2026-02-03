#!/usr/bin/env python3
"""ONEX validation script for pre-commit hook.

Runs ONEX-compliant validators from omnibase-core:
- ValidatorAnyType: Detect problematic Any type usage
- ValidatorPatterns: Enforce code quality patterns
- ValidatorNamingConvention: Enforce naming standards

Usage:
    # Validate specific files (pre-commit passes staged files)
    python scripts/validate_onex.py file1.py file2.py

    # Validate entire directory
    python scripts/validate_onex.py src/

    # Validate with strict mode (fail on warnings too)
    python scripts/validate_onex.py --strict src/

    # No arguments defaults to src/
    python scripts/validate_onex.py

Exit codes:
    0: All validations passed, or warnings only in non-strict mode
    1: Validation errors found, or any issues in --strict mode

Options:
    --strict    Fail on any validation issue (warnings or errors).
                Without this flag, only errors cause exit 1 (failure).
                Warnings-only returns exit 0 (non-blocking for pre-commit).
    --help, -h  Show this help message and exit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omnibase_core.validation import (
    ValidatorAnyType,
    ValidatorNamingConvention,
    ValidatorPatterns,
)

# Directories to exclude from validation
# lib/ contains legacy code marked for deletion post-Beta
EXCLUDE_PATTERNS = [
    "lib/",
    "_archive/",
    "__pycache__/",
    ".venv/",
    "cli/",  # CLI debugging tools use dynamic DB row types by design
]


def _should_exclude(path: Path) -> bool:
    """Check if a path should be excluded from validation.

    Args:
        path: Path to check

    Returns:
        True if the path matches any exclusion pattern
    """
    path_str = str(path)
    return any(pattern in path_str for pattern in EXCLUDE_PATTERNS)


def _is_error_severity(issue: object) -> bool:
    """Check if an issue has error-level severity.

    Args:
        issue: Validation issue object

    Returns:
        True if the issue is an error (not a warning), False otherwise.
        If severity cannot be determined, defaults to True (treat as error).
    """
    severity = getattr(issue, "severity", None)
    if severity is None:
        # If no severity attribute, treat as error (conservative default)
        return True

    # Handle both string and enum severity values
    # Enum str() gives "<EnumSeverity.ERROR: 'error'>" so we check for substring
    severity_str = str(severity).lower()
    return "error" in severity_str or "critical" in severity_str


def validate_paths(paths: list[Path], *, strict: bool = False) -> int:
    """Run ONEX validators on the specified paths.

    Args:
        paths: List of file or directory paths to validate.
        strict: If True, fail on any issue (warnings or errors).
                If False, only errors cause non-zero exit code.

    Returns:
        Exit code:
        - 0: No issues found, or warnings only in non-strict mode
        - 1: Validation errors found, or any issues in strict mode
    """
    validators = [
        ValidatorAnyType(),
        ValidatorPatterns(),
        ValidatorNamingConvention(),
    ]

    error_count = 0
    warning_count = 0
    skipped_count = 0

    for path in paths:
        if not path.exists():
            print(f"Warning: Path '{path}' does not exist, skipping")
            warning_count += 1
            continue

        for validator in validators:
            result = validator.validate(path)
            for issue in result.issues:
                # Filter out issues from excluded paths
                issue_path = Path(str(issue.file_path))
                if _should_exclude(issue_path):
                    skipped_count += 1
                    continue

                is_error = _is_error_severity(issue)
                severity_label = "ERROR" if is_error else "WARNING"
                print(
                    f"{issue.file_path}:{issue.line_number}: "
                    f"[{severity_label}] [{issue.code}] {issue.message}"
                )
                if is_error:
                    error_count += 1
                else:
                    warning_count += 1

    total_issues = error_count + warning_count

    if skipped_count > 0:
        print(f"\n(Skipped {skipped_count} issues in excluded paths: lib/, _archive/)")

    if total_issues > 0:
        print(f"\nONEX validation found {total_issues} issue(s):")
        print(f"  Errors: {error_count}")
        print(f"  Warnings: {warning_count}")

        if strict:
            # In strict mode, any issue is a failure
            print("\n--strict mode: failing on all issues")
            return 1
        elif error_count > 0:
            # In non-strict mode, only errors cause failure
            return 1
        else:
            # Warnings only in non-strict mode - pass (non-blocking)
            print("\nWarnings found (use --strict to fail on warnings)")
            return 0  # Warnings don't block pre-commit

    if paths:
        print("ONEX validation passed")
    return 0


def main(paths: list[str] | None = None, *, strict: bool = False) -> int:
    """Run ONEX validators on the specified paths.

    Args:
        paths: List of file or directory paths to validate.
               If None or empty, defaults to non-legacy src/ subdirectories.
        strict: If True, fail on any issue (warnings or errors).
                If False, only errors cause non-zero exit code.

    Returns:
        Exit code (see validate_paths for details).
    """
    if not paths:
        # Default to non-legacy src/ subdirectories
        # Excludes lib/ which contains legacy code marked for deletion post-Beta
        src_path = Path("src/omniclaude")
        if src_path.exists():
            paths = [
                str(p)
                for p in src_path.iterdir()
                if p.is_dir() and not _should_exclude(p)
            ]
        else:
            paths = ["src/"]

    # Filter out excluded paths from explicit arguments too
    filtered_paths = [p for p in paths if not _should_exclude(Path(p))]

    if not filtered_paths:
        print("No paths to validate after exclusions")
        return 0

    path_objects = [Path(p) for p in filtered_paths]
    return validate_paths(path_objects, strict=strict)


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Run ONEX validators on files or directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/validate_onex.py src/module.py tests/test_module.py
      Validate specific files (used by pre-commit with staged files).

  python scripts/validate_onex.py src/
      Validate entire src/ directory.

  python scripts/validate_onex.py --strict src/ tests/
      Validate src/ and tests/ directories, fail on any warning or error.

  python scripts/validate_onex.py
      No arguments defaults to validating src/.

Exit codes:
  0  No issues found, or warnings only in non-strict mode
  1  Validation errors found, or any issues in strict mode
""",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Files or directories to validate (default: src/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any issue (warnings or errors). Default: exit 1 for errors, exit 0 for warnings only",
    )
    return parser.parse_args(args)


if __name__ == "__main__":
    parsed = _parse_args()
    sys.exit(main(parsed.paths, strict=parsed.strict))
