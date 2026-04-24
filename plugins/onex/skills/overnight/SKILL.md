---
description: Thin dispatch-only shim for the overnight autonomous pipeline. Routes to node_overnight in omnimarket, which sequences nightly_loop_controller, build_loop, merge_sweep, ci_watch, and platform_readiness. No inline LLM orchestration.
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - overnight
  - autonomous
  - orchestrator
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: false
inputs:
  - name: max_cycles
    type: int
    description: "Maximum build loop cycles (default: 0 = unlimited)"
    required: false
  - name: dry_run
    type: bool
    description: "Run all phases in dry-run mode (default: false)"
    required: false
  - name: skip_build_loop
    type: bool
    description: "Skip the build loop phase (default: false)"
    required: false
  - name: skip_merge_sweep
    type: bool
    description: "Skip the merge sweep phase (default: false)"
    required: false
outputs:
  - name: session_status
    type: str
    description: '"completed" | "partial" | "failed"'
  - name: phases_run
    type: list
    description: "Names of phases that executed"
  - name: phases_failed
    type: list
    description: "Names of phases that failed"
args:
  - name: --max-cycles
    description: "Maximum build loop cycles (default: 0 = unlimited)"
    required: false
  - name: --dry-run
    description: "Run all phases in dry-run mode"
    required: false
  - name: --skip-build-loop
    description: "Skip the build loop phase"
    required: false
  - name: --skip-merge-sweep
    description: "Skip the merge sweep phase"
    required: false
---

# /onex:overnight — Thin Dispatch Shim

**Skill ID**: `onex:overnight`
**Version**: 2.0.0
**Owner**: omniclaude
**Ticket**: OMN-8751
**Backing node**: `omnimarket/src/omnimarket/nodes/node_overnight/`

## What this skill does

Dispatches directly to `node_overnight` via `onex run-node`. The node
sequences every phase deterministically and emits the session-completed
envelope. This shim contains no orchestration logic, no inline LLM
reasoning, no multi-phase loop — those live in the node's handler.

## Dispatch

```bash
uv run onex run-node node_overnight -- \
  [--max-cycles N] \
  [--dry-run] \
  [--skip-build-loop] \
  [--skip-merge-sweep]
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned —
surface it directly, do not produce prose.

## Output

The node emits `ModelOvernightResult` to stdout:

```json
{
  "session_status": "completed | partial | failed",
  "phases_run": ["nightly_loop_controller", "build_loop", "merge_sweep", "ci_watch", "platform_readiness"],
  "phases_failed": []
}
```

The terminal Kafka event is
`onex.evt.omnimarket.overnight-session-completed.v1`.

## Relation to `/onex:session --mode autonomous`

`/onex:session --mode autonomous` is the broader unified session
orchestrator (OMN-8340) that layers health gating and RSD priority
scoring on top of the overnight pipeline. This skill remains as a
direct entry point to `node_overnight` for callers that want to bypass
session-level gating and dispatch the overnight pipeline directly.
