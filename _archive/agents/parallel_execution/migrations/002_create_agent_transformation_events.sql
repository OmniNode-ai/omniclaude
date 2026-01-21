-- Migration: 002_create_agent_transformation_events
-- Description: Create agent_transformation_events table for identity assumption tracking
-- Author: agent-workflow-coordinator
-- Created: 2025-10-09
-- ONEX Compliance: Effect node pattern for event persistence

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- Create agent_transformation_events table
CREATE TABLE IF NOT EXISTS agent_transformation_events (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Event identification
    event_type VARCHAR(100) NOT NULL, -- transformation_start, transformation_complete, transformation_failed
    correlation_id UUID NOT NULL, -- Links related events in a workflow
    session_id UUID, -- Links events in a conversation session

    -- Agent identity transformation
    source_agent VARCHAR(255), -- Original agent (coordinator, etc.)
    target_agent VARCHAR(255) NOT NULL, -- Agent being assumed
    transformation_reason TEXT, -- Why this transformation occurred

    -- Context preservation
    context_snapshot JSONB, -- Full context at transformation time
    context_keys TEXT[], -- Keys of context items passed to target agent
    context_size_bytes INTEGER, -- Size of context for performance tracking

    -- Execution metadata
    user_request TEXT, -- Original user request triggering transformation
    routing_confidence DECIMAL(5,4), -- Confidence score from router (0-1)
    routing_strategy VARCHAR(100), -- explicit, fuzzy_match, capability_match, etc.

    -- Performance metrics
    transformation_duration_ms INTEGER, -- Time to complete transformation
    initialization_duration_ms INTEGER, -- Time to initialize target agent
    total_execution_duration_ms INTEGER, -- Total execution time of target agent

    -- Outcome tracking
    success BOOLEAN, -- Whether transformation and execution succeeded
    error_message TEXT, -- Error details if failed
    error_type VARCHAR(100), -- Error classification
    quality_score DECIMAL(5,4), -- Output quality score (0-1)

    -- Related records
    agent_definition_id UUID REFERENCES agent_definitions(id), -- Link to agent definition used
    parent_event_id UUID REFERENCES agent_transformation_events(id), -- For nested transformations

    -- Timestamps
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT agent_transformation_events_confidence_check CHECK (routing_confidence >= 0 AND routing_confidence <= 1),
    CONSTRAINT agent_transformation_events_quality_check CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1))
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_correlation
    ON agent_transformation_events(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_session
    ON agent_transformation_events(session_id);

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_target
    ON agent_transformation_events(target_agent);

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_source
    ON agent_transformation_events(source_agent);

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_type
    ON agent_transformation_events(event_type);

-- Time-series index for chronological queries
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_started_at
    ON agent_transformation_events(started_at DESC);

-- Composite index for filtering by success and time
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_success_time
    ON agent_transformation_events(success, started_at DESC)
    WHERE success IS NOT NULL;

-- Performance analysis index
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_performance
    ON agent_transformation_events(target_agent, total_execution_duration_ms, quality_score);

-- JSONB index for context queries
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_context
    ON agent_transformation_events USING GIN(context_snapshot);

-- Parent-child relationship index
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_parent
    ON agent_transformation_events(parent_event_id)
    WHERE parent_event_id IS NOT NULL;

-- Agent definition relationship index
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_definition
    ON agent_transformation_events(agent_definition_id)
    WHERE agent_definition_id IS NOT NULL;

-- Add comments for documentation
COMMENT ON TABLE agent_transformation_events IS 'Tracks agent identity transformations and execution for observability and learning';
COMMENT ON COLUMN agent_transformation_events.correlation_id IS 'Links all events in a workflow for distributed tracing';
COMMENT ON COLUMN agent_transformation_events.context_snapshot IS 'Full context preserved during transformation for debugging and replay';
COMMENT ON COLUMN agent_transformation_events.routing_confidence IS 'Confidence score from enhanced router for transformation quality analysis';
COMMENT ON COLUMN agent_transformation_events.quality_score IS 'Output quality score for learning and optimization';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP TABLE IF EXISTS agent_transformation_events CASCADE;
