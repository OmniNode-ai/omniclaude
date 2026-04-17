---
description: Dispatch a background worker with role-templated prompt and auto-populated collision fences
mode: full
version: 1.0.0
level: intermediate
debug: false
category: orchestration
tags: [dispatch, team, background, worker, orchestration, role]
args:
  - name: spec
    description: "Inline YAML spec or path to YAML spec file (name/team/role/scope/targets required)"
    required: true
  - name: --dry-run
    description: "Print compiled prompt without spawning agent"
    required: false
inputs:
  - name: spec
    description: "YAML string or file path with dispatch spec"
outputs:
  - name: worker_name
    description: "Name of the dispatched worker"
  - name: task_id
    description: "ID of the created task"
---

# Dispatch Worker

Compile a worker dispatch spec through `node_dispatch_worker` and spawn a background agent.

**Announce at start:** "I'm using the dispatch-worker skill."

> **Autonomous execution**: No human confirmation gate. `--dry-run` is the only preview mechanism.

## Worker Behavior

> **Required for all dispatched workers — enforced by `_COMMON_PREAMBLE` in
> `omnimarket/src/omnimarket/nodes/node_dispatch_worker/handlers/handler_dispatch_worker.py`.**

- **Ack after each deliverable.** After every discrete deliverable (design doc written, test
  run complete, PR opened, finding logged), send a one-line `SendMessage` to `{reports_to}`.
  Never batch acks across multiple deliverables.
- **Stop after primary task.** When the primary task is complete, send exactly:
  `"Primary task done — awaiting further instruction or shutdown."` then stop.
  Ambient-idle looping after task completion is forbidden.

## Quick Start

```
# Inline YAML spec
/dispatch_worker "
name: pr-202-fix
team: daylight-0411
role: fixer
scope: Fix omnimarket#202 halt_conditions CodeRabbit findings
targets: [omnimarket#202, OMN-8375]
"

# From file
/dispatch_worker ~/docs/plans/workers/pr-202-fix.yaml

# Dry run (print compiled prompt, no spawn)
/dispatch_worker --dry-run "
name: vggp-designer
team: daylight-0411
role: designer
scope: Design VGGP inference pipeline
targets: [OMN-8400]
"
```

## Valid Roles

| Role | Purpose | Default cap |
|------|---------|------------|
| `watcher` | CI watch loop, no code changes | 90 min |
| `fixer` | TDD-first fix + hostile_reviewer + PR | 90 min |
| `designer` | Design doc + hostile_reviewer + plan | 120 min |
| `auditor` | Read-only investigation + findings doc | 60 min |
| `synthesizer` | Reconcile cross-domain design docs | 90 min |
| `sweep` | Short-lived cron pulse, one metrics line | 10 min |
| `ops` | Long-lived stateful admin worker | 480 min |

## Spec Format

```yaml
name: <worker-handle>          # required: lowercase, hyphens/underscores, max 64 chars
team: <team-name>              # required
role: <role>                   # required: one of 7 values above
scope: "<goal description>"    # required
targets: [<ticket>, <pr>, ...]  # required: what this worker owns
collision_fences: []           # optional: auto-populated from TaskList if empty
reports_to: team-lead          # optional: default team-lead
wall_clock_cap_min: 90         # optional: defaults by role (range: 5–480)
model: sonnet                  # optional: default sonnet
replace: false                 # optional: kill existing in_progress worker with same name
```

## See Also

- `node_dispatch_worker` (omnimarket) — compiles the prompt template
- Design: `docs/design/dispatch-worker-skill-design.md`
