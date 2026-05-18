---
description: Autonomous demo readiness loop — rehearse, detect drift, auto-fix low-risk issues, and produce morning handoff plan
mode: full
version: 1.0.0
level: advanced
debug: false
category: automation
tags:
  - demo
  - readiness
  - rehearsal
  - drift
  - handoff
  - overnight
author: OmniClaude Team
args:
  - name: subcommand
    description: "Action: rehearse, detect-drift, dispatch-fixes, morning-handoff, or full-loop"
    required: true
  - name: run_id
    description: "Unique run identifier for correlation and replay (e.g. demo-readiness-2026-05-18)"
    required: false
  - name: --proof-of-green
    description: "Path to an existing rehearsal_bundle.json to compare against (detect-drift mode)"
    required: false
  - name: --dry-run
    description: "Run rehearsal and drift detection without dispatching any fixes"
    required: false
  - name: --replay
    description: "Replay from saved evidence under docs/evidence/demo-readiness/<run_id>/"
    required: false
---

# /demo_readiness_team — Autonomous Demo Readiness Skill

Composes production sweeps into a continuous rehearsal loop with bounded authority. Operates
autonomously between sessions: rehearse the demo path, detect drift vs a proof-of-green bundle,
auto-fix low-risk issues (bounded by concurrency and cost limits), and produce a morning handoff
plan for human review.

**Authority boundary**: this skill NEVER deploys runtime changes, restarts production lanes,
merges topology-affecting PRs, or mutates production data. Background agents are advisory by
default. Topology and runtime-affecting actions require explicit human approval.

## Usage

```
/demo_readiness_team rehearse [run_id]
/demo_readiness_team detect-drift [run_id] [--proof-of-green path/to/bundle.json]
/demo_readiness_team dispatch-fixes [run_id] [--dry-run]
/demo_readiness_team morning-handoff [run_id]
/demo_readiness_team full-loop [run_id] [--dry-run]
```

## Behavior

### rehearse

Runs the full demo rehearsal pipeline via `node_demo_rehearsal`. Executes the demo command
envelope, captures runtime topology manifest, checks projection row, probes dashboard API,
takes screenshots, and writes `rehearsal_bundle.json` to `docs/evidence/demo-readiness/<run_id>/`.

- Emits: `onex.cmd.omnimarket.demo-rehearsal-start.v1`
- Artifact: `docs/evidence/demo-readiness/<run_id>/rehearsal_bundle.json`
- Status: GREEN / DEGRADED / BROKEN

### detect-drift

Diffs current state vs an existing proof-of-green bundle via `node_demo_drift_detector`.
Uses truth hierarchy: topology > projection > dashboard > screenshots.

- Emits: `onex.cmd.omnimarket.demo-drift-detect-start.v1`
- Artifact: `docs/evidence/demo-readiness/<run_id>/drift_report.json`
- Criticality levels: DEMO_BLOCKER, DEMO_DEGRADED, COSMETIC, OBSERVABILITY_ONLY, BACKLOG_ONLY

### dispatch-fixes

Auto-fixes low-risk drift (COSMETIC, OBSERVABILITY_ONLY) via `node_demo_fix_dispatcher`.
DEMO_BLOCKER and DEMO_DEGRADED findings require human approval. Respects bounded concurrency
limits: max 4 parallel workers, max $50/day cost, max 5 open auto-fix PRs.

- Emits: `onex.cmd.omnimarket.demo-fix-dispatch-start.v1`
- Artifact: `docs/evidence/demo-readiness/<run_id>/fix_dispatch_log.json`

### morning-handoff

Produces human-readable summary and machine-readable `morning_dispatch_plan.json` via
`node_morning_handoff_generator`. Synthesizes overnight rehearsal runs and drift reports.

- Emits: `onex.cmd.omnimarket.morning-handoff-start.v1`
- Artifact: `docs/evidence/demo-readiness/<run_id>/morning_dispatch_plan.json`

### full-loop

Runs rehearse → detect-drift → dispatch-fixes → morning-handoff as a single unattended loop.
Use for overnight/cron automation. With `--dry-run`, skips dispatch-fixes.

## Replay Mode

```
/demo_readiness_team morning-handoff <run_id> --replay
```

Loads saved evidence from `docs/evidence/demo-readiness/<run_id>/` without re-running sweeps.

## Bounded Authority

| Action | Authority |
|--------|-----------|
| Run demo rehearsal command | Auto |
| Capture projections and screenshots | Auto |
| Detect drift and classify criticality | Auto |
| Auto-fix COSMETIC / OBSERVABILITY_ONLY drift | Auto (bounded) |
| Auto-fix DEMO_DEGRADED drift | Human approval required |
| Auto-fix DEMO_BLOCKER drift | Human approval required |
| Deploy runtime changes | NEVER (blocked) |
| Restart production lanes | NEVER (blocked) |
| Merge topology-affecting PRs | NEVER (blocked) |
| Mutate production data | NEVER (blocked) |

## Concurrency Limits

```yaml
max_parallel_workers: 4
max_runtime_minutes: 120
max_daily_cost_usd: 50.0
max_open_autofix_prs: 5
```

## Evidence Directory

All artifacts written to `docs/evidence/demo-readiness/<run_id>/`:
- `rehearsal_bundle.json` — full rehearsal result with correlation data
- `drift_report.json` — drift findings with criticality classifications
- `fix_dispatch_log.json` — auto-fix dispatch log and results
- `morning_dispatch_plan.json` — human-readable + machine-readable handoff plan

## Implementation

The skill delegates to four omnimarket nodes:

- `node_demo_rehearsal` — executes demo path, captures evidence bundle
- `node_demo_drift_detector` — diffs vs proof-of-green using truth hierarchy
- `node_demo_fix_dispatcher` — auto-fix dispatcher with bounded authority
- `node_morning_handoff_generator` — overnight summary + dispatch plan

All nodes are zero-infra capable (EventBusInmemory, filesystem-only artifacts).

### rehearse invocation

```python
import asyncio
from omnimarket.nodes.node_demo_rehearsal.handlers.handler_demo_rehearsal import (
    HandlerDemoRehearsal, ModelDemoRehearsalRequest,
)
result = asyncio.run(HandlerDemoRehearsal().handle(
    ModelDemoRehearsalRequest(
        run_id="<run_id>",
        dry_run=False,
    )
))
# result.rehearsal_bundle, result.bundle_path, result.overall_status
```

### detect-drift invocation

```python
import asyncio
from omnimarket.nodes.node_demo_drift_detector.handlers.handler_demo_drift_detector import (
    HandlerDemoDriftDetector, ModelDemoDriftDetectRequest,
)
result = asyncio.run(HandlerDemoDriftDetector().handle(
    ModelDemoDriftDetectRequest(
        run_id="<run_id>",
        proof_of_green_path="docs/evidence/demo-readiness/<green_run_id>/rehearsal_bundle.json",
    )
))
# result.drift_findings, result.demo_blocker_count, result.report_path
```

### dispatch-fixes invocation

```python
import asyncio
from omnimarket.nodes.node_demo_fix_dispatcher.handlers.handler_demo_fix_dispatcher import (
    HandlerDemoFixDispatcher, ModelDemoFixDispatchRequest,
)
result = asyncio.run(HandlerDemoFixDispatcher().handle(
    ModelDemoFixDispatchRequest(
        run_id="<run_id>",
        drift_report_path="docs/evidence/demo-readiness/<run_id>/drift_report.json",
        dry_run=False,
    )
))
# result.fixes_dispatched, result.fixes_skipped_human_approval, result.dispatch_log_path
```

### morning-handoff invocation

```python
import asyncio
from omnimarket.nodes.node_morning_handoff_generator.handlers.handler_morning_handoff_generator import (
    HandlerMorningHandoffGenerator, ModelMorningHandoffRequest,
)
result = asyncio.run(HandlerMorningHandoffGenerator().handle(
    ModelMorningHandoffRequest(
        run_id="<run_id>",
        evidence_dir="docs/evidence/demo-readiness/<run_id>",
    )
))
# result.morning_dispatch_plan, result.plan_path, result.human_summary
```

## Architecture

```
SKILL.md   -> thin shell (this file)
rehearse   -> omnimarket/src/omnimarket/nodes/node_demo_rehearsal/
detect     -> omnimarket/src/omnimarket/nodes/node_demo_drift_detector/
dispatch   -> omnimarket/src/omnimarket/nodes/node_demo_fix_dispatcher/
handoff    -> omnimarket/src/omnimarket/nodes/node_morning_handoff_generator/
evidence   -> docs/evidence/demo-readiness/<run_id>/
```
