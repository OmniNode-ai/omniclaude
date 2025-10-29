-- Migration 004 Rollback: Pattern Quality and Usage Tracking
-- Removes quality score columns, usage tracking, pattern_relationships table, and trigger

-- ============================================================================
-- WARNING: This will permanently remove data from the following columns:
-- - pattern_lineage_nodes: complexity_score, documentation_score, test_coverage_score,
--   reusability_score, maintainability_score, overall_quality, usage_count,
--   last_used_at, used_by_agents
-- - pattern_relationships: entire table and all relationship data
-- ============================================================================

BEGIN;

-- ============================================================================
-- PART 1: Remove Trigger and Function
-- ============================================================================

-- Drop the trigger
DROP TRIGGER IF EXISTS increment_pattern_usage_trigger ON agent_manifest_injections;

-- Drop the trigger function
DROP FUNCTION IF EXISTS increment_pattern_usage();

-- ============================================================================
-- PART 2: Drop pattern_relationships Table
-- ============================================================================

-- Drop indexes first (they'll be automatically dropped with table, but being explicit)
DROP INDEX IF EXISTS idx_pattern_rel_source;
DROP INDEX IF EXISTS idx_pattern_rel_target;
DROP INDEX IF EXISTS idx_pattern_rel_type;
DROP INDEX IF EXISTS idx_pattern_rel_confidence;
DROP INDEX IF EXISTS idx_pattern_rel_created;
DROP INDEX IF EXISTS idx_pattern_rel_metadata;

-- Drop the table
DROP TABLE IF EXISTS pattern_relationships;

-- ============================================================================
-- PART 3: Remove Usage Tracking Columns from pattern_lineage_nodes
-- ============================================================================

-- Drop usage tracking indexes
DROP INDEX IF EXISTS idx_pattern_lineage_usage_count;
DROP INDEX IF EXISTS idx_pattern_lineage_last_used;
DROP INDEX IF EXISTS idx_pattern_lineage_used_by_agents;

-- Drop usage tracking columns
ALTER TABLE pattern_lineage_nodes
DROP COLUMN IF EXISTS usage_count,
DROP COLUMN IF EXISTS last_used_at,
DROP COLUMN IF EXISTS used_by_agents;

-- ============================================================================
-- PART 4: Remove Quality Score Columns from pattern_lineage_nodes
-- ============================================================================

-- Drop quality score indexes
DROP INDEX IF EXISTS idx_pattern_lineage_overall_quality;
DROP INDEX IF EXISTS idx_pattern_lineage_complexity;
DROP INDEX IF EXISTS idx_pattern_lineage_maintainability;

-- Drop quality score columns
ALTER TABLE pattern_lineage_nodes
DROP COLUMN IF EXISTS complexity_score,
DROP COLUMN IF EXISTS documentation_score,
DROP COLUMN IF EXISTS test_coverage_score,
DROP COLUMN IF EXISTS reusability_score,
DROP COLUMN IF EXISTS maintainability_score,
DROP COLUMN IF EXISTS overall_quality;

-- ============================================================================
-- PART 5: Remove Migration Record
-- ============================================================================

-- Remove migration record from schema_migrations
DELETE FROM schema_migrations
WHERE version = 4;

COMMIT;

-- ============================================================================
-- Rollback Complete
-- ============================================================================

-- Verify rollback by checking table structure
SELECT 'Rollback complete. Verify with: \d pattern_lineage_nodes' AS status;
