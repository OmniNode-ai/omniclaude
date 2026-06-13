---
description: Projection table health and migration tracking — checks row count, staleness for every table
  in omnidash_analytics, plus migration state across all ONEX databases (pending migrations, failed state,
  schema fingerprint). Auto-creates Linear tickets for stale/empty tables and migration drift.
mode: full
version: 3.0.0
level: advanced
debug: false
category: verification
tags:
  - database
  - projections
  - health
  - sweep
  - close-out
  - dispatch-only
  - routing-enforced
author: omninode
composable: true
args:
  - name: --omni-home
    description: string arg
    required: false
  - name: --table
    description: string arg
    required: false
  - name: --staleness-threshold-hours
    description: integer arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:database_sweep — one command, one typed result

**Skill ID**: `onex:database_sweep` · **Command**: `uv run onex skill database_sweep` (omnibase_infra) · **Backing node**: `node_database_sweep` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[DatabaseSweepResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_database_sweep.handlers.handler_database_sweep.DatabaseSweepResult`
