-- Migration 001: Create claude_session_* tables for omniclaude
-- Date: 2026-02-11
-- Purpose: Adopt session snapshot tables from omnibase_infra (DB-SPLIT-07, OMN-2058)
-- NOTE: No runtime consumer yet. See follow-up ticket for Python integration.
--
-- Tables:
--   claude_session_snapshots  - Parent aggregate with session lifecycle
--   claude_session_prompts    - Child table for prompt records
--   claude_session_tools      - Child table for tool execution records
--   claude_session_event_idempotency - Deduplication tracking (24h TTL)

BEGIN;

-- ============================================================================
-- claude_session_snapshots - main session aggregate
-- ============================================================================
CREATE TABLE IF NOT EXISTS claude_session_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL UNIQUE,
    correlation_id UUID,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    working_directory TEXT NOT NULL,
    git_branch TEXT,
    hook_source TEXT NOT NULL,
    end_reason TEXT,
    prompt_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    tools_used_count INTEGER NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    last_event_at TIMESTAMPTZ NOT NULL,
    schema_version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_snapshots_session_id ON claude_session_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_status ON claude_session_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_last_event ON claude_session_snapshots(last_event_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_snapshots_working_dir ON claude_session_snapshots(working_directory);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION update_claude_session_snapshots_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_session_snapshots_updated_at ON claude_session_snapshots;
CREATE TRIGGER trg_session_snapshots_updated_at
    BEFORE UPDATE ON claude_session_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION update_claude_session_snapshots_updated_at();

COMMENT ON TABLE claude_session_snapshots IS 'Session snapshot aggregates for Claude Code sessions. Adopted from omnibase_infra in DB-SPLIT-07 (OMN-2058).';

-- ============================================================================
-- claude_session_prompts - child table for prompt records
-- ============================================================================
CREATE TABLE IF NOT EXISTS claude_session_prompts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
    prompt_id UUID NOT NULL,
    emitted_at TIMESTAMPTZ,
    prompt_preview TEXT,
    prompt_length INTEGER NOT NULL,
    detected_intent TEXT,
    causation_id UUID,
    UNIQUE (snapshot_id, prompt_id)
);

CREATE INDEX IF NOT EXISTS idx_session_prompts_snapshot ON claude_session_prompts(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_session_prompts_emitted ON claude_session_prompts(emitted_at ASC);

COMMENT ON TABLE claude_session_prompts IS 'Prompt records within a session snapshot. Child of claude_session_snapshots.';

-- ============================================================================
-- claude_session_tools - child table for tool execution records
-- ============================================================================
CREATE TABLE IF NOT EXISTS claude_session_tools (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
    tool_execution_id UUID NOT NULL,
    emitted_at TIMESTAMPTZ,
    tool_name TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER NOT NULL,
    summary TEXT,
    causation_id UUID,
    UNIQUE (snapshot_id, tool_execution_id)
);

CREATE INDEX IF NOT EXISTS idx_session_tools_snapshot ON claude_session_tools(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_session_tools_emitted ON claude_session_tools(emitted_at ASC);
CREATE INDEX IF NOT EXISTS idx_session_tools_tool_name ON claude_session_tools(tool_name);

COMMENT ON TABLE claude_session_tools IS 'Tool execution records within a session snapshot. Child of claude_session_snapshots.';

-- ============================================================================
-- claude_session_event_idempotency - deduplication tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS claude_session_event_idempotency (
    message_id UUID PRIMARY KEY,
    domain TEXT NOT NULL DEFAULT 'claude_session',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_session_idempotency_expires ON claude_session_event_idempotency(expires_at);
CREATE INDEX IF NOT EXISTS idx_session_idempotency_domain ON claude_session_event_idempotency(domain);

COMMENT ON TABLE claude_session_event_idempotency IS 'Idempotency tracking for session events. Records expire after 24 hours.';

-- ============================================================================
-- Verification
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'claude_session_snapshots' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'claude_session_snapshots table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'claude_session_prompts' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'claude_session_prompts table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'claude_session_tools' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'claude_session_tools table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'claude_session_event_idempotency' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'claude_session_event_idempotency table was not created';
    END IF;
    RAISE NOTICE 'All claude_session_* tables created successfully (OMN-2058)';
END $$;

COMMIT;
