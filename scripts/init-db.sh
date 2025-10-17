#!/bin/bash
# PostgreSQL Database Initialization Script for OmniClaude
# Runs automatically when the database container starts for the first time

set -e

echo "Initializing OmniClaude database..."

# Use POSTGRES_HOST environment variable if set, otherwise default to localhost
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"

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
        user_request TEXT NOT NULL,
        selected_agent TEXT NOT NULL,
        confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
        alternatives JSONB DEFAULT '[]'::jsonb,
        reasoning TEXT,
        routing_strategy TEXT,
        context JSONB DEFAULT '{}'::jsonb,
        routing_time_ms INTEGER,
        created_at TIMESTAMPTZ DEFAULT NOW()
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

    -- Create indexes for performance
    CREATE INDEX IF NOT EXISTS idx_routing_decisions_agent ON agent_routing_decisions(selected_agent);
    CREATE INDEX IF NOT EXISTS idx_routing_decisions_created ON agent_routing_decisions(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_routing_decisions_confidence ON agent_routing_decisions(confidence_score DESC);

    CREATE INDEX IF NOT EXISTS idx_transformation_events_target ON agent_transformation_events(target_agent);
    CREATE INDEX IF NOT EXISTS idx_transformation_events_created ON agent_transformation_events(created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_router_metrics_created ON router_performance_metrics(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_router_metrics_strategy ON router_performance_metrics(trigger_match_strategy);

    EOSQL

echo "Database initialization completed successfully!"
