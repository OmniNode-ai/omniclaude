-- Rollback: 016_create_session_snapshots
-- Description: Drop tables for Claude Code session context storage (OMN-1401)
-- Created: 2026-01-24

DROP TRIGGER IF EXISTS update_session_snapshots_updated_at ON claude_session_snapshots;
DROP FUNCTION IF EXISTS update_claude_session_snapshots_updated_at();
DROP TABLE IF EXISTS claude_session_event_idempotency;
DROP TABLE IF EXISTS claude_session_tools;
DROP TABLE IF EXISTS claude_session_prompts;
DROP TABLE IF EXISTS claude_session_snapshots;
