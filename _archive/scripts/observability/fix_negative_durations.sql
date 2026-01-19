-- Fix Negative Duration Bug - Data Validation and Cleanup
-- Created: 2025-10-29
-- Purpose: Find and document records with negative durations caused by timezone bug
--
-- Root Cause:
--   datetime.utcnow() (naive) used instead of datetime.now(timezone.utc) (timezone-aware)
--   in skills/log-execution/execute.py (lines 146, 201)
--
-- Evidence Example:
--   Started:   2025-10-29 21:57:52+00 (9:57 PM UTC)
--   Completed: 2025-10-29 17:57:52+00 (5:57 PM UTC - 4 hours earlier!)
--   Duration:  -14,400,000ms (-4 hours)

-- Step 1: Identify all records with negative durations
SELECT
    execution_id,
    correlation_id,
    agent_name,
    started_at,
    completed_at,
    duration_ms,
    EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000 AS calculated_duration_ms,
    status,
    created_at
FROM agent_execution_logs
WHERE duration_ms < 0
ORDER BY started_at DESC;

-- Step 2: Show statistics on affected records
SELECT
    COUNT(*) AS affected_records,
    MIN(duration_ms) AS worst_negative_duration_ms,
    MAX(duration_ms) AS best_negative_duration_ms,
    AVG(duration_ms) AS avg_negative_duration_ms,
    COUNT(DISTINCT agent_name) AS affected_agents
FROM agent_execution_logs
WHERE duration_ms < 0;

-- Step 3: Show affected agents breakdown
SELECT
    agent_name,
    COUNT(*) AS negative_duration_count,
    AVG(duration_ms) AS avg_negative_duration_ms,
    MIN(started_at) AS first_occurrence,
    MAX(started_at) AS last_occurrence
FROM agent_execution_logs
WHERE duration_ms < 0
GROUP BY agent_name
ORDER BY negative_duration_count DESC;

-- Step 4: (OPTIONAL) Clear invalid durations for reprocessing
-- WARNING: This will NULL out the completed_at and duration_ms fields
-- Uncomment to execute:
--
-- UPDATE agent_execution_logs
-- SET
--     completed_at = NULL,
--     duration_ms = NULL,
--     status = 'error',
--     error_message = COALESCE(
--         error_message || ' | ',
--         ''
--     ) || 'Invalid negative duration (timezone bug) - cleared for reprocessing'
-- WHERE duration_ms < 0
-- RETURNING
--     execution_id,
--     agent_name,
--     started_at,
--     error_message;

-- Step 5: Validate fix by checking recent records (after fix applied)
-- This should return 0 records once the fix is deployed
SELECT
    execution_id,
    agent_name,
    started_at,
    completed_at,
    duration_ms,
    status
FROM agent_execution_logs
WHERE
    started_at > NOW() - INTERVAL '1 hour'
    AND duration_ms < 0
ORDER BY started_at DESC;

-- Step 6: Show healthy records (positive durations) for comparison
SELECT
    execution_id,
    agent_name,
    started_at,
    completed_at,
    duration_ms,
    status
FROM agent_execution_logs
WHERE
    started_at > NOW() - INTERVAL '1 hour'
    AND duration_ms > 0
ORDER BY started_at DESC
LIMIT 10;
