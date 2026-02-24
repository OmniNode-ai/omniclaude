-- Reference rollback: 002_create_quirk_tables
-- Location: docs/db/ (NOT sql/migrations/) — see 002_create_quirk_tables.sql header.
-- Rollback: 002_create_quirk_tables
-- Drops quirk_findings and quirk_signals tables
--
-- Idempotent: safe to run multiple times. CASCADE handles any dependent objects.
-- Order: child table first (quirk_findings), then parent (quirk_signals), to respect
-- the FK constraint even on databases that don't support CASCADE drops.

BEGIN;

-- 1. Drop child table first (FK → quirk_signals).
DROP TABLE IF EXISTS quirk_findings CASCADE;

-- 2. Drop parent table.
DROP TABLE IF EXISTS quirk_signals CASCADE;

-- 3. Remove migration tracking record so init-db.sh will re-apply on next run.
DELETE FROM schema_migrations WHERE filename = '002_create_quirk_tables.sql';

COMMIT;
