-- Test Database Initialization Script
-- Creates necessary tables for agent action logging tests

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Agent Actions Table (for action logging)
CREATE TABLE IF NOT EXISTS agent_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
    action_name VARCHAR(255) NOT NULL,
    action_details JSONB DEFAULT '{}',
    debug_mode BOOLEAN DEFAULT FALSE,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint for idempotency
    CONSTRAINT unique_action UNIQUE (correlation_id, action_name, created_at)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_actions_correlation_id ON agent_actions(correlation_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_agent_name ON agent_actions(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_actions_action_type ON agent_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_agent_actions_created_at ON agent_actions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_debug_mode ON agent_actions(debug_mode) WHERE debug_mode = TRUE;

-- Agent Routing Decisions Table (if needed for broader tests)
CREATE TABLE IF NOT EXISTS agent_routing_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_request TEXT NOT NULL,
    selected_agent VARCHAR(255) NOT NULL,
    confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    alternatives JSONB DEFAULT '[]',
    reasoning TEXT,
    routing_strategy VARCHAR(100),
    context JSONB DEFAULT '{}',
    routing_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent Transformation Events Table (if needed)
CREATE TABLE IF NOT EXISTS agent_transformation_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_agent VARCHAR(255) NOT NULL,
    target_agent VARCHAR(255) NOT NULL,
    transformation_reason TEXT,
    confidence_score NUMERIC(5,4),
    transformation_duration_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Router Performance Metrics Table (if needed)
CREATE TABLE IF NOT EXISTS router_performance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_text TEXT NOT NULL,
    routing_duration_ms INTEGER NOT NULL,
    cache_hit BOOLEAN DEFAULT FALSE,
    trigger_match_strategy VARCHAR(100),
    confidence_components JSONB DEFAULT '{}',
    candidates_evaluated INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Create test data cleanup function
CREATE OR REPLACE FUNCTION cleanup_test_data()
RETURNS VOID AS $$
BEGIN
    DELETE FROM agent_actions WHERE correlation_id LIKE 'test-%' OR correlation_id LIKE 'perf-test-%' OR correlation_id LIKE 'e2e-test-%';
    DELETE FROM agent_routing_decisions WHERE created_at < NOW() - INTERVAL '1 day';
    DELETE FROM agent_transformation_events WHERE created_at < NOW() - INTERVAL '1 day';
    DELETE FROM router_performance_metrics WHERE created_at < NOW() - INTERVAL '1 day';
END;
$$ LANGUAGE plpgsql;

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE '✅ Test database initialized successfully';
    RAISE NOTICE '   - agent_actions table created';
    RAISE NOTICE '   - Indexes created';
    RAISE NOTICE '   - Permissions granted';
END $$;
