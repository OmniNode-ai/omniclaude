#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-commit aislop sweep — fast, changed-files-only check for CRITICAL/ERROR patterns.

Receives changed file paths as argv (pre-commit passes them). Checks only:
  - prohibited-patterns (CRITICAL): ONEX_EVENT_BUS_TYPE=inmemory, OLLAMA_BASE_URL
  - compat-shims (WARNING, non-blocking): # removed, # backwards.compat, _unused_

Hardcoded-topic detection is CI-only (full enum exclusion logic is too slow for
per-commit use and requires scanning the whole StrEnum corpus to avoid false positives).

Exits 1 on CRITICAL findings. WARNING findings produce output but do not block.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def check_file(path: Path) -> list[tuple[str, int, str, str]]:
    """Return list of (severity, lineno, check, message) for the file."""
    findings = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return findings

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip pure comments and rule/error message definitions
        if stripped.startswith("#"):
            continue
        # Skip lines with inline suppression (same mechanism as run_aislop_sweep.py)
        if "aislop: ignore" in stripped:
            continue
        # prohibited-patterns
        if re.search(r"ONEX_EVENT_BUS_TYPE=inmemory|OLLAMA_BASE_URL", line):
            if not re.search(
                r"rule=|message=|FORBIDDEN|forbidden|is FORBIDDEN", stripped
            ):
                findings.append(
                    (
                        "CRITICAL",
                        i,
                        "prohibited-patterns",
                        f"prohibited env var: {stripped[:80]}",
                    )
                )
        # compat-shims (WARNING only — non-blocking)
        if re.search(r"# removed\b|# backwards.compat|_unused_", line):
            findings.append(
                ("WARNING", i, "compat-shims", f"compat shim: {stripped[:80]}")
            )
    return findings


_SELF_EXEMPT = frozenset(
    {"scripts/ci/run_aislop_precommit.py", "scripts/ci/run_aislop_sweep.py"}
)


def main(files: list[str]) -> int:
    criticals = 0
    for filepath in files:
        path = Path(filepath)
        if not path.exists() or path.suffix != ".py":
            continue
        # The aislop scripts themselves contain the pattern strings by design.
        if any(path.as_posix().endswith(exempt) for exempt in _SELF_EXEMPT):
            continue
        for severity, lineno, check, message in check_file(path):
            print(f"{severity:<10} {check:<22} {filepath}:{lineno}: {message}")
            if severity == "CRITICAL":
                criticals += 1

    if criticals:
        print(f"\naislop precommit: {criticals} CRITICAL finding(s). BLOCKED.")
        print(
            "Fix the issues above or use # aislop: ignore to suppress intentional uses."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
