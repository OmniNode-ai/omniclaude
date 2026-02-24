---
name: gap-fix
description: Auto-fix loop for gap-analysis findings — reads a gap-analysis report, classifies findings by auto-dispatch eligibility, dispatches ticket-pipeline for safe-only findings, then calls pr-queue-pipeline on the created PRs
version: 0.1.0
category: workflow
tags:
  - gap-analysis
  - auto-fix
  - pipeline
  - integration
  - repair
  - kafka
  - database
author: OmniClaude Team
composable: false
args:
  - name: --report
    description: "Run path for a gap-analysis report (e.g., multi-epic-2026-02-23/run-001)"
    required: false
  - name: --ticket
    description: Single finding via Linear ticket ID containing a gap-analysis marker block
    required: false
  - name: --latest
    description: "Follow ~/.claude/gap-analysis/latest/ symlink (default if no other entry point given)"
    required: false
  - name: --dry-run
    description: Classify and print plan; produce zero side effects (no ledger writes, no Linear writes, no PR mutations)
    required: false
  - name: --mode
    description: "Execution mode: ticket-pipeline (default) | ticket-work | implement-only"
    required: false
  - name: --choose
    description: "Provide decisions for gated findings (e.g., GAP-b7e2d5f8=A,GAP-c3a1e2d4=B)"
    required: false
  - name: --force-decide
    description: Re-open previously decided findings in decisions.json
    required: false
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: complete | partial | nothing_to_fix | gate_pending | error"
---

# Gap Fix

## Overview

Automates the "detected to fixed" loop that gap-analysis opens but leaves manual. Reads a
gap-analysis report, classifies findings by auto-dispatch eligibility, dispatches
`ticket-pipeline` for safe-only findings, then calls `pr-queue-pipeline --prs` on the created PRs.

**Announce at start:** "I'm using the gap-fix skill to auto-fix gap-analysis findings."

**Scope (v0 — narrow)**: Only auto-dispatch findings with a single deterministic resolution.
Anything multi-option emits a decision gate and waits for human input.

## Entry Points

```
/gap-fix --report <run_path>   # e.g., multi-epic-2026-02-23/run-001
/gap-fix --ticket OMN-XXXX     # single finding via marker block
/gap-fix --latest              # follows ~/.claude/gap-analysis/latest/
/gap-fix --dry-run             # classify and print plan, no side effects
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--report <run_path>` | none | Gap-analysis run path under `~/.claude/gap-analysis/` |
| `--ticket <id>` | none | Single finding via Linear ticket containing a marker block |
| `--latest` | false | Follow `~/.claude/gap-analysis/latest/` symlink |
| `--dry-run` | false | Zero side effects: no ledger, no Linear writes, no PR mutations |
| `--mode <mode>` | `ticket-pipeline` | `ticket-pipeline` \| `ticket-work` \| `implement-only` |
| `--choose <decisions>` | none | `GAP-id=A,GAP-id=B` — provide choices for gated findings |
| `--force-decide` | false | Re-open previously decided findings in decisions.json |

## Phases

```
Phase 0: Parse + normalize report → ModelGapFinding[]
Phase 1: Classify findings by auto-dispatch eligibility
Phase 2: Decision gate — emit choices block for non-auto findings; skip undecided; continue with auto
Phase 3: Execute fix — dispatch ticket-pipeline per auto finding
          → emit gap-fix-output.json with prs_created[]
          → call: pr-queue-pipeline --prs <path>  (NOT --repos — scoped to new PRs only)
Phase 4: Re-probe — minimal grep/AST per boundary_kind before marking fixed
Phase 5: Report — append fix section to .md artifact; update decisions ledger
```

## Auto-Dispatch vs Gate Table

| `boundary_kind` | `rule_name` | Auto-dispatch? |
|-----------------|-------------|----------------|
| `kafka_topic` | `topic_name_mismatch` | YES |
| `db_url_drift` | `legacy_db_name_in_tests` | YES |
| `db_url_drift` | `legacy_env_var` | YES |
| `kafka_topic` | `producer_only_no_consumer` | NO — gate |
| `api_contract` | `missing_openapi` | NO — gate |
| Any `BEST_EFFORT` with multiple resolutions | — | NO — gate |

## Key Invariants

- Re-probe **must pass** before marking a finding `fixed`
- `pr-queue-pipeline` always called with `--prs` (not `--repos`) — only touches created PRs
- `--dry-run` produces zero side effects: no ledger writes, no Linear writes, no PR mutations
- `decisions.json` is write-once per finding; `--force-decide` to re-open
- Blocked-external CI guard propagated from pr-queue-pipeline — do not loop on infra failures

## Modes

| Mode | Description |
|------|-------------|
| `ticket-pipeline` | Default — dispatches `ticket-pipeline` per auto finding; calls `pr-queue-pipeline --prs` on created PRs |
| `ticket-work` | Dispatches `ticket-work` only (no PR creation or merge) |
| `implement-only` | No ticket-pipeline or ticket-work; implements fixes directly in worktree |

## Artifacts

`~/.claude/gap-analysis/<source_run_id>/gap-fix-output.json`:

```json
{
  "prs_created": [
    { "repo": "org/repo", "number": 123, "url": "...", "finding_id": "GAP-a3f9c1d2" }
  ],
  "tickets": ["OMN-XXXX"]
}
```

`~/.claude/gap-analysis/<source_run_id>/decisions.json` — persisted decisions so `--choose`
selections are not re-prompted on every run. `<source_run_id>` is the gap-analysis run
identifier (the original analysis run), NOT the fix run ID — so decisions live alongside
the source report, not in a separate fix-run directory:

```json
{
  "GAP-b7e2d5f8": { "choice": "A", "chosen_at": "...", "by": "jonah" }
}
```

## ModelSkillResult

Written to `~/.claude/gap-analysis/<source_run_id>/gap-fix-result.json`:

```json
{
  "skill": "gap-fix",
  "version": "0.1.0",
  "status": "complete | partial | nothing_to_fix | gate_pending | error",
  "run_id": "<run_id>",
  "findings_total": 12,
  "findings_auto": 5,
  "findings_gated": 4,
  "findings_skipped": 3,
  "prs_created": 5,
  "prs_merged": 4,
  "findings_fixed": 4,
  "findings_still_open": 1,
  "gate_pending": ["GAP-b7e2d5f8", "GAP-c3a1e2d4"],
  "output_path": "~/.claude/gap-analysis/<source_run_id>/gap-fix-output.json"
}
```

Status values:
- `complete` — all auto findings fixed, no gate_pending
- `partial` — some findings fixed, some failed or gated
- `nothing_to_fix` — no auto-dispatchable findings found
- `gate_pending` — gated findings emitted; awaiting human `--choose`
- `error` — unrecoverable error

## Sub-skills Used

- `ticket-pipeline` (existing) — creates PR from finding (default mode)
- `pr-queue-pipeline` (OMN-2618) — merges the created PRs (called with `--prs`, not `--repos`)
- `gap-analysis` (existing) — source of findings

## See Also

- `gap-analysis` skill — source of ModelGapFinding[] reports
- `ticket-pipeline` skill — dispatched per auto finding
- `pr-queue-pipeline` skill — merges created PRs
- `~/.claude/gap-analysis/` — report output directory
- `~/.claude/gap-analysis/<source_run_id>/decisions.json` — persisted gate decisions
