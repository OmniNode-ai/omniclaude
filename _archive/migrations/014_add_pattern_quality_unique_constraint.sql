-- Migration 014: Add UNIQUE constraint on pattern_id
-- Date: 2025-10-31
-- Purpose: Enable proper upsert behavior for pattern quality metrics
--
-- Impact: Prevents duplicate quality scores for the same pattern
--         Enables ON CONFLICT (pattern_id) DO UPDATE for upserts
--
-- Rationale: Pattern quality metrics should have one "current" score per pattern.
--            Multiple measurements over time can be tracked via updated_at timestamp.
--            This allows backfill script to safely re-run without creating duplicates.

BEGIN;

-- Add UNIQUE constraint on pattern_id
-- This allows only one quality measurement per pattern (latest wins)
ALTER TABLE pattern_quality_metrics
ADD CONSTRAINT pattern_quality_metrics_pattern_id_unique UNIQUE (pattern_id);

-- Add comment explaining the constraint
COMMENT ON CONSTRAINT pattern_quality_metrics_pattern_id_unique ON pattern_quality_metrics IS
'Ensures one quality measurement per pattern. Use ON CONFLICT (pattern_id) DO UPDATE for upserts.';

-- Verify constraint was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'pattern_quality_metrics_pattern_id_unique'
        AND table_name = 'pattern_quality_metrics'
        AND constraint_type = 'UNIQUE'
    ) THEN
        RAISE EXCEPTION 'UNIQUE constraint was not created successfully';
    END IF;

    RAISE NOTICE 'Successfully added UNIQUE constraint on pattern_id';
END $$;

COMMIT;

-- Verification query (run after migration)
-- SELECT constraint_name, constraint_type
-- FROM information_schema.table_constraints
-- WHERE table_name = 'pattern_quality_metrics'
-- AND constraint_type = 'UNIQUE';
--
-- Expected output:
-- pattern_quality_metrics_pkey | UNIQUE (on id)
-- pattern_quality_metrics_pattern_id_unique | UNIQUE (on pattern_id)
