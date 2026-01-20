-- Rollback Migration: Remove Monitoring Query Performance Indexes
-- Description: Removes indexes added in 007_add_monitoring_indexes.sql
-- Version: 007 (rollback)
-- Date: 2025-10-16
-- Related: 007_add_monitoring_indexes.sql

BEGIN;

-- ============================================================================
-- Remove Monitoring Performance Indexes
-- ============================================================================

-- Remove correlation_id index
DROP INDEX CONCURRENTLY IF EXISTS idx_hook_events_correlation_id;

-- Remove session_id (all sources) index
DROP INDEX CONCURRENTLY IF EXISTS idx_hook_events_session_all;

-- Remove resource_id composite index
DROP INDEX CONCURRENTLY IF EXISTS idx_hook_events_resource_id;

-- ============================================================================
-- Update Migration Metadata
-- ============================================================================

-- Mark migration as rolled back
DO $$
BEGIN
    -- Create rollback tracking table if it doesn't exist
    CREATE TABLE IF NOT EXISTS schema_migrations_rollback (
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        rolled_back_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- Record rollback
    INSERT INTO schema_migrations_rollback (version, description)
    VALUES (
        7,
        'Rolled back monitoring query performance indexes'
    )
    ON CONFLICT (version) DO UPDATE
    SET rolled_back_at = NOW();

    -- Remove from active migrations
    DELETE FROM schema_migrations WHERE version = 7;
END $$;

COMMIT;

-- ============================================================================
-- Post-Rollback Verification Queries
-- ============================================================================

-- Verify indexes were removed
-- SELECT indexname FROM pg_indexes WHERE tablename = 'hook_events' AND indexname IN ('idx_hook_events_correlation_id', 'idx_hook_events_session_all', 'idx_hook_events_resource_id');
-- Expected: No rows (indexes removed)

-- Verify migration rollback was recorded
-- SELECT * FROM schema_migrations_rollback WHERE version = 7;
-- Expected: 1 row with rollback timestamp

-- Note: After rollback, queries will revert to slower performance:
--   - correlation_id queries: 100-500ms (was 1-5ms with index)
--   - session_id queries: 50-200ms (was 2-10ms with index)
--   - resource_id queries: 30-100ms (was 2-8ms with index)
