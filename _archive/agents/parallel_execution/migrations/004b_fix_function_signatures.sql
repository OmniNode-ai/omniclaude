-- Patch Migration: Fix Function Signatures for Session ID
-- Description: Update get_session_stats and calculate_session_success_score to accept TEXT instead of UUID
-- Version: 004b
-- Date: 2025-10-10
-- Reason: Session IDs in database are TEXT format, not UUID

BEGIN;

-- Drop existing functions
DROP FUNCTION IF EXISTS get_session_stats(UUID);
DROP FUNCTION IF EXISTS calculate_session_success_score(UUID);

-- Recreate get_session_stats with TEXT parameter
CREATE OR REPLACE FUNCTION get_session_stats(p_session_id TEXT)
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
    WHERE metadata->>'session_id' = p_session_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_session_stats IS
'Returns comprehensive session statistics including prompts, tools, agents, duration, workflow pattern, and success rate. Accepts session_id as TEXT.';

-- Recreate calculate_session_success_score with TEXT parameter
CREATE OR REPLACE FUNCTION calculate_session_success_score(p_session_id TEXT)
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
    WHERE metadata->>'session_id' = p_session_id
    AND source = 'PostToolUse';

    -- Calculate average quality score (40% weight)
    SELECT
        COALESCE(AVG((payload->'quality_metrics'->>'quality_score')::numeric) * 100, 0)
    INTO v_avg_quality
    FROM hook_events
    WHERE metadata->>'session_id' = p_session_id
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
    WHERE metadata->>'session_id' = p_session_id
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
'Calculates a composite success score (0-100) for a session based on tool success rate (40%), quality score (40%), and response completion (20%). Accepts session_id as TEXT.';

COMMIT;
