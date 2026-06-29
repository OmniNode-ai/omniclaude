#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI gate: Concurrency-primitive clause (OMN-13047 / Retro D-1).

Any diff that introduces seek_to_end / poll / KafkaConsumer in non-test
Python files MUST also include changes under tests/.

Rationale: blocking/consuming/polling primitives carry starvation and
ordering risks (ladder layers 3-4) that must be answered before live
mutation. This gate enforces that every blocking-primitive introduction
is paired with a concurrent test proving ordering and starvation
properties.

Suppression: add ``# concurrency-ok`` on the flagged line to acknowledge
the primitive is already guarded or is in a migration path.

Modes:
  --ci      Diff against $GITHUB_BASE_REF (default: main) via
            ``git diff origin/<base>...HEAD``. Used in GitHub Actions.
  (default) Staged diff only (``git diff --cached --unified=0``).
            Used as a pre-commit hook or local dev check.

Exit codes:
  0  No unguarded blocking primitive introduced, or all violations
     suppressed via ``# concurrency-ok``.
  1  Blocking primitive introduced in non-test Python source without a
     corresponding change under tests/.
"""

from __future__ import annotations

import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Patterns that indicate a blocking / consuming / polling / seek primitive.
# Each entry is a plain substring; matching is case-sensitive.
# ---------------------------------------------------------------------------
BLOCKING_PATTERNS: tuple[str, ...] = (
    "seek_to_end",
    "KafkaConsumer",
    ".poll(",
)

# Suppression annotation: lines containing this suffix are excluded.
SUPPRESSION_SUFFIX = "# concurrency-ok"

# File extensions that trigger the check.
PYTHON_SUFFIX = ".py"

# Path fragment that indicates a test file.
_TESTS_FRAGMENT = "tests/"

# Regex to extract the current-file path from a diff ``--- a/`` or ``+++ b/``
# header line.
_DIFF_FILE_RE = re.compile(r"^(?:\+\+\+|---) (?:a|b)/(.+)$")


# ---------------------------------------------------------------------------
# Diff parsing helpers
# ---------------------------------------------------------------------------


def _is_test_path(path: str) -> bool:
    """Return True if the path is under a tests/ subtree."""
    return _TESTS_FRAGMENT in path


def _has_blocking_pattern(line: str) -> bool:
    """Return True if *line* contains any blocking pattern (unsuppressed)."""
    if SUPPRESSION_SUFFIX in line:
        return False
    return any(pat in line for pat in BLOCKING_PATTERNS)


def _parse_diff(diff_text: str) -> tuple[list[str], bool]:
    """Parse *diff_text* and return ``(violations, has_test_changes)``.

    ``violations`` is a list of human-readable violation strings.
    ``has_test_changes`` is True if any file under tests/ is modified.
    """
    violations: list[str] = []
    has_test_changes = False
    current_file: str | None = None
    in_source_python = False

    for line in diff_text.splitlines():
        # Detect file boundaries (``diff --git`` or ``+++ b/...`` header)
        if line.startswith("diff --git "):
            # Reset context at every file boundary.
            current_file = None
            in_source_python = False
            continue

        # ``--- a/path`` and ``+++ b/path`` — use +++ to record current file
        m = _DIFF_FILE_RE.match(line)
        if m:
            path = m.group(1)
            if line.startswith("+++"):
                current_file = path
                is_py = path.endswith(PYTHON_SUFFIX)
                is_test = _is_test_path(path)
                in_source_python = is_py and not is_test
                if is_test:
                    has_test_changes = True
            continue

        # Added lines start with ``+`` but not ``++`` (hunk header noise).
        if not line.startswith("+") or line.startswith("+++"):
            continue

        if not in_source_python:
            continue

        content = line[1:]  # strip leading ``+``
        if _has_blocking_pattern(content):
            loc = current_file or "<unknown>"
            violations.append(
                f"{loc}: introduced blocking primitive: {content.strip()!r}"
            )

    return violations, has_test_changes


# ---------------------------------------------------------------------------
# Diff acquisition
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> str:
    """Run *cmd* and return stdout; return empty string on error."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _get_ci_diff(base_ref: str) -> str:
    """Return the diff from ``origin/<base_ref>`` to HEAD (CI / PR mode)."""
    # Ensure the remote ref exists locally.
    _run(["git", "fetch", "origin", base_ref, "--quiet"])
    return _run(["git", "diff", f"origin/{base_ref}...HEAD", "--unified=0"])


def _get_staged_diff() -> str:
    """Return the diff of staged changes only (pre-commit mode)."""
    return _run(["git", "diff", "--cached", "--unified=0"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    ci_mode = "--ci" in args
    if ci_mode:
        import os

        base_ref = os.environ.get("GITHUB_BASE_REF", "main")
        diff_text = _get_ci_diff(base_ref)
        mode_label = f"CI diff (origin/{base_ref}...HEAD)"
    else:
        diff_text = _get_staged_diff()
        mode_label = "staged diff"

    if not diff_text.strip():
        print(f"OK [concurrency-primitive-guard]: no diff in {mode_label}")
        return 0

    violations, has_test_changes = _parse_diff(diff_text)

    if not violations:
        print("OK [concurrency-primitive-guard]: no blocking primitives introduced")
        return 0

    if has_test_changes:
        # Blocking primitives introduced AND tests/ modified — compliant.
        print(
            "OK [concurrency-primitive-guard]: blocking primitive(s) introduced "
            "with concurrent tests/ change — starvation/ordering proof expected"
        )
        for v in violations:
            print(f"  info: {v}")
        return 0

    # Blocking primitives introduced WITHOUT tests/ changes — fail.
    print(
        "ERROR [concurrency-primitive-guard / OMN-13047 Retro D-1]:"
        " blocking/consuming/polling primitive introduced without a tests/ change.\n"
        "\n"
        " Rationale: seek_to_end / poll / KafkaConsumer carry starvation and\n"
        " ordering risks. Before introducing them, answer in writing:\n"
        "   1. What starves while this blocks?\n"
        "   2. What orders publish vs subscribe/seek?\n"
        " Then add a real-dispatch concurrency test (RED/GREEN pattern) in the\n"
        " same PR. See OMN-13047 and OMN-13012 for examples.\n"
        "\n"
        " Violations:"
    )
    for v in violations:
        print(f"  {v}")
    print(
        "\n"
        " Suppression: append ``# concurrency-ok`` to a line only when the\n"
        " primitive is already covered by an existing test suite or is part\n"
        " of a documented migration path."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
