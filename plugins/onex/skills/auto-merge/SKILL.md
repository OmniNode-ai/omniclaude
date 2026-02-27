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
    description: "Shared wall-clock budget in hours for the entire merge flow (CI readiness poll + Slack gate reply poll combined). Default: 24. If either phase exhausts this budget, the skill exits with status: timeout."
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

## Merge Flow (Tier-Aware)

**Timeout model**: `gate_timeout_hours` is a single shared wall-clock budget for the entire flow (Steps 2 + 4 combined). A wall-clock start time is recorded on entry; each poll checks elapsed time against this budget. If the budget is exhausted in either phase, the skill exits with `status: timeout`.

### Step 1: Fetch PR State (Tier-Aware)

The merge readiness check depends on the current ONEX tier (see `@_lib/tier-routing/helpers.md`):

**FULL_ONEX Path**:
```python
from omniclaude.nodes.node_git_effect.models import GitOperation, ModelGitRequest

request = ModelGitRequest(
    operation=GitOperation.PR_VIEW,
    repo=repo,
    pr_number=pr_number,
    json_fields=["mergeable", "mergeStateStatus", "reviewDecision",
                 "statusCheckRollup", "latestReviews"],
)
result = await handler.pr_view(request)
```

**STANDALONE / EVENT_BUS Path**:
```bash
${CLAUDE_PLUGIN_ROOT}/_bin/pr-merge-readiness.sh --pr {pr_number} --repo {repo}
# Returns: { ready, mergeable, ci_status, review_decision, merge_state_status, blockers }
```

### Step 2: Poll CI Readiness

Poll CI readiness (check every 60s until `mergeStateStatus == "CLEAN"`; consumes from the shared `gate_timeout_hours` budget):
   - Each cycle: fetch `mergeable` and `mergeStateStatus`, log both fields:
     ```text
     [auto-merge] poll cycle {N}: mergeable={mergeable} mergeStateStatus={mergeStateStatus}
     ```
   - `mergeStateStatus == "CLEAN"`: exit poll loop, proceed to gate
   - `mergeStateStatus == "DIRTY"`: exit immediately with `status: error`, message: "PR has merge conflicts -- resolve before retrying"
   - `mergeStateStatus == "BEHIND"`, `"BLOCKED"`, `"UNSTABLE"`, `"HAS_HOOKS"`, or `"UNKNOWN"`: continue polling
   - Poll deadline exceeded (`gate_timeout_hours` elapsed): exit with `status: timeout`, message: "CI readiness poll timed out -- mergeStateStatus never reached CLEAN"

### Step 3: Post HIGH_RISK Slack Gate

Post HIGH_RISK Slack gate (see message format below).

### Step 4: Poll for Slack Reply

Poll for Slack reply (check every 5 minutes; this phase shares the same `gate_timeout_hours` budget started in Step 2):
   - On "merge" reply: execute merge (see Step 5)
   - On reject/hold reply (e.g., "hold", "cancel", "no"): exit with `status: held`
   - On budget exhausted: exit with `status: timeout`

### Step 5: Execute Merge (Explicit `gh` Exception)

**The merge mutation always uses `gh pr merge` directly** -- this is an explicit exception
to the tier routing policy. Rationale: the merge is a thin CLI call (single mutation, no
parsing of output needed). There is no benefit to routing through `node_git_effect.pr_merge()`
for this operation.

```bash
gh pr merge {pr_number} --repo {repo} --{strategy} {--delete-branch if delete_branch}
```

This exception is documented and intentional. All other PR operations (view, list, checks)
use tier-aware routing.

### Step 6: Post Merge Notification

Post Slack notification on merge completion.

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

## Tier Routing (OMN-2828)

PR merge readiness checks use tier-aware backend selection:

| Tier | Readiness Check | Merge Execution |
|------|----------------|-----------------|
| `FULL_ONEX` | `node_git_effect.pr_view()` | `gh pr merge` (explicit exception) |
| `STANDALONE` | `_bin/pr-merge-readiness.sh` | `gh pr merge` (explicit exception) |
| `EVENT_BUS` | `_bin/pr-merge-readiness.sh` | `gh pr merge` (explicit exception) |

**Merge execution exception**: The actual `gh pr merge` call is always direct -- it is a
thin mutation (single API call, no output parsing). Routing it through `node_git_effect`
adds complexity without benefit. This is the only exception to the tier routing policy.

Tier detection: see `@_lib/tier-routing/helpers.md`.

## See Also

- `ticket-pipeline` skill (invokes auto-merge after pr-watch passes)
- `pr-watch` skill (runs before auto-merge)
- `slack-gate` skill (LOW_RISK/MEDIUM_RISK/HIGH_RISK gate primitives)
- `_bin/pr-merge-readiness.sh` -- STANDALONE merge readiness backend
- `_lib/tier-routing/helpers.md` -- tier detection and routing helpers
- OMN-2525 -- implementation ticket
