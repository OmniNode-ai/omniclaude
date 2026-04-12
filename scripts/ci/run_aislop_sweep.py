#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI aislop sweep — detect AI-generated quality anti-patterns in omniclaude.

Exits 1 if any CRITICAL or ERROR findings are detected. Implements the
grep-pattern subset of aislop_sweep that is safely executable without the
Claude Code harness (OMN-8622). Covers prohibited-patterns, hardcoded-topics,
and compat-shims checks against src/.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

EXCLUDE_DIRS = [
    ".git", ".venv", "__pycache__", "node_modules", "dist", "build",
    "docs", "examples", "fixtures", "_golden_path_validate", "migrations",
    "vendored",
]

EXCLUDE_ARGS = [arg for d in EXCLUDE_DIRS for arg in ("--exclude-dir", d)]


@dataclass
class Finding:
    check: str
    severity: str  # CRITICAL | ERROR | WARNING
    path: str
    line: int
    message: str


def grep(pattern: str, *extra_args: str, dirs: list[str] | None = None) -> list[str]:
    targets = dirs or ["src"]
    cmd = [
        "grep", "-rn", pattern,
        "--include=*.py",
        *EXCLUDE_ARGS,
        *extra_args,
        *targets,
    ]
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def parse_grep_line(line: str) -> tuple[str, int, str]:
    """Return (filepath, lineno, content) from a grep -n output line."""
    parts = line.split(":", 2)
    if len(parts) >= 3:
        try:
            return parts[0], int(parts[1]), parts[2]
        except ValueError:
            pass
    return line, 0, line


def main() -> int:
    findings: list[Finding] = []

    # --- prohibited-patterns (CRITICAL) ---
    for raw in grep(r"ONEX_EVENT_BUS_TYPE=inmemory\|OLLAMA_BASE_URL"):
        path, lineno, content = parse_grep_line(raw)
        stripped = content.strip()
        # Skip lines that *describe* the prohibition (rule=, message=, comment)
        if re.search(r'rule=|message=|#|FORBIDDEN|forbidden|is FORBIDDEN', stripped):
            continue
        findings.append(Finding(
            check="prohibited-patterns",
            severity="CRITICAL",
            path=path,
            line=lineno,
            message=f"prohibited env var pattern: {stripped}",
        ))

    # --- hardcoded-topics (ERROR in src/) ---
    # Build a set of (path, lineno) pairs that are inside StrEnum/Enum class bodies
    # — those are canonical topic *definitions*, not violations.
    enum_lines: set[tuple[str, int]] = set()
    src_dir = REPO_ROOT / "src"
    for py_file in src_dir.rglob("*.py"):
        rel = str(py_file.relative_to(REPO_ROOT))
        lines = py_file.read_text(errors="replace").splitlines()
        in_enum = False
        enum_indent = -1
        for i, line in enumerate(lines, 1):
            stripped_line = line.rstrip()
            indent = len(line) - len(line.lstrip())
            if re.match(r'\s*class\s+\w+.*(?:StrEnum|Enum)\b', stripped_line):
                in_enum = True
                enum_indent = indent
            elif in_enum:
                if stripped_line and not stripped_line.strip().startswith("#"):
                    if indent <= enum_indent and not re.match(r'\s*class\s', stripped_line) is None:
                        in_enum = False
                    elif indent <= enum_indent and stripped_line.strip() and not stripped_line.strip().startswith(("@", '"', "'")):
                        # back to outer scope
                        in_enum = False
            if in_enum:
                enum_lines.add((rel, i))

    for raw in grep(r'"onex\.'):
        path, lineno, content = parse_grep_line(raw)
        stripped = content.strip()
        # Skip lines inside enum class definitions (canonical topic registries)
        if (path, lineno) in enum_lines:
            continue
        # Skip contract loader references
        if "contract.yaml" in stripped or "contract_loader" in stripped:
            continue
        # Respect inline suppression: # noqa: arch-topic-naming or # aislop: ignore
        if "noqa: arch-topic-naming" in stripped or "aislop: ignore" in stripped:
            continue
        # Skip docstring / >>> examples
        if stripped.startswith("#") or stripped.startswith(">>>"):
            continue
        findings.append(Finding(
            check="hardcoded-topics",
            severity="ERROR",
            path=path,
            line=lineno,
            message=f"hardcoded topic string: {stripped[:80]}",
        ))

    # --- compat-shims (WARNING in src/) ---
    for raw in grep(r'# removed\|# backwards.compat\|_unused_'):
        path, lineno, content = parse_grep_line(raw)
        findings.append(Finding(
            check="compat-shims",
            severity="WARNING",
            path=path,
            line=lineno,
            message=f"compat shim: {content.strip()[:80]}",
        ))

    if not findings:
        print("aislop_sweep: 0 findings. PASS")
        return 0

    critical = [f for f in findings if f.severity == "CRITICAL"]
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    print(f"aislop_sweep: {len(findings)} findings "
          f"(CRITICAL={len(critical)}, ERROR={len(errors)}, WARNING={len(warnings)})\n")

    fmt = f"{'SEVERITY':<10} {'CHECK':<22} {'PATH':<60} LINE  MESSAGE"
    print(fmt)
    print("-" * 130)
    for f in sorted(findings, key=lambda x: (x.severity, x.check, x.path)):
        print(f"{f.severity:<10} {f.check:<22} {f.path:<60} {f.line:<5} {f.message}")

    if critical or errors:
        print(f"\nFAIL: {len(critical)} CRITICAL and {len(errors)} ERROR findings detected.")
        return 1

    print("\nPASS: only WARNING findings (no CRITICAL/ERROR).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
