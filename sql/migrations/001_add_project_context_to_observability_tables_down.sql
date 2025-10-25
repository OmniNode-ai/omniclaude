-- ======================================================================
-- Rollback Migration 001: Remove Project Context from Observability Tables
-- ======================================================================
-- Date: 2025-10-24
-- Purpose: Safely rollback all changes from migration 001
-- Idempotent: Can be run multiple times safely
-- ======================================================================

BEGIN;

-- ======================================================================
-- Drop Indexes First (Dependencies)
-- ======================================================================

DROP INDEX IF EXISTS idx_routing_project;
DROP INDEX IF EXISTS idx_execution_project;
DROP INDEX IF EXISTS idx_actions_project;
DROP INDEX IF EXISTS idx_transformation_project;
DROP INDEX IF EXISTS idx_detection_failures_project;

-- ======================================================================
-- Drop View (Depends on Columns)
-- ======================================================================

DROP VIEW IF EXISTS agent_activity_realtime;

-- ======================================================================
-- Drop Function
-- ======================================================================

DROP FUNCTION IF EXISTS extract_project_name(VARCHAR);

-- ======================================================================
-- Remove Columns from Tables
-- ======================================================================

-- 1. agent_routing_decisions
ALTER TABLE agent_routing_decisions
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id;

-- 2. agent_execution_logs
ALTER TABLE agent_execution_logs
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id,
    DROP COLUMN IF EXISTS terminal_id;

-- 3. agent_actions
ALTER TABLE agent_actions
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS working_directory;

-- 4. agent_transformation_events
ALTER TABLE agent_transformation_events
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id;

-- 5. agent_detection_failures
ALTER TABLE agent_detection_failures
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id;

COMMIT;

-- ======================================================================
-- Rollback Summary
-- ======================================================================
-- Changes rolled back:
-- 1. Dropped 5 project-related indexes
-- 2. Dropped agent_activity_realtime view
-- 3. Dropped extract_project_name() helper function
-- 4. Removed project_path, project_name, claude_session_id from all tables
-- 5. Removed terminal_id from agent_execution_logs
-- 6. Removed working_directory from agent_actions
--
-- Status: Database schema restored to pre-migration state
-- ======================================================================
