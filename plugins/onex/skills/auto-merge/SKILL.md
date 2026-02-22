---
name: auto-merge
description: Merge a GitHub PR when all gates pass; uses Slack HIGH_RISK gate by default
version: 1.0.0
category: workflow
tags: [pr, github, merge, automation, slack-gate]
author: OmniClaude Team
composable: true
inputs:
  - name: pr_number
    type: int
    description: GitHub PR number to merge
    required: true
  - name: repo
    type: str
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: strategy
    type: str
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: gate_timeout_hours
    type: float
    description: Hours to wait for Slack gate approval (default 24)
    required: false
  - name: delete_branch
    type: bool
    description: Delete branch after merge (default true)
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/auto-merge.json"
    fields:
      - status: merged | held | timeout | error
      - pr_number: int
      - repo: str
      - merge_commit: str | null
      - strategy: str
args:
  - name: pr_number
    description: GitHub PR number to merge
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --strategy
    description: "Merge strategy: squash|merge|rebase (default squash)"
    required: false
  - name: --gate-timeout-hours
    description: Hours to wait for Slack approval (default 24)
    required: false
  - name: --no-delete-branch
    description: Don't delete branch after merge
    required: false
---

# Auto Merge

## Overview

Merge a GitHub PR after posting a Slack HIGH_RISK gate. A human must reply "merge" to proceed.
Silence does NOT consent — this gate requires explicit approval. Exit when PR is merged, held,
or timed out.

**Announce at start:** "I'm using the auto-merge skill to merge PR #{pr_number}."

**Implements**: OMN-2525

## Quick Start

```
/auto-merge 123 org/repo
/auto-merge 123 org/repo --strategy merge
/auto-merge 123 org/repo --gate-timeout-hours 48
/auto-merge 123 org/repo --no-delete-branch
```

## Merge Flow

1. Verify PR is mergeable: `gh pr view {pr_number} --repo {repo} --json mergeable,reviews`
2. Post HIGH_RISK Slack gate (see message format below)
3. Poll for reply (check every 5 minutes):
   - On "merge" reply: execute merge via `gh pr merge {pr_number} --repo {repo} --{strategy}{delete_branch_flag}` where `{delete_branch_flag}` is ` --delete-branch` if `delete_branch=true`, else empty
   - On reject/hold reply (e.g., "hold", "cancel", "no"): exit with `status: held`
   - On timeout: exit with `status: timeout`
4. Post Slack notification on merge completion

## Slack Gate Message Format

```
[HIGH_RISK] auto-merge: Ready to merge PR #{pr_number}

Repo: {repo}
PR: {pr_title}
Strategy: {strategy}
Branch: {branch_name}

All gates passed:
  CI: passed
  PR Review: approved (or changes resolved)

Reply "merge" to proceed. Silence = HOLD (this gate requires explicit approval).
Gate expires in {gate_timeout_hours}h.
```

## Skill Result Output

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/auto-merge.json` on exit.

```json
{
  "skill": "auto-merge",
  "status": "merged",
  "pr_number": 123,
  "repo": "org/repo",
  "merge_commit": "abc1234",
  "strategy": "squash",
  "context_id": "{context_id}"
}
```

**Status values**: `merged` | `held` | `timeout` | `error`

- `merged`: PR successfully merged
- `held`: Human explicitly replied with a hold/reject word
- `timeout`: gate_timeout_hours elapsed with no "merge" reply
- `error`: Merge failed (conflicts, permissions, etc.)

## See Also

- `ticket-pipeline` skill (invokes auto-merge as Phase 6)
- `pr-watch` skill (Phase 5, runs before auto-merge)
- `slack-gate` skill (LOW_RISK/MEDIUM_RISK/HIGH_RISK gate primitives)
- OMN-2525 — implementation ticket
