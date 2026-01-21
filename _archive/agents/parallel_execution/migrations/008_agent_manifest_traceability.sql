-- Migration: 008_agent_manifest_traceability
-- Description: Create tables for agent routing decisions and manifest injection traceability
-- Author: polymorphic-agent
-- Created: 2025-10-27
-- ONEX Compliance: Effect node pattern for event persistence
-- Correlation ID: Complete trace from user prompt → agent detection → manifest → execution

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- -------------------------------------------------------------------------
-- Table: agent_routing_decisions
-- Purpose: Track routing decisions with confidence scoring and reasoning
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_routing_decisions (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL, -- Links to workflow events and manifest injections
    session_id UUID, -- Links events in a conversation session

    -- User input
    user_request TEXT NOT NULL, -- Original user request text
    user_request_hash VARCHAR(64), -- SHA-256 hash for deduplication
    context_snapshot JSONB, -- Full context at routing time

    -- Routing decision
    selected_agent VARCHAR(255) NOT NULL, -- Agent name selected
    confidence_score NUMERIC(5,4) NOT NULL, -- Overall confidence 0.0-1.0
    routing_strategy VARCHAR(100) NOT NULL, -- enhanced_fuzzy_matching, explicit, fallback

    -- Confidence breakdown (4-component scoring)
    trigger_confidence NUMERIC(5,4), -- Trigger matching component (40% weight)
    context_confidence NUMERIC(5,4), -- Context alignment component (30% weight)
    capability_confidence NUMERIC(5,4), -- Capability match component (20% weight)
    historical_confidence NUMERIC(5,4), -- Historical success component (10% weight)

    -- Alternative recommendations
    alternatives JSONB, -- Array of {agent, confidence, reason} objects
    alternatives_count INTEGER DEFAULT 0,

    -- Decision reasoning
    reasoning TEXT, -- Why this agent was selected
    matched_triggers TEXT[], -- Trigger phrases that matched
    matched_capabilities TEXT[], -- Capabilities that matched

    -- Performance metrics
    routing_time_ms INTEGER NOT NULL, -- Time taken for routing decision
    cache_hit BOOLEAN DEFAULT FALSE, -- Whether result was from cache
    cache_key VARCHAR(255), -- Cache key if applicable

    -- Outcome validation (filled in after execution)
    selection_validated BOOLEAN DEFAULT FALSE,
    actual_success BOOLEAN, -- Whether execution succeeded
    actual_quality_score NUMERIC(5,4), -- Actual output quality
    prediction_error NUMERIC(5,4), -- |predicted - actual| confidence

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    validated_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT agent_routing_decisions_confidence_check
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CONSTRAINT agent_routing_decisions_components_check CHECK (
        (trigger_confidence IS NULL OR (trigger_confidence >= 0 AND trigger_confidence <= 1)) AND
        (context_confidence IS NULL OR (context_confidence >= 0 AND context_confidence <= 1)) AND
        (capability_confidence IS NULL OR (capability_confidence >= 0 AND capability_confidence <= 1)) AND
        (historical_confidence IS NULL OR (historical_confidence >= 0 AND historical_confidence <= 1))
    ),
    CONSTRAINT agent_routing_decisions_routing_time_check
        CHECK (routing_time_ms >= 0 AND routing_time_ms < 10000) -- Max 10 seconds
);

-- Indexes for agent_routing_decisions
CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_correlation
    ON agent_routing_decisions(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_session
    ON agent_routing_decisions(session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_agent
    ON agent_routing_decisions(selected_agent, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_strategy
    ON agent_routing_decisions(routing_strategy, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_confidence
    ON agent_routing_decisions(confidence_score DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_request_hash
    ON agent_routing_decisions(user_request_hash, context_snapshot)
    WHERE user_request_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_time
    ON agent_routing_decisions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_alternatives
    ON agent_routing_decisions USING GIN(alternatives);

CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_validation
    ON agent_routing_decisions(selection_validated, actual_success)
    WHERE selection_validated = TRUE;

-- Comments
COMMENT ON TABLE agent_routing_decisions IS
    'Tracks agent routing decisions with confidence scoring and full reasoning for traceability';
COMMENT ON COLUMN agent_routing_decisions.correlation_id IS
    'Links routing decision → manifest injection → execution → outcome';
COMMENT ON COLUMN agent_routing_decisions.confidence_score IS
    'Weighted sum of 4 components: trigger(40%) + context(30%) + capability(20%) + historical(10%)';
COMMENT ON COLUMN agent_routing_decisions.routing_time_ms IS
    'Target: <100ms for routing decision';

-- -------------------------------------------------------------------------
-- Table: agent_manifest_injections
-- Purpose: Track complete manifest injections for full execution replay
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_manifest_injections (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL, -- Links to routing decisions and transformation events
    session_id UUID, -- Links events in a conversation session
    routing_decision_id UUID REFERENCES agent_routing_decisions(id), -- Link to routing decision

    -- Agent context
    agent_name VARCHAR(255) NOT NULL, -- Agent receiving the manifest
    agent_version VARCHAR(50) DEFAULT '1.0.0',

    -- Manifest generation metadata
    manifest_version VARCHAR(50) NOT NULL, -- Manifest format version (e.g., "2.0.0")
    generation_source VARCHAR(100) NOT NULL, -- "archon-intelligence-adapter" or "fallback"
    is_fallback BOOLEAN DEFAULT FALSE, -- Whether minimal fallback manifest was used

    -- Manifest sections included
    sections_included TEXT[] NOT NULL, -- ['patterns', 'infrastructure', 'models', 'schemas', 'debug_intelligence']
    sections_requested TEXT[], -- Sections specifically requested (if any)

    -- Query results summary
    patterns_count INTEGER DEFAULT 0, -- Number of patterns included
    infrastructure_services INTEGER DEFAULT 0, -- Number of services in topology
    models_count INTEGER DEFAULT 0, -- Number of models available
    database_schemas_count INTEGER DEFAULT 0, -- Number of database schemas
    debug_intelligence_successes INTEGER DEFAULT 0, -- Successful similar workflows
    debug_intelligence_failures INTEGER DEFAULT 0, -- Failed similar workflows to avoid

    -- Collections queried (for debug intelligence)
    collections_queried JSONB, -- {"execution_patterns": 50, "code_patterns": 100, "workflow_events": 20}

    -- Performance metrics
    query_times JSONB NOT NULL, -- {"patterns": 450, "infrastructure": 200, ...} in milliseconds
    total_query_time_ms INTEGER NOT NULL, -- Sum of all query times
    cache_hit BOOLEAN DEFAULT FALSE, -- Whether manifest was from cache
    cache_age_seconds INTEGER, -- Age of cached manifest if hit

    -- Complete manifest snapshot
    full_manifest_snapshot JSONB NOT NULL, -- Complete manifest data structure
    formatted_manifest_text TEXT, -- Formatted text injected into agent prompt
    manifest_size_bytes INTEGER, -- Size of formatted manifest

    -- Quality indicators
    intelligence_available BOOLEAN DEFAULT TRUE, -- Whether intelligence queries succeeded
    query_failures JSONB, -- {"patterns": "timeout", "infrastructure": null, ...}
    warnings TEXT[], -- Any warnings generated during manifest creation

    -- Outcome tracking (filled in after agent execution)
    agent_execution_success BOOLEAN, -- Whether agent succeeded with this manifest
    agent_execution_time_ms INTEGER, -- How long agent took to execute
    agent_quality_score NUMERIC(5,4), -- Quality of agent output

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE, -- When agent started using this manifest
    completed_at TIMESTAMP WITH TIME ZONE, -- When agent finished

    -- Constraints
    CONSTRAINT agent_manifest_injections_query_time_check
        CHECK (total_query_time_ms >= 0 AND total_query_time_ms < 30000), -- Max 30 seconds
    CONSTRAINT agent_manifest_injections_quality_check
        CHECK (agent_quality_score IS NULL OR (agent_quality_score >= 0 AND agent_quality_score <= 1))
);

-- Indexes for agent_manifest_injections
CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_correlation
    ON agent_manifest_injections(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_session
    ON agent_manifest_injections(session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_routing
    ON agent_manifest_injections(routing_decision_id)
    WHERE routing_decision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_agent
    ON agent_manifest_injections(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_time
    ON agent_manifest_injections(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_source
    ON agent_manifest_injections(generation_source, is_fallback);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_performance
    ON agent_manifest_injections(total_query_time_ms, patterns_count);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_success
    ON agent_manifest_injections(agent_execution_success, agent_quality_score)
    WHERE agent_execution_success IS NOT NULL;

-- JSONB indexes for complex queries
CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_snapshot
    ON agent_manifest_injections USING GIN(full_manifest_snapshot);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_query_times
    ON agent_manifest_injections USING GIN(query_times);

CREATE INDEX IF NOT EXISTS idx_agent_manifest_injections_failures
    ON agent_manifest_injections USING GIN(query_failures);

-- Comments
COMMENT ON TABLE agent_manifest_injections IS
    'Complete record of manifest injections for full execution replay and debugging';
COMMENT ON COLUMN agent_manifest_injections.correlation_id IS
    'Links to routing decision and agent execution for complete trace';
COMMENT ON COLUMN agent_manifest_injections.full_manifest_snapshot IS
    'Complete manifest data structure - enables exact replay of what agent received';
COMMENT ON COLUMN agent_manifest_injections.query_times IS
    'Breakdown of query performance per section for optimization analysis';
COMMENT ON COLUMN agent_manifest_injections.total_query_time_ms IS
    'Target: <2000ms for complete manifest generation';

-- -------------------------------------------------------------------------
-- Views for analysis and debugging
-- -------------------------------------------------------------------------

-- View: Complete trace from user request to agent execution
CREATE OR REPLACE VIEW v_agent_execution_trace AS
SELECT
    ard.correlation_id,
    ard.user_request,
    ard.selected_agent,
    ard.confidence_score,
    ard.routing_strategy,
    ard.reasoning AS routing_reasoning,
    ard.routing_time_ms,
    ami.manifest_version,
    ami.generation_source,
    ami.is_fallback,
    ami.patterns_count,
    ami.debug_intelligence_successes,
    ami.debug_intelligence_failures,
    ami.total_query_time_ms,
    ami.agent_execution_success,
    ami.agent_quality_score,
    ate.transformation_duration_ms,
    ate.total_execution_duration_ms,
    ard.created_at AS routing_time,
    ami.created_at AS manifest_time,
    ate.started_at AS execution_start_time,
    ate.completed_at AS execution_end_time
FROM agent_routing_decisions ard
LEFT JOIN agent_manifest_injections ami
    ON ard.correlation_id = ami.correlation_id
LEFT JOIN agent_transformation_events ate
    ON ard.correlation_id = ate.correlation_id
    AND ard.selected_agent = ate.target_agent
ORDER BY ard.created_at DESC;

COMMENT ON VIEW v_agent_execution_trace IS
    'Complete execution trace: routing → manifest → execution for debugging and analysis';

-- View: Manifest injection performance analysis
CREATE OR REPLACE VIEW v_manifest_injection_performance AS
SELECT
    agent_name,
    generation_source,
    COUNT(*) AS total_injections,
    AVG(total_query_time_ms) AS avg_query_time_ms,
    AVG(patterns_count) AS avg_patterns_count,
    AVG(debug_intelligence_successes + debug_intelligence_failures) AS avg_debug_intel_count,
    COUNT(CASE WHEN is_fallback = TRUE THEN 1 END) AS fallback_count,
    (COUNT(CASE WHEN is_fallback = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) AS fallback_percent,
    COUNT(CASE WHEN agent_execution_success = TRUE THEN 1 END) AS success_count,
    (COUNT(CASE WHEN agent_execution_success = TRUE THEN 1 END)::numeric * 100) /
        NULLIF(COUNT(CASE WHEN agent_execution_success IS NOT NULL THEN 1 END), 0) AS success_percent,
    AVG(agent_quality_score) AS avg_quality_score
FROM agent_manifest_injections
GROUP BY agent_name, generation_source
ORDER BY total_injections DESC;

COMMENT ON VIEW v_manifest_injection_performance IS
    'Performance metrics for manifest injection by agent and source';

-- View: Routing decision accuracy analysis
CREATE OR REPLACE VIEW v_routing_decision_accuracy AS
SELECT
    selected_agent,
    routing_strategy,
    COUNT(*) AS total_decisions,
    AVG(confidence_score) AS avg_confidence,
    COUNT(CASE WHEN selection_validated = TRUE THEN 1 END) AS validated_count,
    COUNT(CASE WHEN actual_success = TRUE THEN 1 END) AS success_count,
    (COUNT(CASE WHEN actual_success = TRUE THEN 1 END)::numeric * 100) /
        NULLIF(COUNT(CASE WHEN selection_validated = TRUE THEN 1 END), 0) AS accuracy_percent,
    AVG(prediction_error) AS avg_prediction_error,
    AVG(routing_time_ms) AS avg_routing_time_ms
FROM agent_routing_decisions
GROUP BY selected_agent, routing_strategy
ORDER BY total_decisions DESC;

COMMENT ON VIEW v_routing_decision_accuracy IS
    'Routing decision accuracy and performance by agent and strategy';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP VIEW IF EXISTS v_routing_decision_accuracy;
-- DROP VIEW IF EXISTS v_manifest_injection_performance;
-- DROP VIEW IF EXISTS v_agent_execution_trace;
-- DROP TABLE IF EXISTS agent_manifest_injections CASCADE;
-- DROP TABLE IF EXISTS agent_routing_decisions CASCADE;
