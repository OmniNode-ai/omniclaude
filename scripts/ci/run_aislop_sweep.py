#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI aislop sweep — detect AI-generated quality anti-patterns in omniclaude.

Exits 1 if any CRITICAL or ERROR findings are detected. Implements the
grep-pattern subset of aislop_sweep that is safely executable without the
Claude Code harness (OMN-8622). Covers prohibited-patterns, hardcoded-topics,
and compat-shims checks against src/.

Diff-scoping (OMN-14086): on a normal PR, CI passes the changed-file list via
``--changed-files-from`` and only those files are scanned — every one of the
three checks is per-file (a violation is fully determined by the file it lives
in), so scanning only the diff preserves detection while dropping the whole-tree
``rglob`` cost. Narrowing is **fail-closed**, mirroring the governed test
selector (``detect_test_paths.py``): the scan escalates to the full ``src/``
tree whenever narrowing cannot be proven safe —

  * no changed-file list is available (no arg, or ``--full-tree``), e.g. on
    ``merge_group``/``push``/``schedule`` where there is no PR diff; or
  * the diff touches the aislop validator sources themselves, since a changed
    pattern could turn a previously-clean file into a violation and only a
    whole-tree re-scan can catch that.

This never silently skips a validation — the only two outcomes are "scan the
changed files" and "scan the whole tree", never "scan nothing".
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

EXCLUDE_DIRS = [
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "docs",
    "examples",
    "fixtures",
    "_golden_path_validate",
    "migrations",
    "vendored",
]

EXCLUDE_ARGS = [arg for d in EXCLUDE_DIRS for arg in ("--exclude-dir", d)]

# The sweep is scoped to src/ (parity with the whole-tree behavior it replaces).
SRC_PREFIX = "src/"

# Changing any of these could change detection semantics for the *whole* tree
# (a tightened pattern or exclusion turns previously-clean files into
# violations), so a diff that touches them must FAIL CLOSED to a full-tree scan
# rather than trusting the narrowed changed-file set.
VALIDATOR_INFRA_PATHS = [
    "scripts/ci/run_aislop_sweep.py",
    "scripts/ci/run_aislop_precommit.py",
]

# Pattern strings stored as constants so the aislop tool doesn't flag its own source.
_PROHIBITED_GREP_PATTERN = (
    "ONEX_EVENT_BUS_TYPE=inmemory\\|OLLAMA_BASE_URL"  # aislop: ignore
)


@dataclass
class Finding:
    check: str
    severity: str  # CRITICAL | ERROR | WARNING
    path: str
    line: int
    message: str


def grep(
    pattern: str,
    *extra_args: str,
    dirs: list[str] | None = None,
    root: Path = REPO_ROOT,
) -> list[str]:
    targets = dirs if dirs is not None else ["src"]
    # An explicit-but-empty target list would make grep read stdin and hang;
    # callers guard against it, but treat it as "nothing to scan" defensively.
    if not targets:
        return []
    cmd = [
        "grep",
        "-rnH",
        pattern,
        "--include=*.py",
        *EXCLUDE_ARGS,
        *extra_args,
        *targets,
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
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


def _is_excluded(rel_path: str) -> bool:
    """True if any path segment is an excluded directory (parity with grep)."""
    return any(seg in EXCLUDE_DIRS for seg in Path(rel_path).parts)


def resolve_scan_targets(changed_files: list[str], root: Path = REPO_ROOT) -> list[str]:
    """Filter a raw git-diff file list to the src/ ``.py`` files this sweep scans.

    Drops non-``.py`` files, anything outside ``src/``, excluded directories, and
    paths that no longer exist on disk (deletions/renames-away carry their own
    violations off with them). Mirrors the whole-tree scan's coverage exactly,
    just restricted to the diff.
    """
    targets: set[str] = set()
    for raw in changed_files:
        rel = raw.strip()
        if not rel or not rel.endswith(".py"):
            continue
        if not rel.startswith(SRC_PREFIX):
            continue
        if _is_excluded(rel):
            continue
        if not (root / rel).is_file():
            continue
        targets.add(rel)
    return sorted(targets)


def should_scan_full_tree(
    changed_files: list[str] | None,
) -> tuple[bool, str | None]:
    """Decide whether narrowing to the diff is provably safe (fail-closed).

    ``changed_files is None`` means no diff was supplied — fail closed to the
    full tree. Otherwise escalate only when the diff touches the aislop
    validator sources, whose change could invalidate the narrowed set.
    """
    if changed_files is None:
        return True, "no_diff_available"
    for raw in changed_files:
        rel = raw.strip()
        if any(
            rel == infra or rel.startswith(infra.rstrip("/") + "/")
            for infra in VALIDATOR_INFRA_PATHS
        ):
            return True, "validator_infra_changed"
    return False, None


def collect_findings(
    targets: list[str] | None,
    root: Path = REPO_ROOT,
) -> list[Finding]:
    """Run all three checks over ``targets``.

    ``targets is None`` scans the whole ``src/`` tree (fail-closed default).
    Otherwise ``targets`` is the pre-filtered list of src/ ``.py`` files to scan;
    an empty list means the diff touched no in-scope file, so there is nothing to
    scan and zero findings.
    """
    findings: list[Finding] = []

    if targets is None:
        grep_targets = ["src"]
        enum_scan_files = list((root / "src").rglob("*.py"))
    else:
        if not targets:
            return findings
        grep_targets = targets
        enum_scan_files = [root / t for t in targets]

    # --- prohibited-patterns (CRITICAL) ---
    for raw in grep(_PROHIBITED_GREP_PATTERN, dirs=grep_targets, root=root):
        path, lineno, content = parse_grep_line(raw)
        stripped = content.strip()
        # Skip lines that *describe* the prohibition (rule=, message=, suppression).
        # Note: bare `#` was too broad — it suppressed any commented line including
        # real violations with unrelated inline comments. Only skip explicit markers.
        if re.search(
            r"rule=|message=|FORBIDDEN|forbidden|is FORBIDDEN|aislop:\s*ignore",
            stripped,
        ):
            continue
        findings.append(
            Finding(
                check="prohibited-patterns",
                severity="CRITICAL",
                path=path,
                line=lineno,
                message=f"prohibited env var pattern: {stripped}",
            )
        )

    # --- hardcoded-topics (ERROR in src/) ---
    # Build a set of (path, lineno) pairs that are inside StrEnum/Enum class bodies
    # — those are canonical topic *definitions*, not violations. Enum detection is
    # per-file, so building it only over the scanned files stays correct.
    enum_lines: set[tuple[str, int]] = set()
    for py_file in enum_scan_files:
        if not py_file.is_file():
            continue
        rel = str(py_file.relative_to(root))
        lines = py_file.read_text(errors="replace").splitlines()
        in_enum = False
        enum_indent = -1
        for i, line in enumerate(lines, 1):
            stripped_line = line.rstrip()
            indent = len(line) - len(line.lstrip())
            if re.match(r"\s*class\s+\w+.*(?:StrEnum|Enum)\b", stripped_line):
                in_enum = True
                enum_indent = indent
            elif in_enum:
                if stripped_line and not stripped_line.strip().startswith("#"):
                    if (
                        indent <= enum_indent
                        and re.match(r"\s*class\s", stripped_line) is not None
                    ):
                        in_enum = False
                    elif (
                        indent <= enum_indent
                        and stripped_line.strip()
                        and not stripped_line.strip().startswith(("@", '"', "'"))
                    ):
                        # back to outer scope
                        in_enum = False
            if in_enum:
                enum_lines.add((rel, i))

    for raw in grep(r'"onex\.', dirs=grep_targets, root=root):
        path, lineno, content = parse_grep_line(raw)
        stripped = content.strip()
        # Skip lines inside enum class definitions (canonical topic registries)
        if (path, lineno) in enum_lines:
            continue
        # Skip contract loader references
        if "contract.yaml" in stripped or "contract_loader" in stripped:
            continue
        # Respect inline suppression markers shared with the architecture gates.
        if (
            "noqa: arch-topic-naming" in stripped
            or "arch-topic-naming: ignore" in stripped
            or "aislop: ignore" in stripped
        ):
            continue
        # Skip docstring / >>> examples
        if stripped.startswith("#") or stripped.startswith(">>>"):
            continue
        findings.append(
            Finding(
                check="hardcoded-topics",
                severity="ERROR",
                path=path,
                line=lineno,
                message=f"hardcoded topic string: {stripped[:80]}",
            )
        )

    # --- compat-shims (WARNING in src/) ---
    for raw in grep(
        r"# removed\|# backwards.compat\|_unused_", dirs=grep_targets, root=root
    ):
        path, lineno, content = parse_grep_line(raw)
        findings.append(
            Finding(
                check="compat-shims",
                severity="WARNING",
                path=path,
                line=lineno,
                message=f"compat shim: {content.strip()[:80]}",
            )
        )

    return findings


def _report(findings: list[Finding]) -> int:
    """Print findings and return the process exit code."""
    if not findings:
        print("aislop_sweep: 0 findings. PASS")
        return 0

    critical = [f for f in findings if f.severity == "CRITICAL"]
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    print(
        f"aislop_sweep: {len(findings)} findings "
        f"(CRITICAL={len(critical)}, ERROR={len(errors)}, WARNING={len(warnings)})\n"
    )

    fmt = f"{'SEVERITY':<10} {'CHECK':<22} {'PATH':<60} LINE  MESSAGE"
    print(fmt)
    print("-" * 130)
    for f in sorted(findings, key=lambda x: (x.severity, x.check, x.path)):
        print(f"{f.severity:<10} {f.check:<22} {f.path:<60} {f.line:<5} {f.message}")

    if critical or errors:
        print(
            f"\nFAIL: {len(critical)} CRITICAL and {len(errors)} ERROR findings detected."
        )
        return 1

    print("\nPASS: only WARNING findings (no CRITICAL/ERROR).")
    return 0


def _read_changed_files(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect AI-generated quality anti-patterns (diff-scoped, fail-closed)."
    )
    parser.add_argument(
        "--changed-files-from",
        type=Path,
        default=None,
        help=(
            "Path to a file with one changed-file path per line (git diff "
            "--name-only). Scan narrows to these files unless a fail-closed "
            "escalation applies. Omitted → full-tree scan."
        ),
    )
    parser.add_argument(
        "--full-tree",
        action="store_true",
        help="Force a whole-src/ scan (used on merge_group/push/schedule, or when "
        "the PR diff cannot be computed).",
    )
    args = parser.parse_args(argv)

    # Read the module global at call time so tests can repoint the scan root.
    root = REPO_ROOT

    if args.full_tree:
        print("aislop_sweep: full-tree scan (explicit --full-tree).")
        targets: list[str] | None = None
    elif args.changed_files_from is None:
        print(
            "aislop_sweep: full-tree scan (no changed-file list; fail-closed default)."
        )
        targets = None
    else:
        changed = _read_changed_files(args.changed_files_from)
        escalate, reason = should_scan_full_tree(changed)
        if escalate:
            print(f"aislop_sweep: full-tree scan (fail-closed escalation: {reason}).")
            targets = None
        else:
            targets = resolve_scan_targets(changed, root=root)
            print(
                f"aislop_sweep: diff-scoped scan over {len(targets)} changed "
                f"src/ file(s) (of {len(changed)} changed path(s))."
            )

    findings = collect_findings(targets, root=root)
    return _report(findings)


if __name__ == "__main__":
    sys.exit(main())
