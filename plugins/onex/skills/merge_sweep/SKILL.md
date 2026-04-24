---
description: Thin dispatch-only shim for the org-wide PR merge sweep pipeline. Routes to node_merge_sweep in omnimarket, which owns PR inventory, triage, auto-merge, pr-polish dispatch, queue stall detection, and pre-merge verification. No inline GH script fallback, no kcat publish, no orchestration logic.
mode: full
version: 6.0.0
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
    description: "Comma-separated org/repo names (default: all OmniNode repos)"
    required: false
  - name: --dry-run
    description: "Print candidates without enabling auto-merge or running pr-polish; zero filesystem writes"
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: "Require GitHub review approval (default: true)"
    required: false
  - name: --require-up-to-date
    description: "Require PR branch to be up-to-date with base before auto-merge (default: repo)"
    required: false
  - name: --max-total-merges
    description: "Hard cap on Track A candidates per run (default: 0 = unlimited)"
    required: false
  - name: --max-parallel-prs
    description: "Concurrent auto-merge enable operations (default: 5)"
    required: false
  - name: --max-parallel-repos
    description: "Repos scanned in parallel (default: 3)"
    required: false
  - name: --max-parallel-polish
    description: "Concurrent pr-polish agents (default: 20)"
    required: false
  - name: --skip-polish
    description: "Skip Track B entirely; only process merge-ready PRs"
    required: false
  - name: --polish-clean-runs
    description: "Clean local-review passes required during pr-polish (default: 2)"
    required: false
  - name: --authors
    description: "Limit to PRs by these GitHub usernames (comma-separated)"
    required: false
  - name: --since
    description: "Filter PRs updated after this date (ISO 8601: YYYY-MM-DD)"
    required: false
  - name: --label
    description: "Filter PRs with this label (comma-separated for any-match)"
    required: false
  - name: --run-id
    description: "Identifier for this run; correlates logs and claim registry ownership"
    required: false
  - name: --resume
    description: "Resume from last checkpoint; skip already-processed repos/PRs"
    required: false
  - name: --reset-state
    description: "Delete existing state file and start clean"
    required: false
  - name: --inventory-only
    description: "Collect and report PR inventory without taking any action"
    required: false
  - name: --fix-only
    description: "Only run the fix (Track B / pr-polish) phase, skip merge phase"
    required: false
  - name: --merge-only
    description: "Only run the merge (Track A) phase, skip fix phase"
    required: false
  - name: --enable-auto-rebase
    description: "Auto-rebase stale PR branches before merge (default: true)"
    required: false
  - name: --use-dag-ordering
    description: "Order PRs by cross-repo dependency DAG before merging (default: true)"
    required: false
  - name: --enable-trivial-comment-resolution
    description: "Resolve trivial CodeRabbit/bot review threads before merge (default: true)"
    required: false
  - name: --enable-admin-merge-fallback
    description: "Admin merge fallback for PRs stuck in queue beyond threshold (default: true)"
    required: false
  - name: --admin-fallback-threshold-minutes
    description: "Minutes a PR must be stuck before admin fallback fires (default: 15)"
    required: false
  - name: --verify
    description: "Run verification_sweep on each PR before enabling auto-merge (default: true)"
    required: false
  - name: --verify-timeout-seconds
    description: "Per-PR verification timeout in seconds (default: 30)"
    required: false
inputs:
  - name: repos
    description: "list[str] — org/repo names to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | nothing_to_merge | partial | error"
---

# /onex:merge_sweep — Thin Dispatch Shim

**Skill ID**: `onex:merge_sweep`
**Version**: 6.0.0
**Owner**: omniclaude
**Ticket**: OMN-8752
**Backing node**: `omnimarket/src/omnimarket/nodes/node_merge_sweep/`

## What this skill does

Dispatches directly to `node_merge_sweep` via `onex run-node`. The node
owns PR inventory, triage, Track A auto-merge, Track B pr-polish
dispatch, queue stall detection, DAG ordering, auto-rebase, bot comment
resolution, and pre-merge verification. This shim contains no
orchestration logic, no inline GH script fallback, no direct Kafka
publish, no claim registry management — those live in the node's
handlers.

**Announce at start:** "I'm using the merge-sweep skill."

> **Autonomous execution:** No Human Confirmation Gate. This skill runs
> end-to-end without human confirmation. `--dry-run` is the only preview
> mechanism; absence of `--dry-run` means "execute everything
> automatically."

## Dispatch

```bash
uv run onex run-node node_merge_sweep -- \
  [--repos <list>] \
  [--dry-run] \
  [--merge-method <squash|merge|rebase>] \
  [--require-approval <bool>] \
  [--require-up-to-date <policy>] \
  [--max-total-merges <n>] \
  [--max-parallel-prs <n>] \
  [--max-parallel-repos <n>] \
  [--max-parallel-polish <n>] \
  [--skip-polish] \
  [--polish-clean-runs <n>] \
  [--authors <list>] \
  [--since <date>] \
  [--label <labels>] \
  [--run-id <id>] \
  [--resume] \
  [--reset-state] \
  [--inventory-only] \
  [--fix-only] \
  [--merge-only] \
  [--enable-auto-rebase] \
  [--use-dag-ordering] \
  [--enable-trivial-comment-resolution] \
  [--enable-admin-merge-fallback] \
  [--admin-fallback-threshold-minutes <n>] \
  [--verify] \
  [--verify-timeout-seconds <n>]
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned —
surface it directly, do not produce prose.

## Output

The node emits `ModelSkillResult` to stdout:

```json
{
  "status": "queued | nothing_to_merge | partial | error",
  "run_id": "<run_id>",
  "message": "<summary>"
}
```

Status values:
- `queued` — all candidates had auto-merge enabled and/or branches updated
- `nothing_to_merge` — no actionable PRs found (after all filters)
- `partial` — some queued/updated, some failed or blocked
- `error` — no PRs successfully queued or updated

The terminal Kafka event is
`onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1`.

## Headless / cron invocation

`scripts/cron-merge-sweep.sh` is the durable launchd trigger for this
skill. It schedules invocations and provides the operator control
surface (PID locks, circuit-breaker timeouts, log rotation) — it is
**not** part of this shim and does **not** perform queue-heal or stall
detection itself. Queue stall detection and queue-heal logic live in
`node_merge_sweep`; the cron wrapper simply triggers the node and
surfaces exit status.

## Relation to autonomous closeout

`/onex:autopilot` and `/onex:session --mode autonomous` invoke this
skill directly as part of their close-out phase. This shim exists so
interactive callers can dispatch the merge sweep pipeline without going
through the full session orchestrator.
