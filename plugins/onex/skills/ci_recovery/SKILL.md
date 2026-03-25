---
description: Poll all open PRs, classify CI failures, apply remediation, generate per-cycle reports
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags: [ci, recovery, overnight, automation]
args:
  - name: --repos
    description: Comma-separated repo slugs to scan (default all OmniNode-ai repos)
    required: false
  - name: --dry-run
    description: Classify failures without applying fixes
    required: false
  - name: --max-fixes-per-cycle
    description: Max fix attempts across all PRs per cycle (default 10)
    required: false
---

# CI Recovery

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT read
files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run ci-recovery",
  prompt="Run the ci-recovery skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

Overnight CI recovery skill that polls all open PRs across OmniNode repos, classifies CI
failures into actionable categories, applies automated remediation, and generates structured
per-cycle reports. Designed to run as a scheduled agent via launchd
(`scripts/ci-recovery-overnight.plist`).

**Announce at start:** "I'm using the ci-recovery skill to scan and fix CI failures across open PRs."

## Failure Classification

| Classification | Heuristic | Remediation |
|----------------|-----------|-------------|
| `flaky_test` | Test name in known-flaky list OR same test passed on re-run within last 7 days | `gh run rerun {run_id} --failed --repo {repo}` |
| `infra_issue` | Log contains: runner, timeout, network, connection refused, 503, lost connection | `gh run rerun {run_id} --repo {repo}` (full re-run) |
| `config_error` | Log contains: lock file, uv.lock, version mismatch, missing dependency | Dispatch `Skill(skill="onex:ci-fix-pipeline", args="--pr {N} --ticket-id {T}")` |
| `real_failure` | None of the above patterns match | Dispatch `Skill(skill="onex:ci-fix-pipeline", args="--pr {N} --ticket-id {T}")` |

Classification is case-insensitive. The classifier module lives at
`plugins/onex/skills/_lib/ci_recovery/classifier.py`.

## Execution Flow

```
ci-recovery [--repos org/repo1,org/repo2] [--dry-run] [--max-fixes-per-cycle 10]
  -> List all open PRs: gh pr list --state open --json number,headRefName,statusCheckRollup
  -> For each PR with failing CI:
      -> Extract failure log: gh run view --log-failed
      -> Classify failure (flaky_test | infra_issue | config_error | real_failure)
      -> Apply remediation (rerun | fix dispatch)
      -> Record classification and action
  -> Write per-cycle report to ~/.claude/ci-recovery/reports/YYYY-MM-DD-HHMMSS.json
  -> Write skill result to ~/.claude/skill-results/{context_id}/ci-recovery.json
```

## Report Schema

```json
{
  "cycle_id": "ci-recovery-2026-03-25-030000",
  "started_at": "2026-03-25T03:00:00Z",
  "completed_at": "2026-03-25T03:15:00Z",
  "prs_scanned": 12,
  "prs_failing": 3,
  "classifications": [
    {"pr": 123, "repo": "OmniNode-ai/omniclaude", "class": "flaky_test", "action": "rerun", "result": "triggered"},
    {"pr": 456, "repo": "OmniNode-ai/omnibase_core", "class": "real_failure", "action": "fix_dispatched", "result": "pending"}
  ],
  "fixes_applied": 2,
  "fixes_remaining": 1
}
```

## Skill Result Output

**Output contract:** `ModelSkillResult` from `omnibase_core.models.skill`

Write to: `~/.claude/skill-results/{context_id}/ci-recovery.json`

| Field | Value |
|-------|-------|
| `skill_name` | `"ci-recovery"` |
| `status` | `"success"` / `"partial"` / `"error"` |
| `extra_status` | `"all_green"` / `"fixes_applied"` / `"fixes_remaining"` |
| `extra` | `{"prs_scanned": int, "prs_failing": int, "fixes_applied": int, "fixes_remaining": int}` |

## Scheduling

Use `scripts/ci-recovery-overnight.plist` (from PR #883) as the launchd scheduler.
The plist runs `claude -p "Run /onex:ci-recovery"` at configured intervals.

## See Also

- `prompt.md` -- authoritative behavioral specification
- `ci_watch` skill -- per-PR CI watching (composable sub-skill)
- `ci_fix_pipeline` skill -- targeted CI fix dispatch
- `node_ci_repair_effect.py` -- ONEX effect node for CI repair strategy rotation
- `scripts/ci-recovery-overnight.plist` -- launchd scheduler
