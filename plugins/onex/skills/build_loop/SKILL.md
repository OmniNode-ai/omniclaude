---
description: Autonomous build loop — runs the ONEX build loop workflow locally via `onex run`
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags: [build-loop, autonomous, automation, orchestrator]
author: OmniClaude Team
composable: true
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
  - name: --max-tickets
    description: "Max tickets to dispatch per fill cycle (default: 5)"
    required: false
  - name: --mode
    description: "Execution mode: build, close_out, full, observe (default: build)"
    required: false
---

# Build Loop

**Announce at start:** "I'm using the build-loop skill to start the autonomous build loop."

## Usage

```
/build-loop                         # Single cycle (default)
/build-loop --max-cycles 3          # Run 3 cycles
/build-loop --skip-closeout         # Skip CLOSING_OUT phase
/build-loop --dry-run               # Simulate without side effects
/build-loop --max-tickets 10        # Dispatch up to 10 tickets per fill
/build-loop --mode close_out        # Close-out only (no fill/build)
```

## Execution

### Step 1 — Parse arguments

- `--max-cycles` → max loop iterations (default: 1)
- `--skip-closeout` → skip CLOSING_OUT phase (default: false)
- `--dry-run` → simulate all phases without side effects (default: false)
- `--max-tickets` → tickets dispatched per fill cycle (default: 5)
- `--mode` → build | close_out | full | observe (default: build)

### Step 2 — Run node

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_build_loop_orchestrator \
  [--max-cycles <n>] \
  [--skip-closeout] \
  [--dry-run] \
  [--max-tickets <n>] \
  [--mode <mode>]
```

Capture stdout (JSON: `ModelOrchestratorResult`). Exit 0 = all cycles completed, exit 1 = any cycle failed.

### Step 3 — Render report

From the JSON output display:
- Summary: cycles completed, cycles failed, total tickets dispatched
- Per-cycle summary: phase outcomes, tickets dispatched, errors
- Circuit breaker status (trips after 3 consecutive failures)

## Phases

| Phase | Node | What It Does |
|-------|------|-------------|
| CLOSING_OUT | `node_closeout_effect` | Merge-sweep, quality gates, release readiness |
| VERIFYING | `node_verify_effect` | Dashboard health, runtime health, data flow |
| FILLING | `node_rsd_fill_compute` | Select top-N tickets by RSD score |
| CLASSIFYING | `node_ticket_classify_compute` | Classify tickets by buildability |
| BUILDING | `node_build_dispatch_effect` | Dispatch ticket-pipeline per ticket |
| COMPLETE | reducer | Cycle finished |

## Safety

- Circuit breaker halts after 3 consecutive phase failures
- `--dry-run` simulates all phases without creating PRs, tickets, or merges
- Max cycles default is 1 — increase only for overnight/cron runs

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_build_loop_orchestrator/ (orchestrator)
fsm        -> omnimarket/src/omnimarket/nodes/node_build_loop/ (FSM reducer)
contract   -> node_build_loop_orchestrator/contract.yaml
```
