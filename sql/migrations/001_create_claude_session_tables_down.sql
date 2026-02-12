-- Rollback: 001_create_claude_session_tables
-- Drops all claude_session_* tables

BEGIN;
DROP TRIGGER IF EXISTS trg_session_snapshots_updated_at ON claude_session_snapshots;
DROP FUNCTION IF EXISTS update_claude_session_snapshots_updated_at();
DROP TABLE IF EXISTS claude_session_prompts;
DROP TABLE IF EXISTS claude_session_tools;
DROP TABLE IF EXISTS claude_session_event_idempotency;
DROP TABLE IF EXISTS claude_session_snapshots;
COMMIT;
