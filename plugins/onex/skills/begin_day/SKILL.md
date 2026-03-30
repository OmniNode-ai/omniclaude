---
description: Automated morning investigation pipeline — syncs repos, checks infra, dispatches 7 parallel probes, aggregates findings into ModelDayOpen YAML, and feeds into design-to-plan
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - day-open
  - morning-routine
  - orchestrator
  - parallel
  - investigation
author: OmniClaude Team
composable: true
inputs:
  - name: date
    type: str
    description: ISO date to open (e.g. 2026-03-18); defaults to today
    required: false
  - name: skip-plan
    type: bool
    description: Skip Phase 4 plan generation
    required: false
  - name: skip-sync
    type: bool
    description: Skip Phase 1 repo sync (pull-all.sh)
    required: false
  - name: probes
    type: str
    description: Comma-separated list of probe names to run (default all 7)
    required: false
  - name: dry-run
    type: bool
    description: Print what would run without dispatching probes
    required: false
outputs:
  - name: yaml_path
    type: str
    description: Path to the day-open YAML artifact
  - name: plan_path
    type: str
    description: Path to the action plan (if Phase 4 ran)
---

# begin-day Skill

> **OMN-5349** — Automated morning investigation pipeline that pairs with `/close-day`
> to form a daily OODA cycle.

## Dispatch Surface: Agent Teams

begin-day uses Claude Code Agent Teams with 7 parallel probe workers. The team lead (this
session) handles Phases 0, 1, 3, and 4 inline. Phase 2 dispatches all probes as parallel
Agent Teams workers, then aggregates their results.

### Lifecycle

```
1. TeamCreate(team_name="begin-day-{run_id}")
2. Phase 0 + Phase 1: team lead runs context load + sync inline
3. Phase 2: for each probe in probe_catalog:
   Agent(name="probe-{probe_name}", team_name="begin-day-{run_id}",
         prompt="Run investigation probe: {skill_invocation}. Write results to
                 $ONEX_STATE_DIR/begin-day/{run_id}/{probe_name}.json.
                 Report findings via SendMessage(to='team-lead').")
4. Team lead collects all 7 probe results via SendMessage
5. Phase 3: team lead aggregates findings into ModelDayOpen YAML
6. Phase 4: team lead feeds findings into design-to-plan (optional)
7. TeamDelete(team_name="begin-day-{run_id}") after aggregation complete
```

All 7 probes are dispatched simultaneously for maximum parallelism (~8min wall-clock).
Each probe writes its JSON artifact independently; the team lead aggregates after all
workers report back or time out.

### Failure on Dispatch

If Agent Teams dispatch fails (TeamCreate error, Agent tool unavailable, auth error):
**STOP immediately.** Report the exact error to the user and wait for direction. Do NOT fall
back to direct Bash, Read, Edit, Write, or Glob calls — falling back bypasses observability,
context management, and the orchestration layer.

## Overview

`/begin-day` automates the entire morning investigation loop:

1. **Phase 0** — Load yesterday's close-day corrections (~30s)
2. **Phase 1** — Sync repos via `pull-all.sh` + check infra health (~2min)
3. **Phase 2** — Dispatch 7 parallel investigation probes (~8min wall-clock)
4. **Phase 3** — Aggregate all findings into a `ModelDayOpen` YAML (~1min)
5. **Phase 4** — Feed findings into `onex:design-to-plan` (optional)

## Quick Start

```
/begin-day
```

Or with options:

```
/begin-day --skip-plan
/begin-day --dry-run
/begin-day --probes list_prs,gap_detect
/begin-day --date 2026-03-18 --skip-sync
```

## Phase Sequence

```
Phase 0: Context Load (sequential, ~30s)
  ├── Compute today/yesterday dates
  ├── Generate run_id
  ├── Create artifact directory
  └── Load yesterday's close-day corrections

Phase 1: Sync & Preconditions (sequential, ~2min)
  ├── Run pull-all.sh (unless --skip-sync)
  ├── Parse output → repo_sync_status
  └── Check infra health (Docker + port probes)

Phase 2: Parallel Investigation (~8min wall-clock)
  └── 7 probes dispatched as parallel Agent Teams workers:
      ├── list_prs         → /list-prs
      ├── dashboard_sweep  → /dashboard-sweep --triage-only
      ├── aislop_sweep     → /aislop-sweep --dry-run
      ├── standardization  → /standardization-sweep --dry-run
      ├── gap_detect       → /gap detect --since-days 1
      ├── env_parity       → /env-parity check
      └── system_status    → /system-status

Phase 3: Aggregate & Model (sequential, ~1min)
  ├── Collect probe JSON artifacts
  ├── Adversarially validate each artifact
  ├── Merge carry-forward corrections
  ├── Dedup findings by (source_probe, finding_id)
  ├── Sort by severity (CRITICAL > HIGH > MEDIUM > LOW > INFO)
  ├── Compute weighted focus areas
  ├── Build + validate ModelDayOpen
  └── Write day_open.yaml + update latest symlink

Phase 4: Plan Generation (optional)
  └── Feed findings into onex:design-to-plan
```

## Artifact Structure

```
$ONEX_STATE_DIR/begin-day/
├── {run_id}/
│   ├── list_prs.json
│   ├── dashboard_sweep.json
│   ├── aislop_sweep.json
│   ├── standardization_sweep.json
│   ├── gap_detect.json
│   ├── env_parity.json
│   ├── system_status.json
│   └── day_open.yaml          ← final aggregate
└── latest -> {run_id}         ← symlink to latest completed run
```

## Probe Catalog

| Probe | Skill | Purpose |
|-------|-------|---------|
| `list_prs` | `/list-prs` | Overnight PR/CI state |
| `dashboard_sweep` | `/dashboard-sweep --triage-only` | Page health, no fixes |
| `aislop_sweep` | `/aislop-sweep --dry-run` | AI slop detection |
| `standardization_sweep` | `/standardization-sweep --dry-run` | Python standards |
| `gap_detect` | `/gap detect --since-days 1` | Cross-repo integration drift |
| `env_parity` | `/env-parity check` | Local vs cloud env var drift |
| `system_status` | `/system-status` | Platform service health |

## Error Handling

- Missing `ONEX_CC_REPO_PATH` → empty corrections, continue
- `pull-all.sh` failure → HIGH finding, continue
- Docker not running → infra flagged down (HIGH), continue probes
- Any probe failure → `status: failed`, continue
- Skill not merged → `status: skipped`, continue
- ModelDayOpen validation failure → stderr error, exit 1
- Already ran today → advisory notice, proceed with new run_id

## Dependencies

- `onex_change_control` package: `ModelDayOpen` schema
- `pull-all.sh` script (omnibase_infra)
- `gh` CLI: for PR state
- `docker` CLI: for infra health
- `pyyaml`: for YAML serialization
- 7 investigation skills (gracefully degraded if unavailable)

## Relationship to close-day

```
/close-day (evening)
  └── writes corrections_for_tomorrow to day_close YAML

/begin-day (morning)
  ├── reads yesterday's corrections
  ├── carries forward as HIGH findings
  └── writes day_open.yaml with aggregated findings

onex:design-to-plan (Phase 4)
  └── converts findings into prioritized action plan
```

## Files

| Path | Purpose |
|------|---------|
| `plugins/onex/skills/begin_day/SKILL.md` | This file (descriptive) |
| `plugins/onex/skills/begin_day/prompt.md` | Authoritative behavior specification |
| `plugins/onex/skills/_lib/begin_day/begin_day.py` | Core logic module (importable for tests) |
| `tests/unit/skills/test_begin_day.py` | Unit test suite |
