-- Rollback Migration 013: Restore Foreign Key Constraint
-- Date: 2025-10-31
-- Purpose: Restore FK constraint if needed (will fail if orphaned records exist)
--
-- WARNING: This rollback will FAIL if there are pattern_quality_metrics records
--          for patterns that don't exist in pattern_lineage_nodes.
--          Clean up orphaned records first if needed.

BEGIN;

-- Re-add the foreign key constraint
ALTER TABLE pattern_quality_metrics
ADD CONSTRAINT pattern_quality_metrics_pattern_id_fkey
FOREIGN KEY (pattern_id) REFERENCES pattern_lineage_nodes(id) ON DELETE CASCADE;

-- Restore original comment
COMMENT ON COLUMN pattern_quality_metrics.pattern_id IS NULL;

-- Verify constraint exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'pattern_quality_metrics_pattern_id_fkey'
        AND table_name = 'pattern_quality_metrics'
    ) THEN
        RAISE EXCEPTION 'FK constraint was not restored';
    END IF;

    RAISE NOTICE 'Successfully restored FK constraint to pattern_quality_metrics';
END $$;

COMMIT;
