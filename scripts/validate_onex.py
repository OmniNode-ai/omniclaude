#!/usr/bin/env python3
"""ONEX validation script for pre-commit hook.

Runs ONEX-compliant validators from omnibase-core:
- ValidatorAnyType: Detect problematic Any type usage
- ValidatorPatterns: Enforce code quality patterns
- ValidatorNamingConvention: Enforce naming standards

Usage:
    python scripts/validate_onex.py [directory]

Exit codes:
    0: All validations passed
    1: Validation issues found
"""

from __future__ import annotations

import sys
from pathlib import Path

from omnibase_core.validation import (
    ValidatorAnyType,
    ValidatorNamingConvention,
    ValidatorPatterns,
)


def main(directory: str = "src/") -> int:
    """Run ONEX validators on the specified directory.

    Args:
        directory: Path to validate (default: src/)

    Returns:
        Exit code (0 for success, 1 for failures)
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

    total_issues = 0

    for validator in validators:
        result = validator.validate(src_path)
        for issue in result.issues:
            print(f"{issue.file_path}:{issue.line_number}: [{issue.code}] {issue.message}")
            total_issues += 1

    if total_issues > 0:
        print(f"\nONEX validation found {total_issues} issue(s)")
        return 1

    return 0


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "src/"
    sys.exit(main(target_dir))
