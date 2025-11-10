-- =====================================================================
-- Migration: 001_debug_loop_core_schema
-- Description: Debug Loop Intelligence Core - Database Schema
-- Created: 2025-11-09
-- Part: Phase 1 - Debug Intelligence Core
-- =====================================================================

-- This migration creates 5 tables for the Debug Loop Intelligence system:
-- 1. debug_transform_functions - STF registry with quality metrics
-- 2. model_price_catalog - LLM model pricing catalog
-- 3. debug_execution_attempts - Enhanced execution correlation tracking
-- 4. debug_error_success_mappings - Error→success pattern mappings
-- 5. debug_golden_states - Proven solution registry

-- =====================================================================
-- Helper Functions
-- =====================================================================

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- Table 1: debug_transform_functions (STF Registry)
-- =====================================================================

CREATE TABLE IF NOT EXISTS debug_transform_functions (
    stf_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identification
    stf_name VARCHAR(255) NOT NULL,
    stf_description TEXT,
    stf_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 of normalized STF code

    -- Source tracking
    source_execution_id UUID,
    source_correlation_id UUID,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    contributor_agent_name VARCHAR(255),

    -- STF content
    stf_code TEXT NOT NULL,
    stf_language VARCHAR(50) DEFAULT 'python',
    stf_parameters JSONB,  -- Input/output schema

    -- Classification
    problem_category VARCHAR(100),  -- e.g., "data_transformation", "api_integration"
    problem_signature TEXT,  -- Normalized problem description

    -- Quality metrics (5 dimensions)
    quality_score DECIMAL(3, 2),  -- 0.00 to 1.00 (composite score)
    completeness_score DECIMAL(3, 2),  -- Dimension 1
    documentation_score DECIMAL(3, 2),  -- Dimension 2
    onex_compliance_score DECIMAL(3, 2),  -- Dimension 3
    metadata_score DECIMAL(3, 2),  -- Dimension 4
    complexity_score DECIMAL(3, 2),  -- Dimension 5

    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP WITH TIME ZONE,

    -- Approval status
    approval_status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for debug_transform_functions
CREATE INDEX IF NOT EXISTS idx_stf_hash ON debug_transform_functions(stf_hash);
CREATE INDEX IF NOT EXISTS idx_stf_category ON debug_transform_functions(problem_category);
CREATE INDEX IF NOT EXISTS idx_stf_quality ON debug_transform_functions(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_stf_approval ON debug_transform_functions(approval_status);
CREATE INDEX IF NOT EXISTS idx_stf_usage ON debug_transform_functions(usage_count DESC);
CREATE INDEX IF NOT EXISTS idx_stf_source_correlation ON debug_transform_functions(source_correlation_id);

-- Trigger to auto-update updated_at
CREATE TRIGGER update_stf_updated_at
    BEFORE UPDATE ON debug_transform_functions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE debug_transform_functions IS 'Registry of Specific Transformation Functions (STFs) extracted from successful agent executions';
COMMENT ON COLUMN debug_transform_functions.stf_hash IS 'SHA-256 hash of normalized STF code for deduplication';
COMMENT ON COLUMN debug_transform_functions.quality_score IS 'Composite quality score (0.00-1.00) calculated from 5 dimensions';
COMMENT ON COLUMN debug_transform_functions.problem_signature IS 'Normalized problem description for similarity matching';

-- =====================================================================
-- Table 2: model_price_catalog (LLM Model Pricing)
-- =====================================================================

CREATE TABLE IF NOT EXISTS model_price_catalog (
    catalog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Model identification
    provider VARCHAR(100) NOT NULL,  -- anthropic, openai, google, zai, together
    model_name VARCHAR(255) NOT NULL,
    model_version VARCHAR(50),

    -- Pricing (per 1M tokens)
    input_price_per_million DECIMAL(10, 6) NOT NULL,
    output_price_per_million DECIMAL(10, 6) NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',

    -- Performance characteristics
    avg_latency_ms INTEGER,
    max_tokens INTEGER,
    context_window INTEGER,

    -- Capabilities
    supports_streaming BOOLEAN DEFAULT false,
    supports_function_calling BOOLEAN DEFAULT false,
    supports_vision BOOLEAN DEFAULT false,

    -- Rate limits
    requests_per_minute INTEGER,
    tokens_per_minute INTEGER,

    -- Availability
    is_active BOOLEAN DEFAULT true,
    deprecated_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    effective_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Composite unique constraint
    UNIQUE (provider, model_name, model_version, effective_date)
);

-- Indexes for model_price_catalog
CREATE INDEX IF NOT EXISTS idx_model_provider ON model_price_catalog(provider);
CREATE INDEX IF NOT EXISTS idx_model_active ON model_price_catalog(is_active);
CREATE INDEX IF NOT EXISTS idx_model_price ON model_price_catalog(input_price_per_million, output_price_per_million);
CREATE INDEX IF NOT EXISTS idx_model_name ON model_price_catalog(model_name);

-- Trigger to auto-update updated_at
CREATE TRIGGER update_model_catalog_updated_at
    BEFORE UPDATE ON model_price_catalog
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE model_price_catalog IS 'Catalog of LLM model pricing for cost tracking and optimization';
COMMENT ON COLUMN model_price_catalog.effective_date IS 'Date when this pricing became effective (allows historical tracking)';

-- =====================================================================
-- Table 3: debug_execution_attempts (Enhanced Correlation Tracking)
-- =====================================================================

CREATE TABLE IF NOT EXISTS debug_execution_attempts (
    attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation
    correlation_id UUID NOT NULL,
    execution_id UUID,
    parent_attempt_id UUID,  -- For retry tracking

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,
    agent_type VARCHAR(100),

    -- Problem identification
    user_request TEXT NOT NULL,
    user_request_hash VARCHAR(64),  -- For similarity matching
    problem_category VARCHAR(100),

    -- Approach taken
    approach_description TEXT,
    stf_ids UUID[],  -- Array of STFs attempted
    model_used VARCHAR(255),
    tools_used JSONB,  -- ["Read", "Edit", "Bash"]

    -- Execution details
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,

    -- Outcome
    status VARCHAR(50) NOT NULL,  -- success, error, timeout, cancelled
    error_type VARCHAR(100),
    error_message TEXT,
    error_stacktrace TEXT,

    -- Quality metrics
    quality_score DECIMAL(3, 2),
    confidence_score DECIMAL(3, 2),  -- How confident we are in this approach

    -- Cost tracking
    tokens_input INTEGER,
    tokens_output INTEGER,
    estimated_cost_usd DECIMAL(10, 6),

    -- Golden state tracking
    is_golden_state BOOLEAN DEFAULT false,
    golden_state_approved_by VARCHAR(255),
    golden_state_approved_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for debug_execution_attempts
CREATE INDEX IF NOT EXISTS idx_attempt_correlation ON debug_execution_attempts(correlation_id);
CREATE INDEX IF NOT EXISTS idx_attempt_execution ON debug_execution_attempts(execution_id);
CREATE INDEX IF NOT EXISTS idx_attempt_status ON debug_execution_attempts(status);
CREATE INDEX IF NOT EXISTS idx_attempt_golden ON debug_execution_attempts(is_golden_state);
CREATE INDEX IF NOT EXISTS idx_attempt_request_hash ON debug_execution_attempts(user_request_hash);
CREATE INDEX IF NOT EXISTS idx_attempt_agent ON debug_execution_attempts(agent_name);
CREATE INDEX IF NOT EXISTS idx_attempt_timestamp ON debug_execution_attempts(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempt_parent ON debug_execution_attempts(parent_attempt_id) WHERE parent_attempt_id IS NOT NULL;

-- Trigger to auto-update updated_at
CREATE TRIGGER update_attempt_updated_at
    BEFORE UPDATE ON debug_execution_attempts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE debug_execution_attempts IS 'Enhanced execution tracking with correlation and retry information';
COMMENT ON COLUMN debug_execution_attempts.parent_attempt_id IS 'Links retries to original failed attempt';
COMMENT ON COLUMN debug_execution_attempts.stf_ids IS 'Array of STF IDs that were attempted in this execution';
COMMENT ON COLUMN debug_execution_attempts.user_request_hash IS 'SHA-256 hash for similarity matching across requests';

-- =====================================================================
-- Table 4: debug_error_success_mappings (Confidence Metrics)
-- =====================================================================

CREATE TABLE IF NOT EXISTS debug_error_success_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Error identification
    error_type VARCHAR(100) NOT NULL,
    error_pattern TEXT NOT NULL,  -- Normalized error signature
    error_context JSONB,  -- Additional context (file types, tools used, etc.)

    -- Successful resolution
    successful_attempt_id UUID NOT NULL REFERENCES debug_execution_attempts(attempt_id),
    successful_stf_ids UUID[],
    successful_approach TEXT,

    -- Failed attempts (for learning)
    failed_attempt_ids UUID[],

    -- Confidence tracking
    confidence_score DECIMAL(3, 2) NOT NULL,  -- 0.00 to 1.00 (auto-calculated)
    success_count INTEGER DEFAULT 1,
    failure_count INTEGER DEFAULT 0,

    -- Last updated
    last_success_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_failure_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for debug_error_success_mappings
CREATE INDEX IF NOT EXISTS idx_mapping_error_type ON debug_error_success_mappings(error_type);
CREATE INDEX IF NOT EXISTS idx_mapping_confidence ON debug_error_success_mappings(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_mapping_success_count ON debug_error_success_mappings(success_count DESC);
CREATE INDEX IF NOT EXISTS idx_mapping_successful_attempt ON debug_error_success_mappings(successful_attempt_id);

-- Trigger to auto-calculate confidence score
CREATE OR REPLACE FUNCTION calculate_error_mapping_confidence()
RETURNS TRIGGER AS $$
BEGIN
    -- Simple confidence formula: success_count / (success_count + failure_count)
    -- With minimum of 0.1 to avoid zero confidence
    NEW.confidence_score = GREATEST(
        0.10,
        LEAST(
            1.00,
            NEW.success_count::DECIMAL / GREATEST(1, NEW.success_count + NEW.failure_count)
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_error_mapping_confidence
    BEFORE INSERT OR UPDATE ON debug_error_success_mappings
    FOR EACH ROW
    EXECUTE FUNCTION calculate_error_mapping_confidence();

-- Trigger to auto-update updated_at
CREATE TRIGGER update_mapping_updated_at
    BEFORE UPDATE ON debug_error_success_mappings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE debug_error_success_mappings IS 'Maps error patterns to successful resolution approaches with confidence metrics';
COMMENT ON COLUMN debug_error_success_mappings.error_pattern IS 'Normalized error signature for matching';
COMMENT ON COLUMN debug_error_success_mappings.confidence_score IS 'Auto-calculated: success_count / (success_count + failure_count)';

-- =====================================================================
-- Table 5: debug_golden_states (Proven Solution Registry)
-- =====================================================================

CREATE TABLE IF NOT EXISTS debug_golden_states (
    golden_state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to successful execution
    execution_attempt_id UUID NOT NULL REFERENCES debug_execution_attempts(attempt_id),
    correlation_id UUID NOT NULL,

    -- Problem solved
    problem_description TEXT NOT NULL,
    problem_category VARCHAR(100),
    problem_hash VARCHAR(64) NOT NULL,  -- For similarity matching

    -- Solution summary
    solution_summary TEXT NOT NULL,
    stf_ids UUID[],
    tools_used JSONB,
    model_used VARCHAR(255),

    -- Quality metrics
    quality_score DECIMAL(3, 2) NOT NULL,
    complexity_score DECIMAL(3, 2),
    reusability_score DECIMAL(3, 2),

    -- Approval workflow
    nominated_by VARCHAR(255),
    nominated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,
    approval_notes TEXT,

    -- Reuse tracking
    reuse_count INTEGER DEFAULT 0,
    last_reused_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for debug_golden_states
CREATE INDEX IF NOT EXISTS idx_golden_category ON debug_golden_states(problem_category);
CREATE INDEX IF NOT EXISTS idx_golden_quality ON debug_golden_states(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_golden_reuse ON debug_golden_states(reuse_count DESC);
CREATE INDEX IF NOT EXISTS idx_golden_problem_hash ON debug_golden_states(problem_hash);
CREATE INDEX IF NOT EXISTS idx_golden_correlation ON debug_golden_states(correlation_id);
CREATE INDEX IF NOT EXISTS idx_golden_execution_attempt ON debug_golden_states(execution_attempt_id);

-- Trigger to auto-update updated_at
CREATE TRIGGER update_golden_state_updated_at
    BEFORE UPDATE ON debug_golden_states
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments
COMMENT ON TABLE debug_golden_states IS 'Registry of proven, high-quality solutions for common problems';
COMMENT ON COLUMN debug_golden_states.problem_hash IS 'SHA-256 hash for similarity matching across problems';
COMMENT ON COLUMN debug_golden_states.reuse_count IS 'Number of times this golden state has been successfully reused';

-- =====================================================================
-- Analytical Views (for queries and reporting)
-- =====================================================================

-- View: High-quality STFs ready for recommendation
CREATE OR REPLACE VIEW v_recommended_stfs AS
SELECT
    stf_id,
    stf_name,
    stf_description,
    problem_category,
    quality_score,
    usage_count,
    success_count,
    (success_count::DECIMAL / NULLIF(usage_count, 0)) AS success_rate,
    last_used_at
FROM debug_transform_functions
WHERE approval_status = 'approved'
  AND quality_score >= 0.7
ORDER BY quality_score DESC, usage_count DESC;

COMMENT ON VIEW v_recommended_stfs IS 'High-quality approved STFs suitable for recommendation';

-- View: Error→Success mapping with context
CREATE OR REPLACE VIEW v_error_resolution_patterns AS
SELECT
    m.mapping_id,
    m.error_type,
    m.error_pattern,
    m.confidence_score,
    m.success_count,
    m.failure_count,
    a.approach_description AS successful_approach,
    a.stf_ids AS successful_stf_ids,
    a.tools_used,
    m.last_success_at
FROM debug_error_success_mappings m
JOIN debug_execution_attempts a ON m.successful_attempt_id = a.attempt_id
WHERE m.confidence_score >= 0.7
ORDER BY m.confidence_score DESC, m.success_count DESC;

COMMENT ON VIEW v_error_resolution_patterns IS 'High-confidence error→success patterns for agent guidance';

-- View: Golden states with full context
CREATE OR REPLACE VIEW v_golden_states_full AS
SELECT
    gs.golden_state_id,
    gs.problem_description,
    gs.problem_category,
    gs.solution_summary,
    gs.quality_score,
    gs.reuse_count,
    a.agent_name,
    a.model_used,
    a.tools_used,
    a.duration_ms,
    gs.approved_at,
    gs.approved_by
FROM debug_golden_states gs
JOIN debug_execution_attempts a ON gs.execution_attempt_id = a.attempt_id
WHERE gs.approved_at IS NOT NULL
ORDER BY gs.quality_score DESC, gs.reuse_count DESC;

COMMENT ON VIEW v_golden_states_full IS 'Approved golden states with complete execution context';

-- =====================================================================
-- Seed Data: Model Price Catalog (Current Pricing)
-- =====================================================================

-- Anthropic Models
INSERT INTO model_price_catalog (provider, model_name, model_version, input_price_per_million, output_price_per_million, max_tokens, context_window, supports_streaming, supports_function_calling)
VALUES
    ('anthropic', 'claude-3-5-sonnet-20241022', '3.5', 3.00, 15.00, 8192, 200000, true, true),
    ('anthropic', 'claude-3-opus-20240229', '3.0', 15.00, 75.00, 4096, 200000, true, true),
    ('anthropic', 'claude-3-haiku-20240307', '3.0', 0.25, 1.25, 4096, 200000, true, true)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;

-- OpenAI Models
INSERT INTO model_price_catalog (provider, model_name, model_version, input_price_per_million, output_price_per_million, max_tokens, context_window, supports_streaming, supports_function_calling)
VALUES
    ('openai', 'gpt-4-turbo', '4.0', 10.00, 30.00, 4096, 128000, true, true),
    ('openai', 'gpt-4', '4.0', 30.00, 60.00, 8192, 8192, true, true),
    ('openai', 'gpt-3.5-turbo', '3.5', 0.50, 1.50, 4096, 16385, true, true)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;

-- Google Gemini Models
INSERT INTO model_price_catalog (provider, model_name, model_version, input_price_per_million, output_price_per_million, max_tokens, context_window, supports_streaming, supports_vision)
VALUES
    ('google', 'gemini-1.5-pro', '1.5', 3.50, 10.50, 8192, 2000000, true, true),
    ('google', 'gemini-1.5-flash', '1.5', 0.075, 0.30, 8192, 1000000, true, true),
    ('google', 'gemini-2.5-flash', '2.5', 0.10, 0.40, 8192, 1000000, true, true)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;

-- Z.ai GLM Models
INSERT INTO model_price_catalog (provider, model_name, model_version, input_price_per_million, output_price_per_million, max_tokens, context_window, supports_streaming)
VALUES
    ('zai', 'glm-4.5-air', '4.5', 0.10, 0.10, 8192, 128000, true),
    ('zai', 'glm-4.5', '4.5', 1.00, 1.00, 8192, 128000, true),
    ('zai', 'glm-4.6', '4.6', 1.50, 1.50, 8192, 128000, true),
    ('zai', 'glm-4-flash', '4.0', 0.10, 0.10, 4096, 128000, true)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;

-- Together AI Models
INSERT INTO model_price_catalog (provider, model_name, model_version, input_price_per_million, output_price_per_million, max_tokens, context_window, supports_streaming)
VALUES
    ('together', 'llama-3.1-405b', '3.1', 3.50, 3.50, 4096, 128000, true),
    ('together', 'llama-3.1-70b', '3.1', 0.88, 0.88, 4096, 128000, true),
    ('together', 'llama-3.1-8b', '3.1', 0.18, 0.18, 4096, 128000, true)
ON CONFLICT (provider, model_name, model_version, effective_date) DO NOTHING;

-- =====================================================================
-- Migration Complete
-- =====================================================================

-- Verify tables created
DO $$
DECLARE
    table_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name IN (
        'debug_transform_functions',
        'model_price_catalog',
        'debug_execution_attempts',
        'debug_error_success_mappings',
        'debug_golden_states'
    );

    IF table_count = 5 THEN
        RAISE NOTICE 'SUCCESS: All 5 debug loop tables created successfully';
    ELSE
        RAISE EXCEPTION 'ERROR: Only % of 5 tables were created', table_count;
    END IF;
END $$;

-- Display summary
SELECT
    'Migration 001 Complete' AS status,
    COUNT(*) AS tables_created
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN (
    'debug_transform_functions',
    'model_price_catalog',
    'debug_execution_attempts',
    'debug_error_success_mappings',
    'debug_golden_states'
);
