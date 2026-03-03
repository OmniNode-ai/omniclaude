#!/usr/bin/env python3
"""Add level: and debug: frontmatter metadata to all skill SKILL.md files.

Reads existing frontmatter, adds level: and debug: after version: (or after description:
if no version:). Skips files with no closing --- boundary.
Overwrites existing level:/debug: if present.
"""

import re
import sys
from pathlib import Path

# Assignments from OMN-3452
ASSIGNMENTS: dict[str, tuple[str, bool]] = {
    # basic / debug=false
    "ticket-work": ("basic", False),
    "pr-review": ("basic", False),
    "pr-watch": ("basic", False),
    "ci-watch": ("basic", False),
    "local-review": ("basic", False),
    "linear": ("basic", False),
    "suggest-work": ("basic", False),
    "deep-dive": ("basic", False),
    "finishing-a-development-branch": ("basic", False),
    "verification-before-completion": ("basic", False),
    "test-driven-development": ("basic", False),
    "systematic-debugging": ("basic", False),
    "using-superpowers": ("basic", False),
    "brainstorming": ("basic", False),
    "writing-plans": ("basic", False),
    # intermediate / debug=false
    "ticket-pipeline": ("intermediate", False),
    "pr-review-dev": ("intermediate", False),
    "pr-release-ready": ("intermediate", False),
    "pr-polish": ("intermediate", False),
    "ci-failures": ("intermediate", False),
    "linear-triage": ("intermediate", False),
    "linear-housekeeping": ("intermediate", False),
    "linear-insights": ("intermediate", False),
    "decision-store": ("intermediate", False),
    "writing-skills": ("intermediate", False),
    "receiving-code-review": ("intermediate", False),
    "requesting-code-review": ("intermediate", False),
    "review-cycle": ("intermediate", False),
    "dispatching-parallel-agents": ("intermediate", False),
    "executing-plans": ("intermediate", False),
    "subagent-driven-development": ("intermediate", False),
    "parallel-solve": ("intermediate", False),
    "gap-analysis": ("intermediate", False),
    "gap-fix": ("intermediate", False),
    "gap-cycle": ("intermediate", False),
    "list-prs": ("intermediate", False),
    "create-followup-tickets": ("intermediate", False),
    "project-status": ("intermediate", False),
    "velocity-estimate": ("intermediate", False),
    "close-day": ("intermediate", False),
    # advanced / debug=false
    "epic-team": ("advanced", False),
    "ticket-plan": ("advanced", False),
    "ticket-plan-sync": ("advanced", False),
    "decompose-epic": ("advanced", False),
    "resume-epic": ("advanced", False),
    "linear-epic-org": ("advanced", False),
    "pipeline-audit": ("advanced", False),
    "pipeline-metrics": ("advanced", False),
    "golden-path-validate": ("advanced", False),
    "contract-compliance-check": ("advanced", False),
    "generate-ticket-contract": ("advanced", False),
    "rrh": ("advanced", False),
    "release": ("advanced", False),
    "redeploy": ("advanced", False),
    "curate-legacy": ("advanced", False),
    "generate-node": ("advanced", False),
    "plan-to-tickets": ("advanced", False),
    "plan-ticket": ("advanced", False),
    "fix-prs": ("advanced", False),
    "pr-queue-pipeline": ("advanced", False),
    "review-all-prs": ("advanced", False),
    "merge-sweep": ("advanced", False),
    "auto-merge": ("advanced", False),
    "sharing-skills": ("advanced", False),
    "testing-anti-patterns": ("advanced", False),
    "testing-skills-with-subagents": ("advanced", False),
    "condition-based-waiting": ("advanced", False),
    "defense-in-depth": ("advanced", False),
    # advanced / debug=true
    "status": ("advanced", True),
    "system-status": ("advanced", True),
    "agent-observability": ("advanced", True),
    "agent-tracking": ("advanced", True),
    "action-logging": ("advanced", True),
    "log-execution": ("advanced", True),
    "routing": ("advanced", True),
    "trace-correlation-id": ("advanced", True),
    "root-cause-tracing": ("advanced", True),
    "crash-recovery": ("advanced", True),
    "checkpoint": ("advanced", True),
    "gather-github-stats": ("advanced", True),
    "integration-gate": ("advanced", True),
    "deploy-local-plugin": ("advanced", True),
    "setup-statusline": ("advanced", True),
    "intelligence": ("advanced", True),
    "ultimate-validate": ("advanced", True),
    "runner-status": ("advanced", True),
    "runner-deploy": ("advanced", True),
    # Skills not in ticket spec — sensible defaults
    "ci-fix-pipeline": ("intermediate", False),
    "create-ticket": ("basic", False),
    "generate-tcb": ("advanced", False),
    "hostile-reviewer": ("intermediate", False),
    "mergeability-gate": ("advanced", False),
    "planning-context-resolver": ("intermediate", False),
    "slack-gate": ("advanced", False),
    "using-git-worktrees": ("basic", False),
}


def inject_frontmatter(content: str, level: str, debug: bool) -> str | None:
    """Inject level: and debug: into frontmatter. Returns None if no valid frontmatter."""
    if not content.startswith("---"):
        return None

    # Find the closing ---
    rest = content[3:]
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return None

    frontmatter_raw = rest[:end_idx]
    after_frontmatter = rest[end_idx:]  # starts with \n---

    # Remove existing level: and debug: lines
    lines = frontmatter_raw.split("\n")
    filtered = [
        line
        for line in lines
        if not re.match(r"^\s*level\s*:", line) and not re.match(r"^\s*debug\s*:", line)
    ]

    # Find insertion point: after version:, or after description:, or at end
    insert_after = None
    for i, line in enumerate(filtered):
        if re.match(r"^\s*version\s*:", line):
            insert_after = i
            break
    if insert_after is None:
        for i, line in enumerate(filtered):
            if re.match(r"^\s*description\s*:", line):
                insert_after = i
                break
    if insert_after is None:
        insert_after = len(filtered) - 1

    debug_str = "true" if debug else "false"
    new_lines = (
        filtered[: insert_after + 1]
        + [f"level: {level}", f"debug: {debug_str}"]
        + filtered[insert_after + 1 :]
    )

    new_frontmatter = "\n".join(new_lines)
    return "---" + new_frontmatter + after_frontmatter


def main() -> int:
    skills_root = Path(__file__).parent.parent / "plugins" / "onex" / "skills"
    updated = []
    skipped = []
    missing_assignment = []

    for skill_dir in sorted(skills_root.iterdir()):
        if skill_dir.name.startswith("_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        skill_name = skill_dir.name
        if skill_name not in ASSIGNMENTS:
            missing_assignment.append(skill_name)
            continue

        level, debug = ASSIGNMENTS[skill_name]
        content = skill_md.read_text(encoding="utf-8")
        new_content = inject_frontmatter(content, level, debug)

        if new_content is None:
            skipped.append(skill_name)
            continue

        if new_content != content:
            skill_md.write_text(new_content, encoding="utf-8")
            updated.append(skill_name)
        else:
            # Already has correct values
            updated.append(f"{skill_name} (unchanged)")

    print(f"Updated: {len(updated)} skills")
    for s in updated:
        print(f"  + {s}")

    if skipped:
        print(f"\nSkipped (no valid frontmatter): {skipped}")

    if missing_assignment:
        print(f"\nMissing from assignment table: {missing_assignment}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
