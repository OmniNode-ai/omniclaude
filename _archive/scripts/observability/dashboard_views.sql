-- =====================================================================
-- Dashboard Views for Agent Execution Monitoring
-- =====================================================================
-- Purpose: Provide dashboard-friendly queries for agent execution status
-- Database: omninode_bridge
-- Created: 2025-10-30
-- =====================================================================

-- =====================================================================
-- View: v_active_agents
-- Purpose: Show agents currently running (in_progress status)
-- =====================================================================
CREATE OR REPLACE VIEW v_active_agents AS
SELECT
    execution_id,
    agent_name,
    correlation_id,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER as running_seconds,
    CASE
        WHEN EXTRACT(EPOCH FROM (NOW() - started_at)) > 3600 THEN '🔴 STUCK'
        WHEN EXTRACT(EPOCH FROM (NOW() - started_at)) > 1800 THEN '🟡 LONG'
        ELSE '🟢 ACTIVE'
    END as status_indicator,
    LEFT(user_prompt, 100) as user_prompt_preview,
    project_path
FROM agent_execution_logs
WHERE status = 'in_progress'
  AND completed_at IS NULL
ORDER BY started_at DESC;

COMMENT ON VIEW v_active_agents IS
'Shows all agents currently in progress. Flags agents stuck >1hr or running >30min.';

-- =====================================================================
-- View: v_agent_completion_stats_24h
-- Purpose: Agent completion statistics for last 24 hours
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_completion_stats_24h AS
SELECT
    COUNT(*) FILTER (WHERE status = 'success') as completed_success,
    COUNT(*) FILTER (WHERE status = 'error') as completed_error,
    COUNT(*) FILTER (WHERE status = 'cancelled') as completed_cancelled,
    COUNT(*) FILTER (WHERE status = 'in_progress' AND completed_at IS NULL) as currently_active,
    COUNT(*) FILTER (WHERE status = 'in_progress' AND completed_at IS NOT NULL) as stuck_marked_complete,
    COUNT(*) as total_executions,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') /
        NULLIF(COUNT(*) FILTER (WHERE status IN ('success', 'error', 'cancelled')), 0),
        1
    ) as success_rate_percent,
    ROUND(AVG(duration_ms) FILTER (WHERE status = 'success'), 0) as avg_success_duration_ms,
    ROUND(AVG(quality_score) FILTER (WHERE status = 'success'), 2) as avg_quality_score,
    MIN(started_at) as oldest_execution,
    MAX(started_at) as newest_execution
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '24 hours';

COMMENT ON VIEW v_agent_completion_stats_24h IS
'24-hour rolling statistics for agent executions including success rate and quality metrics.';

-- =====================================================================
-- View: v_agent_completion_stats_7d
-- Purpose: Agent completion statistics for last 7 days
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_completion_stats_7d AS
SELECT
    COUNT(*) FILTER (WHERE status = 'success') as completed_success,
    COUNT(*) FILTER (WHERE status = 'error') as completed_error,
    COUNT(*) FILTER (WHERE status = 'cancelled') as completed_cancelled,
    COUNT(*) FILTER (WHERE status = 'in_progress') as currently_active,
    COUNT(*) as total_executions,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') /
        NULLIF(COUNT(*) FILTER (WHERE status IN ('success', 'error', 'cancelled')), 0),
        1
    ) as success_rate_percent,
    ROUND(AVG(duration_ms) FILTER (WHERE status = 'success'), 0) as avg_success_duration_ms,
    ROUND(AVG(quality_score) FILTER (WHERE status = 'success'), 2) as avg_quality_score
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '7 days';

COMMENT ON VIEW v_agent_completion_stats_7d IS
'7-day rolling statistics for agent executions.';

-- =====================================================================
-- View: v_agent_performance
-- Purpose: Performance metrics by agent type
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_performance AS
SELECT
    agent_name,
    COUNT(*) as total_executions,
    COUNT(*) FILTER (WHERE status = 'success') as successes,
    COUNT(*) FILTER (WHERE status = 'error') as errors,
    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') /
        NULLIF(COUNT(*), 0),
        1
    ) as success_rate_percent,
    ROUND(AVG(duration_ms) FILTER (WHERE status = 'success'), 0) as avg_duration_ms,
    ROUND(MIN(duration_ms) FILTER (WHERE status = 'success'), 0) as min_duration_ms,
    ROUND(MAX(duration_ms) FILTER (WHERE status = 'success'), 0) as max_duration_ms,
    ROUND(AVG(quality_score) FILTER (WHERE status = 'success'), 2) as avg_quality_score,
    MAX(started_at) as last_run,
    COUNT(*) FILTER (WHERE started_at > NOW() - INTERVAL '24 hours') as runs_last_24h
FROM agent_execution_logs
WHERE agent_name IS NOT NULL
  AND started_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name
ORDER BY total_executions DESC;

COMMENT ON VIEW v_agent_performance IS
'Performance metrics per agent type for last 7 days. Shows success rates, duration stats, and quality scores.';

-- =====================================================================
-- View: v_agent_errors_recent
-- Purpose: Recent agent errors for troubleshooting
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_errors_recent AS
SELECT
    execution_id,
    agent_name,
    correlation_id,
    started_at,
    completed_at,
    duration_ms,
    error_type,
    LEFT(error_message, 200) as error_message_preview,
    LEFT(user_prompt, 100) as user_prompt_preview,
    project_path
FROM agent_execution_logs
WHERE status = 'error'
  AND started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC
LIMIT 50;

COMMENT ON VIEW v_agent_errors_recent IS
'Recent agent errors (last 7 days, max 50) for troubleshooting.';

-- =====================================================================
-- View: v_stuck_agents
-- Purpose: Identify agents stuck in progress for >1 hour
-- =====================================================================
CREATE OR REPLACE VIEW v_stuck_agents AS
SELECT
    execution_id,
    agent_name,
    correlation_id,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER as stuck_duration_seconds,
    ROUND(EXTRACT(EPOCH FROM (NOW() - started_at)) / 3600, 1) as stuck_duration_hours,
    LEFT(user_prompt, 100) as user_prompt_preview,
    project_path,
    CASE
        WHEN EXTRACT(EPOCH FROM (NOW() - started_at)) > 86400 THEN '🔴 CRITICAL (>24h)'
        WHEN EXTRACT(EPOCH FROM (NOW() - started_at)) > 3600 THEN '🟠 WARNING (>1h)'
        ELSE '🟡 MONITOR (>30m)'
    END as severity
FROM agent_execution_logs
WHERE status = 'in_progress'
  AND completed_at IS NULL
  AND EXTRACT(EPOCH FROM (NOW() - started_at)) > 1800  -- 30 minutes
ORDER BY started_at ASC;

COMMENT ON VIEW v_stuck_agents IS
'Agents stuck in progress for >30 minutes. Used by cleanup script to mark as errors.';

-- =====================================================================
-- View: v_agent_daily_trends
-- Purpose: Daily execution trends for last 30 days
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_daily_trends AS
SELECT
    DATE(started_at) as execution_date,
    COUNT(*) as total_executions,
    COUNT(*) FILTER (WHERE status = 'success') as successes,
    COUNT(*) FILTER (WHERE status = 'error') as errors,
    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'success') /
        NULLIF(COUNT(*), 0),
        1
    ) as success_rate_percent,
    ROUND(AVG(duration_ms) FILTER (WHERE status = 'success'), 0) as avg_duration_ms,
    ROUND(AVG(quality_score) FILTER (WHERE status = 'success'), 2) as avg_quality_score,
    COUNT(DISTINCT agent_name) as unique_agents_used
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(started_at)
ORDER BY execution_date DESC;

COMMENT ON VIEW v_agent_daily_trends IS
'Daily execution trends for last 30 days. Shows volume, success rates, and quality over time.';

-- =====================================================================
-- View: v_agent_quality_leaderboard
-- Purpose: Agent quality scores leaderboard
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_quality_leaderboard AS
SELECT
    agent_name,
    COUNT(*) FILTER (WHERE quality_score IS NOT NULL) as scored_executions,
    ROUND(AVG(quality_score), 2) as avg_quality_score,
    ROUND(MIN(quality_score), 2) as min_quality_score,
    ROUND(MAX(quality_score), 2) as max_quality_score,
    COUNT(*) FILTER (WHERE quality_score >= 0.9) as excellent_count,
    COUNT(*) FILTER (WHERE quality_score >= 0.7 AND quality_score < 0.9) as good_count,
    COUNT(*) FILTER (WHERE quality_score >= 0.5 AND quality_score < 0.7) as fair_count,
    COUNT(*) FILTER (WHERE quality_score < 0.5) as poor_count,
    MAX(started_at) as last_run
FROM agent_execution_logs
WHERE status = 'success'
  AND quality_score IS NOT NULL
  AND started_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name
HAVING COUNT(*) FILTER (WHERE quality_score IS NOT NULL) >= 3  -- At least 3 scored runs
ORDER BY avg_quality_score DESC;

COMMENT ON VIEW v_agent_quality_leaderboard IS
'Agent quality scores leaderboard (last 7 days, min 3 scored runs). Shows quality distribution.';

-- =====================================================================
-- View: v_agent_execution_summary
-- Purpose: High-level summary for dashboard homepage
-- =====================================================================
CREATE OR REPLACE VIEW v_agent_execution_summary AS
SELECT
    (SELECT COUNT(*) FROM v_active_agents) as active_now,
    (SELECT COUNT(*) FROM v_stuck_agents) as stuck_now,
    (SELECT completed_success FROM v_agent_completion_stats_24h) as success_24h,
    (SELECT completed_error FROM v_agent_completion_stats_24h) as errors_24h,
    (SELECT success_rate_percent FROM v_agent_completion_stats_24h) as success_rate_24h,
    (SELECT avg_quality_score FROM v_agent_completion_stats_24h) as avg_quality_24h,
    (SELECT COUNT(*) FROM v_agent_errors_recent) as recent_errors,
    (SELECT COUNT(DISTINCT agent_name) FROM agent_execution_logs
     WHERE started_at > NOW() - INTERVAL '24 hours') as unique_agents_24h,
    NOW() as refreshed_at;

COMMENT ON VIEW v_agent_execution_summary IS
'High-level summary for dashboard homepage. Single row with key metrics.';

-- =====================================================================
-- Grant permissions (adjust as needed for your environment)
-- =====================================================================
-- GRANT SELECT ON v_active_agents TO dashboard_readonly;
-- GRANT SELECT ON v_agent_completion_stats_24h TO dashboard_readonly;
-- GRANT SELECT ON v_agent_completion_stats_7d TO dashboard_readonly;
-- GRANT SELECT ON v_agent_performance TO dashboard_readonly;
-- GRANT SELECT ON v_agent_errors_recent TO dashboard_readonly;
-- GRANT SELECT ON v_stuck_agents TO dashboard_readonly;
-- GRANT SELECT ON v_agent_daily_trends TO dashboard_readonly;
-- GRANT SELECT ON v_agent_quality_leaderboard TO dashboard_readonly;
-- GRANT SELECT ON v_agent_execution_summary TO dashboard_readonly;

-- =====================================================================
-- Example Queries
-- =====================================================================

-- Quick dashboard summary
-- SELECT * FROM v_agent_execution_summary;

-- Check active agents
-- SELECT * FROM v_active_agents;

-- Check stuck agents
-- SELECT * FROM v_stuck_agents;

-- View 24h stats
-- SELECT * FROM v_agent_completion_stats_24h;

-- Agent performance rankings
-- SELECT * FROM v_agent_performance;

-- Recent errors
-- SELECT * FROM v_agent_errors_recent LIMIT 10;

-- Daily trends
-- SELECT * FROM v_agent_daily_trends LIMIT 7;

-- Quality leaderboard
-- SELECT * FROM v_agent_quality_leaderboard;
