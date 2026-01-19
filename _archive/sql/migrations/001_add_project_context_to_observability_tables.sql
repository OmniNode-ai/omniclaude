-- ======================================================================
-- Multi-Repository Observability: Project Context Schema Alterations
-- ======================================================================
-- Date: 2025-10-24
-- Purpose: Add project awareness to all agent observability tables
-- NOTE: Using claude_session_id instead of session_id to avoid conflicts
--       with existing session_id UUID columns in some tables
-- ======================================================================

BEGIN;

-- ======================================================================
-- 1. agent_routing_decisions
-- ======================================================================

ALTER TABLE agent_routing_decisions
ADD COLUMN IF NOT EXISTS project_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS project_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS claude_session_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_routing_project
ON agent_routing_decisions(project_name, created_at);

COMMENT ON COLUMN agent_routing_decisions.project_path IS 'Absolute path to project directory (e.g., /Volumes/PRO-G40/Code/omniclaude)';
COMMENT ON COLUMN agent_routing_decisions.project_name IS 'Project name extracted from path (e.g., omniclaude)';
COMMENT ON COLUMN agent_routing_decisions.claude_session_id IS 'Claude Code session ID for correlation across terminals';

-- ======================================================================
-- 2. agent_execution_logs
-- ======================================================================
-- NOTE: This table already has session_id (UUID), so we add claude_session_id

ALTER TABLE agent_execution_logs
ADD COLUMN IF NOT EXISTS project_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS project_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS claude_session_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS terminal_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_execution_project
ON agent_execution_logs(project_name, started_at);

COMMENT ON COLUMN agent_execution_logs.project_path IS 'Absolute path to project directory';
COMMENT ON COLUMN agent_execution_logs.project_name IS 'Project name extracted from path';
COMMENT ON COLUMN agent_execution_logs.claude_session_id IS 'Claude Code session ID (different from internal session_id UUID)';
COMMENT ON COLUMN agent_execution_logs.terminal_id IS 'Terminal identifier (project_name-claude_session_id)';

-- ======================================================================
-- 3. agent_actions
-- ======================================================================

ALTER TABLE agent_actions
ADD COLUMN IF NOT EXISTS project_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS project_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS working_directory VARCHAR(500);

CREATE INDEX IF NOT EXISTS idx_actions_project
ON agent_actions(project_name, created_at);

COMMENT ON COLUMN agent_actions.project_path IS 'Absolute path to project directory';
COMMENT ON COLUMN agent_actions.project_name IS 'Project name extracted from path';
COMMENT ON COLUMN agent_actions.working_directory IS 'Current working directory during action';

-- ======================================================================
-- 4. agent_transformation_events
-- ======================================================================

ALTER TABLE agent_transformation_events
ADD COLUMN IF NOT EXISTS project_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS project_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS claude_session_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_transformation_project
ON agent_transformation_events(project_name, created_at);

COMMENT ON COLUMN agent_transformation_events.project_path IS 'Absolute path to project directory';
COMMENT ON COLUMN agent_transformation_events.project_name IS 'Project name extracted from path';
COMMENT ON COLUMN agent_transformation_events.claude_session_id IS 'Claude Code session ID';

-- ======================================================================
-- 5. agent_detection_failures
-- ======================================================================
-- NOTE: This table already has session_id (VARCHAR), so we add claude_session_id

ALTER TABLE agent_detection_failures
ADD COLUMN IF NOT EXISTS project_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS project_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS claude_session_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_detection_failures_project
ON agent_detection_failures(project_name, created_at);

COMMENT ON COLUMN agent_detection_failures.project_path IS 'Absolute path to project directory';
COMMENT ON COLUMN agent_detection_failures.project_name IS 'Project name extracted from path';
COMMENT ON COLUMN agent_detection_failures.claude_session_id IS 'Claude Code session ID (for multi-terminal tracking)';

-- ======================================================================
-- Helper Function: Extract Project Name from Path
-- ======================================================================

CREATE OR REPLACE FUNCTION extract_project_name(full_path VARCHAR)
RETURNS VARCHAR AS $$
BEGIN
    -- Extract last directory name from path
    -- /Volumes/PRO-G40/Code/omniclaude → omniclaude
    -- /Volumes/PRO-G40/Code/omniclaude/ → omniclaude (handles trailing slash)
    -- First remove trailing slash, then extract last directory name
    RETURN (SELECT regexp_replace(regexp_replace(full_path, '/$', ''), '.*/', ''));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION extract_project_name(VARCHAR) IS 'Extract project name from full path (returns last directory name)';

-- ======================================================================
-- Create Real-Time Multi-Terminal View
-- ======================================================================
-- NOTE: action_type represents the TYPE of logged action, not execution status:
--   - 'tool_call': Agent called a tool (Read, Write, Bash, etc.)
--   - 'decision': Agent made a decision (routing, planning, etc.)
--   - 'error': An error was logged during execution
--   - 'success': A success event was logged
-- The execution_status field from agent_execution_logs indicates overall execution state.
-- ======================================================================

CREATE OR REPLACE VIEW agent_activity_realtime AS
SELECT
    e.project_name,
    e.claude_session_id,
    e.agent_name,
    e.status as execution_status,
    e.started_at,
    COUNT(a.id) as total_actions,
    COUNT(a.id) FILTER (WHERE a.action_type = 'tool_call') as tool_call_count,
    COUNT(a.id) FILTER (WHERE a.action_type = 'decision') as decision_count,
    COUNT(a.id) FILTER (WHERE a.action_type = 'success') as success_event_count,
    COUNT(a.id) FILTER (WHERE a.action_type = 'error') as error_event_count,
    MAX(a.created_at) as last_action_at,
    ARRAY_AGG(DISTINCT a.action_type ORDER BY a.action_type) as action_types_used,
    e.execution_id
FROM agent_execution_logs e
LEFT JOIN agent_actions a ON e.correlation_id = a.correlation_id
WHERE e.started_at > NOW() - INTERVAL '1 hour'
GROUP BY e.project_name, e.claude_session_id, e.agent_name, e.status, e.started_at, e.execution_id
ORDER BY e.started_at DESC;

COMMENT ON VIEW agent_activity_realtime IS 'Real-time agent activity monitoring (last 1 hour). Column names reflect action_type values: tool_call_count, decision_count, success_event_count, error_event_count. Use execution_status for overall execution state.';

COMMIT;

-- ======================================================================
-- Summary
-- ======================================================================
-- Changes applied:
-- 1. Added project_path, project_name, claude_session_id to all tables
-- 2. Added terminal_id to agent_execution_logs
-- 3. Added working_directory to agent_actions
-- 4. Created indexes on (project_name, timestamp) for all tables
-- 5. Created helper function extract_project_name()
-- 6. Created real-time monitoring view agent_activity_realtime
--
-- NOTE: Used claude_session_id instead of session_id to avoid conflicts
--       with existing internal session_id columns
-- ======================================================================
