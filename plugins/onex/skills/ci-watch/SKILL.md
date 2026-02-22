---
name: ci-watch
description: Poll GitHub Actions CI for a PR, auto-fix failures, and report terminal state
version: 1.0.0
category: workflow
tags: [ci, github-actions, automation, polling]
author: OmniClaude Team
composable: true
inputs:
  - name: pr_number
    type: int
    description: GitHub PR number to watch
    required: true
  - name: repo
    type: str
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: timeout_minutes
    type: int
    description: Max minutes to wait for CI (default 60)
    required: false
  - name: max_fix_cycles
    type: int
    description: Max auto-fix attempts before escalating (default 3)
    required: false
  - name: auto_fix
    type: bool
    description: Auto-fix CI failures (default true)
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/ci-watch.json"
    fields:
      - status: passed | capped | timeout | error
      - pr_number: int
      - repo: str
      - fix_cycles_used: int
      - elapsed_minutes: int
args:
  - name: pr_number
    description: GitHub PR number to watch
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --timeout-minutes
    description: Max minutes to wait for CI (default 60)
    required: false
  - name: --max-fix-cycles
    description: Max auto-fix cycles before escalating (default 3)
    required: false
  - name: --no-auto-fix
    description: Poll only, don't attempt fixes
    required: false
---

# CI Watch

## Overview

Poll GitHub Actions CI status for a pull request. Auto-fix test/lint failures and re-push. Exit
when CI reaches a terminal state: `passed`, `capped` (fix cycles exhausted), `timeout`, or `error`.

**Announce at start:** "I'm using the ci-watch skill to monitor CI for PR #{pr_number}."

**Implements**: OMN-2523

## Quick Start

```
/ci-watch 123 org/repo
/ci-watch 123 org/repo --timeout-minutes 30
/ci-watch 123 org/repo --max-fix-cycles 5
/ci-watch 123 org/repo --no-auto-fix
```

## Poll Loop

1. Fetch CI status via `gh pr checks {pr_number} --repo {repo} --json name,state,conclusion`
2. If all checks pass: exit with `status: passed`
3. If any check failed and `auto_fix=true` and cycles remaining:
   - Dispatch fix agent (polymorphic-agent) with failure details
   - Increment fix cycle count
   - Wait 30s, then re-poll
4. If fix cycles exhausted: exit with `status: capped`
5. If elapsed > timeout_minutes: exit with `status: timeout`

## Fix Dispatch Contract

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-watch: fix CI failure (cycle {cycle}/{max_cycles})",
  prompt="CI check '{check_name}' failed for PR #{pr_number} in {repo}.

    Failure details:
    {failure_log}

    Fix the failure. Do NOT create a new PR — commit and push to the existing branch.
    Branch: {branch_name}

    Report: what was fixed, files changed, confidence level."
)
```

## Skill Result Output

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/ci-watch.json` on exit.

```json
{
  "skill": "ci-watch",
  "status": "passed",
  "pr_number": 123,
  "repo": "org/repo",
  "fix_cycles_used": 1,
  "elapsed_minutes": 12,
  "context_id": "{context_id}"
}
```

**Status values**: `passed` | `capped` | `timeout` | `error`

- `passed`: All CI checks green
- `capped`: Reached max_fix_cycles without CI passing
- `timeout`: CI still running after timeout_minutes
- `error`: Unexpected error (API failure, auth issue)

## See Also

- `ticket-pipeline` skill (planned: invokes ci-watch after create_pr phase)
- `pr-watch` skill (planned: runs after ci-watch passes)
- OMN-2523 — implementation ticket
