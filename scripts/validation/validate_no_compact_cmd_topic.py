#!/usr/bin/env python3
"""ARCH: No compact cmd topic validation.

Check: No onex.cmd.* topic may use cleanup.policy=compact.

cmd topics require full offset replay for exactly-once semantics.
compact retention discards intermediate events and breaks replay guarantees.

Scans all topic configuration files (*.yaml, *.yml, *.json, *.properties)
under sql/, config/, and scripts/ for any cmd topic configuration that sets
cleanup.policy=compact.

Exit 0: No violations found.
Exit 1: One or more violations found.

Usage:
    uv run python scripts/validation/validate_no_compact_cmd_topic.py
    uv run python scripts/validation/validate_no_compact_cmd_topic.py --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Pattern to match cmd topic names in topic config lines
_CMD_TOPIC_PATTERN = re.compile(r"onex\.cmd\.[a-zA-Z0-9._-]+")

# Pattern to match cleanup.policy=compact (case-insensitive)
_COMPACT_POLICY_PATTERN = re.compile(r"cleanup\.policy\s*[=:]\s*compact", re.IGNORECASE)

# Directories and file extensions to scan for topic configurations
_SCAN_DIRS = ["sql", "config", "scripts", "src"]
_SCAN_EXTENSIONS = {".yaml", ".yml", ".json", ".properties", ".conf"}

# Suppression comment token checked in file content (not a password)
_NOQA_TOKEN = "# noqa: arch-no-compact-cmd-topic"  # noqa: S105


def scan_file(filepath: Path, verbose: bool = False) -> list[str]:
    """Scan a single file for compact cmd topic violations.

    Args:
        filepath: Path to the file to scan.
        verbose: Whether to print verbose output.

    Returns:
        List of violation messages (empty if no violations).
    """
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        if verbose:
            print(f"  SKIP {filepath}: {e}", file=sys.stderr)
        return []

    violations = []
    lines = content.splitlines()

    # Strategy: look for blocks where a cmd topic name and cleanup.policy=compact
    # appear near each other (within 20 lines). Also check single-line properties.
    for i, line in enumerate(lines):
        # Skip suppressed lines
        if _NOQA_TOKEN in line:
            continue

        # Check for inline single-line pattern (e.g., properties files):
        # onex.cmd.something.cleanup.policy=compact
        if _CMD_TOPIC_PATTERN.search(line) and _COMPACT_POLICY_PATTERN.search(line):
            violations.append(
                f"{filepath}:{i + 1}: cmd topic with cleanup.policy=compact "
                f"(inline pattern)\n  Line: {line.strip()}"
            )
            continue

        # Check for block pattern: cmd topic name followed by compact policy nearby
        if _CMD_TOPIC_PATTERN.search(line):
            # Scan the next 20 lines for cleanup.policy=compact
            end_idx = min(i + 20, len(lines))
            for j in range(i, end_idx):
                if _NOQA_TOKEN in lines[j]:
                    break
                if _COMPACT_POLICY_PATTERN.search(lines[j]):
                    topic_match = _CMD_TOPIC_PATTERN.search(line)
                    topic_name = topic_match.group(0) if topic_match else "unknown"
                    violations.append(
                        f"{filepath}:{j + 1}: cmd topic '{topic_name}' has "
                        f"cleanup.policy=compact (F5.1 violation)\n"
                        f"  Topic at line {i + 1}: {line.strip()}\n"
                        f"  Policy at line {j + 1}: {lines[j].strip()}"
                    )
                    break

    return violations


def main(argv: list[str] | None = None) -> int:
    """Run the compact cmd topic validation.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for no violations, 1 for violations found.
    """
    parser = argparse.ArgumentParser(
        description="Validate no cmd topic uses cleanup.policy=compact (F5.1)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to scan (default: scan standard config/sql/scripts dirs)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).parent.parent.parent
    all_violations: list[str] = []
    files_checked = 0

    if args.paths:
        scan_paths = [Path(p) for p in args.paths]
    else:
        scan_paths = [repo_root / d for d in _SCAN_DIRS if (repo_root / d).exists()]

    for scan_path in scan_paths:
        if scan_path.is_file():
            files = [scan_path]
        else:
            files = [
                f
                for f in scan_path.rglob("*")
                if f.is_file() and f.suffix in _SCAN_EXTENSIONS
            ]

        for filepath in sorted(files):
            violations = scan_file(filepath, verbose=args.verbose)
            files_checked += 1
            if violations:
                all_violations.extend(violations)
                if args.verbose:
                    for v in violations:
                        print(f"  VIOLATION: {v}")
            elif args.verbose:
                print(f"  OK: {filepath}")

    if all_violations:
        print(f"\nF5.1 VIOLATION: {len(all_violations)} compact cmd topic(s) found:")
        for v in all_violations:
            print(f"  - {v}")
        print(
            "\nFix: Remove cleanup.policy=compact from cmd topics. "
            "Only evt topics may use compact retention."
        )
        return 1

    print(
        f"F5.1 check passed: No compact cmd topics found "
        f"({files_checked} files scanned)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
