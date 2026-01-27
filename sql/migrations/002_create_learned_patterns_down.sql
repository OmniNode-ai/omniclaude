-- Rollback Migration 002: Drop learned_patterns Table
-- Date: 2026-01-26
-- Purpose: Remove learned_patterns table and all associated indexes
--
-- WARNING: This will permanently delete all learned pattern data!

BEGIN;

-- Drop indexes (will be dropped automatically with table, but explicit for clarity)
DROP INDEX IF EXISTS idx_learned_patterns_domain;
DROP INDEX IF EXISTS idx_learned_patterns_confidence;
DROP INDEX IF EXISTS idx_learned_patterns_project_scope;
DROP INDEX IF EXISTS idx_learned_patterns_domain_confidence;

-- Drop table
DROP TABLE IF EXISTS learned_patterns;

RAISE NOTICE 'Successfully dropped learned_patterns table and indexes';

COMMIT;
