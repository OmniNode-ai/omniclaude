-- Migration Rollback: 010_rollback_actual_success_column
-- Description: Rollback for migration 010 - removes actual_success column and indexes
-- Author: polymorphic-agent
-- Created: 2025-10-28
-- Correlation ID: 86e57c28-0af3-4f1f-afda-81d11b877258

-- =============================================================================
-- ROLLBACK MIGRATION
-- =============================================================================

-- Drop composite index
DROP INDEX IF EXISTS idx_routing_decisions_agent_success;

-- Drop success index
DROP INDEX IF EXISTS idx_routing_decisions_success;

-- Drop actual_success column
ALTER TABLE agent_routing_decisions DROP COLUMN IF EXISTS actual_success;

-- Verification
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'agent_routing_decisions'
        AND column_name = 'actual_success'
    ) THEN
        RAISE NOTICE '✓ Column actual_success successfully removed';
    ELSE
        RAISE EXCEPTION '✗ Column actual_success still exists!';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename = 'agent_routing_decisions'
        AND indexname = 'idx_routing_decisions_success'
    ) THEN
        RAISE NOTICE '✓ Index idx_routing_decisions_success successfully removed';
    ELSE
        RAISE EXCEPTION '✗ Index idx_routing_decisions_success still exists!';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename = 'agent_routing_decisions'
        AND indexname = 'idx_routing_decisions_agent_success'
    ) THEN
        RAISE NOTICE '✓ Index idx_routing_decisions_agent_success successfully removed';
    ELSE
        RAISE EXCEPTION '✗ Index idx_routing_decisions_agent_success still exists!';
    END IF;
END $$;

-- Display current table structure
\d agent_routing_decisions
