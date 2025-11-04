-- verify_lifecycle_tracking.sql
-- Verification queries to test agent lifecycle completion tracking
--
-- Purpose: Verify that the "Active Agents never reaches 0" bug is fixed
--
-- Database: omninode_bridge
-- Table: agent_manifest_injections
-- Connection: postgresql://postgres:${POSTGRES_PASSWORD}@omninode-bridge-postgres:5436/omninode_bridge

-- ============================================================================
-- VERIFICATION 1: Active Agents Count
-- Expected: Should be 0 when no agents running, small number during execution
-- ============================================================================

SELECT
    'Active Agents Count' AS verification,
    COUNT(*) AS active_agents,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '5 minutes') AS active_last_5min,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') AS active_last_hour
FROM agent_manifest_injections
WHERE completed_at IS NULL;

-- ============================================================================
-- VERIFICATION 2: Lifecycle Fields Population
-- Expected: All fields should be populated for completed agents
-- ============================================================================

SELECT
    'Lifecycle Fields Population' AS verification,
    COUNT(*) AS total_records,
    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS has_completed_at,
    COUNT(*) FILTER (WHERE executed_at IS NOT NULL) AS has_executed_at,
    COUNT(*) FILTER (WHERE agent_execution_success IS NOT NULL) AS has_success_flag,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE completed_at IS NOT NULL) / NULLIF(COUNT(*), 0),
        2
    ) AS completion_percentage
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours';

-- ============================================================================
-- VERIFICATION 3: Agent Name Resolution
-- Expected: Very few or zero "unknown" agents (should be <5%)
-- ============================================================================

SELECT
    'Agent Name Resolution' AS verification,
    COUNT(*) AS total_records,
    COUNT(*) FILTER (WHERE agent_name = 'unknown') AS unknown_agents,
    COUNT(*) FILTER (WHERE agent_name != 'unknown') AS known_agents,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE agent_name = 'unknown') / NULLIF(COUNT(*), 0),
        2
    ) AS unknown_percentage
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours';

-- ============================================================================
-- VERIFICATION 4: Recent Executions with Complete Lifecycle
-- Expected: Should show recent executions with all lifecycle fields populated
-- ============================================================================

SELECT
    correlation_id,
    agent_name,
    created_at,
    completed_at,
    executed_at,
    agent_execution_success,
    EXTRACT(EPOCH FROM (completed_at - created_at)) AS duration_seconds,
    patterns_count,
    is_fallback
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================================
-- VERIFICATION 5: Execution Duration Statistics
-- Expected: Most executions complete within 1-10 seconds
-- ============================================================================

SELECT
    'Execution Duration Statistics' AS verification,
    COUNT(*) AS completed_executions,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS avg_duration_seconds,
    ROUND(MIN(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS min_duration_seconds,
    ROUND(MAX(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS max_duration_seconds,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (completed_at - created_at))) AS median_duration_seconds,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (completed_at - created_at))) AS p95_duration_seconds
FROM agent_manifest_injections
WHERE
    completed_at IS NOT NULL
    AND created_at > NOW() - INTERVAL '24 hours';

-- ============================================================================
-- VERIFICATION 6: Success Rate by Agent
-- Expected: Most agents should have high success rates (>90%)
-- ============================================================================

SELECT
    agent_name,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE agent_execution_success = true) AS successful,
    COUNT(*) FILTER (WHERE agent_execution_success = false) AS failed,
    COUNT(*) FILTER (WHERE completed_at IS NULL) AS still_running,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE agent_execution_success = true) /
        NULLIF(COUNT(*) FILTER (WHERE agent_execution_success IS NOT NULL), 0),
        2
    ) AS success_rate_percent,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS avg_duration_seconds
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name
ORDER BY total_executions DESC
LIMIT 20;

-- ============================================================================
-- VERIFICATION 7: Orphaned Records (should be minimal or zero)
-- Expected: Only very recent records (<5 minutes old) should be incomplete
-- ============================================================================

SELECT
    'Orphaned Records Check' AS verification,
    COUNT(*) AS total_incomplete,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '5 minutes') AS recent_incomplete,
    COUNT(*) FILTER (WHERE created_at < NOW() - INTERVAL '5 minutes') AS stale_incomplete,
    ARRAY_AGG(DISTINCT agent_name) FILTER (WHERE created_at < NOW() - INTERVAL '5 minutes') AS stale_agents
FROM agent_manifest_injections
WHERE completed_at IS NULL;

-- ============================================================================
-- VERIFICATION 8: Mark Agent Completed Method Test
-- Test the new mark_agent_completed() method by checking recent updates
-- Expected: Recent completed records should have all lifecycle fields set
-- ============================================================================

SELECT
    'Recent Completions Test' AS verification,
    correlation_id,
    agent_name,
    created_at,
    completed_at,
    executed_at,
    agent_execution_success,
    CASE
        WHEN completed_at IS NOT NULL AND executed_at IS NOT NULL AND agent_execution_success IS NOT NULL
        THEN 'PASS'
        ELSE 'FAIL'
    END AS lifecycle_tracking_status,
    warnings
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- VERIFICATION 9: Historical Trend (24 hours)
-- Expected: See improvement in completion tracking over time
-- ============================================================================

SELECT
    DATE_TRUNC('hour', created_at) AS hour,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed,
    COUNT(*) FILTER (WHERE completed_at IS NULL) AS incomplete,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE completed_at IS NOT NULL) / NULLIF(COUNT(*), 0),
        2
    ) AS completion_rate_percent,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS avg_duration_seconds
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

-- ============================================================================
-- SUMMARY REPORT
-- ============================================================================

SELECT
    '=== LIFECYCLE TRACKING SUMMARY ===' AS report;

SELECT
    'Total Records (24h)' AS metric,
    COUNT(*)::text AS value
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'

UNION ALL

SELECT
    'Completed Records (24h)',
    COUNT(*)::text
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours' AND completed_at IS NOT NULL

UNION ALL

SELECT
    'Active Agents (now)',
    COUNT(*)::text
FROM agent_manifest_injections
WHERE completed_at IS NULL

UNION ALL

SELECT
    'Unknown Agent Names (24h)',
    COUNT(*)::text
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours' AND agent_name = 'unknown'

UNION ALL

SELECT
    'Average Duration (24h)',
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))), 2)::text || 's'
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours' AND completed_at IS NOT NULL

UNION ALL

SELECT
    'Success Rate (24h)',
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE agent_execution_success = true) /
        NULLIF(COUNT(*) FILTER (WHERE agent_execution_success IS NOT NULL), 0),
        2
    )::text || '%'
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours';
