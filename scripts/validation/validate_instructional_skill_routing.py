#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI validator: Instructional Skill Enforcement (OMN-8766, S19)

Tier 3 instructional skills are pure-prose guidance surfaces; they must NOT
partially adopt the deterministic dispatch contract. This gate rejects two
kinds of partial-port that have historically crept into instructional
SKILL.md files:

  1. ``onex run`` / ``onex run-node`` dispatch commands (belong in Tier 1
     deterministic skills, guarded by OMN-8749 / OMN-8765).
  2. ``rendered_output`` receipt assertions (belong in the DoD evidence
     contract surfaced by deterministic skills).

An instructional skill that ships either of the above signals that the
skill is being lifted into a deterministic contract without the backing
node, routing error surface, or pre-commit gate those contracts require.
That lift must happen as an explicit port (promote skill into
``TIER1_DETERMINISTIC_SKILLS`` + add routing + land a node), not as a
mid-file mutation.

Enforced skills mirror the Tier 3 list on OMN-8766:
  using_git_worktrees, onboarding, systematic_debugging, multi_agent,
  observability, login, authorize, handoff, resume_session, set_session,
  recall, rewind, crash_recovery, checkpoint, writing_skills

Exit codes:
  0  All instructional skills pass the gate
  1  One or more violations found (blocking)

Usage:
  uv run python scripts/validation/validate_instructional_skill_routing.py
  uv run python scripts/validation/validate_instructional_skill_routing.py --report
  uv run python scripts/validation/validate_instructional_skill_routing.py \
      --skills-root plugins/onex/skills --skill authorize

Linear: OMN-8766
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TIER3_INSTRUCTIONAL_SKILLS: set[str] = {
    "using_git_worktrees",
    "onboarding",
    "systematic_debugging",
    "multi_agent",
    "observability",
    "login",
    "authorize",
    "handoff",
    "resume_session",
    "set_session",
    "recall",
    "rewind",
    "crash_recovery",
    "checkpoint",
    "writing_skills",
}

ENFORCED_SKILLS = TIER3_INSTRUCTIONAL_SKILLS

CHECK_ONEX_RUN_DISPATCH = "ONEX_RUN_DISPATCH_IN_INSTRUCTIONAL_SKILL"
CHECK_RENDERED_OUTPUT = "RENDERED_OUTPUT_RECEIPT_IN_INSTRUCTIONAL_SKILL"
CHECK_MISSING_SKILL_MD = "MISSING_SKILL_MD"

SEVERITY_ERROR = "ERROR"

# Matches either ``onex run`` or ``onex run-node`` as an executable dispatch
# token (word-boundary on both sides). The trailing boundary prevents matches
# on hyphenated prose like "onex run-time" or "onex runbook".
_ONEX_RUN_RE = re.compile(
    r"\bonex\s+run(?:-node)?\b",
    re.IGNORECASE,
)

# ``rendered_output`` as a receipt-assertion field. Matches the bare token
# and access expressions (``result['rendered_output']``, ``.rendered_output``,
# ``"rendered_output":``). Word boundary on both sides so generic prose like
# "the output rendered" is not hit.
_RENDERED_OUTPUT_RE = re.compile(
    r"\brendered_output\b",
)


@dataclass
class InstructionalViolation:
    skill_name: str
    skill_path: str
    check: str
    severity: str
    line_number: int
    message: str

    def format_line(self) -> str:
        loc = self.skill_path
        if self.line_number > 0:
            loc = f"{loc}:{self.line_number}"
        return f"{loc}: [{self.severity}] {self.check}: {self.message}"


@dataclass
class ScanResult:
    skills_scanned: int = 0
    skills_with_violations: int = 0
    total_violations: int = 0
    violations: list[InstructionalViolation] = field(default_factory=list)


def _line_for_offset(content: str, offset: int) -> int:
    """Return the 1-indexed line number that the character at ``offset`` sits on."""
    return content.count("\n", 0, offset) + 1


def scan_skill(skill_path: Path) -> list[InstructionalViolation]:
    """Scan a single instructional SKILL.md and return any violations."""
    content = skill_path.read_text(encoding="utf-8")
    skill_name = skill_path.parent.name
    path_str = str(skill_path)
    violations: list[InstructionalViolation] = []

    for match in _ONEX_RUN_RE.finditer(content):
        violations.append(
            InstructionalViolation(
                skill_name=skill_name,
                skill_path=path_str,
                check=CHECK_ONEX_RUN_DISPATCH,
                severity=SEVERITY_ERROR,
                line_number=_line_for_offset(content, match.start()),
                message=(
                    "Instructional skill must not contain 'onex run' or "
                    "'onex run-node' dispatch commands. Dispatch belongs in "
                    "Tier 1 deterministic skills (see OMN-8749 / OMN-8765). "
                    "If this skill should dispatch, promote it into "
                    "TIER1_DETERMINISTIC_SKILLS and land a backing node."
                ),
            )
        )

    for match in _RENDERED_OUTPUT_RE.finditer(content):
        violations.append(
            InstructionalViolation(
                skill_name=skill_name,
                skill_path=path_str,
                check=CHECK_RENDERED_OUTPUT,
                severity=SEVERITY_ERROR,
                line_number=_line_for_offset(content, match.start()),
                message=(
                    "Instructional skill must not reference 'rendered_output' "
                    "receipt fields. Rendered-output evidence belongs in the "
                    "DoD contract of deterministic skills, not in pure-prose "
                    "instructional guidance."
                ),
            )
        )

    return violations


def scan_skills_root(skills_root: Path) -> ScanResult:
    result = ScanResult()
    for skill_name in sorted(ENFORCED_SKILLS):
        skill_file = skills_root / skill_name / "SKILL.md"
        if not skill_file.exists():
            result.violations.append(
                InstructionalViolation(
                    skill_name=skill_name,
                    skill_path=str(skill_file),
                    check=CHECK_MISSING_SKILL_MD,
                    severity=SEVERITY_ERROR,
                    line_number=0,
                    message=(
                        f"SKILL.md not found for instructional skill '{skill_name}'."
                    ),
                )
            )
            result.skills_scanned += 1
            result.skills_with_violations += 1
            result.total_violations += 1
            continue

        result.skills_scanned += 1
        violations = scan_skill(skill_file)
        if violations:
            result.skills_with_violations += 1
            result.total_violations += len(violations)
            result.violations.extend(violations)

    return result


def _print_result(result: ScanResult, report_mode: bool) -> None:
    if not result.violations:
        print(
            f"validate_instructional_skill_routing: OK — "
            f"{result.skills_scanned} Tier 3 instructional skills scanned, "
            f"0 violations."
        )
        return

    mode = "Report" if report_mode else "FAILED"
    print(
        f"\nvalidate_instructional_skill_routing: {mode} — "
        f"{result.total_violations} violation(s) in "
        f"{result.skills_with_violations} skill(s)\n"
    )

    for v in result.violations:
        print(f"  {v.format_line()}")

    if not report_mode:
        print(
            "\nInstructional (Tier 3) skills are pure-prose guidance surfaces.\n"
            "They must NOT contain:\n"
            "  1. 'onex run' or 'onex run-node' dispatch commands\n"
            "  2. 'rendered_output' receipt assertions\n"
            "\n"
            "If a skill should dispatch, promote it to Tier 1 deterministic\n"
            "(see OMN-8749 / OMN-8765): add it to TIER1_DETERMINISTIC_SKILLS,\n"
            "land a backing node, and add routing-error surface language.\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Tier 3 instructional skills stay pure-prose (no dispatch, no receipts).",
    )
    parser.add_argument(
        "--skills-root",
        default="plugins/onex/skills",
        help="Path to the skills directory (default: plugins/onex/skills)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print report without failing (exit 0 even on violations)",
    )
    parser.add_argument(
        "--skill",
        metavar="SKILL_NAME",
        help="Scan only the named skill",
    )
    args = parser.parse_args(argv)

    skills_root = Path(args.skills_root)
    if not skills_root.exists():
        print(f"ERROR: skills-root not found: {skills_root}", file=sys.stderr)
        return 1

    if args.skill:
        skill_file = skills_root / args.skill / "SKILL.md"
        if not skill_file.exists():
            print(
                f"ERROR: SKILL.md not found for skill '{args.skill}': {skill_file}",
                file=sys.stderr,
            )
            if args.report:
                return 0
            return 1
        violations = scan_skill(skill_file)
        result = ScanResult(
            skills_scanned=1,
            skills_with_violations=1 if violations else 0,
            total_violations=len(violations),
            violations=violations,
        )
    else:
        result = scan_skills_root(skills_root)

    _print_result(result, report_mode=args.report)

    if args.report:
        return 0
    return 1 if result.total_violations > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
