---
description: Projection table health verification — checks row count, latest timestamp, and staleness for every table in omnidash_analytics. Flags tables with 0 rows or data older than 24h. Auto-creates Linear tickets for stale/empty tables.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: verification
tags: [database, projections, health, sweep, close-out]
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

# Database Sweep

**Skill ID**: `onex:database-sweep`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6762
**Epic**: OMN-6760

---

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT
read files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run database-sweep",
  prompt="Run the database-sweep skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Purpose

Projection table health check for the `omnidash_analytics` read-model database.
For each projection table, verify it has data and that data is fresh.

**Announce at start:** "I'm using the database-sweep skill to check projection table health in omnidash_analytics."

## Usage

```
/database-sweep
/database-sweep --dry-run
/database-sweep --table agent_routing_decisions
/database-sweep --staleness-threshold 48
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | false | Report only, no Linear tickets created |
| `--table` | _(all)_ | Check a single table instead of all |
| `--staleness-threshold` | 24 | Hours before data is considered stale |

---

## Phase 1 — Table Discovery

Query the database for all user tables in `omnidash_analytics`:

```sql
SELECT tablename FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

Cross-reference with Drizzle schema definitions in `omnidash/shared/intelligence-schema.ts`
to identify expected tables vs actual tables.

Output: table manifest with expected vs actual comparison.

If `--table` is set, filter the manifest to that single table.

---

## Phase 2 — Health Check

For each table, run:

```sql
SELECT
  '{table}' AS table_name,
  count(*) AS row_count,
  max(created_at) AS latest_row,
  CASE
    WHEN count(*) = 0 THEN 'EMPTY'
    WHEN max(created_at) < now() - interval '{staleness_threshold} hours' THEN 'STALE'
    ELSE 'HEALTHY'
  END AS status
FROM {table};
```

If the table lacks a `created_at` column, try `timestamp`, `emitted_at`, `updated_at`,
or `recorded_at` as fallbacks. If no timestamp column exists, classify based on row count only.

Classify each table:
- `HEALTHY`: has rows, latest row within staleness threshold
- `STALE`: has rows but latest row older than threshold
- `EMPTY`: 0 rows
- `MISSING`: defined in Drizzle schema but table does not exist in DB
- `ORPHAN`: exists in DB but not in Drizzle schema
- `NO_TIMESTAMP`: has rows but no timestamp column (report row count only)

---

## Phase 3 — Report + Ticket Creation

Emit a summary table:

| Table | Row Count | Latest Row | Status | Drizzle Defined | Handler |
|-------|-----------|------------|--------|-----------------|---------|

For each non-HEALTHY table, look up the corresponding projection handler in
`omnidash/server/projections/` and the upstream Kafka topic in `omnidash/topics.yaml`.

For `EMPTY` and `STALE` tables, auto-create a Linear ticket unless `--dry-run` is set:

```
Title: fix(projection): {table} — {status}
Project: Active Sprint
Labels: projection, database-sweep
Description:
  - Table: {table}
  - Status: {status}
  - Row count: {count}
  - Latest row: {timestamp or N/A}
  - Projection handler: {handler_file}
  - Upstream topic: {topic}
  - Drizzle schema: omnidash/shared/intelligence-schema.ts
```

Skip ticket creation for:
- `--dry-run` mode
- `ORPHAN` tables (document only, no ticket)
- `NO_TIMESTAMP` tables with row_count > 0 (healthy by count)

---

## Dispatch Rules

```
RULE: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent".
RULE: NEVER modify files directly from the orchestrator context.
RULE: --dry-run produces zero side effects: no tickets, no PRs, no file changes.
```

---

## Integration Points

- **autopilot**: invoked as optional database health step in close-out mode
- **data-flow-sweep**: complementary — data-flow checks pipeline; database-sweep checks table health
- **dashboard-sweep**: complementary — dashboard-sweep checks UI; database-sweep checks storage
