-- Migration: 003_create_router_performance_metrics
-- Description: Create router_performance_metrics table for time-series performance tracking
-- Author: agent-workflow-coordinator
-- Created: 2025-10-09
-- ONEX Compliance: Effect node pattern for metrics persistence

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- Create router_performance_metrics table
CREATE TABLE IF NOT EXISTS router_performance_metrics (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Metric identification
    metric_type VARCHAR(100) NOT NULL, -- routing_decision, cache_hit, cache_miss, fuzzy_match, etc.
    correlation_id UUID, -- Links to transformation events

    -- Routing metadata
    user_request_hash VARCHAR(64), -- Hash of user request for deduplication
    context_hash VARCHAR(64), -- Hash of context for cache key generation

    -- Agent selection
    selected_agent VARCHAR(255), -- Agent selected by router
    selection_strategy VARCHAR(100), -- explicit, fuzzy, capability, historical
    confidence_score DECIMAL(5,4), -- Router confidence (0-1)

    -- Alternative recommendations
    alternative_agents JSONB, -- Array of {agent, confidence, reason} objects
    alternatives_count INTEGER DEFAULT 0,

    -- Performance timings (microsecond precision for router operations)
    cache_lookup_us INTEGER, -- Cache lookup time in microseconds
    trigger_matching_us INTEGER, -- Trigger matching time in microseconds
    confidence_scoring_us INTEGER, -- Confidence calculation time in microseconds
    total_routing_time_us INTEGER, -- Total routing decision time in microseconds

    -- Confidence score breakdown (4 components from enhanced router)
    trigger_confidence DECIMAL(5,4), -- Trigger matching component (40% weight)
    context_confidence DECIMAL(5,4), -- Context alignment component (30% weight)
    capability_confidence DECIMAL(5,4), -- Capability match component (20% weight)
    historical_confidence DECIMAL(5,4), -- Historical success component (10% weight)

    -- Cache performance
    cache_hit BOOLEAN, -- Whether cache was hit
    cache_key VARCHAR(255), -- Cache key used
    cache_age_seconds INTEGER, -- Age of cached result if hit

    -- Outcome validation
    selection_validated BOOLEAN, -- Whether selection was validated post-execution
    actual_success BOOLEAN, -- Whether execution actually succeeded
    actual_quality_score DECIMAL(5,4), -- Actual quality score achieved
    prediction_error DECIMAL(5,4), -- Difference between predicted and actual confidence

    -- Learning feedback
    feedback_provided BOOLEAN DEFAULT FALSE,
    feedback_type VARCHAR(50), -- positive, negative, correction
    feedback_details JSONB,

    -- Timestamps (high precision for performance analysis)
    measured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMP WITH TIME ZONE,

    -- Constraints
    CONSTRAINT router_performance_metrics_confidence_check CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CONSTRAINT router_performance_metrics_component_checks CHECK (
        (trigger_confidence IS NULL OR (trigger_confidence >= 0 AND trigger_confidence <= 1)) AND
        (context_confidence IS NULL OR (context_confidence >= 0 AND context_confidence <= 1)) AND
        (capability_confidence IS NULL OR (capability_confidence >= 0 AND capability_confidence <= 1)) AND
        (historical_confidence IS NULL OR (historical_confidence >= 0 AND historical_confidence <= 1))
    )
);

-- Create indexes for performance (time-series optimized)
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_measured_at
    ON router_performance_metrics(measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_type_time
    ON router_performance_metrics(metric_type, measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_agent_time
    ON router_performance_metrics(selected_agent, measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_correlation
    ON router_performance_metrics(correlation_id)
    WHERE correlation_id IS NOT NULL;

-- Cache performance analysis
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_cache
    ON router_performance_metrics(cache_hit, cache_age_seconds)
    WHERE cache_hit IS NOT NULL;

-- Performance thresholds monitoring
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_timing
    ON router_performance_metrics(total_routing_time_us, measured_at DESC);

-- Quality prediction analysis
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_prediction
    ON router_performance_metrics(confidence_score, actual_quality_score, prediction_error)
    WHERE selection_validated = TRUE;

-- Request deduplication index
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_request_hash
    ON router_performance_metrics(user_request_hash, context_hash);

-- JSONB index for alternative recommendations
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_alternatives
    ON router_performance_metrics USING GIN(alternative_agents);

-- Learning feedback index
CREATE INDEX IF NOT EXISTS idx_router_performance_metrics_feedback
    ON router_performance_metrics(feedback_provided, feedback_type)
    WHERE feedback_provided = TRUE;

-- Add comments for documentation
COMMENT ON TABLE router_performance_metrics IS 'Time-series performance metrics for enhanced router monitoring and optimization';
COMMENT ON COLUMN router_performance_metrics.total_routing_time_us IS 'Target: <100ms (100,000 microseconds) per routing decision';
COMMENT ON COLUMN router_performance_metrics.trigger_confidence IS '40% weight component from trigger matching quality';
COMMENT ON COLUMN router_performance_metrics.context_confidence IS '30% weight component from domain/context alignment';
COMMENT ON COLUMN router_performance_metrics.capability_confidence IS '20% weight component from capability matching';
COMMENT ON COLUMN router_performance_metrics.historical_confidence IS '10% weight component from historical success rates';
COMMENT ON COLUMN router_performance_metrics.prediction_error IS 'Difference between predicted confidence and actual quality for learning';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP TABLE IF EXISTS router_performance_metrics CASCADE;
