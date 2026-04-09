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

Dispatch to the deterministic node — do NOT inline any logic:

```bash
onex run node_overnight -- "${@}"
```
