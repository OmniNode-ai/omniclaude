---
description: Org-wide PR sweep — enables GitHub auto-merge on ready PRs and runs pr-polish on PRs with blocking issues (CI failures, conflicts, changes requested)
mode: full
version: 5.0.0
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
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated org/repo names (default: all OmniNode repos)"
    required: false
  - name: --dry-run
    description: Print candidates without enabling auto-merge or running pr-polish; zero filesystem writes
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: "Require GitHub review approval (default: true)"
    required: false
  - name: --max-total-merges
    description: "Hard cap on Track A candidates per run (default: 0 = unlimited)"
    required: false
  - name: --skip-polish
    description: Skip Track B entirely; only process merge-ready PRs
    required: false
  - name: --authors
    description: "Limit to PRs by these GitHub usernames (comma-separated)"
    required: false
  - name: --since
    description: "Filter PRs updated after this date (ISO 8601: YYYY-MM-DD)"
    required: false
  - name: --require-up-to-date
    description: "Require PR branch to be up-to-date with base before auto-merge (default: true)"
    required: false
  - name: --inventory-only
    description: "Collect and report PR inventory without taking any action (passed to orchestrator)"
    required: false
  - name: --fix-only
    description: "Only run the fix (Track B / pr-polish) phase, skip merge phase"
    required: false
  - name: --merge-only
    description: "Only run the merge (Track A) phase, skip fix phase"
    required: false
  - name: --enable-auto-rebase
    description: "Auto-rebase stale PR branches before merge (default: true). Pass --no-enable-auto-rebase to skip."
    required: false
  - name: --use-dag-ordering
    description: "Order PRs by cross-repo dependency DAG before merging (default: true). Merges omnibase_compat first, omnidash last."
    required: false
  - name: --enable-trivial-comment-resolution
    description: "Resolve trivial CodeRabbit/bot review threads before merge (default: true)"
    required: false
  - name: --enable-admin-merge-fallback
    description: "Admin merge fallback for PRs stuck in queue >threshold. Default: true (OMN-9065 — on-by-default; pass --no-enable-admin-merge-fallback to disable)"
    required: false
  - name: --admin-fallback-threshold-minutes
    description: "Minutes a PR must be stuck in merge queue before admin fallback fires (default: 30)"
    required: false
  - name: --verify
    description: "Run verification_sweep on each PR after CI passes but before enabling auto-merge. Uses changed-file-to-verification-target mapping. Neutral-skip on tool/infra errors; does not block the batch. Default: true (OMN-9066 — on-by-default; pass --no-verify to disable)."
    required: false
  - name: --verify-timeout-seconds
    description: "Per-PR verification timeout in seconds (default: 30). On timeout, PR is neutral-skipped as verification_timeout."
    required: false
inputs:
  - name: repos
    description: "list[str] — org/repo names to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | nothing_to_merge | partial | error"
---

# Merge Sweep

## Tools Required (OMN-8708)

When `merge-sweep` is invoked as a dispatched worker from another orchestrator (e.g. `session`
or `overnight`), it runs in a fresh session where dispatch tools are **deferred**. If this
worker needs to spawn sub-agents for `pr-polish` or Track B work, it must fetch at session start:

```
ToolSearch(query="select:Agent,SendMessage,TaskCreate,TaskUpdate,TaskGet", max_results=5)
```

The dispatch prompt from the parent orchestrator must include this as its first instruction.

## Overview

Thin trigger skill for the PR lifecycle pipeline. Parses CLI args, maps them to
`pr_lifecycle_orchestrator` entry flags, publishes a command event, and monitors
for orchestrator completion.

**All orchestration logic is delegated to the `pr_lifecycle_orchestrator` node
(omnimarket). This skill is a pure entry point: parse → publish → monitor.**

**Announce at start:** "I'm using the merge-sweep skill."

> **Autonomous execution**: No Human Confirmation Gate. This skill runs end-to-end without
> human confirmation. `--dry-run` is the only preview mechanism; absence of `--dry-run`
> means "execute everything automatically."

## Quick Start

```
/merge-sweep                                       # Scan all repos, enable auto-merge + polish
/merge-sweep --dry-run                             # Print candidates only (no mutations)
/merge-sweep --repos omniclaude,omnibase_core      # Limit to specific repos
/merge-sweep --skip-polish                         # Only enable auto-merge on ready PRs
/merge-sweep --merge-only                          # Skip fix phase entirely
/merge-sweep --inventory-only                      # Report PR inventory without acting
/merge-sweep --authors jonahgabriel                # Only PRs by this author
/merge-sweep --max-total-merges 5                  # Cap auto-merge queue at 5
/merge-sweep --since 2026-02-01                    # Only PRs updated after Feb 1, 2026
/merge-sweep --label ready-for-merge               # Only PRs with this label
/merge-sweep --resume                              # Resume interrupted sweep from checkpoint
/merge-sweep --reset-state                         # Clear stale state and start fresh
```

## How It Works

```
/merge-sweep [args]
    │
    ├─ 1. Parse and validate CLI args
    ├─ 2. Map args → ModelPrLifecycleOrchestratorCommand fields
    ├─ 3. Publish to onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1
    ├─ 4. Poll $ONEX_STATE_DIR/merge-sweep/{run_id}/result.json
    └─ 5. Surface result as ModelSkillResult
```

## Arg → Orchestrator Entry Flag Mapping

| Skill Arg | Orchestrator Field |
|-----------|-------------------|
| `--repos` | `repos` (CSV → list) |
| `--dry-run` | `dry_run: true` |
| `--merge-method` | `merge_method` |
| `--require-approval` | `require_approval` |
| `--require-up-to-date` | `require_up_to_date` |
| `--max-total-merges` | `max_total_merges` |
| `--max-parallel-prs` | `max_parallel_prs` |
| `--max-parallel-repos` | `max_parallel_repos` |
| `--max-parallel-polish` | `max_parallel_polish` |
| `--skip-polish` | `skip_polish: true` |
| `--polish-clean-runs` | `polish_clean_runs` |
| `--authors` | `authors` (CSV → list) |
| `--since` | `since` (ISO 8601 string) |
| `--label` | `labels` (CSV → list) |
| `--resume` | `resume: true` |
| `--reset-state` | `reset_state: true` |
| `--run-id` | `run_id` |
| `--inventory-only` | `inventory_only: true` |
| `--fix-only` | `fix_only: true` |
| `--merge-only` | `merge_only: true` |
| `--enable-auto-rebase` | `enable_auto_rebase: true` (default: true) |
| `--use-dag-ordering` | `use_dag_ordering: true` (default: true) |
| `--enable-trivial-comment-resolution` | `enable_trivial_comment_resolution: true` (default: true) |
| `--enable-admin-merge-fallback` | `enable_admin_merge_fallback: true` (default: **true** — OMN-9065 on-by-default) |
| `--admin-fallback-threshold-minutes` | `admin_fallback_threshold_minutes` (default: 15 — OMN-9065 lowered from 30) |
| `--verify` | `verify: true` (default: **true** — OMN-9066 on-by-default pre-merge verification gate; pass `--no-verify` to disable) |
| `--verify-timeout-seconds` | `verify_timeout_seconds` (default: 30) |

## New Flows (v5.0.0)

### 1. Auto-Rebase Flow

When `--enable-auto-rebase` (default: true), stale PRs (`merge_state_status=BEHIND` or `UNKNOWN`) are rebased before the merge attempt:

```
TRIAGING → REBASING → gh pr update-branch → re-triage → MERGING
```

A `REBASING` FSM state has been added to the orchestrator. Rebase failures are logged as warnings but do not block the sweep.

### 2. DAG Dependency Ordering

When `--use-dag-ordering` (default: true), PRs are merged in repo dependency order to prevent downstream breakage:

| Tier | Repo |
|------|------|
| 0 | omnibase_compat |
| 1 | omnibase_spi |
| 2 | omnibase_core |
| 3 | omnibase_infra |
| 4 | omnimarket |
| 5 | omniclaude |
| 6 | omniintelligence |
| 7 | omnimemory |
| 8 | omninode_infra |
| 9 | onex_change_control |
| 10 | omnidash |
| 11 | omniweb |
| 99 | (unknown repos — merge last) |

Within each tier, GREEN PRs sort before non-green (stable sort preserves original order within same tier+status).

### 3. Stuck Queue Detection

During the INVENTORYING phase, the inventory compute node checks all `QUEUED` PRs for queue age via `gh pr view --json mergeQueueEntry`. PRs queued longer than `--admin-fallback-threshold-minutes` (default: 30 min) are flagged as `stuck_queue_prs` and logged as WARN-level events.

If `--enable-admin-merge-fallback` is on (default: **true** as of OMN-9065; pass `--no-enable-admin-merge-fallback` to disable), stuck PRs are admin-merged via `gh pr merge --admin --squash`. An explicit `ADMIN MERGE TRIGGERED pr={n} repo={r}` log line is emitted before each admin merge for audit traceability. Repos without merge queue support are skipped silently.

### 5. Pre-Merge Verification Gate (`--verify`, OMN-7742)

When `--verify` is on (default: **true** as of OMN-9066; pass `--no-verify` to disable),
after CI passes but **before** enabling auto-merge, each PR is routed through
`onex:verification_sweep` using a deterministic changed-file-to-target mapping. The gate
runs by default; CI green plus structurally correct code is no longer sufficient to merge
when a verification target exists for the PR's changed files.

The per-PR check runs with a hard timeout (`--verify-timeout-seconds`, default 30s) and
neutral-skips on any infra error. Failure on one PR does **not** block other PRs in the
same sweep; PRs are re-evaluated on the next run (no automatic retries in v1).

#### Verification target mapping

First-match-wins table applied against the PR's `gh pr diff --name-only` output:

| Changed-file pattern | Verification target | Check |
|---|---|---|
| `src/**/projection*.py`, `src/**/projector*.py` | Projection table for that module | Table exists, `row_count > 0`, sample row has all non-null required columns matching the Drizzle schema |
| `src/**/handler*.py` (Kafka consumer) | Projection sink + summary endpoint consuming it | Endpoint returns HTTP 2xx with structurally valid JSON matching expected response shape |
| `src/**/route*.py`, `src/**/api*.py`, `pages/api/**` | The modified API route(s) | Endpoint returns HTTP 2xx with non-error payload; response body contains expected top-level keys |
| `drizzle/**`, `migrations/**` | All projection tables in the affected database | Tables exist, migrations applied without error, row schema matches Drizzle definition |
| `topics.yaml`, `contract.yaml` (event bus) | Kafka topic exists + consumer group lag | Topic in `rpk topic list`, consumer group lag via `rpk group describe` |
| No pattern match | Skip verification for this PR | Logged as `skipped_no_mapping` |

The mapping is deterministic and lives in `pr_lifecycle_orchestrator` so new patterns
can be added without editing this skill.

#### Per-PR verification outcomes

Each PR in the sweep is classified into exactly one of seven categories. Only
`verification_failed` blocks auto-merge for that PR; every other category either proceeds
to merge as usual or is a neutral skip.

| Category | Meaning | PR action |
|---|---|---|
| `merged` | CI + verification passed (or skipped by policy) | Enable auto-merge as usual |
| `verification_failed` | Verification ran, produced a concrete failure | PR comment with which check failed, expected vs actual, target mapping used; auto-merge **not** enabled; PR stays open for re-evaluation |
| `verification_unavailable` | Target unreachable (service down, DB offline) | Neutral skip, WARN log, no PR comment |
| `verification_timeout` | Did not complete within `--verify-timeout-seconds` | Neutral skip, WARN log |
| `verification_tool_error` | `verification_sweep` itself errored (exception, missing binary) | Neutral skip, ERROR log |
| `skipped_no_mapping` | No verification target pattern matched the diff | Normal skip, INFO log |
| `skipped_by_policy` | `--no-verify` passed, or repo on the verify-exclude list | Normal skip |

The merge-sweep report is extended to split PRs across all seven categories. A failure
in one PR never short-circuits the batch: other PRs continue to their own verification
and merge decisions independently.

#### PR comment on `verification_failed`

On a concrete verification failure, a single PR comment is posted with:

1. Which check failed (target kind + identifier)
2. Expected vs actual (row count, HTTP code, schema columns, etc.)
3. The target mapping entry that selected this check
4. A pointer to the verification receipt under `.onex_state/verification-failures/`

The PR is left open; the next merge_sweep run re-evaluates it. No automatic retries.

### 4. Bot Comment Resolution

When `--enable-trivial-comment-resolution` (default: true), trivial CodeRabbit/bot review threads are resolved before the merge attempt. "Trivial" = comment body matches bot nit patterns (nit, nitpick, style, minor) AND the author is a known bot login (`coderabbitai`, `github-actions[bot]`, etc.). Human comments are always preserved.

## Kafka Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1` | publish | Trigger the orchestrator |
| `onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1` | subscribe | Monitor completion |
| `onex.evt.omnimarket.pr-lifecycle-orchestrator-failed.v1` | subscribe | Monitor failure |

## Command Event Wire Schema

Published to `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`:

```json
{
  "run_id": "20260223-143012-a3f",
  "repos": ["OmniNode-ai/omniclaude"],
  "dry_run": false,
  "merge_method": "squash",
  "require_approval": true,
  "require_up_to_date": "repo",
  "max_total_merges": 0,
  "max_parallel_prs": 5,
  "max_parallel_repos": 3,
  "max_parallel_polish": 20,
  "skip_polish": false,
  "polish_clean_runs": 2,
  "authors": [],
  "since": null,
  "labels": [],
  "resume": false,
  "reset_state": false,
  "inventory_only": false,
  "fix_only": false,
  "merge_only": false,
  "emitted_at": "2026-02-23T14:30:12Z",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## Completion Monitoring

After publishing the command event, the skill polls for the orchestrator result file:

**Poll target**: `$ONEX_STATE_DIR/merge-sweep/{run_id}/result.json`

**Poll interval**: 10 seconds
**Poll timeout**: 3600 seconds (1 hour)

The result file is written by `pr_lifecycle_orchestrator` on completion. Its schema
mirrors the existing ModelSkillResult contract so downstream consumers are unaffected.

On timeout: emit `ModelSkillResult(status="error", message="orchestrator timeout")`.

## Result Passthrough

The orchestrator's result is surfaced directly as the skill's `ModelSkillResult`:

**Written to**: `$ONEX_STATE_DIR/skill-results/{run_id}/merge-sweep.json`

Status values (unchanged from v3.x for backward compatibility):
- `queued` — all candidates had auto-merge enabled and/or branches updated
- `nothing_to_merge` — no actionable PRs found (after all filters)
- `partial` — some queued/updated, some failed or blocked
- `error` — no PRs successfully queued or updated

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--dry-run` | false | Print candidates without enabling auto-merge or polishing; zero filesystem writes |
| `--run-id` | generated | Identifier for this run; correlates logs and claim registry ownership |
| `--merge-method` | `squash` | `squash` \| `merge` \| `rebase` |
| `--require-approval` | true | Require at least one GitHub APPROVED review |
| `--require-up-to-date` | `repo` | `always` \| `never` \| `repo` (respect branch protection) |
| `--max-total-merges` | 0 (unlimited) | Hard cap on Track A candidates per run. 0 = no cap. |
| `--max-parallel-prs` | 5 | Concurrent auto-merge enable operations |
| `--max-parallel-repos` | 3 | Repos scanned in parallel |
| `--max-parallel-polish` | 20 | Concurrent pr-polish agents (safety cap) |
| `--resume` | false | Resume from last checkpoint; skip already-processed repos/PRs |
| `--reset-state` | false | Delete existing state file and start clean |
| `--skip-polish` | false | Skip Track B entirely |
| `--polish-clean-runs` | 2 | Clean local-review passes required during pr-polish |
| `--authors` | all | Limit to PRs by these GitHub usernames (comma-separated) |
| `--since` | — | Filter PRs updated after this date (ISO 8601). Skips ancient PRs. |
| `--label` | all | Filter PRs with this label. Comma-separated = any match. |
| `--inventory-only` | false | Collect and report PR inventory without taking any action |
| `--fix-only` | false | Only run the fix (Track B) phase |
| `--merge-only` | false | Only run the merge (Track A) phase |
| `--enable-auto-rebase` | true | Auto-rebase stale (behind-base) PR branches before merging. Pass `--no-enable-auto-rebase` to skip. |
| `--use-dag-ordering` | true | Order merge PRs by cross-repo dependency DAG (omnibase_compat first, omnidash last). Pass `--no-use-dag-ordering` to skip. |
| `--enable-trivial-comment-resolution` | true | Auto-resolve trivial CodeRabbit/bot review threads (nit/style/minor) with no human reply before merge. |
| `--enable-admin-merge-fallback` | **true** (OMN-9065) | **On-by-default**: Admin merge fallback for PRs stuck in merge queue beyond threshold. Logs "ADMIN MERGE TRIGGERED" before every action. Pass `--no-enable-admin-merge-fallback` to disable. |
| `--admin-fallback-threshold-minutes` | 15 (OMN-9065, from 30) | Minutes a PR must be in merge queue before admin fallback fires. |
| `--verify` | **true** (OMN-9066) | **On-by-default**: After CI passes, run `onex:verification_sweep` per-PR using the changed-file-to-target mapping before enabling auto-merge. Only `verification_failed` blocks that PR; unavailable/timeout/tool_error are neutral skips. Failure in one PR does not block others. Pass `--no-verify` to disable. |
| `--verify-timeout-seconds` | 30 | Hard per-PR verification timeout. On timeout the PR is neutral-skipped as `verification_timeout`. |

## Headless Mode

Use `scripts/cron-merge-sweep.sh` for overnight/unattended runs.

```bash
./scripts/cron-merge-sweep.sh
./scripts/cron-merge-sweep.sh --repos omniclaude,omnibase_core
./scripts/cron-merge-sweep.sh --skip-polish
./scripts/cron-merge-sweep.sh --resume
./scripts/cron-merge-sweep.sh --dry-run
```

## What This Skill Does NOT Do

- Scan GitHub repos directly (delegated to orchestrator)
- Classify PRs (delegated to orchestrator)
- Call `gh pr merge --auto` directly (delegated to orchestrator)
- Dispatch pr-polish agents (delegated to orchestrator)
- Manage claim registry state (delegated to orchestrator)
- Track failure history across sweeps (delegated to orchestrator)
- Manage sweep state/checkpoints (delegated to orchestrator)

## Integration Test

Tests verify the skill → orchestrator delegation contract:

```
tests/integration/skills/merge_sweep/test_merge_sweep_integration.py
Run with: uv run pytest tests/integration/skills/merge_sweep/ -m unit -v
```

Test coverage:
- SKILL.md declares publish-monitor pattern
- All CLI args map to documented orchestrator entry flags
- Correct command topic documented
- Correct completion event topics documented
- Backward-compatible CLI surface (all v3.x args still accepted)
- `--dry-run` maps to `dry_run: true` in command event
- No orchestration logic in SKILL.md (no direct `gh pr merge`, no claim registry)

## See Also

- `pr_lifecycle_orchestrator` node (omnimarket) — owns all orchestration logic (OMN-8087)
- `pr_lifecycle_inventory_compute` node — PR scanning and classification
- `pr_lifecycle_triage_compute` node — triage and routing
- `pr_lifecycle_merge_effect` node — `gh pr merge --auto` execution
- `pr_lifecycle_fix_effect` node — pr-polish dispatch

## Changelog

- **v5.1.0** (OMN-7742): Add opt-in `--verify` pre-merge verification gate. After CI
  passes, each PR is routed through `onex:verification_sweep` using a deterministic
  changed-file-to-target mapping (projections, handlers, API routes, migrations, event
  bus). PRs classified into 7 categories: `merged`, `verification_failed`,
  `verification_unavailable`, `verification_timeout`, `verification_tool_error`,
  `skipped_no_mapping`, `skipped_by_policy`. Only `verification_failed` blocks that PR;
  infra errors neutral-skip. Failure in one PR never blocks the batch. `--verify-timeout-seconds`
  (default 30) controls per-PR timeout. Closes OMN-6405-class regressions where CI green
  plus structurally correct code merged with garbage projection data.
- **v5.0.0** (OMN-8204–OMN-8208): Expose 5 new `node_pr_lifecycle_orchestrator` capabilities from OMN-8197 Workstream 2. All args map 1:1 to new `ModelPrLifecycleStartCommand` fields:
  - `--enable-auto-rebase`: Auto-rebase stale PR branches via `gh pr update-branch` (REBASING FSM state)
  - `--use-dag-ordering`: Dependency DAG ordering — merges omnibase_compat first, omnidash last
  - Stuck merge queue detection in inventory (>30 min in queue → `stuck_queue_prs`)
  - `--enable-trivial-comment-resolution`: Auto-resolve trivial bot comment threads before merge
  - `--enable-admin-merge-fallback`: Opt-in admin merge for stuck queue PRs (default: false)
- **v4.0.0** (OMN-8088): Rewrite as thin publish-monitor trigger. All orchestration
  logic delegated to `pr_lifecycle_orchestrator` node (omnimarket). Skill parses CLI
  args, publishes `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`, polls for
  result at `$ONEX_STATE_DIR/merge-sweep/{run_id}/result.json`. Backward-compatible CLI
  surface preserved. Added `--inventory-only`, `--fix-only`, `--merge-only` pass-through
  flags for orchestrator entry modes.
- **v3.6.0** (OMN-7573): Cross-run failure history tracking.
- **v3.5.0** (OMN-7083): State recovery with per-repo checkpointing and `--resume`.
- **v3.4.0** (OMN-6253): Two-layer PR branch name defense.
- **v3.3.0** (OMN-5134): Intelligent review thread resolution.
- **v3.2.0** (OMN-4517): Post-scan repo coverage assertion.
- **v3.1.0** (OMN-3818): Proactive stale branch detection and update.
- **v3.0.0**: Replace HIGH_RISK Slack gate with GitHub native auto-merge.
- **v2.1.0** (OMN-2633 + OMN-2635): Migrate legacy bypass flags.
- **v2.0.0** (OMN-2629): Add `--since` date filter, `--label` filter.
- **v1.0.0** (OMN-2616): Initial implementation.
