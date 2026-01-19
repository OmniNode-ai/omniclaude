-- Migration 011: Add execution_succeeded column to agent_routing_decisions
-- Replaces the poorly-named "actual_success" with clear "execution_succeeded"
--
-- Purpose: Track whether the routed agent successfully completed task execution
-- Type: boolean (true = success, false = failure, null = outcome not yet determined)
--
-- This migration:
-- 1. Adds new execution_succeeded column
-- 2. Copies existing data from actual_success
-- 3. Creates indexes for the new column
-- 4. Keeps actual_success temporarily for backward compatibility

BEGIN;

-- Add new column
ALTER TABLE agent_routing_decisions
ADD COLUMN IF NOT EXISTS execution_succeeded BOOLEAN DEFAULT NULL;

-- Copy existing data
UPDATE agent_routing_decisions
SET execution_succeeded = actual_success
WHERE actual_success IS NOT NULL;

-- Create indexes matching the pattern from actual_success
CREATE INDEX IF NOT EXISTS idx_routing_decisions_execution_succeeded
ON agent_routing_decisions(execution_succeeded)
WHERE execution_succeeded IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_routing_decisions_agent_execution_succeeded
ON agent_routing_decisions(selected_agent, execution_succeeded, created_at DESC)
WHERE execution_succeeded IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN agent_routing_decisions.execution_succeeded IS
'Boolean flag indicating whether the selected agent successfully completed the task execution. NULL = outcome not yet determined, TRUE = success, FALSE = failure.';

COMMIT;
