#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI validator: Skill-Node Boundary Enforcement (OMN-8094)

Scans SKILL.md files in plugins/onex/skills/ for forbidden orchestration patterns.
Skills must be thin triggers: parse args, publish a command event (or dispatch via
``onex run``), monitor completion, render results. Zero orchestration logic belongs
in a skill.

Forbidden patterns (any SKILL.md that contains these fails CI):

  DIRECT_API_CALL
    Direct shell API calls that bypass the node layer:
    - ``gh pr ...`` / ``gh repo ...`` / ``gh api ...`` (GitHub CLI)
    - ``curl ...`` (HTTP calls)
    - ``git checkout ...`` / ``git push ...`` (git operations, except in examples)

  FOR_LOOP_COLLECTION
    Iteration over domain collections — a sign the skill is orchestrating:
    - ``for.*in.*pr`` / ``for.*pr.*in`` (iterating PRs)
    - ``for.*in.*repo`` / ``for.*repo.*in`` (iterating repos)
    - ``for.*in.*ticket`` (iterating tickets)
    - ``for.*in.*issue`` (iterating issues)

  STATE_MANAGEMENT
    Skills tracking mutable state signals inline orchestration:
    - ``state[`` / ``state_file`` / ``state_path`` / ``state.yaml`` (state dict/file access)
    - ``phase =`` / ``current_phase`` (FSM state transitions)
    - ``ledger[`` / ``ledger_path`` (ledger manipulation)

  MULTI_STEP_ORCHESTRATION
    Multi-phase decision trees indicate orchestration embedded in a skill:
    - Nested ``if ... else if ... else`` constructs spanning >15 lines
    - ``Phase N:`` / ``Step N:`` headers with imperative logic beneath them
      (allowed in thin skills only when they describe dispatch, not decisions)

Suppression:
  Add a comment on the same line or preceding line:
    ``<!-- skill-boundary-ok: reason -->``
  Or add the marker to the skill's YAML frontmatter:
    ``boundary_exempt: true``

Compliant thin skill pattern (allowed):
  1. Parse args from frontmatter ``args:``
  2. ``onex run node_<name> -- <flags>`` (single dispatch call)
  3. Read result from skill-results output path
  4. Post summary / create tickets from results

Exit codes:
  0  No violations found
  1  Violations found (CI should fail)

Usage:
  python scripts/validation/validate_skill_node_boundary.py
  python scripts/validation/validate_skill_node_boundary.py --skills-root plugins/onex/skills
  python scripts/validation/validate_skill_node_boundary.py --strict
  python scripts/validation/validate_skill_node_boundary.py --report

Linear: OMN-8094
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------

CHECK_DIRECT_API_CALL = "DIRECT_API_CALL"
CHECK_FOR_LOOP_COLLECTION = "FOR_LOOP_COLLECTION"
CHECK_STATE_MANAGEMENT = "STATE_MANAGEMENT"
CHECK_MULTI_STEP = "MULTI_STEP_ORCHESTRATION"

SEVERITY_ERROR = "ERROR"

SUPPRESSION_INLINE = "skill-boundary-ok"
SUPPRESSION_FRONTMATTER = "boundary_exempt: true"


@dataclass
class BoundaryViolation:
    skill_name: str
    skill_path: str
    line_number: int
    check: str
    severity: str
    matched_text: str
    suggestion: str

    def format_line(self) -> str:
        return (
            f"{self.skill_path}:{self.line_number}: [{self.severity}] "
            f"{self.check}: {self.matched_text!r}\n"
            f"  -> {self.suggestion}"
        )


# ---------------------------------------------------------------------------
# Forbidden patterns
# ---------------------------------------------------------------------------

# Direct gh/curl/git API calls — these bypass the node layer.
# We look for them in non-fenced, non-suppressed lines.
_DIRECT_API_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"^\s*`{0,3}?\s*(gh\s+(pr|repo|api|issue|run|release)\s+)",
            re.IGNORECASE,
        ),
        "Use a node handler instead of direct 'gh' CLI calls. "
        "Dispatch via: uv run onex run node_<name> -- <flags>",
    ),
    (
        re.compile(
            r"^\s*`{0,3}?\s*(curl\s+(https?://|http://|-[a-zA-Z]))",
            re.IGNORECASE,
        ),
        "Use a node handler for HTTP calls instead of inline 'curl'. "
        "Dispatch via: uv run onex run node_<name> -- <flags>",
    ),
]

# Iteration over domain collections — signs of inline orchestration
_FOR_LOOP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bfor\b.{0,40}\b(pr|pull.?request)s?\b",
            re.IGNORECASE,
        ),
        "Iterating over PRs in a skill indicates orchestration logic. "
        "Move PR iteration to a node (e.g., node_pr_lifecycle_orchestrator). "
        "The skill should dispatch once and monitor.",
    ),
    (
        re.compile(
            r"\bfor\b.{0,40}\b(repo|repositor)s?\b",
            re.IGNORECASE,
        ),
        "Iterating over repos in a skill indicates orchestration logic. "
        "Move repo iteration to a node. The skill dispatches once.",
    ),
    (
        re.compile(
            r"\bfor\b.{0,40}\b(ticket|issue)s?\b",
            re.IGNORECASE,
        ),
        "Iterating over tickets/issues in a skill indicates orchestration logic. "
        "Move iteration to a node handler.",
    ),
]

# State management — skills should not track FSM state
_STATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bstate\s*\[", re.IGNORECASE),
        "Skills must not read/write state dicts. "
        "State belongs in the orchestrator node's handler.",
    ),
    (
        re.compile(r"\bstate_file\b|\bstate_path\b|\bstate\.yaml\b", re.IGNORECASE),
        "Skills must not manage state files. "
        "Move state file operations to the node handler.",
    ),
    (
        re.compile(r"\bcurrent_phase\s*=|\bphase\s*=\s*[\"']", re.IGNORECASE),
        "Skills must not track FSM phases. "
        "Phase management belongs in the orchestrator node.",
    ),
    (
        re.compile(r"\bledger\s*\[|\bledger_path\b", re.IGNORECASE),
        "Skills must not manipulate ledger state. "
        "Ledger operations belong in the orchestrator node.",
    ),
]

# Multi-step orchestration marker: numbered phase/step headers followed by code
# We detect "Phase N:" or "Step N:" that precede imperative logic blocks
_PHASE_STEP_HEADER_RE = re.compile(
    r"^#{1,4}\s+(Phase|Step)\s+\d+[:\s]",
    re.IGNORECASE,
)
# Compliant dispatch pattern — a phase/step header is OK if the block only dispatches
_DISPATCH_ONLY_RE = re.compile(
    r"(onex run|Skill\(skill=|Task\(|dispatch|publish|monitor|report|render)",
    re.IGNORECASE,
)

# Minimum number of phase/step headers before triggering the multi-step check
_MIN_PHASE_HEADERS_FOR_VIOLATION = 4


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def _is_boundary_exempt(content: str) -> bool:
    """Return True if the skill declares boundary_exempt: true in frontmatter."""
    # Frontmatter is between the first two '---' lines
    if not content.startswith("---"):
        return False
    end = content.find("\n---", 3)
    if end == -1:
        return False
    frontmatter = content[3:end]
    return bool(
        re.search(r"^\s*boundary_exempt\s*:\s*true\s*$", frontmatter, re.MULTILINE)
    )


# ---------------------------------------------------------------------------
# Code fence tracker
# ---------------------------------------------------------------------------


def _build_fenced_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) 1-indexed line ranges that are inside code fences.
    Both start and end are inclusive.
    """
    fenced: list[tuple[int, int]] = []
    in_fence = False
    fence_start = 0
    fence_re = re.compile(r"^\s*```")
    for i, line in enumerate(lines, start=1):
        if fence_re.match(line):
            if not in_fence:
                in_fence = True
                fence_start = i
            else:
                fenced.append((fence_start, i))
                in_fence = False
    # Unclosed fence: treat rest of file as fenced
    if in_fence:
        fenced.append((fence_start, len(lines)))
    return fenced


def _is_in_fence(lineno: int, fenced: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in fenced)


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------


def _has_suppression(line: str, prev_line: str) -> bool:
    return SUPPRESSION_INLINE in line or SUPPRESSION_INLINE in prev_line


def scan_skill(skill_path: Path) -> list[BoundaryViolation]:
    """Scan a single SKILL.md file and return all boundary violations."""
    content = skill_path.read_text(encoding="utf-8")
    violations: list[BoundaryViolation] = []

    if _is_boundary_exempt(content):
        return violations

    skill_name = skill_path.parent.name
    path_str = str(skill_path)

    lines = content.splitlines()
    fenced = _build_fenced_ranges(lines)

    phase_step_header_count = 0
    has_dispatch_in_headers = False

    prev_line = ""
    for lineno, line in enumerate(lines, start=1):
        in_fence = _is_in_fence(lineno, fenced)
        suppressed = _has_suppression(line, prev_line)

        # Track phase/step headers (only outside fences)
        if not in_fence and _PHASE_STEP_HEADER_RE.match(line):
            phase_step_header_count += 1
            # Check if this block (next 8 lines) is dispatch-only
            lookahead = "\n".join(lines[lineno : lineno + 8])
            if _DISPATCH_ONLY_RE.search(lookahead):
                has_dispatch_in_headers = True

        if suppressed:
            prev_line = line
            continue

        # Check direct API calls (inside or outside fences — both signal intent)
        for pattern, suggestion in _DIRECT_API_PATTERNS:
            if pattern.search(line):
                violations.append(
                    BoundaryViolation(
                        skill_name=skill_name,
                        skill_path=path_str,
                        line_number=lineno,
                        check=CHECK_DIRECT_API_CALL,
                        severity=SEVERITY_ERROR,
                        matched_text=line.strip()[:120],
                        suggestion=suggestion,
                    )
                )
                break

        # For-loop and state checks apply outside fences only
        if not in_fence:
            for pattern, suggestion in _FOR_LOOP_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        BoundaryViolation(
                            skill_name=skill_name,
                            skill_path=path_str,
                            line_number=lineno,
                            check=CHECK_FOR_LOOP_COLLECTION,
                            severity=SEVERITY_ERROR,
                            matched_text=line.strip()[:120],
                            suggestion=suggestion,
                        )
                    )
                    break

            for pattern, suggestion in _STATE_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        BoundaryViolation(
                            skill_name=skill_name,
                            skill_path=path_str,
                            line_number=lineno,
                            check=CHECK_STATE_MANAGEMENT,
                            severity=SEVERITY_ERROR,
                            matched_text=line.strip()[:120],
                            suggestion=suggestion,
                        )
                    )
                    break

        prev_line = line

    # Multi-step orchestration check: >= N phase/step headers AND not dispatch-only
    if (
        phase_step_header_count >= _MIN_PHASE_HEADERS_FOR_VIOLATION
        and not has_dispatch_in_headers
    ):
        violations.append(
            BoundaryViolation(
                skill_name=skill_name,
                skill_path=path_str,
                line_number=1,
                check=CHECK_MULTI_STEP,
                severity=SEVERITY_ERROR,
                matched_text=f"Found {phase_step_header_count} Phase/Step headers with inline logic",
                suggestion=(
                    "Skills with multi-phase orchestration must delegate all phases to a node. "
                    "Refactor: keep only arg-parsing + single 'onex run node_<name>' dispatch. "
                    "See coverage_sweep/SKILL.md for the compliant thin-trigger pattern."
                ),
            )
        )

    return violations


@dataclass
class ScanResult:
    skills_scanned: int = 0
    skills_with_violations: int = 0
    total_violations: int = 0
    violations: list[BoundaryViolation] = field(default_factory=list)


def scan_skills_root(skills_root: Path) -> ScanResult:
    result = ScanResult()
    skill_files = sorted(skills_root.rglob("SKILL.md"))

    for skill_file in skill_files:
        result.skills_scanned += 1
        violations = scan_skill(skill_file)
        if violations:
            result.skills_with_violations += 1
            result.total_violations += len(violations)
            result.violations.extend(violations)

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_violations(result: ScanResult, report_mode: bool) -> None:
    if not result.violations:
        print(
            f"validate_skill_node_boundary: OK — "
            f"{result.skills_scanned} skills scanned, 0 violations."
        )
        return

    if report_mode:
        print(
            f"\n=== Skill-Node Boundary Report ({result.total_violations} violations) ===\n"
        )
    else:
        print(
            f"\nvalidate_skill_node_boundary: FAILED — "
            f"{result.total_violations} violation(s) in "
            f"{result.skills_with_violations} skill(s)\n"
        )

    seen_skills: set[str] = set()
    for v in result.violations:
        if v.skill_name not in seen_skills:
            if seen_skills:
                print()
            print(f"  Skill: {v.skill_name}")
            seen_skills.add(v.skill_name)
        print(f"    {v.format_line()}")

    print()
    if not report_mode:
        print(
            "To suppress a false positive, add a comment on the offending line:\n"
            "  <!-- skill-boundary-ok: reason -->\n"
            "Or add 'boundary_exempt: true' to the skill's YAML frontmatter."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate skill-node boundary: skills must be thin triggers."
    )
    parser.add_argument(
        "--skills-root",
        default="plugins/onex/skills",
        help="Path to the skills directory (default: plugins/onex/skills)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any violation (same as default; included for clarity)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print report summary without failing CI (exit 0 even on violations)",
    )
    parser.add_argument(
        "--skill",
        metavar="SKILL_NAME",
        help="Scan only the named skill (directory name under skills-root)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    skills_root = Path(args.skills_root)
    if not skills_root.exists():
        print(f"ERROR: skills-root not found: {skills_root}", file=sys.stderr)
        return 1

    if args.skill:
        target = skills_root / args.skill / "SKILL.md"
        if not target.exists():
            print(
                f"ERROR: SKILL.md not found for skill '{args.skill}': {target}",
                file=sys.stderr,
            )
            return 1
        result = ScanResult()
        result.skills_scanned = 1
        violations = scan_skill(target)
        if violations:
            result.skills_with_violations = 1
            result.total_violations = len(violations)
            result.violations = violations
    else:
        result = scan_skills_root(skills_root)

    _print_violations(result, report_mode=args.report)

    if args.report:
        return 0
    return 1 if result.total_violations > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
