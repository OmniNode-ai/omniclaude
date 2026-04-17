# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SD-05 enforcement: R-class skill shims must use onex run-node, not uv run python -m omni*.

DoD gate for OMN-8792: zero `uv run python -m omnimarket.*` or
`uv run python -m omnibase_infra.*` references in R-class skill files.
"""

import re
from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills"

# 47 R-class skills per SD-05 plan (§ 5.2)
R_CLASS_SKILLS = {
    "aislop_sweep",
    "agent_healthcheck",
    "autopilot",
    "baseline",
    "begin_day",
    "build_loop",
    "bus_audit",
    "checkpoint",
    "compliance_sweep",
    "contract_sweep",
    "coverage_sweep",
    "crash_recovery",
    "dashboard_sweep",
    "data_flow_sweep",
    "database_sweep",
    "decompose_epic",
    "delegate",
    "demo",
    "dispatch_worker",
    "dod_sweep",
    "dod_verify",
    "duplication_sweep",
    "env_parity",
    "epic_team",
    "feature_dashboard",
    "gap",
    "generate_node",
    "golden_chain_sweep",
    "hook_health_alert",
    "integration_sweep",
    "local_review",
    "multi_agent",
    "observability",
    "onboarding",
    "overnight",
    "pipeline_audit",
    "pipeline_fill",
    "platform_readiness",
    "redeploy",
    "refill_sprint",
    "release",
    "resume_session",
    "runtime_sweep",
    "session",
    "start_environment",
    "tech_debt_sweep",
    "ticket_pipeline",
    "ticket_work",
    "verification_sweep",
    "verify_plugin",
}

# Patterns forbidden in R-class skill files after SD-05 conversion
FORBIDDEN_PATTERNS = [
    re.compile(r"uv run python -m omnimarket"),
    re.compile(r"uv run python -m omnibase_infra"),
    re.compile(r"uv run python -m omnibase_core"),
]

# Files to scan within each skill directory (SKILL.md and any prompt.md)
SCAN_GLOBS = ["SKILL.md", "prompt.md", "*.md"]


def _collect_violations() -> list[tuple[str, str, str]]:
    """Return list of (skill, file, matched_line) for every violation."""
    violations = []
    for skill in sorted(R_CLASS_SKILLS):
        skill_dir = SKILLS_ROOT / skill
        if not skill_dir.exists():
            continue
        for md_file in skill_dir.glob("*.md"):
            text = md_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                for pat in FORBIDDEN_PATTERNS:
                    if pat.search(line):
                        violations.append(
                            (skill, f"{md_file.name}:{lineno}", line.strip())
                        )
    return violations


@pytest.mark.parametrize("skill", sorted(R_CLASS_SKILLS))
def test_r_class_skill_directory_exists(skill: str) -> None:
    assert (SKILLS_ROOT / skill).exists(), f"R-class skill directory missing: {skill}"


def test_zero_uv_run_python_in_r_class_skills() -> None:
    """SD-05 DoD: zero uv run python -m omni* in any R-class SKILL.md or prompt.md."""
    violations = _collect_violations()
    if violations:
        lines = [f"  {skill} / {fname}: {line}" for skill, fname, line in violations]
        msg = (
            f"{len(violations)} forbidden pattern(s) found in R-class skills:\n"
            + "\n".join(lines)
        )
        pytest.fail(msg)
