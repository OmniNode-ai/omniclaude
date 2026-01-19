-- Migration: add_service_metrics
-- Description: Add service-level metrics to agent_routing_decisions and create performance view
-- Author: polymorphic-agent (Observability & Testing Suite)
-- Created: 2025-10-30
-- Correlation ID: ca95e668-6b52-4387-ba28-8d87ddfaf699
-- ONEX Compliance: Effect node pattern for service metrics persistence

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- -------------------------------------------------------------------------
-- Add service-level columns to agent_routing_decisions
-- -------------------------------------------------------------------------

-- Add service version tracking (for A/B testing and rollback analysis)
ALTER TABLE agent_routing_decisions
ADD COLUMN IF NOT EXISTS service_version VARCHAR(50);

COMMENT ON COLUMN agent_routing_decisions.service_version IS 'Version of routing service that made the decision (for A/B testing)';

-- Add service latency tracking (end-to-end HTTP request time)
ALTER TABLE agent_routing_decisions
ADD COLUMN IF NOT EXISTS service_latency_ms INTEGER;

COMMENT ON COLUMN agent_routing_decisions.service_latency_ms IS 'End-to-end service latency including HTTP overhead (target: <200ms)';

-- Add constraint for service latency
ALTER TABLE agent_routing_decisions
DROP CONSTRAINT IF EXISTS agent_routing_decisions_service_latency_check;

ALTER TABLE agent_routing_decisions
ADD CONSTRAINT agent_routing_decisions_service_latency_check
    CHECK (service_latency_ms IS NULL OR (service_latency_ms >= 0 AND service_latency_ms < 30000));

-- -------------------------------------------------------------------------
-- Create view: v_router_service_performance
-- Purpose: Aggregate service performance metrics for monitoring
-- -------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_router_service_performance AS
WITH recent_decisions AS (
    SELECT
        service_version,
        routing_strategy,
        selected_agent,
        confidence_score,
        routing_time_ms,
        service_latency_ms,
        cache_hit,
        actual_success,
        actual_quality_score,
        created_at
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '1 hour'
),
service_stats AS (
    SELECT
        COALESCE(service_version, 'unknown') as service_version,
        COUNT(*) as total_requests,
        COUNT(*) FILTER (WHERE cache_hit = TRUE) as cache_hits,
        COUNT(*) FILTER (WHERE cache_hit = FALSE) as cache_misses,
        ROUND(AVG(routing_time_ms), 2) as avg_routing_time_ms,
        ROUND(AVG(service_latency_ms), 2) as avg_service_latency_ms,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY service_latency_ms) as p50_latency_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY service_latency_ms) as p95_latency_ms,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY service_latency_ms) as p99_latency_ms,
        ROUND(AVG(confidence_score), 4) as avg_confidence_score,
        COUNT(*) FILTER (WHERE actual_success = TRUE) as successful_executions,
        COUNT(*) FILTER (WHERE actual_success = FALSE) as failed_executions,
        ROUND(AVG(actual_quality_score), 4) as avg_actual_quality_score,
        MIN(created_at) as first_seen,
        MAX(created_at) as last_seen
    FROM recent_decisions
    GROUP BY service_version
)
SELECT
    service_version,
    total_requests,
    cache_hits,
    cache_misses,
    ROUND(
        CASE WHEN total_requests > 0
        THEN (cache_hits::NUMERIC / total_requests::NUMERIC) * 100
        ELSE 0
        END, 2
    ) as cache_hit_rate_percent,
    avg_routing_time_ms,
    avg_service_latency_ms,
    p50_latency_ms,
    p95_latency_ms,
    p99_latency_ms,
    avg_confidence_score,
    successful_executions,
    failed_executions,
    ROUND(
        CASE WHEN (successful_executions + failed_executions) > 0
        THEN (successful_executions::NUMERIC / (successful_executions + failed_executions)::NUMERIC) * 100
        ELSE 0
        END, 2
    ) as success_rate_percent,
    avg_actual_quality_score,
    first_seen,
    last_seen,
    -- Performance assessment flags
    CASE
        WHEN avg_service_latency_ms <= 50 THEN 'excellent'
        WHEN avg_service_latency_ms <= 100 THEN 'good'
        WHEN avg_service_latency_ms <= 200 THEN 'acceptable'
        ELSE 'slow'
    END as latency_assessment,
    CASE
        WHEN (cache_hits::NUMERIC / NULLIF(total_requests, 0)::NUMERIC) >= 0.60 THEN 'excellent'
        WHEN (cache_hits::NUMERIC / NULLIF(total_requests, 0)::NUMERIC) >= 0.40 THEN 'good'
        WHEN (cache_hits::NUMERIC / NULLIF(total_requests, 0)::NUMERIC) >= 0.20 THEN 'fair'
        ELSE 'poor'
    END as cache_assessment,
    CASE
        WHEN avg_confidence_score >= 0.80 THEN 'excellent'
        WHEN avg_confidence_score >= 0.70 THEN 'good'
        WHEN avg_confidence_score >= 0.60 THEN 'fair'
        ELSE 'poor'
    END as confidence_assessment
FROM service_stats
ORDER BY last_seen DESC;

COMMENT ON VIEW v_router_service_performance IS 'Router service performance metrics aggregated over last hour';

-- -------------------------------------------------------------------------
-- Create view: v_router_agent_performance
-- Purpose: Per-agent performance breakdown
-- -------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_router_agent_performance AS
WITH recent_decisions AS (
    SELECT
        selected_agent,
        confidence_score,
        routing_time_ms,
        service_latency_ms,
        cache_hit,
        routing_strategy,
        actual_success,
        actual_quality_score,
        created_at
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '24 hours'
),
agent_stats AS (
    SELECT
        selected_agent,
        COUNT(*) as total_selections,
        ROUND(AVG(confidence_score), 4) as avg_confidence,
        ROUND(AVG(routing_time_ms), 2) as avg_routing_time_ms,
        ROUND(AVG(service_latency_ms), 2) as avg_service_latency_ms,
        COUNT(*) FILTER (WHERE cache_hit = TRUE) as cache_hits,
        COUNT(*) FILTER (WHERE routing_strategy = 'explicit') as explicit_selections,
        COUNT(*) FILTER (WHERE routing_strategy = 'enhanced_fuzzy_matching') as fuzzy_selections,
        COUNT(*) FILTER (WHERE actual_success = TRUE) as successful_executions,
        COUNT(*) FILTER (WHERE actual_success = FALSE) as failed_executions,
        ROUND(AVG(actual_quality_score), 4) as avg_quality_score,
        MIN(created_at) as first_selected,
        MAX(created_at) as last_selected
    FROM recent_decisions
    GROUP BY selected_agent
)
SELECT
    selected_agent,
    total_selections,
    avg_confidence,
    avg_routing_time_ms,
    avg_service_latency_ms,
    cache_hits,
    ROUND((cache_hits::NUMERIC / total_selections::NUMERIC) * 100, 2) as cache_hit_rate_percent,
    explicit_selections,
    fuzzy_selections,
    successful_executions,
    failed_executions,
    ROUND(
        CASE WHEN (successful_executions + failed_executions) > 0
        THEN (successful_executions::NUMERIC / (successful_executions + failed_executions)::NUMERIC) * 100
        ELSE 0
        END, 2
    ) as success_rate_percent,
    avg_quality_score,
    first_selected,
    last_selected,
    -- Performance indicators
    CASE
        WHEN avg_confidence >= 0.80 THEN '🟢 High'
        WHEN avg_confidence >= 0.70 THEN '🟡 Medium'
        ELSE '🔴 Low'
    END as confidence_indicator,
    CASE
        WHEN successful_executions > 0 AND failed_executions = 0 THEN '🟢 Excellent'
        WHEN (successful_executions::NUMERIC / NULLIF(successful_executions + failed_executions, 0)::NUMERIC) >= 0.90 THEN '🟡 Good'
        ELSE '🔴 Needs Review'
    END as reliability_indicator
FROM agent_stats
ORDER BY total_selections DESC, avg_confidence DESC;

COMMENT ON VIEW v_router_agent_performance IS 'Per-agent routing performance metrics over last 24 hours';

-- -------------------------------------------------------------------------
-- Create indexes for service metrics queries
-- -------------------------------------------------------------------------

-- Index for service version analysis
CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_service_version
    ON agent_routing_decisions(service_version, created_at DESC)
    WHERE service_version IS NOT NULL;

-- Index for service latency analysis
CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_service_latency
    ON agent_routing_decisions(service_latency_ms, created_at DESC)
    WHERE service_latency_ms IS NOT NULL;

-- Composite index for performance queries
CREATE INDEX IF NOT EXISTS idx_agent_routing_decisions_performance_query
    ON agent_routing_decisions(service_version, cache_hit, created_at DESC)
    WHERE service_version IS NOT NULL;

-- -------------------------------------------------------------------------
-- Update existing comments
-- -------------------------------------------------------------------------

COMMENT ON TABLE agent_routing_decisions IS 'Agent routing decisions with confidence scoring, service metrics, and outcome validation';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration:
/*
-- Drop views
DROP VIEW IF EXISTS v_router_agent_performance;
DROP VIEW IF EXISTS v_router_service_performance;

-- Drop indexes
DROP INDEX IF EXISTS idx_agent_routing_decisions_performance_query;
DROP INDEX IF EXISTS idx_agent_routing_decisions_service_latency;
DROP INDEX IF EXISTS idx_agent_routing_decisions_service_version;

-- Drop constraint
ALTER TABLE agent_routing_decisions
DROP CONSTRAINT IF EXISTS agent_routing_decisions_service_latency_check;

-- Drop columns
ALTER TABLE agent_routing_decisions
DROP COLUMN IF EXISTS service_latency_ms;

ALTER TABLE agent_routing_decisions
DROP COLUMN IF EXISTS service_version;
*/
