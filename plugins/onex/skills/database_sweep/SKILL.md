---
description: Projection table health and migration tracking — checks row count, staleness for every table in omnidash_analytics, plus migration state across all ONEX databases (pending migrations, failed state, schema fingerprint). Auto-creates Linear tickets for stale/empty tables and migration drift.
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
  - name: --dry-run
    description: "Report findings without creating Linear tickets (default: false)"
    required: false
  - name: --table
    description: "Check a single table only (e.g., agent_routing_decisions)"
    required: false
  - name: --staleness-threshold
    description: "Hours before data is considered stale (default: 24)"
    required: false
---

# /onex:database_sweep — Database Health Sweep

**Skill ID**: `onex:database-sweep`
**Version**: 3.0.0
**Backing node**: `node_database_sweep`

## Changelog

- **3.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_database_sweep`.
- **2.0.0** — Added node_platform_diagnostics dispatch path.

## What this skill does

Dispatches through `onex run-node node_database_sweep`. The node owns table health
checks, migration state validation, and ticket creation. This shim contains no
inline database probe logic.

**Announce at start:** "I'm using the database-sweep skill."

## Dispatch

```bash
uv run onex run-node node_database_sweep --input '{
  "dry_run": false,
  "table": null,
  "staleness_threshold_hours": 24
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_database_sweep`

Command topic: `onex.cmd.omnimarket.database-sweep-start.v1`

Terminal events:
- `onex.evt.omnimarket.database-sweep-table-checked.v1`
- `onex.evt.omnimarket.database-sweep-completed.v1`
