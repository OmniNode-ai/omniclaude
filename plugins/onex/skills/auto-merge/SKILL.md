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

1. Fetch PR state: `gh pr view {pr_number} --repo {repo} --json mergeable,mergeStateStatus,reviews`
2. Poll CI readiness (check every 60s until `mergeStateStatus == "CLEAN"`; max duration: `gate_timeout_hours`):
   - Each cycle: fetch `mergeable` and `mergeStateStatus`, log both fields:
     ```text
     [auto-merge] poll cycle {N}: mergeable={mergeable} mergeStateStatus={mergeStateStatus}
     ```
   - `mergeStateStatus == "CLEAN"`: exit poll loop, proceed to gate
   - `mergeStateStatus == "DIRTY"`: exit immediately with `status: error`, message: "PR has merge conflicts — resolve before retrying"
   - `mergeStateStatus == "BEHIND"`, `"BLOCKED"`, `"UNSTABLE"`, `"HAS_HOOKS"`, or `"UNKNOWN"`: continue polling
   - Poll deadline exceeded (`gate_timeout_hours` elapsed): exit with `status: timeout`, message: "CI readiness poll timed out — mergeStateStatus never reached CLEAN"
3. Post HIGH_RISK Slack gate (see message format below)
4. Poll for reply (check every 5 minutes):
   - On "merge" reply: execute merge via `gh pr merge {pr_number} --repo {repo} --{strategy}{delete_branch_flag}` where `{delete_branch_flag}` is `--delete-branch` (with a leading space) if `delete_branch=true`, else empty
   - On reject/hold reply (e.g., "hold", "cancel", "no"): exit with `status: held`
   - On timeout: exit with `status: timeout`
5. Post Slack notification on merge completion

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
- `timeout`: `gate_timeout_hours` elapsed — either CI readiness poll never reached CLEAN, or Slack gate received no "merge" reply
- `error`: Merge failed — includes:
  - `mergeStateStatus == "DIRTY"`: message "PR has merge conflicts — resolve before retrying"
  - Permissions error, API failure, or other terminal failure

## Executable Scripts

### `auto-merge.sh`

Bash wrapper for programmatic invocation of this skill.

```bash
#!/usr/bin/env bash
set -euo pipefail

# auto-merge.sh — wrapper for the auto-merge skill
# Usage: auto-merge.sh <PR_NUMBER> <REPO> [--strategy squash|merge|rebase] [--gate-timeout-hours N] [--no-delete-branch]

PR_NUMBER=""
REPO=""
STRATEGY="squash"
GATE_TIMEOUT_HOURS="24"
DELETE_BRANCH="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strategy)            STRATEGY="$2";            shift 2 ;;
    --gate-timeout-hours)  GATE_TIMEOUT_HOURS="$2";  shift 2 ;;
    --no-delete-branch)    DELETE_BRANCH="false";     shift   ;;
    -*)  echo "Unknown flag: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$PR_NUMBER" ]]; then PR_NUMBER="$1"; shift
      elif [[ -z "$REPO" ]];     then REPO="$1";      shift
      else echo "Unexpected argument: $1" >&2; exit 1
      fi
      ;;
  esac
done

if [[ -z "$PR_NUMBER" || -z "$REPO" ]]; then
  echo "Usage: auto-merge.sh <PR_NUMBER> <REPO> [options]" >&2
  exit 1
fi

exec claude --skill onex:auto-merge \
  --arg "pr_number=${PR_NUMBER}" \
  --arg "repo=${REPO}" \
  --arg "strategy=${STRATEGY}" \
  --arg "gate_timeout_hours=${GATE_TIMEOUT_HOURS}" \
  --arg "delete_branch=${DELETE_BRANCH}"
```

| Invocation | Description |
|------------|-------------|
| `/auto-merge 123 org/repo` | Interactive: merge PR 123 with default HIGH_RISK gate (24h timeout) |
| `/auto-merge 123 org/repo --strategy merge` | Interactive: use merge commit strategy |
| `Skill(skill="onex:auto-merge", args="123 org/repo --gate-timeout-hours 48")` | Programmatic: composable invocation from orchestrator |
| `auto-merge.sh 123 org/repo --no-delete-branch` | Shell: direct invocation, keep branch after merge |

## See Also

- `ticket-pipeline` skill (planned: invokes auto-merge after pr-watch passes)
- `pr-watch` skill (planned: runs before auto-merge)
- `slack-gate` skill (LOW_RISK/MEDIUM_RISK/HIGH_RISK gate primitives)
- OMN-2525 — implementation ticket
