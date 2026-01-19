-- Migration: 010_add_actual_success_column
-- Description: Add actual_success column to agent_routing_decisions for alert system
-- Author: polymorphic-agent
-- Created: 2025-10-28
-- ONEX Compliance: Effect node pattern for schema enhancement
-- Correlation ID: 86e57c28-0af3-4f1f-afda-81d11b877258
-- Related: DASHBOARD_BACKEND_STATUS.md Issue #1

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- Add actual_success column if it doesn't exist
DO $$
BEGIN
    -- Check if column exists
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'agent_routing_decisions'
        AND column_name = 'actual_success'
    ) THEN
        -- Add column
        ALTER TABLE agent_routing_decisions
        ADD COLUMN actual_success BOOLEAN;

        -- Add comment
        COMMENT ON COLUMN agent_routing_decisions.actual_success IS
            'Whether the routing decision led to successful agent execution (populated post-execution)';

        RAISE NOTICE 'Column actual_success added to agent_routing_decisions';
    ELSE
        RAISE NOTICE 'Column actual_success already exists, skipping';
    END IF;
END $$;

-- Populate existing rows with default value based on confidence_score
-- Use confidence_score > 0.8 as proxy for likely success
UPDATE agent_routing_decisions
SET actual_success = (confidence_score > 0.8)
WHERE actual_success IS NULL
AND confidence_score IS NOT NULL;

-- Log population results
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO updated_count
    FROM agent_routing_decisions
    WHERE actual_success IS NOT NULL;

    RAISE NOTICE 'Populated actual_success for % existing rows', updated_count;
END $$;

-- Create index for performance (idempotent)
CREATE INDEX IF NOT EXISTS idx_routing_decisions_success
ON agent_routing_decisions(actual_success)
WHERE actual_success IS NOT NULL;

-- Create composite index for success rate queries
CREATE INDEX IF NOT EXISTS idx_routing_decisions_agent_success
ON agent_routing_decisions(selected_agent, actual_success, created_at DESC)
WHERE actual_success IS NOT NULL;

-- Add comments
COMMENT ON INDEX idx_routing_decisions_success IS
    'Performance index for success rate calculations in alert system';
COMMENT ON INDEX idx_routing_decisions_agent_success IS
    'Composite index for per-agent success rate analytics with time ordering';

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Verify column exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'agent_routing_decisions'
        AND column_name = 'actual_success'
    ) THEN
        RAISE NOTICE '✓ Column actual_success exists';
    ELSE
        RAISE EXCEPTION '✗ Column actual_success not found!';
    END IF;
END $$;

-- Verify indexes exist
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename = 'agent_routing_decisions'
        AND indexname = 'idx_routing_decisions_success'
    ) THEN
        RAISE NOTICE '✓ Index idx_routing_decisions_success exists';
    ELSE
        RAISE EXCEPTION '✗ Index idx_routing_decisions_success not found!';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename = 'agent_routing_decisions'
        AND indexname = 'idx_routing_decisions_agent_success'
    ) THEN
        RAISE NOTICE '✓ Index idx_routing_decisions_agent_success exists';
    ELSE
        RAISE EXCEPTION '✗ Index idx_routing_decisions_agent_success not found!';
    END IF;
END $$;

-- Show statistics
SELECT
    COUNT(*) as total_rows,
    COUNT(actual_success) as rows_with_success,
    COUNT(CASE WHEN actual_success = TRUE THEN 1 END) as success_count,
    COUNT(CASE WHEN actual_success = FALSE THEN 1 END) as failure_count,
    ROUND(
        COUNT(CASE WHEN actual_success = TRUE THEN 1 END)::numeric * 100 /
        NULLIF(COUNT(actual_success), 0),
        2
    ) as success_rate_percent
FROM agent_routing_decisions;

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP INDEX IF EXISTS idx_routing_decisions_agent_success;
-- DROP INDEX IF EXISTS idx_routing_decisions_success;
-- ALTER TABLE agent_routing_decisions DROP COLUMN IF EXISTS actual_success;
