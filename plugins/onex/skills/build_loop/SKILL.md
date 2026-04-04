---
description: Autonomous build loop — runs the ONEX build loop workflow locally via `onex run`
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

Start the autonomous build loop. This skill runs the build loop workflow locally
via `onex run`, executing the full 6-phase cycle in-process:

```
IDLE -> CLOSING_OUT -> VERIFYING -> FILLING -> CLASSIFYING -> BUILDING -> COMPLETE
```

**Announce at start:** "I'm using the build-loop skill to start the autonomous build loop."

**Implements**: OMN-5113

## Quick Start

```
# Single cycle (default)
cd /Volumes/PRO-G40/Code/omni_home/omnibase_infra  # local-path-ok
uv run onex run src/omnibase_infra/workflows/build_loop_workflow.yaml

# With custom state directory
uv run onex run src/omnibase_infra/workflows/build_loop_workflow.yaml \
  --state-root "$ONEX_STATE_DIR/build-loop"

# With timeout
uv run onex run src/omnibase_infra/workflows/build_loop_workflow.yaml \
  --state-root "$ONEX_STATE_DIR/build-loop" \
  --timeout 600
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

### Execute Workflow

Run the build loop workflow locally via RuntimeLocal:

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnibase_infra  # local-path-ok
uv run onex run src/omnibase_infra/workflows/build_loop_workflow.yaml \
  --state-root "$ONEX_STATE_DIR/build-loop" \
  --timeout 600
```

This executes the full 6-phase FSM in-process with:
- In-memory event bus (no Kafka required)
- Filesystem state (no Postgres required)
- Direct handler invocation (no Docker runtime required)

The exit code indicates the result:
- 0 = COMPLETED (all cycles successful)
- 1 = FAILED or TIMEOUT
- 3 = PARTIAL (some evidence written)

### Write Skill Result

The workflow automatically writes its result to `$ONEX_STATE_DIR/build-loop/workflow_result.json`.
This contains the full `ModelLoopOrchestratorResult` with per-cycle summaries.

## Skill Result Output

| Field | Value |
|-------|-------|
| `skill_name` | `"build_loop"` |
| `status` | `"success"` or `"error"` |
| `run_id` | Correlation ID |
| `extra` | `{"cycles_completed": int, "cycles_failed": int, "total_tickets_dispatched": int}` |

## Delegation

When `ENABLE_LOCAL_DELEGATION=true` and `ENABLE_LOCAL_INFERENCE_PIPELINE=true` are set
(default in `cron-buildloop.sh`), the build loop delegates lightweight tasks to local
LLMs instead of frontier Claude:

| Phase | Delegation Behavior |
|-------|-------------------|
| CLOSING_OUT | Merge-sweep runs GitHub API calls (no LLM needed). PR polish delegates to local models via delegation orchestrator. |
| VERIFYING | Health checks are HTTP/shell — no LLM delegation needed. |
| FILLING | RSD scoring is pure computation — no LLM needed. |
| CLASSIFYING | Keyword heuristics — no LLM needed. |
| BUILDING | Dispatches ticket-pipeline per ticket. Within ticket-pipeline, the hostile-reviewer already uses local models (DeepSeek-R1, Qwen3-Coder). Testing and CI-fix phases route through the delegation orchestrator when env vars are set. |

Disable delegation with `cron-buildloop.sh --no-delegation` or by unsetting the env vars.

## Friction Logging

All failure paths emit friction events to `$ONEX_STATE_DIR/friction/build-loop.ndjson`:

- Phase failures (verification, dispatch, etc.)
- Circuit breaker trips
- Cycle-level failures
- Cron script timeouts and non-zero exits

These events are classified by the `node_friction_observer_compute` contract rules
and visible to the `/friction-triage` skill and omnidash friction dashboard.

## See Also

- `node_autonomous_loop_orchestrator` — orchestrates the 6-phase cycle
- `node_loop_state_reducer` — FSM with circuit breaker
- `ticket-pipeline` skill — individual ticket execution (dispatched by BUILDING phase)
- OMN-5113 — Autonomous Build Loop epic
