#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI validator: Deterministic Skill Routing Enforcement (OMN-8749, S2)

Verifies that every Tier 1 deterministic skill SKILL.md contains:
  1. A node dispatch command (``onex node`` or ``onex run-node``)
  2. ``SkillRoutingError`` error handling text
  3. No prose fallback instructions for routing failures

Skills missing their backing node (T1-07, T1-09, T1-14, T1-17, T1-19, T1-25)
are excluded via the ``MISSING_NODE_SKILLS`` set.

Exit codes:
  0  All deterministic skills pass routing enforcement
  1  One or more violations found

Usage:
  python scripts/validation/validate_deterministic_skill_routing.py
  python scripts/validation/validate_deterministic_skill_routing.py --report
  python scripts/validation/validate_deterministic_skill_routing.py --skills-root plugins/onex/skills

Linear: OMN-8749
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TIER1_DETERMINISTIC_SKILLS: set[str] = {
    "autopilot",
    "aislop_sweep",
    "build_loop",
    "ci_watch",
    "compliance_sweep",
    "contract_sweep",
    "dashboard_sweep",
    "data_flow_sweep",
    "golden_chain_sweep",
    "merge_sweep",
    "overnight",
    "pipeline_fill",
    "platform_readiness",
    "pr_review",
    "pr_review_bot",
    "redeploy",
    "release",
    "runtime_sweep",
    "session",
    "start_environment",
    "verify_plugin",
}

MISSING_NODE_SKILLS: set[str] = {
    "bus_audit",
    "dod_sweep",
    "env_parity",
    "gap",
    "integration_sweep",
    "pr_watch",
}

DEPRECATED_SKILLS: set[str] = set()

ENFORCED_SKILLS = TIER1_DETERMINISTIC_SKILLS

CHECK_DISPATCH = "MISSING_DISPATCH"
CHECK_ROUTING_ERROR = "MISSING_SKILL_ROUTING_ERROR"
CHECK_PROSE_FALLBACK = "PROSE_FALLBACK"

SEVERITY_ERROR = "ERROR"

_DISPATCH_RE = re.compile(
    r"(?:"
    r"onex\s+(?:run-node|node)\s+\w+"
    r"|"
    r"(?:publish(?:es)?|send(?:s)?)(?:\s+\w+){0,6}?\s+(?:to\s+)?`?onex\.cmd\.\w+"
    r"|"
    r"`?onex\.cmd\.\w+[`\s]+(?:\w+\s+){0,6}?(?:publish(?:ed)?|sent)"
    r"|"
    r"Kafka\s+publish"
    r")",
    re.IGNORECASE,
)
_ROUTING_ERROR_RE = re.compile(r"SkillRoutingError", re.IGNORECASE)
_NO_PROSE_RE = re.compile(r"do not produce prose", re.IGNORECASE)

_PROSE_FALLBACK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:fallback|degrade|degradation).*?(?:prose|claude|llm|advisory)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:if|when).*?(?:node|service).*?(?:unavailable|down|fails?).{0,40}?(?:prose|claude|just|simply|write|respond)",
        re.IGNORECASE,
    ),
]


@dataclass
class RoutingViolation:
    skill_name: str
    skill_path: str
    check: str
    severity: str
    message: str

    def format_line(self) -> str:
        return f"{self.skill_path}: [{self.severity}] {self.check}: {self.message}"


@dataclass
class ScanResult:
    skills_scanned: int = 0
    skills_with_violations: int = 0
    total_violations: int = 0
    violations: list[RoutingViolation] = field(default_factory=list)


def scan_skill(skill_path: Path) -> list[RoutingViolation]:
    content = skill_path.read_text(encoding="utf-8")
    skill_name = skill_path.parent.name
    path_str = str(skill_path)
    violations: list[RoutingViolation] = []

    if not _DISPATCH_RE.search(content):
        violations.append(
            RoutingViolation(
                skill_name=skill_name,
                skill_path=path_str,
                check=CHECK_DISPATCH,
                severity=SEVERITY_ERROR,
                message=(
                    "Deterministic skill must contain a node dispatch command "
                    "('onex node <name>' or 'onex run-node <name>')."
                ),
            )
        )

    if not _ROUTING_ERROR_RE.search(content):
        violations.append(
            RoutingViolation(
                skill_name=skill_name,
                skill_path=path_str,
                check=CHECK_ROUTING_ERROR,
                severity=SEVERITY_ERROR,
                message=(
                    "Deterministic skill must reference 'SkillRoutingError' "
                    "with instruction to surface it directly, not produce prose."
                ),
            )
        )

    has_routing_error = _ROUTING_ERROR_RE.search(content) is not None
    has_no_prose = _NO_PROSE_RE.search(content) is not None
    if has_routing_error and not has_no_prose:
        violations.append(
            RoutingViolation(
                skill_name=skill_name,
                skill_path=path_str,
                check=CHECK_PROSE_FALLBACK,
                severity=SEVERITY_ERROR,
                message=(
                    "Skill references SkillRoutingError but missing "
                    "'do not produce prose' instruction."
                ),
            )
        )

    for pattern in _PROSE_FALLBACK_PATTERNS:
        if pattern.search(content):
            violations.append(
                RoutingViolation(
                    skill_name=skill_name,
                    skill_path=path_str,
                    check=CHECK_PROSE_FALLBACK,
                    severity=SEVERITY_ERROR,
                    message=(
                        "Deterministic skill must not contain prose fallback "
                        "instructions for routing failures."
                    ),
                )
            )
            break

    return violations


def scan_skills_root(skills_root: Path) -> ScanResult:
    result = ScanResult()
    for skill_name in sorted(ENFORCED_SKILLS):
        skill_file = skills_root / skill_name / "SKILL.md"
        if not skill_file.exists():
            result.violations.append(
                RoutingViolation(
                    skill_name=skill_name,
                    skill_path=str(skill_file),
                    check="MISSING_SKILL_MD",
                    severity=SEVERITY_ERROR,
                    message=f"SKILL.md not found for deterministic skill '{skill_name}'.",
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
            f"validate_deterministic_skill_routing: OK — "
            f"{result.skills_scanned} Tier 1 skills scanned, 0 violations."
        )
        return

    mode = "Report" if report_mode else "FAILED"
    print(
        f"\nvalidate_deterministic_skill_routing: {mode} — "
        f"{result.total_violations} violation(s) in "
        f"{result.skills_with_violations} skill(s)\n"
    )

    for v in result.violations:
        print(f"  {v.format_line()}")

    if not report_mode:
        print(
            "\nEach Tier 1 deterministic skill must:\n"
            "  1. Contain a dispatch command: onex node <name> or onex run-node <name>\n"
            "  2. Reference SkillRoutingError with 'do not produce prose'\n"
            "  3. Not contain prose fallback instructions for routing failures\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Tier 1 deterministic skills have routing enforcement."
    )
    parser.add_argument(
        "--skills-root",
        default="plugins/onex/skills",
        help="Path to the skills directory (default: plugins/onex/skills)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print report without failing CI (exit 0 even on violations)",
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
