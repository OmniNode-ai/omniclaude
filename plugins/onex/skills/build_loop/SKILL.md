---
description: Autonomous build loop — publishes cmd.build-loop.start.v1 to kick off the ONEX node-based build loop
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags: [build-loop, autonomous, automation, orchestrator]
author: OmniClaude Team
composable: true
inputs:
  - name: max_cycles
    type: int
    description: "Maximum number of build loop cycles to run (default: 1)"
    required: false
  - name: skip_closeout
    type: bool
    description: "Skip the CLOSING_OUT phase (default: false)"
    required: false
  - name: dry_run
    type: bool
    description: "Run without side effects (default: false)"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/build_loop.json"
    fields:
      - status: '"success" | "error"'
      - cycles_completed: int
      - cycles_failed: int
      - total_tickets_dispatched: int
args:
  - name: --max-cycles
    description: "Maximum cycles (default: 1)"
    required: false
  - name: --skip-closeout
    description: "Skip close-out phase"
    required: false
  - name: --dry-run
    description: "No side effects — simulate the full loop"
    required: false
---

# Build Loop

## Overview

Start the autonomous build loop. This skill publishes a `cmd.build-loop.start.v1` event
that triggers the `node_autonomous_loop_orchestrator` to execute the full 6-phase cycle:

```
IDLE -> CLOSING_OUT -> VERIFYING -> FILLING -> CLASSIFYING -> BUILDING -> COMPLETE
```

**Announce at start:** "I'm using the build-loop skill to start the autonomous build loop."

**Implements**: OMN-5113

## Quick Start

```
/build-loop
/build-loop --max-cycles 3
/build-loop --skip-closeout --dry-run
/build-loop --max-cycles 5 --skip-closeout
```

## Phase Descriptions

| Phase | Node | What It Does |
|-------|------|-------------|
| CLOSING_OUT | `node_closeout_effect` | Merge-sweep, quality gates, release readiness |
| VERIFYING | `node_verify_effect` | Dashboard health, runtime health, data flow |
| FILLING | `node_rsd_fill_compute` | Select top-N tickets by RSD score |
| CLASSIFYING | `node_ticket_classify_compute` | Classify tickets by buildability |
| BUILDING | `node_build_dispatch_effect` | Dispatch ticket-pipeline per ticket |
| COMPLETE | reducer | Cycle finished |

## Safety

- **Circuit breaker**: After 3 consecutive failures, the loop halts with FAILED state.
- **Dry run**: Use `--dry-run` to simulate without side effects.
- **Max cycles**: Defaults to 1 cycle. Use `--max-cycles` to run multiple.

## Execution Steps

### Parse Arguments

Parse `--max-cycles` (default 1), `--skip-closeout` (default false), `--dry-run` (default false).

### Publish Start Command

Publish `cmd.build-loop.start.v1` to Kafka with:
- `correlation_id`: New UUID
- `max_cycles`: From args
- `skip_closeout`: From args
- `dry_run`: From args
- `requested_at`: Current timestamp

### Monitor Loop Progress

The orchestrator node handles the actual execution. This skill monitors progress
by subscribing to build loop events:
- `evt.build-loop-started.v1` — loop accepted
- `evt.build-loop-cycle-completed.v1` — cycle finished
- `evt.build-loop-failed.v1` — loop failed

### Write Skill Result

Write result to `$ONEX_STATE_DIR/skill-results/{context_id}/build_loop.json`.

## Skill Result Output

| Field | Value |
|-------|-------|
| `skill_name` | `"build_loop"` |
| `status` | `"success"` or `"error"` |
| `run_id` | Correlation ID |
| `extra` | `{"cycles_completed": int, "cycles_failed": int, "total_tickets_dispatched": int}` |

## See Also

- `node_autonomous_loop_orchestrator` — orchestrates the 6-phase cycle
- `node_loop_state_reducer` — FSM with circuit breaker
- `ticket-pipeline` skill — individual ticket execution (dispatched by BUILDING phase)
- OMN-5113 — Autonomous Build Loop epic
