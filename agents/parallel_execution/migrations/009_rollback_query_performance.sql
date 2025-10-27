-- Rollback Migration: 009_optimize_query_performance
-- Description: Remove performance optimization indexes added in migration 009
-- Author: agent-performance
-- Created: 2025-10-27
-- ONEX Compliance: Safe rollback with minimal disruption

-- WARNING: Rolling back this migration will degrade query performance
-- Queries will return to ~8s response times (from optimized <2s)

BEGIN;

-- ============================================================================
-- Remove Indexes (in reverse order of creation)
-- ============================================================================

-- Step 6: Additional Composite Indexes
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_routing_decisions_strategy_confidence;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_manifest_injections_time_agent;

-- Step 5: Partial Indexes
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_actions_recent_debug;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_routing_decisions_high_confidence;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_manifest_injections_non_fallback;

-- Step 4: Covering Indexes
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_routing_decisions_query_covering;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_manifest_injections_list_covering;

-- Step 3: Text Search Indexes
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_actions_agent_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_routing_decisions_agent_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_manifest_injections_agent_trgm;

-- Step 2: Critical Performance Index
DROP INDEX CONCURRENTLY IF EXISTS idx_agent_actions_agent_time;

-- Step 1: pg_trgm extension
-- Note: We don't drop the extension as other parts of the system might use it
-- and it's safe to leave installed. If you need to remove it:
-- DROP EXTENSION IF EXISTS pg_trgm CASCADE;

-- ============================================================================
-- Update Statistics
-- ============================================================================

ANALYZE agent_manifest_injections;
ANALYZE agent_routing_decisions;
ANALYZE agent_actions;

-- ============================================================================
-- Migration Metadata
-- ============================================================================

DELETE FROM schema_migrations WHERE version = 9;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Verify indexes were removed
-- SELECT
--     tablename,
--     indexname
-- FROM pg_indexes
-- WHERE tablename IN ('agent_manifest_injections', 'agent_routing_decisions', 'agent_actions')
-- AND indexname IN (
--     'idx_agent_actions_agent_time',
--     'idx_agent_manifest_injections_agent_trgm',
--     'idx_agent_routing_decisions_agent_trgm',
--     'idx_agent_actions_agent_trgm',
--     'idx_agent_manifest_injections_list_covering',
--     'idx_agent_routing_decisions_query_covering',
--     'idx_agent_manifest_injections_non_fallback',
--     'idx_agent_routing_decisions_high_confidence',
--     'idx_agent_actions_recent_debug',
--     'idx_agent_manifest_injections_time_agent',
--     'idx_agent_routing_decisions_strategy_confidence'
-- );
-- Expected: No results (all indexes dropped)
