#!/usr/bin/env python3
"""ONEX validation script for pre-commit hook.

Runs ONEX-compliant validators from omnibase-core:
- ValidatorAnyType: Detect problematic Any type usage
- ValidatorPatterns: Enforce code quality patterns
- ValidatorNamingConvention: Enforce naming standards

Usage:
    python scripts/validate_onex.py [directory]
    python scripts/validate_onex.py --strict [directory]

Exit codes:
    0: All validations passed
    1: Validation errors found (or warnings in --strict mode)
    2: Warnings found (non-strict mode only, for informational purposes)

Options:
    --strict    Fail on any validation issue (warnings or errors).
                Without this flag, only errors cause a non-zero exit code.
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


def main(directory: str = "src/", *, strict: bool = False) -> int:
    """Run ONEX validators on the specified directory.

    Args:
        directory: Path to validate (default: src/)
        strict: If True, fail on any issue (warnings or errors).
                If False, only errors cause non-zero exit code.

    Returns:
        Exit code:
        - 0: No issues (or only warnings in non-strict mode)
        - 1: Errors found (or any issues in strict mode)
        - 2: Warnings found (non-strict mode only)
    """
    validators = [
        ValidatorAnyType(),
        ValidatorPatterns(),
        ValidatorNamingConvention(),
    ]

    src_path = Path(directory)
    if not src_path.exists():
        print(f"Error: Directory '{directory}' does not exist")
        return 1

    error_count = 0
    warning_count = 0

    for validator in validators:
        result = validator.validate(src_path)
        for issue in result.issues:
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
            # Warnings only in non-strict mode
            print("\nWarnings found (use --strict to fail on warnings)")
            return 2

    print("ONEX validation passed")
    return 0


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Run ONEX validators on a directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/validate_onex.py src/
      Run validation on src/, fail only on errors.

  python scripts/validate_onex.py --strict src/
      Run validation on src/, fail on any warning or error.

  python scripts/validate_onex.py --strict .
      Run validation on current directory in strict mode.

Exit codes:
  0  All validations passed (or only warnings in non-strict mode)
  1  Validation errors found (or any issues in strict mode)
  2  Warnings found (non-strict mode only)
""",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="src/",
        help="Directory to validate (default: src/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any validation issue (warnings or errors)",
    )
    return parser.parse_args(args)


if __name__ == "__main__":
    parsed = _parse_args()
    sys.exit(main(parsed.directory, strict=parsed.strict))
