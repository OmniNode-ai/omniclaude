# Migration 012: Create pattern_quality_metrics Table

**Date**: 2025-11-02
**Status**: ✅ Applied
**Impact**: Creates the missing pattern_quality_metrics table required for pattern quality scoring

## Problem Statement

The `pattern_quality_metrics` table was referenced by:
- Migration 013 (removes FK constraint)
- Migration 014 (adds UNIQUE constraint)
- `agents/lib/pattern_quality_scorer.py` (stores quality metrics)
- `agents/tests/test_pattern_quality_database_integration.py` (10 tests)

**But the table didn't exist!** This caused all 10 integration tests to fail.

## Root Cause

The table creation migration was never written. Migrations 013 and 014 assumed the table already existed, but there was no migration 012 to create it.

## Solution

Created migration `012_create_pattern_quality_metrics.sql` that:

1. Creates the `pattern_quality_metrics` table with:
   - `id` (uuid, primary key)
   - `pattern_id` (uuid, NOT NULL) - will get UNIQUE constraint in migration 014
   - `quality_score` (double precision, CHECK 0-1)
   - `confidence` (double precision, CHECK 0-1)
   - `measurement_timestamp` (timestamp with time zone)
   - `version` (text, default '1.0.0')
   - `metadata` (jsonb) - stores dimension scores
   - `created_at`, `updated_at` (timestamp with time zone)

2. Creates indexes on:
   - `pattern_id` (for lookups)
   - `quality_score` (for filtering high-quality patterns)
   - `measurement_timestamp` (for recent measurements)
   - `metadata` (GIN index for JSONB queries)

3. Adds comprehensive column comments

## Application

```bash
# Apply migration
source .env && PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -f migrations/012_create_pattern_quality_metrics.sql

# Verify table exists
source .env && PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "\d pattern_quality_metrics"
```

## Migration Sequence

**Correct order**:
1. **Migration 012**: Creates `pattern_quality_metrics` table (this migration)
2. **Migration 013**: Removes FK constraint (no-op since we didn't create one)
3. **Migration 014**: Adds UNIQUE constraint on `pattern_id`

## Test Fixes

Fixed 2 test issues in `agents/tests/test_pattern_quality_database_integration.py`:

### 1. Floating Point Precision (test_uuid_type_casting_in_query)

**Before**:
```python
assert result[0] == 0.80  # Fails: 0.7999999999999999 != 0.80
```

**After**:
```python
assert abs(result[0] - 0.80) < 0.0001  # Approximate comparison
```

### 2. UUID Type Mismatch (test_bulk_upsert_performance)

**Before**:
```python
cursor.execute(
    "SELECT COUNT(*) FROM pattern_quality_metrics WHERE pattern_id = ANY(%s)",
    (test_pattern_ids,),  # List of strings
)
# Error: operator does not exist: uuid = text
```

**After**:
```python
cursor.execute(
    "SELECT COUNT(*) FROM pattern_quality_metrics WHERE pattern_id = ANY(%s::uuid[])",
    (test_pattern_ids,),  # Cast to uuid array
)
```

## Test Results

**Before Migration 012**: ❌ 10 tests failed (table doesn't exist)

**After Migration 012 + Test Fixes**: ✅ 10 tests passed

```
agents/tests/test_pattern_quality_database_integration.py::test_unique_constraint_exists PASSED
agents/tests/test_pattern_quality_database_integration.py::test_check_constraints_exist PASSED
agents/tests/test_pattern_quality_database_integration.py::test_insert_with_valid_uuid PASSED
agents/tests/test_pattern_quality_database_integration.py::test_upsert_updates_existing_record PASSED
agents/tests/test_pattern_quality_database_integration.py::test_constraint_violation_on_invalid_score_range PASSED
agents/tests/test_pattern_quality_database_integration.py::test_concurrent_upserts_handle_conflicts PASSED
agents/tests/test_pattern_quality_database_integration.py::test_uuid_type_casting_in_query PASSED
agents/tests/test_pattern_quality_database_integration.py::test_invalid_uuid_format_rejected PASSED
agents/tests/test_pattern_quality_database_integration.py::test_metadata_jsonb_storage PASSED
agents/tests/test_pattern_quality_database_integration.py::test_bulk_upsert_performance PASSED

======================== 10 passed, 12 warnings in 20.65s =======================
```

## Table Schema

```sql
Table "public.pattern_quality_metrics"
        Column         |           Type           | Nullable |      Default
-----------------------+--------------------------+----------+-------------------
 id                    | uuid                     | not null | gen_random_uuid()
 pattern_id            | uuid                     | not null |
 quality_score         | double precision         | not null |
 confidence            | double precision         | not null |
 measurement_timestamp | timestamp with time zone | not null | now()
 version               | text                     |          | '1.0.0'::text
 metadata              | jsonb                    |          | '{}'::jsonb
 created_at            | timestamp with time zone |          | now()
 updated_at            | timestamp with time zone |          | now()

Indexes:
    "pattern_quality_metrics_pkey" PRIMARY KEY, btree (id)
    "pattern_quality_metrics_pattern_id_unique" UNIQUE, btree (pattern_id)
    "idx_pattern_quality_metrics_measurement_timestamp" btree (measurement_timestamp DESC)
    "idx_pattern_quality_metrics_metadata" gin (metadata)
    "idx_pattern_quality_metrics_pattern_id" btree (pattern_id)
    "idx_pattern_quality_metrics_quality_score" btree (quality_score DESC)

Check constraints:
    "pattern_quality_metrics_confidence_check" CHECK (confidence >= 0::double precision AND confidence <= 1::double precision)
    "pattern_quality_metrics_quality_score_check" CHECK (quality_score >= 0::double precision AND quality_score <= 1::double precision)
```

## Verification

```bash
# Run all tests
poetry run pytest agents/tests/test_pattern_quality_database_integration.py -v

# Check table exists
source .env && PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT tablename FROM pg_tables WHERE tablename = 'pattern_quality_metrics';"

# Check constraints
source .env && PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT constraint_name, constraint_type
      FROM information_schema.table_constraints
      WHERE table_name = 'pattern_quality_metrics';"
```

## Related Files

- **Migration**: `migrations/012_create_pattern_quality_metrics.sql`
- **Test Fixes**: `agents/tests/test_pattern_quality_database_integration.py`
- **Implementation**: `agents/lib/pattern_quality_scorer.py`
- **Follow-up Migrations**: `013_remove_pattern_quality_fk.sql`, `014_add_pattern_quality_unique_constraint.sql`

---

**Migration Author**: Claude Code (automated fix for missing table)
**Test Status**: ✅ All 10 tests passing
**Production Status**: ✅ Applied to omninode_bridge database
