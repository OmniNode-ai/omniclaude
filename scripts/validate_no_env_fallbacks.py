#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate that no localhost/default fallbacks exist in src/ and scripts/.

Scans Python and shell files for patterns like:
  - os.environ.get("VAR", "localhost...")
  - os.getenv("VAR", "localhost...")
  - ${VAR:-localhost}
  - hardcoded localhost:<port> connection strings (outside comments/docstrings)

Exit code 0 if clean, 1 if violations found.

[OMN-7227]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Directories to scan (relative to repo root)
SCAN_DIRS = ["src", "scripts"]

# Directories/files to skip
SKIP_DIRS = {"tests", "__pycache__", ".git", "scripts/tests"}
SKIP_FILES = {
    "validate_no_env_fallbacks.py",  # this file
    "validate_no_hardcoded_kafka_broker.py",  # existing validator (has examples in comments)
    "cron-closeout.sh",  # documentation-only references in heredoc strings
    "start-dashboard.sh",  # informational echo of local URL
    "validate_secrets.py",  # example strings in validation messages
}

# Patterns that indicate a localhost fallback
PYTHON_FALLBACK_PATTERNS = [
    # os.environ.get("VAR", "localhost...") or os.getenv("VAR", "localhost...")
    re.compile(
        r"""os\.(?:environ\.get|getenv)\(\s*["'][^"']+["']\s*,\s*["'][^"']*localhost[^"']*["']\s*\)"""
    ),
    # Hardcoded connection strings with localhost
    re.compile(
        r"""[=:]\s*["'](?:postgresql|redis|http|https)://[^"']*localhost[^"']*["']"""
    ),
    # bootstrap_servers="localhost:..."
    re.compile(r"""bootstrap_servers\s*=\s*["']localhost:[^"']*["']"""),
]

SHELL_FALLBACK_PATTERNS = [
    # ${VAR:-localhost}
    re.compile(r"""\$\{[A-Z_]+:-localhost[^}]*\}"""),
]

# Lines containing these markers are exempted
EXEMPT_MARKERS = [
    "# cloud-bus-ok",
    "# fallback-ok",
    "# OMN-7227-exempt",
    "SKIP_DIRS",  # this script's own skip list
]


def _is_comment_or_docstring_line(line: str) -> bool:
    """Rough heuristic: skip lines that are pure comments or docstring content."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    if stripped.startswith(('"""', "'''", ">>>")):
        return True
    # Lines inside docstrings are harder to detect; we check for leading prose patterns
    if stripped.startswith(("description=", "help=")):
        # argparse help strings reference localhost in docs — check if it's a default value
        return False
    return False


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) violations."""
    violations: list[tuple[int, str]] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations

    lines = content.splitlines()
    is_python = path.suffix == ".py"
    is_shell = path.suffix in (".sh", ".bash")

    patterns = []
    if is_python:
        patterns = PYTHON_FALLBACK_PATTERNS
    elif is_shell:
        patterns = SHELL_FALLBACK_PATTERNS
    else:
        return violations

    for i, line in enumerate(lines, start=1):
        # Skip exempt lines
        if any(marker in line for marker in EXEMPT_MARKERS):
            continue
        # Skip pure comment lines
        if _is_comment_or_docstring_line(line):
            continue
        for pattern in patterns:
            if pattern.search(line):
                violations.append((i, line.rstrip()))
                break

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    all_violations: list[tuple[str, int, str]] = []

    for scan_dir in SCAN_DIRS:
        base = repo_root / scan_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in (".py", ".sh", ".bash"):
                continue
            # Check skip dirs
            rel = path.relative_to(repo_root)
            if any(skip in rel.parts for skip in SKIP_DIRS):
                continue
            if path.name in SKIP_FILES:
                continue

            violations = scan_file(path)
            for line_num, line_text in violations:
                all_violations.append((str(rel), line_num, line_text))

    if all_violations:
        print(f"FAIL: {len(all_violations)} localhost/default fallback(s) found:\n")
        for filepath, line_num, line_text in all_violations:
            print(f"  {filepath}:{line_num}")
            print(f"    {line_text}\n")
        print(
            "Fix: Replace with os.environ[\"VAR\"] (no fallback) or raise an error "
            "when the env var is missing. [OMN-7227]"
        )
        return 1

    print("PASS: No localhost/default fallbacks found in src/ and scripts/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
