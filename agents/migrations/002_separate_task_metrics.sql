-- Migration: Separate Task Completion Metrics from Routing Metrics
-- Purpose: Fix data quality issue where task completion times were logged as routing times
-- Phase: P2 - Routing Metrics Data Quality Cleanup
-- Correlation ID: fe9bbe61-39d7-4124-b6ec-d61de1e0ee41-P2

-- ============================================================================
-- PHASE 1: Create New Task Completion Metrics Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS task_completion_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    correlation_id UUID,
    task_type VARCHAR(255),
    task_description TEXT,
    completion_time_ms INTEGER NOT NULL,
    success BOOLEAN DEFAULT true,
    agent_name VARCHAR(255),
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Performance constraints
    CONSTRAINT valid_completion_time CHECK (completion_time_ms >= 0 AND completion_time_ms < 3600000)  -- Max 1 hour
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_task_metrics_created ON task_completion_metrics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_metrics_correlation ON task_completion_metrics(correlation_id);
CREATE INDEX IF NOT EXISTS idx_task_metrics_type ON task_completion_metrics(task_type);
CREATE INDEX IF NOT EXISTS idx_task_metrics_agent ON task_completion_metrics(agent_name);
CREATE INDEX IF NOT EXISTS idx_task_metrics_success ON task_completion_metrics(success);

-- ============================================================================
-- PHASE 2: Data Migration
-- ============================================================================

-- Identify and move misclassified routing metrics (likely task completions)
-- Threshold: routing_duration_ms > 500ms indicates task completion, not routing
DO $$
DECLARE
    moved_count INTEGER := 0;
BEGIN
    -- Insert misclassified data into task_completion_metrics
    INSERT INTO task_completion_metrics (
        id,
        created_at,
        correlation_id,
        task_type,
        task_description,
        completion_time_ms,
        success,
        agent_name,
        metadata
    )
    SELECT
        id,  -- Preserve original UUID
        created_at,
        NULL::UUID as correlation_id,  -- Not available in original data
        trigger_match_strategy as task_type,
        query_text as task_description,
        routing_duration_ms as completion_time_ms,
        true as success,  -- Assume success if logged
        NULL as agent_name,  -- Not available in original data
        jsonb_build_object(
            'original_table', 'router_performance_metrics',
            'cache_hit', cache_hit,
            'confidence_components', confidence_components,
            'candidates_evaluated', candidates_evaluated,
            'migrated_at', NOW()
        ) as metadata
    FROM router_performance_metrics
    WHERE routing_duration_ms > 500;  -- Threshold for task completion vs routing

    GET DIAGNOSTICS moved_count = ROW_COUNT;

    -- Delete moved records from router_performance_metrics
    DELETE FROM router_performance_metrics
    WHERE routing_duration_ms > 500;

    RAISE NOTICE 'Migration complete: Moved % records from router_performance_metrics to task_completion_metrics', moved_count;
END $$;

-- ============================================================================
-- PHASE 3: Add Constraints to Prevent Future Mixing
-- ============================================================================

-- Add CHECK constraint to router_performance_metrics to prevent task completion times
ALTER TABLE router_performance_metrics
    ADD CONSTRAINT valid_routing_duration
    CHECK (routing_duration_ms IS NULL OR (routing_duration_ms >= 0 AND routing_duration_ms < 1000));

-- Comment explaining the constraint
COMMENT ON CONSTRAINT valid_routing_duration ON router_performance_metrics IS
    'Routing decisions should complete in <1000ms. Longer durations indicate task completion and should use task_completion_metrics table.';

-- ============================================================================
-- PHASE 4: Create Views for Unified Analysis
-- ============================================================================

-- View: Combined metrics for analysis
CREATE OR REPLACE VIEW v_all_performance_metrics AS
SELECT
    'routing' as metric_type,
    id,
    created_at,
    NULL::UUID as correlation_id,
    query_text as description,
    routing_duration_ms as duration_ms,
    cache_hit,
    trigger_match_strategy as strategy,
    NULL::VARCHAR(255) as agent_name,
    jsonb_build_object(
        'candidates_evaluated', candidates_evaluated,
        'confidence_components', confidence_components
    ) as metadata
FROM router_performance_metrics

UNION ALL

SELECT
    'task_completion' as metric_type,
    id,
    created_at,
    correlation_id,
    task_description as description,
    completion_time_ms as duration_ms,
    NULL::BOOLEAN as cache_hit,
    task_type as strategy,
    agent_name,
    metadata
FROM task_completion_metrics;

COMMENT ON VIEW v_all_performance_metrics IS
    'Unified view of routing and task completion metrics for cross-analysis';

-- ============================================================================
-- PHASE 5: Migration Tracking
-- ============================================================================

-- Record this migration
INSERT INTO schema_migrations (name, filename, applied_at)
VALUES (
    '002_separate_task_metrics',
    '002_separate_task_metrics.sql',
    NOW()
)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- ROLLBACK SCRIPT (for reference - run manually if needed)
-- ============================================================================

/*
-- To rollback this migration:

-- 1. Move data back to router_performance_metrics
INSERT INTO router_performance_metrics (
    id, created_at, query_text, routing_duration_ms, cache_hit,
    trigger_match_strategy, confidence_components, candidates_evaluated
)
SELECT
    id, created_at, task_description, completion_time_ms,
    (metadata->>'cache_hit')::BOOLEAN,
    task_type,
    metadata->'confidence_components',
    (metadata->>'candidates_evaluated')::INTEGER
FROM task_completion_metrics
WHERE metadata->>'original_table' = 'router_performance_metrics';

-- 2. Drop constraint
ALTER TABLE router_performance_metrics DROP CONSTRAINT IF EXISTS valid_routing_duration;

-- 3. Drop view
DROP VIEW IF EXISTS v_all_performance_metrics;

-- 4. Drop table
DROP TABLE IF EXISTS task_completion_metrics;

-- 5. Remove migration record
DELETE FROM schema_migrations WHERE name = '002_separate_task_metrics';
*/

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Verify data distribution
DO $$
DECLARE
    routing_count INTEGER;
    task_count INTEGER;
    routing_max_ms INTEGER;
    task_max_ms INTEGER;
BEGIN
    SELECT COUNT(*), MAX(routing_duration_ms) INTO routing_count, routing_max_ms
    FROM router_performance_metrics;

    SELECT COUNT(*), MAX(completion_time_ms) INTO task_count, task_max_ms
    FROM task_completion_metrics;

    RAISE NOTICE 'Validation Results:';
    RAISE NOTICE '  router_performance_metrics: % records, max duration: %ms', routing_count, routing_max_ms;
    RAISE NOTICE '  task_completion_metrics: % records, max duration: %ms', task_count, task_max_ms;

    -- Verify no routing durations exceed threshold
    IF routing_max_ms >= 1000 THEN
        RAISE WARNING 'Data quality issue: router_performance_metrics contains durations >= 1000ms';
    END IF;
END $$;
