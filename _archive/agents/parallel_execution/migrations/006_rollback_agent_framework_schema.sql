-- Rollback Migration: 006_agent_framework_schema_enhancements
-- Description: Rollback agent framework refinement schema changes
-- Author: agent-workflow-coordinator
-- Created: 2025-10-15
-- IMPORTANT: This rollback script safely removes all agent framework enhancements

-- =============================================================================
-- ROLLBACK MIGRATION
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: Drop Views (in reverse dependency order)
-- =============================================================================

DROP VIEW IF EXISTS event_processing_health;
DROP VIEW IF EXISTS template_cache_efficiency;
DROP VIEW IF EXISTS performance_metrics_summary;
DROP VIEW IF EXISTS pattern_feedback_analysis;
DROP VIEW IF EXISTS mixin_compatibility_summary;

-- =============================================================================
-- STEP 2: Drop Functions
-- =============================================================================

DROP FUNCTION IF EXISTS record_pattern_feedback;
DROP FUNCTION IF EXISTS update_mixin_compatibility;

-- =============================================================================
-- STEP 3: Drop Tables (in reverse dependency order)
-- =============================================================================

DROP TABLE IF EXISTS event_processing_metrics CASCADE;
DROP TABLE IF EXISTS template_cache_metadata CASCADE;
DROP TABLE IF EXISTS generation_performance_metrics CASCADE;
DROP TABLE IF EXISTS pattern_feedback_log CASCADE;
DROP TABLE IF EXISTS mixin_compatibility_matrix CASCADE;

-- =============================================================================
-- STEP 4: Remove Migration Record
-- =============================================================================

DELETE FROM schema_migrations WHERE version = 6;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES (run these after rollback to verify clean state)
-- =============================================================================

/*
-- Verify tables are dropped
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'mixin_compatibility_matrix',
    'pattern_feedback_log',
    'generation_performance_metrics',
    'template_cache_metadata',
    'event_processing_metrics'
  );
-- Should return 0 rows

-- Verify views are dropped
SELECT table_name
FROM information_schema.views
WHERE table_schema = 'public'
  AND table_name IN (
    'mixin_compatibility_summary',
    'pattern_feedback_analysis',
    'performance_metrics_summary',
    'template_cache_efficiency',
    'event_processing_health'
  );
-- Should return 0 rows

-- Verify functions are dropped
SELECT routine_name
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name IN (
    'update_mixin_compatibility',
    'record_pattern_feedback'
  );
-- Should return 0 rows

-- Verify migration record is removed
SELECT * FROM schema_migrations WHERE version = 6;
-- Should return 0 rows
*/
