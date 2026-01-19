-- Migration: Create agent_actions table for comprehensive debug logging
-- Purpose: Track every action an agent takes in debug mode for complete execution traces
-- Related Skills: /log-agent-action
-- Created: 2025-10-20

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create agent_actions table
CREATE TABLE IF NOT EXISTS agent_actions (
    -- Identity
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id UUID NOT NULL,

    -- Agent Information
    agent_name TEXT NOT NULL,

    -- Action Classification
    action_type TEXT NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
    action_name TEXT NOT NULL,

    -- Action Details
    action_details JSONB DEFAULT '{}'::jsonb,

    -- Debug Context
    debug_mode BOOLEAN NOT NULL DEFAULT true,
    duration_ms INTEGER,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_actions_correlation_id
    ON agent_actions(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_actions_agent_name
    ON agent_actions(agent_name);

CREATE INDEX IF NOT EXISTS idx_agent_actions_action_type
    ON agent_actions(action_type);

CREATE INDEX IF NOT EXISTS idx_agent_actions_created_at
    ON agent_actions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_actions_debug_mode
    ON agent_actions(debug_mode) WHERE debug_mode = true;

-- Create composite index for common trace queries
CREATE INDEX IF NOT EXISTS idx_agent_actions_trace
    ON agent_actions(correlation_id, created_at DESC);

-- Add helpful comments
COMMENT ON TABLE agent_actions IS 'Comprehensive debug logging of every agent action (tool calls, decisions, errors)';
COMMENT ON COLUMN agent_actions.correlation_id IS 'Links related actions across agent execution';
COMMENT ON COLUMN agent_actions.action_type IS 'Type: tool_call (Read/Write/etc), decision (routing), error, success';
COMMENT ON COLUMN agent_actions.action_name IS 'Specific action: Read, Write, select_agent, import_error, etc';
COMMENT ON COLUMN agent_actions.action_details IS 'Full details of action (file paths, parameters, results, etc)';
COMMENT ON COLUMN agent_actions.debug_mode IS 'Whether this was logged in debug mode (for cleanup)';
COMMENT ON COLUMN agent_actions.duration_ms IS 'How long the action took in milliseconds';

-- Create view for recent debug traces
CREATE OR REPLACE VIEW recent_debug_traces AS
SELECT
    correlation_id,
    agent_name,
    COUNT(*) as action_count,
    MIN(created_at) as trace_started,
    MAX(created_at) as trace_ended,
    EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at))) * 1000 as total_duration_ms,
    COUNT(*) FILTER (WHERE action_type = 'error') as error_count,
    COUNT(*) FILTER (WHERE action_type = 'success') as success_count,
    jsonb_agg(
        jsonb_build_object(
            'action_type', action_type,
            'action_name', action_name,
            'created_at', created_at
        ) ORDER BY created_at
    ) as actions_timeline
FROM agent_actions
WHERE debug_mode = true
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY correlation_id, agent_name
ORDER BY trace_started DESC;

COMMENT ON VIEW recent_debug_traces IS 'Summary of debug traces from last 24 hours with action timeline';

-- Create function for automatic cleanup of old debug logs (30+ days)
CREATE OR REPLACE FUNCTION cleanup_old_debug_logs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM agent_actions
    WHERE debug_mode = true
      AND created_at < NOW() - INTERVAL '30 days';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_debug_logs() IS 'Delete debug logs older than 30 days (call via cron)';

-- Grant permissions (adjust as needed for your setup)
-- GRANT SELECT, INSERT ON agent_actions TO your_app_user;
-- GRANT SELECT ON recent_debug_traces TO your_app_user;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Migration 005: agent_actions table created successfully';
    RAISE NOTICE 'Indexes created for optimal query performance';
    RAISE NOTICE 'View created: recent_debug_traces';
    RAISE NOTICE 'Function created: cleanup_old_debug_logs()';
END $$;
