-- Rollback Migration 011: Remove execution_succeeded column
--
-- This rollback:
-- 1. Drops indexes created for execution_succeeded
-- 2. Removes the execution_succeeded column
-- 3. Restores the system to use actual_success only

BEGIN;

-- Drop indexes
DROP INDEX IF EXISTS idx_routing_decisions_execution_succeeded;
DROP INDEX IF EXISTS idx_routing_decisions_agent_execution_succeeded;

-- Drop column
ALTER TABLE agent_routing_decisions
DROP COLUMN IF EXISTS execution_succeeded;

COMMIT;
