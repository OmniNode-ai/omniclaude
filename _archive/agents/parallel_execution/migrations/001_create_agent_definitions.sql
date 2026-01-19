-- Migration: 001_create_agent_definitions
-- Description: Create agent_definitions table for storing agent YAML configurations
-- Author: agent-workflow-coordinator
-- Created: 2025-10-09
-- ONEX Compliance: Effect node pattern for persistence

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- Create agent_definitions table
CREATE TABLE IF NOT EXISTS agent_definitions (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Agent identification
    agent_name VARCHAR(255) NOT NULL,
    agent_version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    agent_type VARCHAR(100) NOT NULL, -- coordinator, specialist, transformer

    -- Configuration storage (JSONB for flexible YAML->JSON storage)
    yaml_config JSONB NOT NULL,
    parsed_metadata JSONB, -- Extracted metadata for quick queries

    -- Agent capabilities
    capabilities TEXT[] DEFAULT '{}', -- Array of capability tags
    domain VARCHAR(100), -- general, api_development, debugging, etc.

    -- Trigger matching for router
    triggers TEXT[] DEFAULT '{}', -- Array of trigger phrases
    trigger_patterns TEXT[] DEFAULT '{}', -- Array of regex patterns

    -- Performance characteristics
    avg_execution_time_ms INTEGER,
    success_rate DECIMAL(5,4), -- 0.0000 to 1.0000
    quality_score DECIMAL(5,4), -- 0.0000 to 1.0000

    -- Status and lifecycle
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, deprecated, testing

    -- Registry information
    registry_path TEXT, -- Path to YAML file in registry
    definition_hash VARCHAR(64), -- SHA-256 hash of YAML content

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_loaded_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT agent_definitions_name_version_unique UNIQUE (agent_name, agent_version),
    CONSTRAINT agent_definitions_success_rate_check CHECK (success_rate >= 0 AND success_rate <= 1),
    CONSTRAINT agent_definitions_quality_score_check CHECK (quality_score >= 0 AND quality_score <= 1)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_definitions_name
    ON agent_definitions(agent_name);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_type
    ON agent_definitions(agent_type);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_domain
    ON agent_definitions(domain);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_active
    ON agent_definitions(is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_agent_definitions_capabilities
    ON agent_definitions USING GIN(capabilities);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_triggers
    ON agent_definitions USING GIN(triggers);

-- JSONB indexes for metadata queries
CREATE INDEX IF NOT EXISTS idx_agent_definitions_yaml_config
    ON agent_definitions USING GIN(yaml_config);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_metadata
    ON agent_definitions USING GIN(parsed_metadata);

-- Performance index for sorting by quality/success
CREATE INDEX IF NOT EXISTS idx_agent_definitions_performance
    ON agent_definitions(success_rate DESC, quality_score DESC, avg_execution_time_ms ASC);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_agent_definitions_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_agent_definitions_updated_at
    BEFORE UPDATE ON agent_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_definitions_timestamp();

-- Add comments for documentation
COMMENT ON TABLE agent_definitions IS 'Storage for agent YAML configurations and metadata for dynamic agent loading';
COMMENT ON COLUMN agent_definitions.yaml_config IS 'Full YAML configuration stored as JSONB for flexible querying';
COMMENT ON COLUMN agent_definitions.parsed_metadata IS 'Extracted metadata for fast queries without parsing full YAML';
COMMENT ON COLUMN agent_definitions.capabilities IS 'Array of capability tags for capability-based routing';
COMMENT ON COLUMN agent_definitions.triggers IS 'Array of trigger phrases for fuzzy matching in router';
COMMENT ON COLUMN agent_definitions.definition_hash IS 'SHA-256 hash of YAML content for change detection';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP TRIGGER IF EXISTS trigger_agent_definitions_updated_at ON agent_definitions;
-- DROP FUNCTION IF EXISTS update_agent_definitions_timestamp();
-- DROP TABLE IF EXISTS agent_definitions CASCADE;
