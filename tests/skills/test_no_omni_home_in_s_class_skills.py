# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-8791: Assert zero $OMNI_HOME references remain in S-class skill files."""

import re
from pathlib import Path

import pytest

# S-class skills per docs/plans/2026-04-14-standalone-plugin-distribution.md
# These are standalone-capable skills that must not reference $OMNI_HOME.
S_CLASS_SKILLS = [
    "adversarial_pipeline",
    "agent_healthcheck",
    "auto_merge",
    "authorize",
    "baseline",
    "checkpoint",
    "ci_watch",
    "coderabbit_triage",
    "create_followup_tickets",
    "create_ticket",
    "decision_store",
    "dep_cascade_dedup",
    "design_to_plan",
    "dispatch_watchdog",
    "dispatch_worker",
    "duplication_sweep",
    "executing_plans",
    "friction_triage",
    "handoff",
    "hostile_reviewer",
    "insights_to_plan",
    "linear_epic_org",
    "linear_housekeeping",
    "linear_insights",
    "linear_triage",
    "login",
    "merge_sweep",
    "pipeline_fill",
    "plan_audit",
    "plan_to_tickets",
    "pr_polish",
    "pr_review",
    "pr_review_bot",
    "pr_watch",
    "preflight",
    "recall",
    "record_friction",
    "rewind",
    "set_session",
    "systematic_debugging",
    "ticket_plan",
    "using_git_worktrees",
    "wave_scheduler",
    "writing_skills",
]

SKILLS_ROOT = Path(__file__).parents[2] / "plugins" / "onex" / "skills"
OMNI_HOME_PATTERN = re.compile(r"\$OMNI_HOME|\$\{OMNI_HOME[^}]*\}|omni_home/")


def _skill_files(skill_name: str) -> list[Path]:
    skill_dir = SKILLS_ROOT / skill_name
    return list(skill_dir.glob("*.md")) if skill_dir.exists() else []


@pytest.mark.unit
def test_no_omni_home_refs_in_s_class_skills() -> None:
    offenders: list[str] = []
    for skill_name in S_CLASS_SKILLS:
        for md_file in _skill_files(skill_name):
            text = md_file.read_text()
            lines = [
                f"  line {i + 1}: {line.rstrip()}"
                for i, line in enumerate(text.splitlines())
                if OMNI_HOME_PATTERN.search(line)
            ]
            if lines:
                offenders.append(
                    f"{md_file.relative_to(SKILLS_ROOT.parents[2])}:\n"
                    + "\n".join(lines)
                )
    assert not offenders, (
        f"$OMNI_HOME found in {len(offenders)} S-class skill file(s):\n\n"
        + "\n\n".join(offenders)
    )
