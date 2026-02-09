-- Migration 003: Add evidence_tier column to learned_patterns
-- Date: 2026-02-09
-- Purpose: Add evidence_tier for measurement quality tracking (OMN-2044)
--
-- Valid values: UNMEASURED, MEASURED, VERIFIED
-- Default: UNMEASURED (patterns without measurement data)
--
-- Part of OMN-2044: L4 Evidence Tier in Retrieval Path

BEGIN;

-- Add evidence_tier column if not present
ALTER TABLE learned_patterns
    ADD COLUMN IF NOT EXISTS evidence_tier TEXT NOT NULL DEFAULT 'UNMEASURED';

-- Add CHECK constraint for valid values
-- Use DO block for idempotency (constraint may already exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_evidence_tier_valid'
    ) THEN
        ALTER TABLE learned_patterns
            ADD CONSTRAINT chk_evidence_tier_valid
            CHECK (evidence_tier IN ('UNMEASURED', 'MEASURED', 'VERIFIED'));
    END IF;
END $$;

-- Create index for filtering by evidence_tier
CREATE INDEX IF NOT EXISTS idx_learned_patterns_evidence_tier
    ON learned_patterns(evidence_tier);

COMMENT ON COLUMN learned_patterns.evidence_tier IS
'Measurement quality tier: UNMEASURED (no measurement data), MEASURED (has metrics), VERIFIED (validated by review).';

-- Verify column was added
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'learned_patterns'
        AND column_name = 'evidence_tier'
    ) THEN
        RAISE EXCEPTION 'evidence_tier column was not added to learned_patterns';
    END IF;

    RAISE NOTICE 'Successfully added evidence_tier column to learned_patterns';
END $$;

COMMIT;
