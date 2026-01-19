# Migration 013: Remove Foreign Key Constraint from pattern_quality_metrics

**Date**: 2025-10-31
**Status**: ✅ Applied
**Impact**: Enables quality scoring for 100% of Qdrant patterns (1,085 patterns)

## Problem Statement

The `pattern_quality_metrics` table had a foreign key constraint requiring `pattern_id` to exist in `pattern_lineage_nodes` table:

```sql
FOREIGN KEY (pattern_id) REFERENCES pattern_lineage_nodes(id) ON DELETE CASCADE
```

**Impact**:
- Only ~5% of Qdrant patterns could be scored (65 out of 1,085 patterns)
- 95% of patterns failed with `ForeignKeyViolation` errors
- Pattern quality filtering was ineffective due to sparse data

## Root Cause

Qdrant contains patterns from multiple sources:
- Code patterns discovered from codebases
- Execution patterns from workflows
- Manually added patterns

Only patterns that went through the lineage tracking system have records in `pattern_lineage_nodes`. Most patterns in Qdrant were never tracked in lineage, making them incompatible with quality metrics storage.

## Solution

Remove the foreign key constraint to allow independent pattern quality tracking:

```sql
ALTER TABLE pattern_quality_metrics
DROP CONSTRAINT pattern_quality_metrics_pattern_id_fkey;
```

**Rationale**:
- Pattern quality is independent of lineage tracking
- Quality metrics should be available for ALL patterns in Qdrant
- Lineage tracking is optional; quality scoring is universal

## Migration Files

1. **Forward Migration**: `013_remove_pattern_quality_fk.sql`
   - Drops FK constraint
   - Adds explanatory comment to column
   - Includes verification checks

2. **Rollback Migration**: `013_rollback_pattern_quality_fk.sql`
   - Restores FK constraint (if needed)
   - **WARNING**: Will fail if orphaned records exist
   - Clean up orphaned records before rollback

## Application

```bash
# Apply migration
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -f migrations/013_remove_pattern_quality_fk.sql

# Verify FK is removed
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge \
  -c "\d pattern_quality_metrics"

# Run backfill to populate all patterns
python3 scripts/backfill_pattern_quality.py \
  --batch-size 100 --delay 0.5 \
  --database-url "postgresql://postgres:password@host:5436/omninode_bridge"
```

## Expected Results

**Before Migration**:
- Patterns stored: 5-65 (~5%)
- Patterns skipped: 1,020-1,080 (95%)
- Error: `ForeignKeyViolation: pattern_id does not exist`

**After Migration**:
- Patterns stored: 1,085 (100%)
- Patterns skipped: 0
- No foreign key errors

## Verification

```sql
-- Check constraint is removed
SELECT constraint_name
FROM information_schema.table_constraints
WHERE table_name = 'pattern_quality_metrics'
AND constraint_type = 'FOREIGN KEY';
-- Expected: 0 rows

-- Check pattern count after backfill
SELECT COUNT(*) FROM pattern_quality_metrics;
-- Expected: 1,085 rows

-- Verify quality score distribution
SELECT
    COUNT(CASE WHEN quality_score >= 0.9 THEN 1 END) as excellent,
    COUNT(CASE WHEN quality_score >= 0.7 AND quality_score < 0.9 THEN 1 END) as good,
    COUNT(CASE WHEN quality_score >= 0.5 AND quality_score < 0.7 THEN 1 END) as fair,
    COUNT(CASE WHEN quality_score < 0.5 THEN 1 END) as poor
FROM pattern_quality_metrics;
```

## Rollback Procedure

**WARNING**: Only rollback if you need to restore lineage-only quality tracking.

```bash
# 1. Delete orphaned records (patterns not in lineage)
psql -h host -p 5436 -U postgres -d omninode_bridge <<SQL
DELETE FROM pattern_quality_metrics
WHERE pattern_id NOT IN (SELECT id FROM pattern_lineage_nodes);
SQL

# 2. Apply rollback
psql -h host -p 5436 -U postgres -d omninode_bridge \
  -f migrations/013_rollback_pattern_quality_fk.sql
```

## Related Changes

- **Code**: `agents/lib/pattern_quality_scorer.py`
  - Kept `ForeignKeyViolation` handler as defensive measure
  - Updated comments to note FK was removed

- **Documentation**: `docs/planning/OMNICLAUDE_INTELLIGENCE_OPTIMIZATION_PLAN.md`
  - Updated Phase 2 status with FK constraint fix

## Testing

1. **Pre-migration**: Verified only 5% of patterns stored
2. **Post-migration**: FK constraint successfully removed
3. **Backfill**: Ready to process all 1,085 patterns (pending Qdrant availability)

## Performance Impact

- **Storage**: +1,080 rows in `pattern_quality_metrics` (~200KB)
- **Query Performance**: No impact (indexed on pattern_id)
- **Backfill Time**: ~2-3 minutes for full 1,085 patterns

## Security Considerations

- No security impact - removes constraint, doesn't expose data
- Pattern IDs remain UUIDs, no information leakage
- Quality metrics are read-only for manifest generation

---

**Migration Author**: Phase 2 Intelligence Optimization
**Approved By**: Auto-applied during Phase 2 completion
**Production Status**: ✅ Applied to omninode_bridge database
