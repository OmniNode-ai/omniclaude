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

## Watch Loop

Use `gh run watch` to block until CI completes. Reacts immediately when the run finishes —
no fixed polling interval.

1. Get PR head branch and latest run ID:
   ```bash
   BRANCH=$(gh pr view {pr_number} --repo {repo} --json headRefName -q '.headRefName')
   RUN_ID=$(gh run list --branch "$BRANCH" --repo {repo} -L 1 --json databaseId -q '.[0].databaseId')
   ```
   If no run found yet: wait 30s and retry (up to 5 attempts).

2. Block until run completes:
   ```bash
   gh run watch "$RUN_ID" --repo {repo} --exit-status
   EXIT_CODE=$?
   ```

3. If exit code 0: all checks passed → exit with `status: passed`

4. If exit code non-zero and `auto_fix=true` and cycles remaining:
   - Fetch failure log: `gh run view "$RUN_ID" --repo {repo} --log-failed`
   - Dispatch fix agent (polymorphic-agent) with failure details
   - Increment fix cycle count
   - Wait up to 60s for a new CI run to appear on the branch, then go to step 1
5. If fix cycles exhausted: exit with `status: capped`
6. If elapsed > timeout_minutes: exit with `status: timeout`

## Fix Dispatch Contract

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="ci-watch: auto-fix CI failures on PR #{pr_number} (cycle {N})",
  prompt="Invoke: Skill(skill=\"ci-fix-pipeline\",
    args=\"--pr {pr_number} --ticket-id {ticket_id}\")

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

| Error | Behavior |
|-------|----------|
| `gh pr checks` unavailable | Retry 3x, then `status: failed` with error |
| ci-fix-pipeline hard-fails | Log error, continue watching (don't retry fix) |
| Slack unavailable for gate | Skip gate, apply default behavior for risk level |
| Linear sub-ticket creation fails | Log warning, continue |

## Executable Scripts

### `ci-watch.sh`

Bash wrapper for programmatic and CI invocation of this skill.

```bash
#!/usr/bin/env bash
set -euo pipefail

# ci-watch.sh — wrapper for the ci-watch skill
# Usage: ci-watch.sh --pr <PR> [--ticket-id <ID>] [--timeout-minutes <N>] [--max-fix-cycles <N>] [--no-auto-fix]

PR=""
TICKET_ID=""
TIMEOUT_MINUTES="60"
MAX_FIX_CYCLES="3"
AUTO_FIX_CI="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)             PR="$2";             shift 2 ;;
    --ticket-id)      TICKET_ID="$2";      shift 2 ;;
    --timeout-minutes) TIMEOUT_MINUTES="$2"; shift 2 ;;
    --max-fix-cycles) MAX_FIX_CYCLES="$2"; shift 2 ;;
    --no-auto-fix)    AUTO_FIX_CI="false"; shift   ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$PR" ]]; then
  echo "Error: --pr is required" >&2
  exit 1
fi

exec claude --skill ci-watch \
  --arg "pr_number=${PR}" \
  --arg "ticket_id=${TICKET_ID}" \
  --arg "policy.timeout_minutes=${TIMEOUT_MINUTES}" \
  --arg "policy.max_fix_cycles=${MAX_FIX_CYCLES}" \
  --arg "policy.auto_fix_ci=${AUTO_FIX_CI}"
```

| Invocation | Description |
|------------|-------------|
| `/ci-watch --pr {N}` | Interactive: poll CI on PR N, auto-fix on failure |
| `/ci-watch --pr {N} --no-auto-fix` | Interactive: poll CI on PR N, gate on failure |
| `Skill(skill="ci-watch", args="--pr {N} --ticket-id {T}")` | Programmatic: composable invocation from orchestrator |
| `ci-watch.sh --pr {N} --ticket-id {T} --timeout-minutes 90` | Shell: direct invocation with all parameters |

## Invocation from ticket-pipeline

`ticket-pipeline` invokes `ci-watch` from Phase 4 as a **non-blocking background agent**
(`run_in_background=True`). The pipeline does NOT block on or await the ci-watch result —
it advances to Phase 5 immediately after dispatching.

The background dispatch only occurs when the initial CI snapshot (taken in Phase 4) shows
one or more failing checks. If CI is passing or pending, no dispatch happens at all and
GitHub's auto-merge handles the rest.

**Pass-through policy args** forwarded from ticket-pipeline to ci-watch:
- `--max-fix-cycles {max_ci_fix_cycles}` — max fix attempts before capping (default 3)
- `--timeout-minutes {ci_watch_timeout_minutes}` — max wait time (default 60); governs the
  background ci-watch agent, not the ticket-pipeline itself

```
# Example background dispatch from ticket-pipeline Phase 4:
Task(
  subagent_type="onex:polymorphic-agent",
  run_in_background=True,
  description="ci-watch: fix CI failures for {ticket_id} PR #{pr_number}",
  prompt="CI is failing for PR #{pr_number} in {repo} ({ticket_id}).
    Invoke: Skill(skill=\"onex:ci-watch\",
      args=\"{pr_number} {repo} --max-fix-cycles {max_ci_fix_cycles} --no-auto-fix\")
    Fix any failures, push fixes. GitHub will auto-merge once CI is green."
)
```

## Push-Based Notification Support (OMN-2826)

ci-watch supports two notification modes, selected automatically based on infrastructure
availability:

### EVENT_BUS+ Mode (preferred)

When Kafka and Valkey are available (`ENABLE_REAL_TIME_EVENTS=true`):

1. Register watch: agent registers interest in `(repo, pr_number)` via Valkey watch registry
2. Wait for inbox: block until a `pr-status` event arrives in the agent's inbox topic
   (`onex.evt.omniclaude.agent-inbox.{agent_id}.v1`)
3. Process result: extract conclusion from event payload, proceed with fix or exit

```python
from omniclaude.services.inbox_wait import register_watch, wait_for_pr_status

# Register watch for this PR
await register_watch(agent_id=agent_id, repo=repo, pr_number=pr_number)

# Wait for notification (replaces gh run watch polling)
result = wait_for_pr_status(
    repo=repo,
    pr_number=pr_number,
    run_id=run_id,
    agent_id=agent_id,
    timeout_seconds=timeout_minutes * 60,
)
```

### STANDALONE Mode (fallback)

When Kafka/Valkey are unavailable:

1. Spawn `gh run watch {run_id} --exit-status` as background process
2. Wait for result in file-based inbox (`~/.claude/pr-inbox/`)
3. Max 5 concurrent watchers (`OMNICLAUDE_MAX_WATCHERS=5`)

```python
from omniclaude.services.inbox_wait import wait_for_pr_status

# Unified interface -- automatically falls back to STANDALONE
result = wait_for_pr_status(
    repo=repo,
    pr_number=pr_number,
    run_id=run_id,
    timeout_seconds=timeout_minutes * 60,
)
```

### Migration Notes

The original polling loop (`gh run watch` inline) is preserved as the STANDALONE fallback.
The `wait_for_pr_status()` function provides a unified interface that works in both modes.
No changes needed for existing callers -- the function handles mode detection internally.

## See Also

- `ticket-pipeline` skill (Phase 4 dispatches ci-watch as a background agent on CI failure)
- `pr-watch` skill (runs after Phase 4 in ticket-pipeline)
- `inbox_wait` module (`omniclaude.services.inbox_wait`) — unified wait interface
- `node_github_pr_watcher_effect` — ONEX node for EVENT_BUS+ mode routing
- OMN-2523 — ci-watch implementation ticket
- OMN-2826 — push-based notifications ticket
