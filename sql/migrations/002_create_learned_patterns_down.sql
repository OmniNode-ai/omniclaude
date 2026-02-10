-- Rollback Migration 002: Drop learned_patterns Table
-- Date: 2026-01-26
-- Purpose: Remove learned_patterns table and all associated indexes
--
-- WARNING: This will permanently delete all learned pattern data!

BEGIN;

-- Drop trigger and function (must be dropped before table)
DROP TRIGGER IF EXISTS trg_learned_patterns_updated_at ON learned_patterns;
DROP FUNCTION IF EXISTS update_learned_patterns_updated_at();

-- Drop indexes (will be dropped automatically with table, but explicit for clarity)
DROP INDEX IF EXISTS idx_learned_patterns_scope_domain_confidence;
DROP INDEX IF EXISTS idx_learned_patterns_updated_at;
DROP INDEX IF EXISTS idx_learned_patterns_domain;
DROP INDEX IF EXISTS idx_learned_patterns_confidence;
DROP INDEX IF EXISTS idx_learned_patterns_project_scope;
DROP INDEX IF EXISTS idx_learned_patterns_domain_confidence;

-- Drop table
DROP TABLE IF EXISTS learned_patterns;

DO $$
BEGIN
    RAISE NOTICE 'Successfully dropped learned_patterns table, trigger, function, and indexes';
END $$;

COMMIT;
