-- Rollback Migration: 005_debug_state_management
-- Description: Rollback debug loop tables and restore original schema
-- Author: agent-workflow-coordinator
-- Created: 2025-10-11

BEGIN;

-- =============================================================================
-- STEP 1: Drop Views
-- =============================================================================

DROP VIEW IF EXISTS debug_error_recovery_patterns;
DROP VIEW IF EXISTS debug_workflow_context;
DROP VIEW IF EXISTS debug_llm_call_summary;

-- =============================================================================
-- STEP 2: Drop Functions
-- =============================================================================

DROP FUNCTION IF EXISTS get_workflow_debug_summary;
DROP FUNCTION IF EXISTS capture_state_snapshot;

-- =============================================================================
-- STEP 3: Remove Foreign Keys from Existing Tables
-- =============================================================================

-- Remove foreign keys from agent_transformation_events
ALTER TABLE agent_transformation_events
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_snapshot,
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_error,
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_success;

-- =============================================================================
-- STEP 4: Remove Columns from Existing Tables
-- =============================================================================

-- Remove columns from agent_transformation_events
ALTER TABLE agent_transformation_events
  DROP COLUMN IF EXISTS state_snapshot_id,
  DROP COLUMN IF EXISTS error_event_id,
  DROP COLUMN IF EXISTS success_event_id;

-- =============================================================================
-- STEP 5: Drop New Tables (in reverse dependency order)
-- =============================================================================

-- Drop workflow_steps first (has foreign keys to all other tables)
DROP TABLE IF EXISTS debug_workflow_steps CASCADE;

-- Drop correlation table (has foreign keys to error/success events)
DROP TABLE IF EXISTS debug_error_success_correlation CASCADE;

-- Drop success events (has foreign key to state_snapshots)
DROP TABLE IF EXISTS debug_success_events CASCADE;

-- Drop error events (has foreign key to state_snapshots)
DROP TABLE IF EXISTS debug_error_events CASCADE;

-- Drop state snapshots last (referenced by all other tables)
DROP TABLE IF EXISTS debug_state_snapshots CASCADE;

-- =============================================================================
-- STEP 6: Remove Migration Record
-- =============================================================================

DELETE FROM schema_migrations WHERE version = 5;

COMMIT;

-- =============================================================================
-- Verification Queries
-- =============================================================================

-- Verify tables were dropped
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'debug_%';

-- Verify views were dropped
-- SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname LIKE 'debug_%';

-- Verify functions were dropped
-- SELECT proname FROM pg_proc WHERE proname LIKE '%debug%' OR proname LIKE 'capture_state_snapshot' OR proname LIKE 'get_workflow_debug_summary';

-- Verify agent_transformation_events columns were removed
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_transformation_events';
