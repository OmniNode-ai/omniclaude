-- Rollback Migration: Remove unique constraint from agent_actions table
-- Purpose: Rollback for migration 015 if needed
-- Created: 2025-11-23

-- Remove the unique constraint
ALTER TABLE agent_actions
DROP CONSTRAINT IF EXISTS unique_action_per_correlation_timestamp;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Rollback 015: Removed unique constraint from agent_actions table';
    RAISE NOTICE 'Constraint removed: unique_action_per_correlation_timestamp';
END $$;
