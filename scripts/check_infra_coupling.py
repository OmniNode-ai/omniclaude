#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Infrastructure coupling detector for ONEX handler compliance.

Scans Python files across all repos under omni_home for patterns where handlers
check infrastructure availability instead of relying on injected dependencies.
This is Check 7 in the compliance_sweep skill (OMN-7677).

Anti-patterns detected:
  - Publisher/event_bus None guards (if self._publisher is None)
  - has_publisher variable/parameter usage
  - use_filesystem_fallback parameter usage
  - publisher_available / kafka_available checks
  - Event bus availability checks (if not self._event_bus)

Usage:
    python scripts/check_infra_coupling.py
    python scripts/check_infra_coupling.py --repos omnibase_infra
    python scripts/check_infra_coupling.py --json
    python scripts/check_infra_coupling.py --handlers-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Anti-pattern definitions
# ---------------------------------------------------------------------------

INFRA_COUPLING_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "PUBLISHER_NONE_GUARD",
        re.compile(
            r"""
            (?:self\.)?_?\w*publisher\w* \s+ is \s+ (?:None|not\s+None)
            """,
            re.VERBOSE,
        ),
        "Publisher None guard — code checks publisher availability instead of using injected dependency",
    ),
    (
        "EVENT_BUS_NONE_GUARD",
        re.compile(
            r"""
            (?:self\.)?_?event_bus \s+ is \s+ (?:None|not\s+None)
            """,
            re.VERBOSE,
        ),
        "Event bus None guard — code checks event_bus availability",
    ),
    (
        "EVENT_BUS_FALSY_GUARD",
        re.compile(
            r"""
            (?:if|elif|while) \s+
            not \s+ (?:self\.)?_?event_bus\b
            """,
            re.VERBOSE,
        ),
        "Event bus falsy guard — code checks if event_bus is falsy",
    ),
    (
        "PUBLISHER_FALSY_GUARD",
        re.compile(
            r"""
            (?:if|elif|while) \s+
            not \s+ (?:self\.)?_?\w*publisher\b
            """,
            re.VERBOSE,
        ),
        "Publisher falsy guard — code checks if publisher is falsy",
    ),
    (
        "HAS_PUBLISHER",
        re.compile(r"\bhas_publisher\b"),
        "has_publisher variable — infrastructure availability flag",
    ),
    (
        "USE_FILESYSTEM_FALLBACK",
        re.compile(r"\buse_filesystem_fallback\b"),
        "use_filesystem_fallback — fallback path when publisher unavailable",
    ),
    (
        "PUBLISHER_AVAILABLE",
        re.compile(r"\bpublisher_available\b"),
        "publisher_available — infrastructure availability flag",
    ),
    (
        "KAFKA_AVAILABLE",
        re.compile(r"\bkafka_available\b"),
        "kafka_available — infrastructure availability flag",
    ),
    (
        "PUBLISHER_NONE_ASSIGNMENT",
        re.compile(
            r"""
            (?:self\.)?_?\w*publisher\w* \s* = \s* None\b
            """,
            re.VERBOSE,
        ),
        "Publisher assigned None — sets up optional publisher pattern",
    ),
    (
        "EVENT_BUS_NONE_ASSIGNMENT",
        re.compile(
            r"""
            (?:self\.)?_?event_bus \s* = \s* None\b
            """,
            re.VERBOSE,
        ),
        "Event bus assigned None — sets up optional event_bus pattern",
    ),
    (
        "PUBLISHER_OPTIONAL_TYPE",
        re.compile(
            r"""
            (?:Optional\[.*(?:Publisher|EventBus))|(?:(?:Publisher|EventBus).*\|\s*None)
            """,
            re.VERBOSE,
        ),
        "Optional publisher/event_bus type annotation — dependency should not be optional",
    ),
    (
        "EVENT_BUS_OR_FALLBACK",
        re.compile(
            r"""
            event_bus \s+ or \s+
            """,
            re.VERBOSE,
        ),
        "Event bus or-fallback — creates fallback when event_bus is falsy",
    ),
]

# File classification for severity assignment
HANDLER_PATH_RE = re.compile(r"nodes/node_[^/]+/handlers/")
PLUGIN_PATH_RE = re.compile(r"nodes/node_[^/]+/plugin\.py")
ORCHESTRATOR_PATH_RE = re.compile(r"(?:orchestrat|runtime|service)")

DEFAULT_REPOS = [
    "omnibase_infra",
    "omniintelligence",
    "omnimemory",
    "omnibase_core",
    "omniclaude",
    "onex_change_control",
    "omnibase_spi",
]

OMNI_HOME = Path("/Users/jonah/Code/omni_home")  # local-path-ok


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    repo: str
    file: str
    line: int
    pattern_id: str
    matched_text: str
    description: str
    severity: str  # CRITICAL or WARN

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "file": self.file,
            "line": self.line,
            "pattern_id": self.pattern_id,
            "matched_text": self.matched_text,
            "description": self.description,
            "severity": self.severity,
        }


@dataclass
class ScanResult:
    repos_scanned: int = 0
    files_scanned: int = 0
    violations: list[Violation] = field(default_factory=list)
    per_repo: dict[str, list[Violation]] = field(default_factory=dict)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def warn_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARN")

    def to_dict(self) -> dict:
        per_repo_summary = {}
        for repo, violations in self.per_repo.items():
            per_repo_summary[repo] = {
                "total": len(violations),
                "critical": sum(1 for v in violations if v.severity == "CRITICAL"),
                "warn": sum(1 for v in violations if v.severity == "WARN"),
                "by_pattern": {},
            }
            for v in violations:
                per_repo_summary[repo]["by_pattern"][v.pattern_id] = (
                    per_repo_summary[repo]["by_pattern"].get(v.pattern_id, 0) + 1
                )

        return {
            "repos_scanned": self.repos_scanned,
            "files_scanned": self.files_scanned,
            "total_violations": len(self.violations),
            "critical_count": self.critical_count,
            "warn_count": self.warn_count,
            "per_repo": per_repo_summary,
            "violations": [v.to_dict() for v in self.violations],
        }


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def classify_severity(rel_path: str) -> str:
    """Assign severity based on file location."""
    if HANDLER_PATH_RE.search(rel_path):
        return "CRITICAL"
    return "WARN"


def is_in_comment_or_docstring(line: str, matched_text: str) -> bool:
    """Basic heuristic to skip comments and string-only lines."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return True
    # Skip lines that are purely docstring content (inside triple quotes)
    # This is a rough heuristic; full AST analysis is in the compliance scanner
    if stripped.startswith(('"""', "'''", '"', "'")):
        # Check if the match is inside the string literal
        before_match = line[: line.index(matched_text)] if matched_text in line else ""
        quote_count = before_match.count('"""') + before_match.count("'''")
        if quote_count % 2 == 1:
            return True
    return False


def scan_file(
    file_path: Path,
    repo_name: str,
    repo_root: Path,
    *,
    handlers_only: bool = False,
) -> list[Violation]:
    """Scan a single Python file for infrastructure coupling patterns."""
    rel_path = str(file_path.relative_to(repo_root))

    if handlers_only and not HANDLER_PATH_RE.search(rel_path):
        return []

    severity = classify_severity(rel_path)
    violations: list[Violation] = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern_id, pattern, description in INFRA_COUPLING_PATTERNS:
            match = pattern.search(line)
            if match and not is_in_comment_or_docstring(line, match.group()):
                violations.append(
                    Violation(
                        repo=repo_name,
                        file=rel_path,
                        line=line_num,
                        pattern_id=pattern_id,
                        matched_text=match.group().strip(),
                        description=description,
                        severity=severity,
                    )
                )

    return violations


def scan_repo(
    repo_name: str,
    *,
    handlers_only: bool = False,
) -> tuple[int, list[Violation]]:
    """Scan a repo for infrastructure coupling violations."""
    repo_root = OMNI_HOME / repo_name
    src_dir = repo_root / "src"

    if not src_dir.is_dir():
        return 0, []

    files_scanned = 0
    violations: list[Violation] = []

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name == "__init__.py":
            continue
        files_scanned += 1
        violations.extend(
            scan_file(py_file, repo_name, repo_root, handlers_only=handlers_only)
        )

    return files_scanned, violations


def run_scan(
    repos: list[str],
    *,
    handlers_only: bool = False,
) -> ScanResult:
    """Run the full infrastructure coupling scan."""
    result = ScanResult()

    for repo_name in repos:
        files_scanned, violations = scan_repo(
            repo_name, handlers_only=handlers_only
        )
        if files_scanned > 0:
            result.repos_scanned += 1
            result.files_scanned += files_scanned
            result.violations.extend(violations)
            if violations:
                result.per_repo[repo_name] = violations

    return result


def print_summary(result: ScanResult) -> None:
    """Print a human-readable summary."""
    print("Infrastructure Coupling Detection")
    print("=" * 50)
    print(f"Repos scanned:     {result.repos_scanned}")
    print(f"Files scanned:     {result.files_scanned}")
    print(f"Total violations:  {len(result.violations)}")
    print(f"  CRITICAL:        {result.critical_count}")
    print(f"  WARN:            {result.warn_count}")
    print()

    if result.per_repo:
        print("Per-repo breakdown:")
        for repo, violations in sorted(result.per_repo.items()):
            critical = sum(1 for v in violations if v.severity == "CRITICAL")
            warn = sum(1 for v in violations if v.severity == "WARN")
            print(f"  {repo}: {len(violations)} violations ({critical} critical, {warn} warn)")
        print()

    # Pattern histogram
    pattern_counts: dict[str, int] = {}
    for v in result.violations:
        pattern_counts[v.pattern_id] = pattern_counts.get(v.pattern_id, 0) + 1

    if pattern_counts:
        print("By pattern:")
        for pattern_id, count in sorted(
            pattern_counts.items(), key=lambda x: -x[1]
        ):
            print(f"  {pattern_id}: {count}")
        print()

    # Show first few CRITICAL violations
    critical_violations = [v for v in result.violations if v.severity == "CRITICAL"]
    if critical_violations:
        print(f"CRITICAL violations ({len(critical_violations)} total):")
        for v in critical_violations[:20]:
            print(f"  {v.file}:{v.line} [{v.pattern_id}] {v.matched_text}")
        if len(critical_violations) > 20:
            print(f"  ... and {len(critical_violations) - 20} more")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect infrastructure coupling anti-patterns in ONEX repos"
    )
    parser.add_argument(
        "--repos",
        type=str,
        default=None,
        help="Comma-separated repo names (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--handlers-only",
        action="store_true",
        help="Only scan handler files (src/*/nodes/*/handlers/)",
    )
    args = parser.parse_args()

    repos = args.repos.split(",") if args.repos else DEFAULT_REPOS
    result = run_scan(repos, handlers_only=args.handlers_only)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print_summary(result)

    # Exit with 1 if CRITICAL violations found
    sys.exit(1 if result.critical_count > 0 else 0)


if __name__ == "__main__":
    main()
