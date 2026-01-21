-- Rollback Migration: Remove Hook Intelligence Indexes and Analytics Views
-- Description: Safely removes all indexes, views, and functions added in migration 004
-- Version: 004 Rollback
-- Date: 2025-10-10
-- Safe to run: Yes (only removes additions, preserves data)

BEGIN;

-- ============================================================================
-- STEP 1: Drop Helper Functions
-- ============================================================================

DROP FUNCTION IF EXISTS calculate_session_success_score(UUID);
DROP FUNCTION IF EXISTS get_recent_workflow_patterns(INTEGER);
DROP FUNCTION IF EXISTS get_tool_performance(TEXT);
DROP FUNCTION IF EXISTS get_session_stats(UUID);

-- ============================================================================
-- STEP 2: Drop Analytics Views
-- ============================================================================

DROP VIEW IF EXISTS quality_metrics_summary;
DROP VIEW IF EXISTS agent_usage_patterns;
DROP VIEW IF EXISTS workflow_pattern_distribution;
DROP VIEW IF EXISTS tool_success_rates;
DROP VIEW IF EXISTS session_intelligence_summary;

-- ============================================================================
-- STEP 3: Drop Performance Indexes
-- ============================================================================

DROP INDEX IF EXISTS idx_hook_events_created_source;
DROP INDEX IF EXISTS idx_hook_events_agent;
DROP INDEX IF EXISTS idx_hook_events_response;
DROP INDEX IF EXISTS idx_hook_events_success;
DROP INDEX IF EXISTS idx_hook_events_quality;
DROP INDEX IF EXISTS idx_hook_events_workflow;
DROP INDEX IF EXISTS idx_hook_events_session;

-- ============================================================================
-- STEP 4: Remove Migration Record
-- ============================================================================

DELETE FROM schema_migrations WHERE version = 4;

COMMIT;

-- Verify rollback
-- SELECT indexname FROM pg_indexes WHERE tablename = 'hook_events' AND indexname LIKE 'idx_hook_events_%';
-- SELECT viewname FROM pg_views WHERE viewname IN ('session_intelligence_summary', 'tool_success_rates', 'workflow_pattern_distribution', 'agent_usage_patterns', 'quality_metrics_summary');
