-- Migration 002: Create hook_events table for HookEventLogger
-- Date: 2026-03-15
-- Purpose: Add hook telemetry table used by plugins/onex/hooks/lib/hook_event_logger.py
-- Ticket: OMN-5132

CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

-- ============================================================================
-- hook_events - telemetry from Claude Code hook scripts
-- ============================================================================
CREATE TABLE IF NOT EXISTS hook_events (
    id UUID PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(100) NOT NULL,
    resource_id VARCHAR(500),
    payload JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    processed BOOLEAN DEFAULT FALSE,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hook_events_source ON hook_events(source);
CREATE INDEX IF NOT EXISTS idx_hook_events_created_at ON hook_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hook_events_resource ON hook_events(resource, resource_id);
CREATE INDEX IF NOT EXISTS idx_hook_events_processed ON hook_events(processed) WHERE processed = FALSE;

COMMENT ON TABLE hook_events IS 'Hook event telemetry from Claude Code hooks (HookEventLogger). Created in OMN-5132.';

-- ============================================================================
-- Verification
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'hook_events' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'hook_events table was not created';
    END IF;
    RAISE NOTICE 'hook_events table created successfully (OMN-5132)';
END $$;

COMMIT;
