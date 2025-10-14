-- Shim: ensure schema_migrations has columns used by legacy migrations
BEGIN;
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT);
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS id TEXT;
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS filename TEXT;
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ DEFAULT NOW();
COMMIT;


