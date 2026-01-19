-- Migration 013: Remove Foreign Key Constraint from pattern_quality_metrics
-- Date: 2025-10-31
-- Purpose: Allow storing quality metrics for all Qdrant patterns,
--          not just those in pattern_lineage_nodes table
--
-- Impact: Enables quality scoring for 100% of patterns (1,085 patterns)
--         instead of just ~5% that exist in lineage table
--
-- Rationale: Pattern quality metrics should be independent of lineage tracking.
--            Patterns from Qdrant may not have lineage records but still need
--            quality scoring for manifest injection filtering.

BEGIN;

-- Drop the foreign key constraint
ALTER TABLE pattern_quality_metrics
DROP CONSTRAINT IF EXISTS pattern_quality_metrics_pattern_id_fkey;

-- Add comment explaining why FK was removed
COMMENT ON COLUMN pattern_quality_metrics.pattern_id IS
'Pattern UUID from Qdrant. No FK constraint to allow scoring all patterns independently of lineage tracking.';

-- Verify constraint is removed
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'pattern_quality_metrics_pattern_id_fkey'
        AND table_name = 'pattern_quality_metrics'
    ) THEN
        RAISE EXCEPTION 'FK constraint still exists after DROP';
    END IF;

    RAISE NOTICE 'Successfully removed FK constraint from pattern_quality_metrics';
END $$;

COMMIT;

-- Verification query (run after migration)
-- SELECT COUNT(*) FROM pattern_quality_metrics;
-- Expected: Can now insert quality metrics for all Qdrant patterns
