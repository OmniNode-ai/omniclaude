---
description: Bootstrap the entire overnight autonomous operation — reads standing orders, creates agent team, dispatches merge-sweep and monitoring workers, starts build loop with frontier model routing, and sets up priority check cron
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - overnight
  - autonomous
  - orchestrator
  - bootstrap
  - agent-team
  - build-loop
  - merge-sweep
author: OmniClaude Team
composable: false
inputs:
  - name: max_cycles
    type: int
    description: "Maximum build loop cycles (default: unlimited — runs until stopped)"
    required: false
  - name: dry_run
    type: bool
    description: "Print bootstrap plan without dispatching workers (default: false)"
    required: false
  - name: skip_build_loop
    type: bool
    description: "Skip build loop startup (default: false)"
    required: false
  - name: skip_merge_sweep
    type: bool
    description: "Skip merge-sweep cron (default: false)"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/overnight.json"
    fields:
      - status: '"success" | "error"'
      - team_name: str
      - workers_dispatched: int
      - crons_created: int
      - session_id: str
args:
  - name: --max-cycles
    description: "Maximum build loop cycles (default: unlimited)"
    required: false
  - name: --dry-run
    description: "Print plan without executing"
    required: false
  - name: --skip-build-loop
    description: "Skip build loop startup"
    required: false
  - name: --skip-merge-sweep
    description: "Skip merge-sweep cron"
    required: false
---

# Overnight Bootstrap

## Overview

Single-command bootstrap for the entire overnight autonomous operation. Invoke `/overnight`
to stand up the full night shift: agent team, merge-sweep cron, monitoring worker, build
loop, and priority checks — all correlated under one session ID.

**Announce at start:** "I'm using the overnight skill to bootstrap the night session."

**Implements**: OMN-7810

## Quick Start

```
/overnight                         # Full bootstrap — all workers, build loop, crons
/overnight --dry-run               # Print plan without dispatching
/overnight --skip-build-loop       # Team + merge sweep + monitoring, no build loop
/overnight --max-cycles 5          # Limit build loop to 5 cycles
```

## What It Does

1. **Reads standing orders** from `$ONEX_STATE_DIR/nightly-loop-decisions.md`
2. **Creates agent team** (`overnight-ops-{session_id}`) via TeamCreate
3. **Dispatches merge-sweep worker** — runs `/onex:merge_sweep` on 30-minute cron
4. **Dispatches monitoring worker** — checks runtime health (.201 ports), PR status, dashboard state
5. **Starts build loop** — full 6-phase cycle with frontier model routing via `/onex:build_loop`
6. **Sets up priority check cron** — reads standing orders every 60 minutes for changes
7. **Binds session ID** as correlation ID for all workers and artifacts

## Dispatch Surface: Agent Teams

overnight uses Claude Code Agent Teams with parallel workers. The team lead (this session)
reads standing orders, creates the team, and dispatches all workers.

### Lifecycle

```
1. Read standing orders from $ONEX_STATE_DIR/nightly-loop-decisions.md
2. Generate session_id (correlation key)
3. TeamCreate(team_name="overnight-ops-{session_id}")
4. Dispatch workers in parallel:
   a. Agent(name="merge-sweep-worker", ...) — merge-sweep on 30min cron
   b. Agent(name="monitoring-worker", ...) — health checks on 15min cron
   c. Agent(name="build-loop-worker", ...) — build loop with model routing
5. CronCreate — priority check every 60min
6. Team lead monitors via SendMessage, aggregates results
```

### Failure on Dispatch

If Agent Teams dispatch fails (TeamCreate error, Agent tool unavailable, auth error):
**STOP immediately.** Report the exact error to the user and wait for direction. Do NOT fall
back to direct Bash, Read, Edit, Write, or Glob calls — falling back bypasses observability,
context management, and the orchestration layer.

## Standing Orders Integration

The file `$ONEX_STATE_DIR/nightly-loop-decisions.md` contains:
- **Standing Priorities** — ordered list of what the night shift should focus on
- **Standing Rules** — non-negotiable constraints (worktrees, evidence, pre-commit)
- **Delegation Routing** — which task types go to which model/backend
- **Active Gaps** — known issues to investigate or fix

Workers receive the full standing orders in their dispatch prompt so they operate with
complete context.

## Workers

| Worker | Skill | Interval | Purpose |
|--------|-------|----------|---------|
| `merge-sweep-worker` | `/onex:merge_sweep` | 30 min cron | Drain PR queue, enable auto-merge, polish fixable PRs |
| `monitoring-worker` | (inline checks) | 15 min cron | Runtime health, PR status, dashboard state |
| `build-loop-worker` | `/onex:build_loop` | Continuous | Pull tickets, delegate to LLMs, create PRs |
| Priority check (cron) | (team lead) | 60 min | Re-read standing orders, adjust worker priorities |

## Safety

- **Correlation**: All workers share the session ID for log correlation
- **Standing rules enforced**: Workers receive standing rules and must respect them
- **Worktree discipline**: All code changes happen in worktrees, never omni_home
- **Evidence required**: Workers must provide DB queries, API responses, PR links as proof

## Artifact Structure

```
$ONEX_STATE_DIR/overnight/
  {session_id}/
    bootstrap.yaml         -- bootstrap metadata and worker dispatch records
    standing-orders.md     -- snapshot of standing orders at bootstrap time
    merge-sweep/           -- merge-sweep worker artifacts
    monitoring/            -- monitoring worker artifacts
    build-loop/            -- build loop worker artifacts
```

## Error Handling

| Error | Behavior |
|-------|----------|
| Standing orders file missing | WARN and proceed with defaults (build loop + merge sweep) |
| TeamCreate fails | STOP — report error, wait for user direction |
| Worker dispatch fails | Log failure, continue dispatching remaining workers |
| Cron creation fails | Log failure, continue — workers still run their first cycle |
| Build loop circuit breaker trips | Worker reports via SendMessage; team lead logs and continues |
| Merge sweep rate limited | Worker handles internally (exponential backoff with checkpoint) |

## See Also

- `build_loop` skill — 6-phase autonomous build cycle
- `merge_sweep` skill — PR queue draining
- `system_status` skill — runtime health monitoring
- `begin_day` skill — morning counterpart (investigation pipeline)
- `nightly-loop-decisions.md` — standing orders file
