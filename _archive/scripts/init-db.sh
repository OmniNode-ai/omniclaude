#!/bin/bash
# PostgreSQL Database Initialization Script for OmniClaude
# Runs automatically when the database container starts for the first time

set -e

echo "Initializing OmniClaude database..."

# Use POSTGRES_HOST environment variable if set, otherwise default to localhost
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"

# Support both POSTGRES_DB and POSTGRES_DATABASE environment variable names
POSTGRES_DB="${POSTGRES_DB:-${POSTGRES_DATABASE:-postgres}}"

# Create extensions if needed
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --host="$POSTGRES_HOST" <<-EOSQL
    -- Enable UUID extension for generating UUIDs
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- Enable pg_trgm for fuzzy text search
    CREATE EXTENSION IF NOT EXISTS pg_trgm;

    -- Enable btree_gin for advanced indexing
    CREATE EXTENSION IF NOT EXISTS btree_gin;

    -- Create application schema
    CREATE SCHEMA IF NOT EXISTS omniclaude;

    -- Grant privileges
    GRANT ALL PRIVILEGES ON SCHEMA omniclaude TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA omniclaude TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA omniclaude TO $POSTGRES_USER;

    -- Set default privileges for future tables
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON TABLES TO $POSTGRES_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA omniclaude GRANT ALL ON SEQUENCES TO $POSTGRES_USER;

    -- Create agent_routing_decisions table for routing observability
    CREATE TABLE IF NOT EXISTS agent_routing_decisions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        correlation_id UUID NOT NULL,
        session_id UUID,
        user_request TEXT NOT NULL,
        user_request_hash VARCHAR(64),
        context_snapshot JSONB,
        selected_agent VARCHAR(255) NOT NULL,
        confidence_score NUMERIC(5,4) NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
        routing_strategy VARCHAR(100) NOT NULL,
        trigger_confidence NUMERIC(5,4),
        context_confidence NUMERIC(5,4),
        capability_confidence NUMERIC(5,4),
        historical_confidence NUMERIC(5,4),
        alternatives JSONB,
        alternatives_count INTEGER DEFAULT 0,
        reasoning TEXT,
        matched_triggers TEXT[],
        matched_capabilities TEXT[],
        routing_time_ms INTEGER NOT NULL,
        cache_hit BOOLEAN DEFAULT FALSE,
        cache_key VARCHAR(255),
        selection_validated BOOLEAN DEFAULT FALSE,
        actual_success BOOLEAN,
        actual_quality_score NUMERIC(5,4),
        prediction_error NUMERIC(5,4),
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        validated_at TIMESTAMPTZ,
        CONSTRAINT agent_routing_decisions_routing_time_check
            CHECK (routing_time_ms >= 0 AND routing_time_ms < 10000)
    );

    -- Create agent_manifest_injections table
    CREATE TABLE IF NOT EXISTS agent_manifest_injections (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        correlation_id UUID NOT NULL,
        session_id UUID,
        routing_decision_id UUID REFERENCES agent_routing_decisions(id),
        agent_name VARCHAR(255) NOT NULL,
        agent_version VARCHAR(50) DEFAULT '1.0.0',
        manifest_version VARCHAR(50) NOT NULL,
        generation_source VARCHAR(100) NOT NULL,
        is_fallback BOOLEAN DEFAULT FALSE,
        sections_included TEXT[] NOT NULL,
        sections_requested TEXT[],
        patterns_count INTEGER DEFAULT 0,
        infrastructure_services INTEGER DEFAULT 0,
        models_count INTEGER DEFAULT 0,
        database_schemas_count INTEGER DEFAULT 0,
        debug_intelligence_successes INTEGER DEFAULT 0,
        debug_intelligence_failures INTEGER DEFAULT 0,
        collections_queried JSONB,
        query_times JSONB NOT NULL,
        total_query_time_ms INTEGER NOT NULL,
        cache_hit BOOLEAN DEFAULT FALSE,
        cache_age_seconds INTEGER,
        full_manifest_snapshot JSONB NOT NULL,
        formatted_manifest_text TEXT,
        manifest_size_bytes INTEGER,
        intelligence_available BOOLEAN DEFAULT TRUE,
        query_failures JSONB,
        warnings TEXT[],
        agent_execution_success BOOLEAN,
        agent_execution_time_ms INTEGER,
        agent_quality_score NUMERIC(5,4),
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        executed_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        CONSTRAINT agent_manifest_injections_query_time_check
            CHECK (total_query_time_ms >= 0 AND total_query_time_ms < 30000),
        CONSTRAINT agent_manifest_injections_quality_check
            CHECK (agent_quality_score IS NULL OR (agent_quality_score >= 0 AND agent_quality_score <= 1))
    );

    -- Create agent_execution_logs table
    CREATE TABLE IF NOT EXISTS agent_execution_logs (
        execution_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        correlation_id UUID NOT NULL,
        session_id UUID NOT NULL,
        agent_name VARCHAR(255) NOT NULL,
        user_prompt TEXT,
        status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
        quality_score NUMERIC(5,4),
        error_message TEXT,
        error_type VARCHAR(255),
        duration_ms INTEGER,
        project_path TEXT,
        project_name VARCHAR(255),
        claude_session_id VARCHAR(255),
        terminal_id VARCHAR(255),
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    );

    -- Create agent_transformation_events table
    CREATE TABLE IF NOT EXISTS agent_transformation_events (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        source_agent TEXT NOT NULL,
        target_agent TEXT NOT NULL,
        transformation_reason TEXT,
        confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
        transformation_duration_ms INTEGER,
        success BOOLEAN DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- Create router_performance_metrics table
    CREATE TABLE IF NOT EXISTS router_performance_metrics (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        query_text TEXT NOT NULL,
        routing_duration_ms INTEGER,
        cache_hit BOOLEAN DEFAULT false,
        trigger_match_strategy TEXT,
        confidence_components JSONB DEFAULT '{}'::jsonb,
        candidates_evaluated INTEGER,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- Create agent_actions table for comprehensive debug logging
    CREATE TABLE IF NOT EXISTS agent_actions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        correlation_id UUID NOT NULL,
        agent_name TEXT NOT NULL,
        action_type TEXT NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
        action_name TEXT NOT NULL,
        action_details JSONB DEFAULT '{}'::jsonb,
        debug_mode BOOLEAN NOT NULL DEFAULT true,
        duration_ms INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Create indexes for performance
    -- Indexes for agent_routing_decisions
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_correlation ON agent_routing_decisions(correlation_id);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_session ON agent_routing_decisions(session_id) WHERE session_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_agent ON agent_routing_decisions(selected_agent, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_strategy ON agent_routing_decisions(routing_strategy, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_confidence ON agent_routing_decisions(confidence_score DESC, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_request_hash ON agent_routing_decisions(user_request_hash, context_snapshot) WHERE user_request_hash IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_time ON agent_routing_decisions(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_alternatives ON agent_routing_decisions USING GIN(alternatives);
    CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_validation ON agent_routing_decisions(selection_validated, actual_success) WHERE selection_validated = TRUE;

    -- Indexes for agent_manifest_injections
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_correlation ON agent_manifest_injections(correlation_id);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_session ON agent_manifest_injections(session_id) WHERE session_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_routing ON agent_manifest_injections(routing_decision_id) WHERE routing_decision_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_agent ON agent_manifest_injections(agent_name, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_time ON agent_manifest_injections(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_source ON agent_manifest_injections(generation_source, is_fallback);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_performance ON agent_manifest_injections(total_query_time_ms, patterns_count);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_success ON agent_manifest_injections(agent_execution_success, agent_quality_score) WHERE agent_execution_success IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_snapshot ON agent_manifest_injections USING GIN(full_manifest_snapshot);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_query_times ON agent_manifest_injections USING GIN(query_times);
    CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_failures ON agent_manifest_injections USING GIN(query_failures);

    -- Indexes for agent_execution_logs
    CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_correlation ON agent_execution_logs(correlation_id);
    CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_session ON agent_execution_logs(session_id);
    CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_agent ON agent_execution_logs(agent_name, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_status ON agent_execution_logs(status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_time ON agent_execution_logs(created_at DESC);

    -- Indexes for agent_transformation_events
    CREATE INDEX IF NOT EXISTS idx_transformation_events_target ON agent_transformation_events(target_agent);
    CREATE INDEX IF NOT EXISTS idx_transformation_events_created ON agent_transformation_events(created_at DESC);

    -- Indexes for router_performance_metrics
    CREATE INDEX IF NOT EXISTS idx_router_metrics_created ON router_performance_metrics(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_router_metrics_strategy ON router_performance_metrics(trigger_match_strategy);

    -- Indexes for agent_actions
    CREATE INDEX IF NOT EXISTS idx_agent_actions_correlation_id ON agent_actions(correlation_id);
    CREATE INDEX IF NOT EXISTS idx_agent_actions_agent_name ON agent_actions(agent_name);
    CREATE INDEX IF NOT EXISTS idx_agent_actions_action_type ON agent_actions(action_type);
    CREATE INDEX IF NOT EXISTS idx_agent_actions_created_at ON agent_actions(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_actions_debug_mode ON agent_actions(debug_mode) WHERE debug_mode = true;
    CREATE INDEX IF NOT EXISTS idx_agent_actions_trace ON agent_actions(correlation_id, created_at DESC);

EOSQL

echo "Database initialization completed successfully!"
