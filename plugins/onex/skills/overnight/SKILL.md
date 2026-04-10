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

# Overnight Session

## Phase 0: Session Bootstrap

Run this FIRST, before any other phase:

```bash
SESSION_ID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
onex run node_session_bootstrap -- \
  --session-id "$SESSION_ID" \
  --session-label "$(date +%Y-%m-%d) overnight" \
  --phases-expected "build_loop,merge_sweep,ci_watch,platform_readiness" \
  ${dry_run:+--dry-run}
```

Apply the following policy on the bootstrap result `status` field:

| Bootstrap Status | Action |
|-----------------|--------|
| **ready** | Proceed to Phase 1 |
| **degraded** | Log warnings inline, proceed to Phase 1 |
| **failed** | **HALT** — do not start the overnight session. Report bootstrap failure. Wait for user direction. |

## Phase 1: Pre-flight Readiness Check

Before dispatching the overnight node, run the platform readiness gate:

```bash
onex run node_platform_readiness --output-format json
```

Then read `.onex_state/readiness/latest.yaml` and apply the following policy:

| Overall Status | Action |
|----------------|--------|
| **PASS** | Proceed with dispatch |
| **WARN** | Proceed with a warning — surface all degraded dimensions inline |
| **FAIL** | **HALT** — do not start the overnight session. Report all blockers with actionable_items. Wait for user direction. |

## Phase 2: Dispatch

Dispatch to the deterministic node — do NOT inline any logic:

```bash
onex run node_overnight -- "${@}"
```

Capture the overnight result JSON from stdout. Extract `phases_run` and `phases_failed` for Phase 3.

## Phase 3: Session Post-Mortem

Run this LAST, regardless of overnight outcome (success or failure):

```bash
onex run node_session_post_mortem -- \
  --session-id "$SESSION_ID" \
  --session-label "$(date +%Y-%m-%d) overnight" \
  --phases-planned "build_loop,merge_sweep,ci_watch,platform_readiness" \
  --phases-completed "${phases_run:-}" \
  --phases-failed "${phases_failed:-}" \
  ${dry_run:+--dry-run}
```

The post-mortem report path is printed to stdout. Surface it in the session summary.
