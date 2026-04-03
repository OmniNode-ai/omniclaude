# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Detect hardcoded numeric fallback patterns in dashboard/frontend code.

Targets production code paths only — not demos, fixtures, seeds, or test files.
Catches:
  - Ternary expressions with hardcoded decimal fallbacks (e.g., ? 0.87 : 0.82)
  - Hardcoded quality/confidence/score assignments outside test/mock context

Suppression: add `# fallback-ok` to the flagged line.

[OMN-7436]
"""

from __future__ import annotations

import re
import subprocess
import sys

# Patterns to detect
TERNARY_FALLBACK = re.compile(r"\?\s*0\.\d+\s*:\s*0\.\d+")
SCORE_ASSIGNMENT = re.compile(
    r"(quality|confidence|score)\s*[:=]\s*0\.\d+", re.IGNORECASE
)

# File extensions to check
TARGET_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}

# Path patterns to exclude (test, mock, seed, fixture, demo files)
EXCLUDE_PATTERNS = re.compile(
    r"(__test__|\.test\.|\.spec\.|mock-data|seed-demo|/test/|/tests/|"
    r"/fixtures/|/demo/|\.stories\.)"
)

# Suppression marker
SUPPRESSION = "fallback-ok"


def get_staged_files() -> list[str]:
    """Get list of staged files matching target extensions."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    files = []
    for f in result.stdout.strip().splitlines():
        f = f.strip()
        if not f:
            continue
        if any(f.endswith(ext) for ext in TARGET_EXTENSIONS):
            if not EXCLUDE_PATTERNS.search(f):
                files.append(f)
    return files


def check_file(filepath: str) -> list[str]:
    """Check a single file for hardcoded fallback violations."""
    violations = []
    try:
        with open(filepath) as fh:
            for lineno, line in enumerate(fh, start=1):
                if SUPPRESSION in line:
                    continue

                if TERNARY_FALLBACK.search(line):
                    violations.append(
                        f"  {filepath}:{lineno}: ternary numeric fallback: {line.strip()}"
                    )

                if SCORE_ASSIGNMENT.search(line):
                    violations.append(
                        f"  {filepath}:{lineno}: hardcoded score/confidence: {line.strip()}"
                    )
    except OSError:
        pass
    return violations


def main() -> int:
    files = get_staged_files()
    if not files:
        return 0

    all_violations: list[str] = []
    for f in files:
        all_violations.extend(check_file(f))

    if all_violations:
        print("ERROR: Hardcoded numeric fallback values detected:")
        print()
        for v in all_violations:
            print(v)
        print()
        print(
            "FIX: Use null/undefined instead of hardcoded values. "
            "If data isn't available, show empty state."
        )
        print("     Add `# fallback-ok` to suppress a specific line.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
