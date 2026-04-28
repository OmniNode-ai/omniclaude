---
description: Thin dispatch-only shim for the org-wide PR merge sweep pipeline. Builds the contract-canonical pr_lifecycle_orchestrator start envelope and invokes the omnimarket module CLI. No inline GH script fallback, no direct Kafka publish, no orchestration logic.
mode: full
version: 7.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - org-wide
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated org/repo names to scan; empty means all OmniNode repos"
    required: false
  - name: --dry-run
    description: "Run without side effects"
    required: false
  - name: --inventory-only
    description: "Stop after inventory"
    required: false
  - name: --fix-only
    description: "Only run the fix phase; skip merge"
    required: false
  - name: --merge-only
    description: "Only run the merge phase; skip fix"
    required: false
  - name: --max-parallel-polish
    description: "Maximum concurrent pr-polish agents during the fix phase"
    required: false
  - name: --enable-auto-rebase
    description: "Auto-rebase stale PR branches before merge"
    required: false
  - name: --use-dag-ordering
    description: "Order merge candidates by dependency DAG"
    required: false
  - name: --enable-trivial-comment-resolution
    description: "Resolve trivial bot review threads before merge"
    required: false
  - name: --enable-admin-merge-fallback
    description: "Admin-merge PRs stuck in queue past threshold"
    required: false
  - name: --admin-fallback-threshold-minutes
    description: "Minutes before a queued PR is considered stuck"
    required: false
  - name: --verify
    description: "Run verification_sweep per PR before merge"
    required: false
  - name: --verify-timeout-seconds
    description: "Hard per-PR verification timeout in seconds"
    required: false
  - name: --run-id
    description: "Identifier for this run; generated when omitted"
    required: false
inputs:
  - name: envelope
    description: "ModelEventEnvelope[ModelPrLifecycleStartCommand]"
outputs:
  - name: orchestrator_result
    description: "ModelPrLifecycleResult JSON"
---

# /onex:merge_sweep — PR Lifecycle Dispatch Shim

**Skill ID**: `onex:merge_sweep`
**Version**: 7.0.0
**Owner**: omniclaude
**Ticket**: OMN-10167
**Backing node**: `omnimarket/src/omnimarket/nodes/node_pr_lifecycle_orchestrator/`

## Changelog

- **7.0.0** — Breaking dispatch contract change. The shim now builds a
  `ModelEventEnvelope[ModelPrLifecycleStartCommand]` and invokes
  `python -m omnimarket.nodes.node_pr_lifecycle_orchestrator --input ...`.
  This replaces the stale legacy run-node route.
- **6.1.0** — Repointed the old shim after the merge-sweep decomposition.

## What this skill does

Dispatches directly to `node_pr_lifecycle_orchestrator`. The node owns PR
inventory, triage, merge, fix dispatch, state reduction, result persistence,
and terminal event emission. This shim contains no orchestration logic, no
inline GitHub merge script fallback, no direct Kafka publish, and no claim
registry management.

**Announce at start:** "I'm using the merge-sweep skill."

## Wire Schema

Contract:
`omnimarket/src/omnimarket/nodes/node_pr_lifecycle_orchestrator/contract.yaml`

Command topic:
`onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`

Dispatch declaration for deterministic routing gates:
Kafka publish to `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`
is performed by `plugins/onex/skills/merge_sweep/run.sh` through the
contract-canonical omnimarket launcher.

Event type alias:
`omnimarket.pr-lifecycle-orchestrator-start`

Terminal event:
`onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1`

Envelope shape:

```json
{
  "event_type": "omnimarket.pr-lifecycle-orchestrator-start",
  "correlation_id": "<uuid>",
  "payload": {
    "correlation_id": "<uuid>",
    "run_id": "<safe-run-id>",
    "dry_run": false,
    "inventory_only": false,
    "fix_only": false,
    "merge_only": false,
    "repos": "",
    "max_parallel_polish": 20,
    "enable_auto_rebase": true,
    "use_dag_ordering": true,
    "enable_trivial_comment_resolution": true,
    "enable_admin_merge_fallback": true,
    "admin_fallback_threshold_minutes": 15,
    "verify": false,
    "verify_timeout_seconds": 30
  }
}
```

## Dispatch

```bash
plugins/onex/skills/merge_sweep/run.sh \
  [--repos <org/repo,org/repo>] \
  [--dry-run] \
  [--inventory-only] \
  [--fix-only] \
  [--merge-only] \
  [--max-parallel-polish <n>] \
  [--enable-auto-rebase true|false] \
  [--use-dag-ordering true|false] \
  [--enable-trivial-comment-resolution true|false] \
  [--enable-admin-merge-fallback true|false] \
  [--admin-fallback-threshold-minutes <n>] \
  [--verify true|false] \
  [--verify-timeout-seconds <n>] \
  [--run-id <id>]
```

The launcher dispatches to `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`
and prints the `ModelPrLifecycleResult` JSON emitted by the backing node.
Surface non-zero exits directly. On routing failure raise `SkillRoutingError`;
do not produce prose.

## Headless / Cron Invocation

`scripts/cron-merge-sweep.sh` is the durable launchd trigger for this skill. It
schedules invocations and provides the operator control surface (PID locks,
circuit-breaker timeouts, log rotation, auth retry). Live launchd reinstall or
reload remains a user-gated operation.
