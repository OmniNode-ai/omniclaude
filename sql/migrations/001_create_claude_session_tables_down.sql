-- Rollback: 001_create_claude_session_tables
-- Drops all claude_session_* tables
--
-- Idempotent: safe to run multiple times. CASCADE handles any dependent objects.
-- Order: child tables first, then parent, to respect FK constraints on databases
-- that don't support CASCADE.

BEGIN;

-- 1. Drop trigger conditionally: the ON clause fails if the table is already gone,
--    so guard with a DO block that checks for the table first.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'claude_session_snapshots'
    ) THEN
        DROP TRIGGER IF EXISTS trg_session_snapshots_updated_at ON claude_session_snapshots;
    END IF;
END $$;

-- 2. Drop trigger function (standalone, no table dependency).
DROP FUNCTION IF EXISTS update_claude_session_snapshots_updated_at();

-- 3. Drop child tables first (FK → claude_session_snapshots).
DROP TABLE IF EXISTS claude_session_prompts CASCADE;
DROP TABLE IF EXISTS claude_session_tools CASCADE;

-- 4. Drop standalone tables.
DROP TABLE IF EXISTS claude_session_event_idempotency CASCADE;

-- 5. Drop parent table last.
DROP TABLE IF EXISTS claude_session_snapshots CASCADE;

COMMIT;
