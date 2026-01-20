-- Migration: Add Hook Intelligence Indexes and Analytics Views
-- Description: Enhance hook_events table with performance indexes and analytics capabilities
-- Version: 004
-- Date: 2025-10-10
-- Backward Compatible: Yes (extends JSONB fields, no schema changes)
-- Performance Target: <100ms query execution for all views

BEGIN;

-- ============================================================================
-- STEP 1: Performance Indexes for JSONB Fields
-- ============================================================================

-- Index for session-based queries (SessionStart/SessionEnd)
-- Enables fast session lookup and aggregation
CREATE INDEX IF NOT EXISTS idx_hook_events_session
ON hook_events ((metadata->>'session_id'))
WHERE source IN ('SessionStart', 'SessionEnd');

COMMENT ON INDEX idx_hook_events_session IS
'Performance index for session intelligence queries. Supports fast session lookup and duration calculations.';

-- Index for workflow pattern queries
-- Enables workflow pattern distribution analysis
CREATE INDEX IF NOT EXISTS idx_hook_events_workflow
ON hook_events ((payload->>'workflow_pattern'))
WHERE source = 'SessionEnd';

COMMENT ON INDEX idx_hook_events_workflow IS
'Performance index for workflow pattern analysis. Supports pattern distribution and frequency queries.';

-- Index for quality score queries
-- Enables quality metrics analysis per tool
CREATE INDEX IF NOT EXISTS idx_hook_events_quality
ON hook_events (((payload->'quality_metrics'->>'quality_score')::numeric))
WHERE source = 'PostToolUse' AND payload->'quality_metrics'->>'quality_score' IS NOT NULL;

COMMENT ON INDEX idx_hook_events_quality IS
'Performance index for quality score analysis. Supports tool quality metrics and success rate calculations.';

-- Index for success classification queries
-- Enables success rate analysis by tool
CREATE INDEX IF NOT EXISTS idx_hook_events_success
ON hook_events ((payload->>'success_classification'))
WHERE source = 'PostToolUse';

COMMENT ON INDEX idx_hook_events_success IS
'Performance index for success classification queries. Supports tool success rate analysis.';

-- Index for response completion queries
-- Enables response quality analysis
CREATE INDEX IF NOT EXISTS idx_hook_events_response
ON hook_events ((payload->>'completion_status'))
WHERE source = 'Stop';

COMMENT ON INDEX idx_hook_events_response IS
'Performance index for response completion analysis. Supports response quality and completion tracking.';

-- Index for agent detection queries
-- Enables agent usage pattern analysis
CREATE INDEX IF NOT EXISTS idx_hook_events_agent
ON hook_events ((payload->>'agent_detected'))
WHERE payload->>'agent_detected' IS NOT NULL;

COMMENT ON INDEX idx_hook_events_agent IS
'Performance index for agent detection queries. Supports agent usage pattern and routing analysis.';

-- Composite index for time-series analysis
-- Enables efficient time-based filtering with source filtering
CREATE INDEX IF NOT EXISTS idx_hook_events_created_source
ON hook_events (created_at DESC, source);

COMMENT ON INDEX idx_hook_events_created_source IS
'Composite performance index for time-series analysis with source filtering.';

-- ============================================================================
-- STEP 2: Analytics Views
-- ============================================================================

-- Session Intelligence Summary View
-- Provides aggregated session statistics for analytics and reporting
CREATE OR REPLACE VIEW session_intelligence_summary AS
SELECT
    metadata->>'session_id' as session_id,
    MIN(created_at) as session_start,
    MAX(created_at) as session_end,
    EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at))) as duration_seconds,
    COUNT(CASE WHEN source = 'UserPromptSubmit' THEN 1 END) as total_prompts,
    COUNT(CASE WHEN source = 'PostToolUse' THEN 1 END) as total_tools,
    COUNT(DISTINCT resource_id) FILTER (WHERE source = 'PostToolUse') as unique_tools,
    COUNT(CASE WHEN source = 'PostToolUse' AND payload->>'success_classification' = 'full_success' THEN 1 END) as successful_tools,
    ARRAY_AGG(DISTINCT payload->>'agent_detected') FILTER (WHERE payload->>'agent_detected' IS NOT NULL) as agents_used,
    MAX(payload->>'workflow_pattern') FILTER (WHERE source = 'SessionEnd') as workflow_pattern
FROM hook_events
WHERE metadata->>'session_id' IS NOT NULL
GROUP BY metadata->>'session_id';

COMMENT ON VIEW session_intelligence_summary IS
'Aggregated session statistics including duration, prompts, tools, success rates, and agent usage. Target: <100ms query time.';

-- Tool Success Rate View
-- Provides tool-level performance metrics and success rates
CREATE OR REPLACE VIEW tool_success_rates AS
SELECT
    resource_id as tool_name,
    COUNT(*) as total_uses,
    COUNT(CASE WHEN payload->>'success_classification' = 'full_success' THEN 1 END) as successful_uses,
    COUNT(CASE WHEN payload->>'success_classification' = 'partial_success' THEN 1 END) as partial_success_uses,
    COUNT(CASE WHEN payload->>'success_classification' = 'failure' THEN 1 END) as failed_uses,
    ROUND(100.0 * COUNT(CASE WHEN payload->>'success_classification' = 'full_success' THEN 1 END) / NULLIF(COUNT(*), 0), 2) as success_rate_pct,
    ROUND(AVG((payload->'quality_metrics'->>'quality_score')::numeric), 3) as avg_quality_score,
    ROUND(MIN((payload->'quality_metrics'->>'quality_score')::numeric), 3) as min_quality_score,
    ROUND(MAX((payload->'quality_metrics'->>'quality_score')::numeric), 3) as max_quality_score,
    MIN(created_at) as first_used,
    MAX(created_at) as last_used
FROM hook_events
WHERE source = 'PostToolUse'
GROUP BY resource_id
ORDER BY total_uses DESC;

COMMENT ON VIEW tool_success_rates IS
'Tool-level performance metrics including success rates, quality scores, and usage statistics. Target: <100ms query time.';

-- Workflow Pattern Distribution View
-- Provides workflow pattern analysis and characteristics
CREATE OR REPLACE VIEW workflow_pattern_distribution AS
SELECT
    payload->>'workflow_pattern' as workflow_pattern,
    COUNT(*) as session_count,
    ROUND(AVG((payload->>'total_prompts')::integer), 1) as avg_prompts_per_session,
    ROUND(AVG((payload->>'total_tools')::integer), 1) as avg_tools_per_session,
    ROUND(AVG((payload->>'duration_seconds')::numeric), 1) as avg_duration_seconds,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage_of_total,
    MIN(created_at) as first_seen,
    MAX(created_at) as last_seen
FROM hook_events
WHERE source = 'SessionEnd'
AND payload->>'workflow_pattern' IS NOT NULL
GROUP BY payload->>'workflow_pattern'
ORDER BY session_count DESC;

COMMENT ON VIEW workflow_pattern_distribution IS
'Workflow pattern distribution with session characteristics. Target: <100ms query time.';

-- Agent Usage Patterns View
-- Provides agent routing and usage analysis
CREATE OR REPLACE VIEW agent_usage_patterns AS
SELECT
    payload->>'agent_detected' as agent_name,
    COUNT(*) as detection_count,
    COUNT(DISTINCT metadata->>'session_id') as unique_sessions,
    ARRAY_AGG(DISTINCT source) as detected_in_sources,
    MIN(created_at) as first_detected,
    MAX(created_at) as last_detected,
    COUNT(*) FILTER (WHERE source = 'UserPromptSubmit') as prompts_with_agent,
    COUNT(*) FILTER (WHERE source = 'PostToolUse') as tools_with_agent
FROM hook_events
WHERE payload->>'agent_detected' IS NOT NULL
GROUP BY payload->>'agent_detected'
ORDER BY detection_count DESC;

COMMENT ON VIEW agent_usage_patterns IS
'Agent detection and routing patterns with usage statistics. Target: <100ms query time.';

-- Quality Metrics Summary View
-- Provides quality score distribution and analysis
CREATE OR REPLACE VIEW quality_metrics_summary AS
SELECT
    resource_id as tool_name,
    COUNT(*) as total_executions,
    ROUND(AVG((payload->'quality_metrics'->>'quality_score')::numeric), 3) as avg_quality,
    ROUND(STDDEV((payload->'quality_metrics'->>'quality_score')::numeric), 3) as stddev_quality,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (payload->'quality_metrics'->>'quality_score')::numeric))::numeric, 3) as median_quality,
    ROUND((PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY (payload->'quality_metrics'->>'quality_score')::numeric))::numeric, 3) as p25_quality,
    ROUND((PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY (payload->'quality_metrics'->>'quality_score')::numeric))::numeric, 3) as p75_quality,
    COUNT(CASE WHEN (payload->'quality_metrics'->>'quality_score')::numeric >= 0.8 THEN 1 END) as high_quality_count,
    COUNT(CASE WHEN (payload->'quality_metrics'->>'quality_score')::numeric < 0.5 THEN 1 END) as low_quality_count
FROM hook_events
WHERE source = 'PostToolUse'
AND payload->'quality_metrics'->>'quality_score' IS NOT NULL
GROUP BY resource_id
HAVING COUNT(*) >= 3  -- Only include tools with at least 3 executions
ORDER BY avg_quality DESC;

COMMENT ON VIEW quality_metrics_summary IS
'Quality score distribution with statistical analysis per tool. Target: <100ms query time.';

-- ============================================================================
-- STEP 3: Helper Functions
-- ============================================================================

-- Function: get_session_stats
-- Returns comprehensive session statistics for a given session_id
CREATE OR REPLACE FUNCTION get_session_stats(p_session_id UUID)
RETURNS TABLE(
    prompts INTEGER,
    tools INTEGER,
    agents TEXT[],
    duration_seconds NUMERIC,
    workflow_pattern TEXT,
    success_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(CASE WHEN source = 'UserPromptSubmit' THEN 1 END)::INTEGER,
        COUNT(CASE WHEN source = 'PostToolUse' THEN 1 END)::INTEGER,
        ARRAY_AGG(DISTINCT payload->>'agent_detected') FILTER (WHERE payload->>'agent_detected' IS NOT NULL),
        EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at)))::NUMERIC,
        MAX(payload->>'workflow_pattern') FILTER (WHERE source = 'SessionEnd'),
        ROUND(
            100.0 * COUNT(CASE WHEN source = 'PostToolUse' AND payload->>'success_classification' = 'full_success' THEN 1 END)
            / NULLIF(COUNT(CASE WHEN source = 'PostToolUse' THEN 1 END), 0),
            2
        )::NUMERIC
    FROM hook_events
    WHERE metadata->>'session_id' = p_session_id::TEXT;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_session_stats IS
'Returns comprehensive session statistics including prompts, tools, agents, duration, workflow pattern, and success rate.';

-- Function: get_tool_performance
-- Returns performance metrics for a specific tool
CREATE OR REPLACE FUNCTION get_tool_performance(p_tool_name TEXT)
RETURNS TABLE(
    total_uses BIGINT,
    success_rate NUMERIC,
    avg_quality NUMERIC,
    last_7_days_uses BIGINT,
    trending TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*),
        ROUND(
            100.0 * COUNT(CASE WHEN payload->>'success_classification' = 'full_success' THEN 1 END)
            / NULLIF(COUNT(*), 0),
            2
        ),
        ROUND(AVG((payload->'quality_metrics'->>'quality_score')::numeric), 3),
        COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days'),
        CASE
            WHEN COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') >
                 COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '14 days' AND created_at < NOW() - INTERVAL '7 days')
            THEN 'increasing'
            WHEN COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') <
                 COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '14 days' AND created_at < NOW() - INTERVAL '7 days')
            THEN 'decreasing'
            ELSE 'stable'
        END
    FROM hook_events
    WHERE source = 'PostToolUse'
    AND resource_id = p_tool_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_tool_performance IS
'Returns performance metrics for a specific tool including success rate, quality score, recent usage, and trending analysis.';

-- Function: get_recent_workflow_patterns
-- Returns workflow patterns from the last N days
CREATE OR REPLACE FUNCTION get_recent_workflow_patterns(p_days INTEGER DEFAULT 7)
RETURNS TABLE(
    workflow_pattern TEXT,
    session_count BIGINT,
    avg_duration NUMERIC,
    avg_prompts NUMERIC,
    avg_tools NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        payload->>'workflow_pattern',
        COUNT(*),
        ROUND(AVG((payload->>'duration_seconds')::numeric), 1),
        ROUND(AVG((payload->>'total_prompts')::integer), 1),
        ROUND(AVG((payload->>'total_tools')::integer), 1)
    FROM hook_events
    WHERE source = 'SessionEnd'
    AND payload->>'workflow_pattern' IS NOT NULL
    AND created_at >= NOW() - (p_days || ' days')::INTERVAL
    GROUP BY payload->>'workflow_pattern'
    ORDER BY COUNT(*) DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_recent_workflow_patterns IS
'Returns workflow patterns from the last N days with session characteristics and usage statistics.';

-- Function: calculate_session_success_score
-- Calculates a composite success score for a session
CREATE OR REPLACE FUNCTION calculate_session_success_score(p_session_id UUID)
RETURNS NUMERIC AS $$
DECLARE
    v_tool_success_rate NUMERIC;
    v_avg_quality NUMERIC;
    v_response_completion NUMERIC;
    v_composite_score NUMERIC;
BEGIN
    -- Calculate tool success rate (40% weight)
    SELECT
        COALESCE(
            100.0 * COUNT(CASE WHEN payload->>'success_classification' = 'full_success' THEN 1 END)
            / NULLIF(COUNT(*), 0),
            0
        )
    INTO v_tool_success_rate
    FROM hook_events
    WHERE metadata->>'session_id' = p_session_id::TEXT
    AND source = 'PostToolUse';

    -- Calculate average quality score (40% weight)
    SELECT
        COALESCE(AVG((payload->'quality_metrics'->>'quality_score')::numeric) * 100, 0)
    INTO v_avg_quality
    FROM hook_events
    WHERE metadata->>'session_id' = p_session_id::TEXT
    AND source = 'PostToolUse'
    AND payload->'quality_metrics'->>'quality_score' IS NOT NULL;

    -- Calculate response completion rate (20% weight)
    SELECT
        COALESCE(
            100.0 * COUNT(CASE WHEN payload->>'completion_status' = 'completed' THEN 1 END)
            / NULLIF(COUNT(*), 0),
            0
        )
    INTO v_response_completion
    FROM hook_events
    WHERE metadata->>'session_id' = p_session_id::TEXT
    AND source = 'Stop';

    -- Calculate composite score
    v_composite_score := ROUND(
        (v_tool_success_rate * 0.4) +
        (v_avg_quality * 0.4) +
        (v_response_completion * 0.2),
        2
    );

    RETURN v_composite_score;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calculate_session_success_score IS
'Calculates a composite success score (0-100) for a session based on tool success rate (40%), quality score (40%), and response completion (20%).';

-- ============================================================================
-- STEP 4: Performance Verification
-- ============================================================================

-- Analyze tables to update statistics for query planner
ANALYZE hook_events;

-- ============================================================================
-- STEP 5: Migration Metadata
-- ============================================================================

-- Record migration application
DO $$
BEGIN
    -- Create migrations table if it doesn't exist
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        execution_time_ms INTEGER
    );

    -- Record this migration
    INSERT INTO schema_migrations (version, description, execution_time_ms)
    VALUES (
        4,
        'Add hook intelligence indexes, analytics views, and helper functions',
        EXTRACT(MILLISECONDS FROM NOW() - statement_timestamp())::INTEGER
    )
    ON CONFLICT (version) DO NOTHING;
END $$;

COMMIT;

-- ============================================================================
-- Post-Migration Verification Queries
-- ============================================================================

-- Verify indexes were created
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'hook_events' AND indexname LIKE 'idx_hook_events_%';

-- Verify views were created
-- SELECT viewname FROM pg_views WHERE viewname LIKE '%intelligence%' OR viewname LIKE '%workflow%' OR viewname LIKE '%tool%';

-- Verify functions were created
-- SELECT proname, prosrc FROM pg_proc WHERE proname LIKE 'get_%' OR proname LIKE 'calculate_%';

-- Test query performance (should be <100ms)
-- EXPLAIN ANALYZE SELECT * FROM session_intelligence_summary LIMIT 10;
-- EXPLAIN ANALYZE SELECT * FROM tool_success_rates LIMIT 10;
