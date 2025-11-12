# Database Migrations

This directory contains database migration scripts for OmniClaude. Migrations manage schema changes, data transformations, and database evolution in a versioned, traceable manner.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Migration Sequence](#migration-sequence)
3. [Numbering Convention](#numbering-convention)
4. [Running Migrations](#running-migrations)
5. [Rollback Procedures](#rollback-procedures)
6. [Data Migration Strategy](#data-migration-strategy)
7. [Dependencies](#dependencies)
8. [Verification](#verification)
9. [Best Practices](#best-practices)
10. [Migration Index](#migration-index)

---

## Quick Start

```bash
# 1. Load environment variables (REQUIRED)
source .env

# 2. Verify credentials are loaded
echo "Host: ${POSTGRES_HOST}"
echo "Database: ${POSTGRES_DATABASE}"

# 3. Run a specific migration
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -f migrations/001_debug_loop_core_schema.sql

# 4. Verify migration success
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'debug_%';"
```

---

## Migration Sequence

**Current Migration Order** (as of 2025-11-12):

1. **001_debug_loop_core_schema.sql** - Phase 1: Debug Intelligence Core (5 tables + 3 views)
2. **005_create_agent_actions_table.sql** - Agent action logging table + view
3. **012_create_pattern_quality_metrics.sql** - Pattern quality metrics table
4. **013_remove_pattern_quality_fk.sql** - Remove FK constraint from pattern_quality_metrics
5. **014_add_pattern_quality_unique_constraint.sql** - Add unique constraint to pattern_quality_metrics
6. **add_service_metrics.sql** - Add service-level metrics columns + 2 views

**Note**: Not all migrations have sequential numbers. Some use descriptive names (e.g., `add_service_metrics.sql`). Always check dependencies before running.

---

## Numbering Convention

### Standard Format

```
<sequence>_<descriptive_name>.sql
```

**Examples**:
- `001_debug_loop_core_schema.sql` - Numbered migration (001)
- `005_create_agent_actions_table.sql` - Numbered migration (005)
- `add_service_metrics.sql` - Descriptive name (no number)

### Numbering Rules

1. **Sequential Numbers**: Use 3-digit zero-padded numbers (001, 002, 003)
2. **Non-sequential**: Gaps in numbering are acceptable (001 → 005 → 012)
3. **Descriptive Names**: Use lowercase with underscores (snake_case)
4. **Purpose-Driven**: Name should clearly indicate what the migration does

### When to Use Numbers vs Descriptive Names

| Migration Type | Naming Convention | Example |
|----------------|-------------------|---------|
| **Major feature** | Use numbers (001-999) | `001_debug_loop_core_schema.sql` |
| **Schema changes** | Use descriptive name | `add_service_metrics.sql` |
| **Data migration** | Use numbers + descriptive | `002_migrate_legacy_data.sql` |
| **Hotfix/patch** | Use descriptive name | `fix_null_correlation_ids.sql` |
| **Rollback** | Use original number + `_rollback` | `013_rollback_pattern_quality_fk.sql` |

### Rollback File Convention

```
<sequence>_rollback_<original_migration_name>.sql
```

**Example**: `013_rollback_pattern_quality_fk.sql` rolls back `013_remove_pattern_quality_fk.sql`

---

## Running Migrations

### Security Note

⚠️ **Always load credentials from `.env` before running database commands**:

```bash
source .env
```

Never hardcode database credentials in documentation or scripts. All connection details should use environment variables.

### Prerequisites

1. **PostgreSQL Access**: Ensure you have access to the PostgreSQL database
   - Host: `${POSTGRES_HOST}` (default: `192.168.86.200`)
   - Port: `${POSTGRES_PORT}` (default: `5436`)
   - Database: `${POSTGRES_DATABASE}` (default: `omninode_bridge`)
   - User: `${POSTGRES_USER}` (default: `postgres`)

2. **Environment Variables**: Load credentials from `.env` before running migrations

```bash
# Load environment variables (REQUIRED)
source .env

# Verify credentials are loaded
echo "Host: ${POSTGRES_HOST}"
echo "Port: ${POSTGRES_PORT}"
echo "Database: ${POSTGRES_DATABASE}"
echo "User: ${POSTGRES_USER}"
```

### Method 1: Using psql (Recommended)

```bash
# Load credentials
source .env

# Run migration
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -f migrations/001_debug_loop_core_schema.sql

# Run with verbose output
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -v ON_ERROR_STOP=1 -f migrations/001_debug_loop_core_schema.sql

# Run multiple migrations sequentially
for migration in migrations/00{1,5}*.sql; do
  echo "Running $migration..."
  psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
    -v ON_ERROR_STOP=1 -f "$migration"
done
```

### Method 2: Using Python Config

If you have the Python environment set up:

```bash
python3 -c "
from config import settings
import subprocess
import os

os.environ['PGPASSWORD'] = settings.postgres_password
subprocess.run([
    'psql',
    '-h', settings.postgres_host,
    '-p', str(settings.postgres_port),
    '-U', settings.postgres_user,
    '-d', settings.postgres_database,
    '-f', 'migrations/001_debug_loop_core_schema.sql'
])
"
```

### Method 3: Interactive psql Session

```bash
# Load credentials
source .env

# Connect to database
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}

-- Inside psql, run migration
\i migrations/001_debug_loop_core_schema.sql

-- Check results
\dt debug_*
\dv v_*
```

### Common Options

| Option | Purpose | Example |
|--------|---------|---------|
| `-f <file>` | Run SQL file | `-f migrations/001_*.sql` |
| `-v ON_ERROR_STOP=1` | Stop on first error | Prevents partial migrations |
| `-c "<command>"` | Run single command | `-c "SELECT version()"` |
| `-a` | Echo all input | Shows SQL being executed |
| `-q` | Quiet mode | Suppress notices |
| `-X` | Ignore .psqlrc | Clean environment |

---

## Rollback Procedures

### General Rollback Strategy

1. **Identify migration to rollback**
2. **Check for dependent migrations** (see Dependencies section)
3. **Run rollback SQL** (if available)
4. **Verify rollback success**

### Rollback Methods

#### Method 1: Using Embedded Rollback SQL

Some migrations include rollback SQL in comments at the bottom of the file:

```bash
# Load credentials
source .env

# Extract rollback SQL (lines starting with -- followed by SQL)
# Then run manually or save to file

# Example: add_service_metrics.sql has rollback SQL in comments
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} <<EOF
DROP VIEW IF EXISTS v_router_agent_performance;
DROP VIEW IF EXISTS v_router_service_performance;
DROP INDEX IF EXISTS idx_agent_routing_decisions_performance_query;
ALTER TABLE agent_routing_decisions DROP COLUMN IF EXISTS service_latency_ms;
ALTER TABLE agent_routing_decisions DROP COLUMN IF EXISTS service_version;
EOF
```

#### Method 2: Using Dedicated Rollback Files

Some migrations have dedicated rollback files (e.g., `013_rollback_pattern_quality_fk.sql`):

```bash
# Load credentials
source .env

# Run rollback file
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -f migrations/013_rollback_pattern_quality_fk.sql
```

#### Method 3: Manual Rollback

If no rollback script exists, manually reverse the migration:

```sql
-- General pattern for rolling back table creation
DROP TABLE IF EXISTS <table_name> CASCADE;

-- Rolling back column additions
ALTER TABLE <table_name> DROP COLUMN IF EXISTS <column_name>;

-- Rolling back constraint additions
ALTER TABLE <table_name> DROP CONSTRAINT IF EXISTS <constraint_name>;

-- Rolling back index creation
DROP INDEX IF EXISTS <index_name>;

-- Rolling back view creation
DROP VIEW IF EXISTS <view_name>;

-- Rolling back function creation
DROP FUNCTION IF EXISTS <function_name>() CASCADE;
```

### Rollback Examples

#### Rollback Migration 001 (Debug Loop Core Schema)

```sql
-- Drop tables (cascades to foreign keys)
DROP TABLE IF EXISTS debug_golden_states CASCADE;
DROP TABLE IF EXISTS debug_error_success_mappings CASCADE;
DROP TABLE IF EXISTS debug_execution_attempts CASCADE;
DROP TABLE IF EXISTS model_price_catalog CASCADE;
DROP TABLE IF EXISTS debug_transform_functions CASCADE;

-- Drop views
DROP VIEW IF EXISTS v_recommended_stfs;
DROP VIEW IF EXISTS v_error_resolution_patterns;
DROP VIEW IF EXISTS v_golden_states_full;

-- Drop helper functions
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
DROP FUNCTION IF EXISTS calculate_error_mapping_confidence() CASCADE;
```

#### Rollback Migration 005 (Agent Actions Table)

```sql
-- Drop view
DROP VIEW IF EXISTS recent_debug_traces;

-- Drop function
DROP FUNCTION IF EXISTS cleanup_old_debug_logs();

-- Drop table
DROP TABLE IF EXISTS agent_actions CASCADE;
```

#### Rollback Migration 012-014 (Pattern Quality Metrics)

```sql
-- Rollback in reverse order (014 → 013 → 012)

-- 014: Remove unique constraint
ALTER TABLE pattern_quality_metrics
DROP CONSTRAINT IF EXISTS pattern_quality_metrics_pattern_id_measurement_timestamp_key;

-- 013: Re-add foreign key (if needed)
-- NOTE: Only if you rolled back to before 012
-- ALTER TABLE pattern_quality_metrics
-- ADD CONSTRAINT pattern_quality_metrics_pattern_id_fkey
-- FOREIGN KEY (pattern_id) REFERENCES pattern_lineage_nodes(id);

-- 012: Drop table
DROP TABLE IF EXISTS pattern_quality_metrics CASCADE;
```

### Rollback Verification

After rollback, verify changes:

```sql
-- Check tables were dropped
SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'debug_%';

-- Check views were dropped
SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname LIKE 'v_%';

-- Check columns were removed
SELECT column_name FROM information_schema.columns
WHERE table_name = 'agent_routing_decisions' AND column_name IN ('service_version', 'service_latency_ms');

-- Check constraints were removed
SELECT constraint_name FROM information_schema.table_constraints
WHERE table_name = 'pattern_quality_metrics';
```

---

## Data Migration Strategy

### Data Migration Types

OmniClaude migrations fall into three categories:

| Type | Description | Examples |
|------|-------------|----------|
| **Schema-only** | No data changes | 012, 013, 014, add_service_metrics |
| **Schema + Seed Data** | Schema with initial data | 001 (model pricing seed data) |
| **Data Transformation** | Modify existing data | None currently |

### Seed Data Strategy

**Migration 001** includes seed data for model pricing catalog (15 models):

```sql
-- Seed data uses ON CONFLICT to allow idempotent migrations
INSERT INTO model_price_catalog (provider, model_name, model_version, ...)
VALUES ('anthropic', 'claude-3-5-sonnet-20241022', '3.5', ...)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;
```

**Why this approach?**
- ✅ **Idempotent**: Can run multiple times safely
- ✅ **Versioned**: Tracks pricing changes over time using `effective_date`
- ✅ **Updatable**: New pricing can be added without conflicts

### Data Transformation Best Practices

When creating data transformation migrations:

1. **Use transactions**: Wrap in `BEGIN` / `COMMIT`
2. **Include rollback**: Provide reverse transformation
3. **Validate data**: Include verification queries
4. **Backup first**: Document backup requirements
5. **Test on staging**: Never run untested migrations on production

**Example Template**:

```sql
-- Migration: <number>_<name>.sql
-- Description: Transform data from format A to format B
-- Rollback: See bottom of file

BEGIN;

-- Step 1: Backup data (optional - create temp table)
CREATE TEMP TABLE backup_table AS SELECT * FROM target_table;

-- Step 2: Transform data
UPDATE target_table
SET new_column = CASE
    WHEN old_column = 'value1' THEN 'new_value1'
    WHEN old_column = 'value2' THEN 'new_value2'
    ELSE old_column
END;

-- Step 3: Verify transformation
DO $$
DECLARE
    invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO invalid_count
    FROM target_table
    WHERE new_column IS NULL;

    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'Data transformation failed: % rows have NULL values', invalid_count;
    END IF;

    RAISE NOTICE 'Data transformation verified: All rows valid';
END $$;

COMMIT;

-- ROLLBACK:
-- BEGIN;
-- UPDATE target_table SET new_column = old_column;
-- COMMIT;
```

### Handling Large Data Migrations

For migrations affecting >100K rows:

1. **Use batching**: Process in chunks to avoid locks
2. **Monitor progress**: Add RAISE NOTICE for milestones
3. **Consider downtime**: Schedule during maintenance window
4. **Test performance**: Measure time on staging with production-like data

**Batching Example**:

```sql
-- Process in batches of 10,000 rows
DO $$
DECLARE
    batch_size INTEGER := 10000;
    processed INTEGER := 0;
    total_rows INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_rows FROM target_table WHERE needs_migration = true;

    LOOP
        UPDATE target_table
        SET new_column = transform_function(old_column),
            needs_migration = false
        WHERE id IN (
            SELECT id FROM target_table
            WHERE needs_migration = true
            LIMIT batch_size
        );

        processed := processed + batch_size;
        RAISE NOTICE 'Processed % of % rows (%.1f%%)',
            processed, total_rows, (processed::FLOAT / total_rows * 100);

        EXIT WHEN NOT FOUND;

        -- Allow other queries to run
        PERFORM pg_sleep(0.1);
    END LOOP;

    RAISE NOTICE 'Migration complete: % rows processed', total_rows;
END $$;
```

---

## Dependencies

Understanding migration dependencies is critical to avoid breaking changes.

### Dependency Graph

```
001_debug_loop_core_schema.sql (Independent)
  └─ Creates: debug_* tables, model_price_catalog, helper functions

005_create_agent_actions_table.sql (Independent)
  └─ Creates: agent_actions table, recent_debug_traces view

012_create_pattern_quality_metrics.sql (Independent)
  └─ Creates: pattern_quality_metrics table
       │
       ├─ 013_remove_pattern_quality_fk.sql (Depends on 012)
       │    └─ Removes FK constraint
       │         │
       │         └─ 014_add_pattern_quality_unique_constraint.sql (Depends on 013)
       │              └─ Adds unique constraint

add_service_metrics.sql (Depends on agent_routing_decisions existing)
  └─ Adds columns to agent_routing_decisions
  └─ Creates: v_router_service_performance, v_router_agent_performance
```

### External Dependencies

Some migrations depend on tables created in other repositories:

| Migration | External Dependency | Repository | Table |
|-----------|---------------------|------------|-------|
| `add_service_metrics.sql` | `agent_routing_decisions` | omninode_bridge | Yes |
| `012_create_pattern_quality_metrics.sql` | None | - | - |

### Checking Dependencies

Before running a migration:

```sql
-- Check if required tables exist
SELECT tablename FROM pg_tables
WHERE schemaname = 'public'
AND tablename IN ('agent_routing_decisions', 'pattern_lineage_nodes');

-- Check if required columns exist
SELECT column_name FROM information_schema.columns
WHERE table_name = 'agent_routing_decisions'
AND column_name IN ('correlation_id', 'created_at');

-- Check if required functions exist
SELECT proname FROM pg_proc
WHERE proname IN ('update_updated_at_column', 'calculate_error_mapping_confidence');
```

### Safe Migration Order

**When running all migrations from scratch**:

```bash
# Run in this order to satisfy dependencies
psql -f migrations/001_debug_loop_core_schema.sql
psql -f migrations/005_create_agent_actions_table.sql
psql -f migrations/012_create_pattern_quality_metrics.sql
psql -f migrations/013_remove_pattern_quality_fk.sql
psql -f migrations/014_add_pattern_quality_unique_constraint.sql
psql -f migrations/add_service_metrics.sql
```

**When running rollbacks**:

```bash
# Roll back in REVERSE order
psql -f migrations/rollback_add_service_metrics.sql
psql -f migrations/014_rollback_*.sql
psql -f migrations/013_rollback_pattern_quality_fk.sql
psql -f migrations/rollback_012_*.sql
psql -f migrations/rollback_005_*.sql
psql -f migrations/rollback_001_*.sql
```

---

## Verification

After running migrations, always verify success.

### Quick Verification

```bash
# Load credentials
source .env

# Check tables created
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'debug_%' ORDER BY tablename;"
```

### Detailed Verification Queries

#### Verify Migration 001 (Debug Loop Core Schema)

```sql
-- Check table creation (expect 5 tables)
SELECT tablename FROM pg_tables WHERE schemaname = 'public'
AND tablename IN (
    'debug_transform_functions',
    'model_price_catalog',
    'debug_execution_attempts',
    'debug_error_success_mappings',
    'debug_golden_states'
);

-- Check view creation (expect 3 views)
SELECT viewname FROM pg_views WHERE schemaname = 'public'
AND viewname IN ('v_recommended_stfs', 'v_error_resolution_patterns', 'v_golden_states_full');

-- Check seed data (expect 15 model entries)
SELECT provider, COUNT(*) as model_count
FROM model_price_catalog
GROUP BY provider
ORDER BY provider;

-- Expected output:
--   anthropic | 3
--   google    | 3
--   openai    | 3
--   together  | 3
--   zai       | 4

-- Check indexes (expect 23 indexes)
SELECT tablename, COUNT(*) as index_count
FROM pg_indexes
WHERE schemaname = 'public'
AND tablename LIKE 'debug_%'
GROUP BY tablename;

-- Check helper functions
SELECT proname FROM pg_proc
WHERE proname IN ('update_updated_at_column', 'calculate_error_mapping_confidence');
```

#### Verify Migration 005 (Agent Actions Table)

```sql
-- Check table structure
\d agent_actions

-- Check indexes (expect 6 indexes)
SELECT indexname FROM pg_indexes
WHERE tablename = 'agent_actions';

-- Check view exists
SELECT * FROM recent_debug_traces LIMIT 0;

-- Check function exists
SELECT proname FROM pg_proc WHERE proname = 'cleanup_old_debug_logs';

-- Test cleanup function (dry run - won't delete anything recent)
SELECT cleanup_old_debug_logs();
```

#### Verify Migration 012-014 (Pattern Quality Metrics)

```sql
-- Check table exists
\d pattern_quality_metrics

-- Check indexes (expect 4 indexes)
SELECT indexname FROM pg_indexes WHERE tablename = 'pattern_quality_metrics';

-- Verify FK constraint removed (013)
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'pattern_quality_metrics'
AND constraint_type = 'FOREIGN KEY';
-- Expected: 0 rows (FK removed in 013)

-- Verify unique constraint added (014)
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'pattern_quality_metrics'
AND constraint_type = 'UNIQUE';
-- Expected: 1 row (unique constraint added in 014)

-- Test insert (should succeed)
INSERT INTO pattern_quality_metrics (pattern_id, quality_score, confidence)
VALUES (gen_random_uuid(), 0.85, 0.90);

-- Test duplicate insert (should fail due to unique constraint)
-- This verifies 014 migration worked
```

#### Verify Migration add_service_metrics

```sql
-- Check new columns exist
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'agent_routing_decisions'
AND column_name IN ('service_version', 'service_latency_ms');

-- Check new views exist
SELECT viewname FROM pg_views WHERE schemaname = 'public'
AND viewname IN ('v_router_service_performance', 'v_router_agent_performance');

-- Check new indexes
SELECT indexname FROM pg_indexes
WHERE tablename = 'agent_routing_decisions'
AND indexname LIKE '%service%';

-- Test views return data (even if empty)
SELECT COUNT(*) FROM v_router_service_performance;
SELECT COUNT(*) FROM v_router_agent_performance;
```

### Comprehensive Health Check

Run this query to get overall migration status:

```sql
-- Comprehensive migration health check
WITH expected_objects AS (
    SELECT 'table' as object_type, 'debug_transform_functions' as object_name
    UNION ALL SELECT 'table', 'model_price_catalog'
    UNION ALL SELECT 'table', 'debug_execution_attempts'
    UNION ALL SELECT 'table', 'debug_error_success_mappings'
    UNION ALL SELECT 'table', 'debug_golden_states'
    UNION ALL SELECT 'table', 'agent_actions'
    UNION ALL SELECT 'table', 'pattern_quality_metrics'
    UNION ALL SELECT 'view', 'v_recommended_stfs'
    UNION ALL SELECT 'view', 'v_error_resolution_patterns'
    UNION ALL SELECT 'view', 'v_golden_states_full'
    UNION ALL SELECT 'view', 'recent_debug_traces'
    UNION ALL SELECT 'view', 'v_router_service_performance'
    UNION ALL SELECT 'view', 'v_router_agent_performance'
    UNION ALL SELECT 'function', 'update_updated_at_column'
    UNION ALL SELECT 'function', 'calculate_error_mapping_confidence'
    UNION ALL SELECT 'function', 'cleanup_old_debug_logs'
),
actual_tables AS (
    SELECT 'table' as object_type, tablename as object_name
    FROM pg_tables WHERE schemaname = 'public'
),
actual_views AS (
    SELECT 'view' as object_type, viewname as object_name
    FROM pg_views WHERE schemaname = 'public'
),
actual_functions AS (
    SELECT 'function' as object_type, proname as object_name
    FROM pg_proc WHERE pronamespace = 'public'::regnamespace
),
actual_objects AS (
    SELECT * FROM actual_tables
    UNION ALL SELECT * FROM actual_views
    UNION ALL SELECT * FROM actual_functions
)
SELECT
    e.object_type,
    e.object_name,
    CASE WHEN a.object_name IS NOT NULL THEN '✅ EXISTS' ELSE '❌ MISSING' END as status
FROM expected_objects e
LEFT JOIN actual_objects a ON e.object_type = a.object_type AND e.object_name = a.object_name
ORDER BY e.object_type, e.object_name;
```

---

## Best Practices

### Before Creating a Migration

1. **Check existing migrations** for similar changes
2. **Review dependencies** to understand impact
3. **Test on local database** before committing
4. **Document the purpose** in migration header comments
5. **Include rollback SQL** in comments or separate file

### Migration File Structure

```sql
-- =====================================================================
-- Migration: <number>_<descriptive_name>
-- Description: <what this migration does>
-- Created: <YYYY-MM-DD>
-- Author: <your_name>
-- Dependencies: <list of required migrations or tables>
-- Part: <Phase N - <feature_name>> (optional)
-- =====================================================================

-- Optional: Check prerequisites
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'required_table') THEN
        RAISE EXCEPTION 'Required table "required_table" does not exist. Run migration XYZ first.';
    END IF;
END $$;

-- Wrap in transaction (optional but recommended)
BEGIN;

-- Your migration SQL here
CREATE TABLE ...;
CREATE INDEX ...;
INSERT INTO ...;

-- Verify migration success
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'new_table') THEN
        RAISE EXCEPTION 'Migration failed: new_table was not created';
    END IF;

    RAISE NOTICE 'Migration completed successfully';
END $$;

COMMIT;

-- =====================================================================
-- ROLLBACK (uncomment to rollback)
-- =====================================================================
/*
BEGIN;
DROP TABLE IF EXISTS new_table CASCADE;
COMMIT;
*/
```

### Testing Migrations

1. **Test on local database first**:
   ```bash
   # Load credentials for local test database
   export POSTGRES_DATABASE=omninode_bridge_test
   source .env

   # Run migration
   psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
     -v ON_ERROR_STOP=1 -f migrations/new_migration.sql
   ```

2. **Test rollback**:
   ```bash
   # Run rollback
   psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
     -f migrations/rollback_new_migration.sql

   # Verify rollback success
   psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
     -c "SELECT tablename FROM pg_tables WHERE tablename = 'new_table';"
   # Should return 0 rows
   ```

3. **Test idempotency**:
   ```bash
   # Run migration twice - should succeed both times
   psql -f migrations/new_migration.sql
   psql -f migrations/new_migration.sql
   ```

### Common Pitfalls to Avoid

| Pitfall | Why It's Bad | Solution |
|---------|--------------|----------|
| **Hardcoded credentials** | Security risk | Use environment variables |
| **Missing rollback** | Can't undo changes | Include rollback SQL |
| **No transaction** | Partial failures | Wrap in `BEGIN`/`COMMIT` |
| **No verification** | Silent failures | Add verification queries |
| **Missing dependencies** | Migration fails | Check prerequisites first |
| **Non-idempotent SQL** | Can't rerun safely | Use `IF NOT EXISTS`, `ON CONFLICT` |
| **No comments** | Hard to understand | Document purpose and impact |
| **Breaking changes** | Data loss risk | Test thoroughly first |

### Performance Considerations

1. **Index creation**: Use `CONCURRENTLY` for production:
   ```sql
   CREATE INDEX CONCURRENTLY idx_name ON table(column);
   ```

2. **Large data changes**: Batch updates to avoid locks:
   ```sql
   -- Bad: locks entire table
   UPDATE large_table SET column = 'value';

   -- Good: batched updates
   UPDATE large_table SET column = 'value' WHERE id IN (
       SELECT id FROM large_table WHERE column IS NULL LIMIT 10000
   );
   ```

3. **Constraint validation**: Add constraints as NOT VALID first, then validate:
   ```sql
   -- Add constraint without validating existing rows
   ALTER TABLE table_name ADD CONSTRAINT check_name CHECK (condition) NOT VALID;

   -- Validate in separate transaction (can be cancelled)
   ALTER TABLE table_name VALIDATE CONSTRAINT check_name;
   ```

---

## Migration Index

### Active Migrations

| # | File | Description | Tables | Views | Functions | Seed Data | Dependencies |
|---|------|-------------|--------|-------|-----------|-----------|--------------|
| 001 | `001_debug_loop_core_schema.sql` | Debug Intelligence Core | 5 | 3 | 2 | ✅ 15 models | None |
| 005 | `005_create_agent_actions_table.sql` | Agent action logging | 1 | 1 | 1 | ❌ | None |
| 012 | `012_create_pattern_quality_metrics.sql` | Pattern quality metrics | 1 | 0 | 0 | ❌ | None |
| 013 | `013_remove_pattern_quality_fk.sql` | Remove FK constraint | 0 (ALTER) | 0 | 0 | ❌ | 012 |
| 014 | `014_add_pattern_quality_unique_constraint.sql` | Add unique constraint | 0 (ALTER) | 0 | 0 | ❌ | 013 |
| - | `add_service_metrics.sql` | Service-level metrics | 0 (ALTER) | 2 | 0 | ❌ | agent_routing_decisions |

**Legend**:
- ✅ = Includes seed data
- ❌ = No seed data
- (ALTER) = Modifies existing table

### Rollback Files

| File | Rolls Back | Status |
|------|------------|--------|
| `013_rollback_pattern_quality_fk.sql` | Migration 013 | ✅ Available |

### Documentation Files

| File | Purpose | Migration |
|------|---------|-----------|
| `README_MIGRATION_012.md` | Pattern quality metrics guide | 012 |
| `README_MIGRATION_013.md` | FK removal guide | 013 |
| `README_MIGRATION_014.md` | Unique constraint guide | 014 |
| `README_MIGRATION_015.md` | Hook integration guide | 015 |
| `015_hook_agent_invocation_integration.md` | Hook integration details | 015 |
| `015_completion_report.md` | Completion status | 015 |
| `015_SUMMARY.txt` | Summary of changes | 015 |
| `015_VERIFICATION.md` | Verification checklist | 015 |

---

## Troubleshooting

### Common Issues

#### Migration Fails with "relation already exists"

**Cause**: Migration was already run or partially completed.

**Solution**:
```sql
-- Check if objects exist
SELECT tablename FROM pg_tables WHERE tablename = 'table_name';

-- If exists, either:
-- 1. Skip the migration (it's already applied)
-- 2. Run rollback first, then rerun migration
```

#### Migration Fails with "permission denied"

**Cause**: Database user lacks required permissions.

**Solution**:
```sql
-- Check current user permissions
SELECT * FROM information_schema.role_table_grants WHERE grantee = current_user;

-- Grant required permissions (as superuser)
GRANT CREATE ON SCHEMA public TO your_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO your_user;
```

#### Migration Fails with "column does not exist"

**Cause**: Missing dependency migration.

**Solution**:
```sql
-- Check dependencies
SELECT tablename, column_name FROM information_schema.columns
WHERE table_name = 'required_table' AND column_name = 'required_column';

-- If missing, run dependency migrations first
```

#### Rollback Fails with "other objects depend on it"

**Cause**: Foreign key constraints or views reference the object.

**Solution**:
```sql
-- Use CASCADE to drop dependent objects
DROP TABLE table_name CASCADE;

-- Or, drop dependencies first:
-- 1. Find dependencies
SELECT
    tc.table_name,
    tc.constraint_name,
    kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
AND kcu.table_name = 'dependent_table';

-- 2. Drop dependencies manually
ALTER TABLE dependent_table DROP CONSTRAINT constraint_name;
```

### Getting Help

1. **Check migration documentation**: See `README_MIGRATION_*.md` files
2. **Review migration SQL**: Comments often explain dependencies and caveats
3. **Check database logs**: `tail -f /var/log/postgresql/postgresql.log`
4. **Ask in #omniclaude-dev**: Slack channel for migration support

---

## Future Migrations

### Planned Migrations

1. **Debug Loop Phase 2** (Week 2)
   - Node implementation tables
   - Workflow orchestration tables
   - Contract validation tables

2. **Debug Loop Phase 3** (Week 3-4)
   - Integration tables
   - Performance metrics tables
   - Cost optimization tables

See `docs/planning/DEBUG_LOOP_ONEX_IMPLEMENTATION_PLAN.md` for complete roadmap.

### Creating New Migrations

When you need to create a new migration:

1. **Copy template**:
   ```bash
   cp migrations/migration_template.sql migrations/016_your_feature.sql
   ```

2. **Fill in details**:
   - Migration number (next available: 016+)
   - Descriptive name
   - Dependencies
   - SQL changes
   - Rollback SQL

3. **Test locally**:
   ```bash
   # Test on local database
   ./scripts/test_migration.sh migrations/016_your_feature.sql
   ```

4. **Update this README**:
   - Add to [Migration Index](#migration-index)
   - Update [Dependencies](#dependencies) if needed
   - Add verification queries to [Verification](#verification)

5. **Commit**:
   ```bash
   git add migrations/016_your_feature.sql migrations/README.md
   git commit -m "feat(migrations): add 016_your_feature migration"
   ```

---

**Last Updated**: 2025-11-12
**Total Migrations**: 6 active migrations (001, 005, 012, 013, 014, add_service_metrics)
**Total Tables Created**: 7 tables across all migrations
**Total Views Created**: 6 views across all migrations
**Rollback Coverage**: Partial (1 dedicated rollback file, others have embedded rollback SQL)
