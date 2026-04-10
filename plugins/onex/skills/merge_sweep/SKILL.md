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
    description: "Admin merge fallback for PRs stuck in queue >30 min (default: false — opt-in only)"
    required: false
  - name: --admin-fallback-threshold-minutes
    description: "Minutes a PR must be stuck in merge queue before admin fallback fires (default: 30)"
    required: false
inputs:
  - name: repos
    description: "list[str] — org/repo names to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | nothing_to_merge | partial | error"
---

# Merge Sweep

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
| `--enable-admin-merge-fallback` | `enable_admin_merge_fallback: true` (default: false — opt-in) |
| `--admin-fallback-threshold-minutes` | `admin_fallback_threshold_minutes` (default: 30) |

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
| `--enable-admin-merge-fallback` | false | **Opt-in**: Admin merge fallback for PRs stuck in merge queue beyond threshold. Logs "ADMIN MERGE TRIGGERED" before every action. |
| `--admin-fallback-threshold-minutes` | 30 | Minutes a PR must be in merge queue before admin fallback fires (only when `--enable-admin-merge-fallback` is set). |

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

- **v5.0.0** (OMN-8204–OMN-8208): Expose 5 new `node_pr_lifecycle_orchestrator` capabilities:
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
