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
  - name: ticket_id
    type: str
    description: "Linear ticket identifier (e.g. OMN-1234) to mark Done after merge (optional)"
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
  - name: --ticket-id
    description: Linear ticket ID to mark Done after merge (e.g. OMN-1234)
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

## CDQA Pre-Condition (Mandatory)

**CDQA gates must pass before any merge proceeds. This requirement applies on all invocation
paths — whether called from ticket-pipeline or directly.**

When invoked from `ticket-pipeline`: CDQA gates run in Phase 5.5 before this skill is
dispatched. The gate log is written to `~/.claude/skill-results/{context_id}/cdqa-gate-log.json`.

When invoked directly (not from ticket-pipeline): this skill MUST run the CDQA gates itself
before executing the merge mutation.

### Direct Invocation: CDQA gate check

```
1. Read: ~/.claude/skill-results/{context_id}/cdqa-gate-log.json
   If record exists with overall=PASS or overall=bypassed AND pr_number matches:
     → skip re-run, proceed to Step 1
   If no matching record:
     → run all 3 CDQA gates (see @_lib/cdqa-gate/helpers.md)
     → BLOCK result: post HIGH_RISK bypass gate, await operator reply
     → BLOCK + held/timeout: exit with status: held
     → all PASS or bypassed: proceed to Step 1
```

**There is no `--skip-cdqa` flag.** Bypassing CDQA requires the explicit Slack bypass
protocol documented in `@_lib/cdqa-gate/helpers.md`. Any attempt to invoke auto-merge
without CDQA gates passing (or a recorded bypass) must exit with `status: error` and
message: `"CDQA gates not passed — run contract-compliance-check and verify CI gates"`.

---

## Merge Flow (Tier-Aware)

**Timeout model**: `gate_timeout_hours` is a single shared wall-clock budget for the entire flow (Steps 2 + 4 combined). A wall-clock start time is recorded on entry; each poll checks elapsed time against this budget. If the budget is exhausted in either phase, the skill exits with `status: timeout`.

### Step 1: Fetch PR State (Tier-Aware) <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

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

### Step 2: Poll CI Readiness <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Poll CI readiness (check every 60s until `mergeStateStatus == "CLEAN"`; consumes from the shared `gate_timeout_hours` budget):
   - Each cycle: fetch `mergeable` and `mergeStateStatus`, log both fields:
     ```text
     [auto-merge] poll cycle {N}: mergeable={mergeable} mergeStateStatus={mergeStateStatus}
     ```
   - `mergeStateStatus == "CLEAN"`: exit poll loop, proceed to gate
   - `mergeStateStatus == "DIRTY"`: exit immediately with `status: error`, message: "PR has merge conflicts -- resolve before retrying"
   - `mergeStateStatus == "BEHIND"`, `"BLOCKED"`, `"UNSTABLE"`, `"HAS_HOOKS"`, or `"UNKNOWN"`: continue polling
   - Poll deadline exceeded (`gate_timeout_hours` elapsed): exit with `status: timeout`, message: "CI readiness poll timed out -- mergeStateStatus never reached CLEAN"

### Step 3: Post HIGH_RISK Slack Gate <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Post HIGH_RISK Slack gate (see message format below).

### Step 4: Poll for Slack Reply <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Poll for Slack reply (check every 5 minutes; this phase shares the same `gate_timeout_hours` budget started in Step 2):
   - On "merge" reply: execute merge (see Step 5)
   - On reject/hold reply (e.g., "hold", "cancel", "no"): exit with `status: held`
   - On budget exhausted: exit with `status: timeout`

### Step 5: Execute Merge (Explicit `gh` Exception) <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

**The merge mutation always uses `gh pr merge` directly** -- this is an explicit exception
to the tier routing policy. Rationale: the merge is a thin CLI call (single mutation, no
parsing of output needed). There is no benefit to routing through `node_git_effect.pr_merge()`
for this operation.

```bash
gh pr merge {pr_number} --repo {repo} --{strategy} {--delete-branch if delete_branch}
```

This exception is documented and intentional. All other PR operations (view, list, checks)
use tier-aware routing.

### Step 6: Post Merge Notification and Close Linear Ticket <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

After a successful merge:

1. **Post Slack notification** on merge completion.
2. **Close Linear ticket** (if `ticket_id` is available in context — passed by `ticket-pipeline`):
   ```python
   if ticket_id:
       try:
           mcp__linear-server__save_issue(id=ticket_id, state="Done")
       except Exception as e:
           print(f"[auto-merge] Warning: Could not mark {ticket_id} as Done: {e}")
           # Non-blocking: merge already succeeded; do not fail the skill
   ```
   This is a belt-and-suspenders step. The primary path (`ticket-pipeline` Phase 6)
   also marks the ticket Done. If the pipeline session ended before the merge (e.g.
   CI was still running), the `linear-close-on-merge` GitHub Actions workflow
   (`.github/workflows/linear-close-on-merge.yml`) provides a third fallback.

**Ticket ID resolution order:**
1. Passed explicitly as `--ticket-id OMN-XXXX` argument
2. Extracted from PR branch name via `OMN-XXXX` pattern (fallback if `--ticket-id` not provided)
3. Skip update if neither resolves to a valid ID

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

- `ticket-pipeline` skill (invokes auto-merge after cdqa_gate Phase 5.5 passes)
- `pr-watch` skill (runs before auto-merge; Phase 5 in ticket-pipeline)
- `contract-compliance-check` skill (CDQA Gate 1, OMN-2978)
- `_lib/cdqa-gate/helpers.md` (CDQA gate protocol, bypass flow, result schema — OMN-3189)
- `slack-gate` skill (LOW_RISK/MEDIUM_RISK/HIGH_RISK gate primitives)
- `_bin/pr-merge-readiness.sh` -- STANDALONE merge readiness backend
- `_lib/tier-routing/helpers.md` -- tier detection and routing helpers
- OMN-2525 -- implementation ticket
- OMN-3189 -- CDQA gate enforcement ticket
