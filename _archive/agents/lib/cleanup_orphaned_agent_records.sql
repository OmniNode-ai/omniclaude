-- cleanup_orphaned_agent_records.sql
-- Cleanup script for orphaned agent_manifest_injections records
--
-- Purpose: Fix "Active Agents never reaches 0" bug by marking old records as completed
--
-- Problem: Database has lifecycle fields (completed_at, executed_at, agent_execution_success)
--          but NO code updates them, causing "Active Agents" counter to stay high.
--
-- Solution: Mark all orphaned records (completed_at IS NULL) as completed with reasonable
--           timestamps based on when they were created.
--
-- Safety: This script is IDEMPOTENT - safe to run multiple times.
--
-- Database: omninode_bridge
-- Table: agent_manifest_injections
-- Connection: postgresql://postgres:${POSTGRES_PASSWORD}@omninode-bridge-postgres:5436/omninode_bridge

-- Display current orphaned records status BEFORE cleanup
SELECT
    'BEFORE CLEANUP' AS status,
    COUNT(*) AS total_records,
    COUNT(*) FILTER (WHERE completed_at IS NULL) AS orphaned_records,
    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_records,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE completed_at IS NULL) / NULLIF(COUNT(*), 0),
        2
    ) AS orphaned_percentage
FROM agent_manifest_injections;

-- Show sample of orphaned records
SELECT
    correlation_id,
    agent_name,
    created_at,
    completed_at,
    agent_execution_success,
    is_fallback,
    patterns_count
FROM agent_manifest_injections
WHERE completed_at IS NULL
ORDER BY created_at DESC
LIMIT 10;

-- BEGIN CLEANUP TRANSACTION
BEGIN;

-- Update orphaned records with completion timestamps
-- Strategy: Assume old records completed successfully after ~5 minutes
UPDATE agent_manifest_injections
SET
    completed_at = created_at + INTERVAL '5 minutes',
    executed_at = created_at + INTERVAL '5 minutes',
    agent_execution_success = CASE
        -- If record has warnings or is fallback, mark as degraded success
        WHEN is_fallback = true THEN true
        WHEN ARRAY_LENGTH(warnings, 1) > 0 THEN true
        -- Otherwise assume success
        ELSE true
    END,
    warnings = CASE
        -- Add cleanup warning to track which records were auto-completed
        WHEN warnings IS NULL THEN
            ARRAY['Auto-completed by cleanup script - assumed successful after 5 minutes']
        ELSE
            warnings || ARRAY['Auto-completed by cleanup script - assumed successful after 5 minutes']
    END
WHERE
    completed_at IS NULL
    -- Safety check: Only cleanup records older than 1 hour to avoid interfering with running agents
    AND created_at < NOW() - INTERVAL '1 hour';

-- Display cleanup results
SELECT
    'CLEANUP RESULTS' AS status,
    COUNT(*) AS records_updated
FROM agent_manifest_injections
WHERE
    'Auto-completed by cleanup script - assumed successful after 5 minutes' = ANY(warnings);

-- Display current status AFTER cleanup
SELECT
    'AFTER CLEANUP' AS status,
    COUNT(*) AS total_records,
    COUNT(*) FILTER (WHERE completed_at IS NULL) AS orphaned_records,
    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_records,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE completed_at IS NULL) / NULLIF(COUNT(*), 0),
        2
    ) AS orphaned_percentage
FROM agent_manifest_injections;

-- Show sample of recently completed records
SELECT
    correlation_id,
    agent_name,
    created_at,
    completed_at,
    agent_execution_success,
    (completed_at - created_at) AS execution_duration,
    patterns_count
FROM agent_manifest_injections
WHERE completed_at IS NOT NULL
ORDER BY completed_at DESC
LIMIT 10;

-- COMMIT or ROLLBACK
-- Uncomment ONE of the following lines:
COMMIT;   -- Apply changes
-- ROLLBACK;  -- Undo changes (for testing)

-- Verification: Show "Active Agents" count (should be 0 or very low after cleanup)
SELECT
    COUNT(*) AS active_agents,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') AS active_recent
FROM agent_manifest_injections
WHERE completed_at IS NULL;

-- Show agent name distribution (identify any remaining "unknown" agents)
SELECT
    agent_name,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE completed_at IS NULL) AS still_active,
    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed,
    ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))), 2) AS avg_duration_seconds
FROM agent_manifest_injections
GROUP BY agent_name
ORDER BY total_executions DESC
LIMIT 20;
