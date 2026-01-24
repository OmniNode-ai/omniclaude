-- Migration: 016_create_session_snapshots
-- Description: Create tables for Claude Code session context storage (OMN-1401)
-- Created: 2026-01-24

-- Session snapshots table (main aggregate)
CREATE TABLE IF NOT EXISTS claude_session_snapshots (
    -- Identity
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) NOT NULL,  -- Claude Code uses string session IDs
    correlation_id UUID,

    -- Session lifecycle
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- orphan, active, ended, timed_out
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_seconds FLOAT,

    -- Context
    working_directory TEXT NOT NULL,
    git_branch VARCHAR(255),
    hook_source VARCHAR(50) NOT NULL,  -- startup, resume, compact, synthetic
    end_reason VARCHAR(50),  -- user_exit, timeout, error, compact, unknown

    -- Metrics
    prompt_count INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    tools_used_count INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,

    -- Aggregation metadata
    last_event_at TIMESTAMPTZ NOT NULL,
    schema_version VARCHAR(20) DEFAULT '1.0.0',

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_status CHECK (status IN ('orphan', 'active', 'ended', 'timed_out')),
    CONSTRAINT valid_hook_source CHECK (hook_source IN ('startup', 'resume', 'compact', 'synthetic'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_session_snapshots_session_id ON claude_session_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_status ON claude_session_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_working_directory ON claude_session_snapshots(working_directory);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_last_event_at ON claude_session_snapshots(last_event_at);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_created_at ON claude_session_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_git_branch ON claude_session_snapshots(git_branch);

-- Unique constraint: one snapshot per session_id (latest wins on conflict)
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_snapshots_session_id_unique ON claude_session_snapshots(session_id);

-- Prompt records table (child of session)
CREATE TABLE IF NOT EXISTS claude_session_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
    prompt_id UUID NOT NULL,
    emitted_at TIMESTAMPTZ NOT NULL,
    prompt_preview VARCHAR(100),  -- Truncated, sanitized
    prompt_length INTEGER NOT NULL,
    detected_intent VARCHAR(100),
    causation_id UUID,

    -- Deduplication
    CONSTRAINT unique_prompt_per_session UNIQUE (snapshot_id, prompt_id)
);

CREATE INDEX IF NOT EXISTS idx_session_prompts_snapshot_id ON claude_session_prompts(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_session_prompts_emitted_at ON claude_session_prompts(emitted_at);

-- Tool execution records table (child of session)
CREATE TABLE IF NOT EXISTS claude_session_tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
    tool_execution_id UUID NOT NULL,
    emitted_at TIMESTAMPTZ NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER,  -- Nullable: tool may not have duration yet
    summary VARCHAR(500),  -- Truncated
    causation_id UUID,

    -- Deduplication
    CONSTRAINT unique_tool_per_session UNIQUE (snapshot_id, tool_execution_id)
);

CREATE INDEX IF NOT EXISTS idx_session_tools_snapshot_id ON claude_session_tools(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_session_tools_emitted_at ON claude_session_tools(emitted_at);
CREATE INDEX IF NOT EXISTS idx_session_tools_tool_name ON claude_session_tools(tool_name);

-- Idempotency tracking for event processing
CREATE TABLE IF NOT EXISTS claude_session_event_idempotency (
    message_id UUID PRIMARY KEY,
    domain VARCHAR(100) NOT NULL DEFAULT 'claude_session',
    processed_at TIMESTAMPTZ DEFAULT NOW(),

    -- TTL for cleanup
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at ON claude_session_event_idempotency(expires_at);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_session_snapshots_updated_at
    BEFORE UPDATE ON claude_session_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comment on tables
COMMENT ON TABLE claude_session_snapshots IS 'Claude Code session snapshots for OmniMemory (OMN-1401)';
COMMENT ON TABLE claude_session_prompts IS 'Prompt records within Claude Code sessions';
COMMENT ON TABLE claude_session_tools IS 'Tool execution records within Claude Code sessions';
COMMENT ON TABLE claude_session_event_idempotency IS 'Idempotency tracking for event deduplication';
