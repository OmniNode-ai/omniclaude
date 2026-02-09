-- Migration 003 DOWN: Remove evidence_tier column from learned_patterns
-- Date: 2026-02-09
-- Part of OMN-2044: L4 Evidence Tier in Retrieval Path

BEGIN;

ALTER TABLE learned_patterns DROP CONSTRAINT IF EXISTS chk_evidence_tier_valid;
DROP INDEX IF EXISTS idx_learned_patterns_evidence_tier;
ALTER TABLE learned_patterns DROP COLUMN IF EXISTS evidence_tier;

COMMIT;
