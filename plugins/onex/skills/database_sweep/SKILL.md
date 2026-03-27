---
description: Projection table health and migration tracking — checks row count, staleness for every table in omnidash_analytics, plus migration state across all ONEX databases (pending migrations, failed state, schema fingerprint). Auto-creates Linear tickets for stale/empty tables and migration drift.
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

## Purpose

Projection table health check and migration tracking across all ONEX databases.
For each projection table, verify it has data and that data is fresh.
For each database, verify migrations are fully applied and schema is consistent.

## Announce

"I'm using the database-sweep skill to check projection table health in omnidash_analytics."

## Usage

/database-sweep
/database-sweep --dry-run
/database-sweep --table agent_routing_decisions
/database-sweep --staleness-threshold 48

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

## Phase 3 — Migration Tracking

For each ONEX database, verify migration state is clean.

**Database inventory:**

| Repo | Database | Migration Path | Migration Tool |
|------|----------|---------------|----------------|
| omnibase_infra | `omnibase_infra` | `omnibase_infra/src/omnibase_infra/migrations/` | Alembic |
| omniintelligence | `omniintelligence` | `omniintelligence/src/omniintelligence/migrations/` | Alembic |
| omnimemory | `omnimemory_db` | `omnimemory/src/omnimemory/migrations/` | Alembic |
| omnidash | `omnidash_analytics` | `omnidash/migrations/` | Drizzle |

**Step 3a: Count migrations on disk vs applied**

For Alembic repos, count migration files on disk:

```bash
ls {migration_path}/versions/*.py | wc -l
```

Then query the `alembic_version` table for the current head:

```sql
SELECT version_num FROM alembic_version;
```

Walk the Alembic revision chain from the on-disk head back to base and count
revisions. Compare on-disk count with applied head position.

For omnidash (Drizzle), count migration files:

```bash
ls omnidash/migrations/*.sql | wc -l
```

Query the Drizzle migrations journal:

```sql
SELECT count(*) FROM drizzle.__drizzle_migrations;
```

**Step 3b: Flag pending/unapplied migrations**

Compare disk count vs applied count. If disk > applied, migrations are pending.

Classify each database:
- `CURRENT`: all migrations applied, head matches latest on disk
- `PENDING`: unapplied migrations exist (disk > applied)
- `AHEAD`: applied version not found on disk (possible branch divergence)
- `FAILED`: migration marked as failed in state table
- `NO_TABLE`: `alembic_version` / `drizzle.__drizzle_migrations` table missing

**Step 3c: Verify schema fingerprint**

For each database, capture a schema fingerprint by hashing the sorted list of
tables and their column definitions:

```sql
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

Compare this fingerprint across runs to detect schema drift (changes not
captured by migrations).

**Step 3d: Check for failed migration state**

For Alembic repos, check if any migration is in a partially-applied state:

```sql
-- Multiple heads = branching issue
SELECT count(*) FROM alembic_version;
-- Should be exactly 1
```

For Drizzle, check for failed entries:

```sql
SELECT * FROM drizzle.__drizzle_migrations
WHERE created_at = (SELECT max(created_at) FROM drizzle.__drizzle_migrations);
```

## Phase 4 — Report + Ticket Creation

Emit two summary tables:

### Table Health
| Table | Row Count | Latest Row | Status | Drizzle Defined | Handler |
|-------|-----------|------------|--------|-----------------|---------|

### Migration State
| Database | Repo | Disk Migrations | Applied Migrations | Status | Head |
|----------|------|-----------------|-------------------|--------|------|

For each non-HEALTHY table, look up the corresponding projection handler in
`omnidash/server/projections/` and the upstream Kafka topic in `omnidash/topics.yaml`.

For `EMPTY` and `STALE` tables, auto-create a Linear ticket:

Title: `fix(projection): {table} — {status}`
Project: Active Sprint
Labels: projection, database-sweep
Description template:
  - Table: {table}
  - Status: {status}
  - Row count: {count}
  - Latest row: {timestamp or N/A}
  - Projection handler: {handler_file}
  - Upstream topic: {topic}
  - Drizzle schema: `omnidash/shared/intelligence-schema.ts`

For `PENDING`, `AHEAD`, `FAILED`, or `NO_TABLE` migration states, auto-create a Linear ticket:

Title: `fix(migration): {database} — {migration_status}`
Project: Active Sprint
Labels: migration, database-sweep
Description template:
  - Database: {database}
  - Repo: {repo}
  - Migration status: {status}
  - Disk migrations: {disk_count}
  - Applied migrations: {applied_count}
  - Current head: {head_version}
  - Migration path: {migration_path}

Skip ticket creation for:
- `--dry-run` mode
- `ORPHAN` tables (document only)
- `NO_TIMESTAMP` tables with row_count > 0 (healthy by count)
- `CURRENT` migration state (healthy)

## Dispatch Rules

- ALL work dispatched through `onex:polymorphic-agent`
- NEVER edit files directly from orchestrator context
- `--dry-run` produces zero side effects (no tickets)

## Integration Points

- **autopilot**: invoked as optional database health step in close-out mode
- **data-flow-sweep**: complementary — data-flow checks pipeline; database-sweep checks table health
- **dashboard-sweep**: complementary — dashboard-sweep checks UI; database-sweep checks storage
