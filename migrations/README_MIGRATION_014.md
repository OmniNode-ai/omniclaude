# Migration 014: Add UNIQUE Constraint on pattern_id

**Date**: 2025-10-31
**Status**: ✅ Applied
**Impact**: Enables proper upsert behavior for pattern quality metrics

## Problem Statement

After Migration 013 removed the FK constraint, the `pattern_quality_metrics` table had no UNIQUE constraint on `pattern_id`:

```sql
-- Before Migration 014
CREATE TABLE pattern_quality_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id uuid NOT NULL,  -- No UNIQUE constraint!
    quality_score double precision NOT NULL,
    ...
);
```

**Issues**:
1. **No upsert capability**: Can't use `ON CONFLICT (pattern_id) DO UPDATE`
2. **Duplicate records**: Running backfill twice creates duplicate entries
3. **Misleading code**: Docstring claims "Uses upsert" but implementation was simple INSERT
4. **Error prone**: No protection against duplicate quality measurements

**Example Problem**:
```python
# First run: Insert pattern quality
await store_quality_metrics(score)  # SUCCESS: 1 record

# Second run: Duplicate!
await store_quality_metrics(score)  # SUCCESS: 2 records (WRONG!)
```

## Root Cause

1. **Migration 013** removed FK constraint to allow scoring all patterns
2. But no UNIQUE constraint existed on `pattern_id` alone
3. Code used simple INSERT without ON CONFLICT (to avoid errors)
4. This allowed duplicate pattern quality records

## Solution

Add UNIQUE constraint on `pattern_id` to enable proper upsert:

```sql
ALTER TABLE pattern_quality_metrics
ADD CONSTRAINT pattern_quality_metrics_pattern_id_unique UNIQUE (pattern_id);
```

**Updated Code**:
```python
# Upsert query with ON CONFLICT on pattern_id
query = """
    INSERT INTO pattern_quality_metrics (...)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (pattern_id) DO UPDATE SET
        quality_score = EXCLUDED.quality_score,
        confidence = EXCLUDED.confidence,
        measurement_timestamp = EXCLUDED.measurement_timestamp,
        version = EXCLUDED.version,
        metadata = EXCLUDED.metadata
"""
```

**Behavior**:
- **First insert**: Creates new record
- **Second insert with same pattern_id**: Updates existing record (upsert)
- **No duplicates**: UNIQUE constraint prevents duplicate pattern_ids

## Migration Files

1. **Forward Migration**: `014_add_pattern_quality_unique_constraint.sql`
   - Adds UNIQUE constraint on `pattern_id`
   - Includes verification checks
   - Safe to run on empty or populated table

2. **Rollback Migration**: Not provided (constraint removal is trivial if needed)
   - Use: `ALTER TABLE pattern_quality_metrics DROP CONSTRAINT pattern_quality_metrics_pattern_id_unique;`

## Application

```bash
# Apply migration
PGPASSWORD="***REDACTED***" psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -f migrations/014_add_pattern_quality_unique_constraint.sql

# Verify constraint exists
PGPASSWORD="***REDACTED***" psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT constraint_name, constraint_type
      FROM information_schema.table_constraints
      WHERE table_name = 'pattern_quality_metrics'
      AND constraint_type = 'UNIQUE';"

# Expected output:
# pattern_quality_metrics_pattern_id_unique | UNIQUE
```

## Code Changes

**File**: `agents/lib/pattern_quality_scorer.py`

**Before** (Migration 013):
```python
# Simple INSERT without upsert
query = """
    INSERT INTO pattern_quality_metrics (...)
    VALUES (%s, %s, %s, %s, %s, %s)
"""
# Issue: Allows duplicates, no upsert capability
```

**After** (Migration 014):
```python
# Upsert with ON CONFLICT
query = """
    INSERT INTO pattern_quality_metrics (...)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (pattern_id) DO UPDATE SET
        quality_score = EXCLUDED.quality_score,
        ...
"""
# Fixed: Proper upsert behavior, no duplicates
```

## Testing

### Unit Test

Created `scripts/test_pattern_quality_upsert.py` to verify:

```bash
python3 scripts/test_pattern_quality_upsert.py
```

**Test Cases**:
1. ✓ Insert new pattern quality metric
2. ✓ Update existing pattern (upsert)
3. ✓ Verify only one record per pattern_id
4. ✓ Verify updated values are correct

**Expected Output**:
```
================================================================================
✓ ALL TESTS PASSED
================================================================================
```

### Integration Test

Run backfill twice to verify no duplicates:

```bash
# First run
python3 scripts/backfill_pattern_quality.py \
  --limit 10 \
  --database-url "postgresql://postgres:***REDACTED***@192.168.86.200:5436/omninode_bridge"

# Check count
PGPASSWORD="***REDACTED***" psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM pattern_quality_metrics;"
# Expected: 10 rows

# Second run (should update, not duplicate)
python3 scripts/backfill_pattern_quality.py \
  --limit 10 \
  --database-url "postgresql://postgres:***REDACTED***@192.168.86.200:5436/omninode_bridge"

# Check count again
PGPASSWORD="***REDACTED***" psql \
  -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM pattern_quality_metrics;"
# Expected: Still 10 rows (upserted, not duplicated)
```

## Verification Queries

```sql
-- Check UNIQUE constraint exists
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'pattern_quality_metrics'
AND constraint_type = 'UNIQUE';
-- Expected: pattern_quality_metrics_pattern_id_unique

-- Verify no duplicate pattern_ids
SELECT pattern_id, COUNT(*) as count
FROM pattern_quality_metrics
GROUP BY pattern_id
HAVING COUNT(*) > 1;
-- Expected: 0 rows (no duplicates)

-- Check total pattern count
SELECT COUNT(DISTINCT pattern_id) as unique_patterns,
       COUNT(*) as total_records
FROM pattern_quality_metrics;
-- Expected: unique_patterns = total_records
```

## Expected Results

**Before Migration 014**:
- ❌ Simple INSERT only (no upsert)
- ❌ Duplicate pattern_ids allowed
- ❌ Running backfill twice creates 2x records

**After Migration 014**:
- ✅ Proper upsert with ON CONFLICT
- ✅ One record per pattern_id (UNIQUE constraint)
- ✅ Running backfill twice updates existing records

## Performance Impact

- **Storage**: No additional storage overhead
- **Query Performance**: UNIQUE index improves lookup performance
- **Upsert Performance**: ON CONFLICT is efficient for updates
- **Backfill Time**: No significant change

## Security Considerations

- No security impact - adds constraint only
- Pattern IDs remain UUIDs
- Quality metrics are read-only for manifest generation

## Rollback Procedure

If you need to remove the constraint (not recommended):

```sql
-- Remove UNIQUE constraint
ALTER TABLE pattern_quality_metrics
DROP CONSTRAINT pattern_quality_metrics_pattern_id_unique;

-- WARNING: This allows duplicate pattern_ids again!
-- Only rollback if you have a specific reason to allow duplicates.
```

## Related Migrations

- **Migration 013**: Removed FK constraint (enabled 100% pattern coverage)
- **Migration 014**: Added UNIQUE constraint (enabled proper upsert)

Together, these migrations enable:
- ✅ Scoring all 1,085 patterns (not just 5% in lineage)
- ✅ Proper upsert behavior (no duplicates)
- ✅ Safe re-runs of backfill script

## Notes

- UNIQUE constraint on `pattern_id` means one "current" quality score per pattern
- Historical quality tracking would require different approach (e.g., composite UNIQUE on pattern_id + measurement_timestamp)
- Current design prioritizes simplicity: "latest measurement wins"
- Measurement timestamp is updated on upsert to track when score was last calculated

---

**Migration Author**: Phase 2 Intelligence Optimization
**Approved By**: Auto-applied during ON CONFLICT error fix
**Production Status**: ✅ Applied to omninode_bridge database
