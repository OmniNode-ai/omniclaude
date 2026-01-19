-- Migration: Add unique constraint to agent_actions table
-- Purpose: Prevent duplicate insertions in concurrent scenarios
-- Related: PR #33 CRITICAL fix - kafka_agent_action_consumer.py line 176
-- Created: 2025-11-23

-- Add unique constraint on (correlation_id, action_name, created_at)
-- This prevents the same action from being logged multiple times due to race conditions
-- in concurrent Kafka consumer scenarios

-- First, remove any existing duplicates (if any exist)
-- Keep the oldest record for each duplicate group
WITH duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY correlation_id, action_name, created_at
            ORDER BY id
        ) as rn
    FROM agent_actions
)
DELETE FROM agent_actions
WHERE id IN (
    SELECT id FROM duplicates WHERE rn > 1
);

-- Now add the unique constraint
-- This constraint ensures that the same action with the same correlation_id,
-- action_name, and timestamp cannot be inserted twice
ALTER TABLE agent_actions
ADD CONSTRAINT unique_action_per_correlation_timestamp
UNIQUE (correlation_id, action_name, created_at);

-- Add comment explaining the constraint
COMMENT ON CONSTRAINT unique_action_per_correlation_timestamp ON agent_actions IS
'Prevents duplicate action logging in concurrent Kafka consumer scenarios. Uses correlation_id + action_name + timestamp to identify unique actions.';

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Migration 015: Added unique constraint to agent_actions table';
    RAISE NOTICE 'Constraint: unique_action_per_correlation_timestamp (correlation_id, action_name, created_at)';
    RAISE NOTICE 'Duplicate records (if any) have been cleaned up';
END $$;
