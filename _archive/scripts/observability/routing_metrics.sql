-- ============================================================================
-- ROUTING METRICS MONITORING QUERIES
-- ============================================================================
-- Purpose: Monitor routing health with key metrics
-- Database: omninode_bridge
-- Tables: agent_transformation_events, agent_routing_decisions, router_performance_metrics
-- Correlation ID: 60d7acac-8d46-4041-ae43-49f1aa7fdccc
-- ============================================================================

-- ============================================================================
-- METRIC 1: Self-Transformation Rate (TARGET: <10%)
-- ============================================================================
-- Description: Percentage of transformations where polymorphic-agent
--              transforms to itself, indicating routing bypass
-- Alert: CRITICAL if >10%
-- ============================================================================

\echo '=== METRIC 1: Self-Transformation Rate ==='

WITH transformation_stats AS (
    SELECT
        COUNT(*) FILTER (
            WHERE source_agent = 'polymorphic-agent'
            AND target_agent = 'polymorphic-agent'
        ) as self_transformations,
        COUNT(*) FILTER (
            WHERE source_agent = 'polymorphic-agent'
        ) as total_transformations,
        COUNT(*) FILTER (
            WHERE source_agent = 'polymorphic-agent'
            AND target_agent = 'polymorphic-agent'
            AND started_at > NOW() - INTERVAL '24 hours'
        ) as self_transformations_24h,
        COUNT(*) FILTER (
            WHERE source_agent = 'polymorphic-agent'
            AND started_at > NOW() - INTERVAL '24 hours'
        ) as total_transformations_24h
    FROM agent_transformation_events
    WHERE started_at > NOW() - INTERVAL '7 days'
)
SELECT
    self_transformations,
    total_transformations,
    ROUND(
        CASE
            WHEN total_transformations > 0
            THEN (self_transformations::numeric / total_transformations::numeric) * 100
            ELSE 0
        END,
        2
    ) as self_transformation_rate_pct,
    self_transformations_24h,
    total_transformations_24h,
    ROUND(
        CASE
            WHEN total_transformations_24h > 0
            THEN (self_transformations_24h::numeric / total_transformations_24h::numeric) * 100
            ELSE 0
        END,
        2
    ) as self_transformation_rate_24h_pct,
    CASE
        WHEN total_transformations > 0 AND
             (self_transformations::numeric / total_transformations::numeric) * 100 > 10
        THEN '🔴 CRITICAL'
        WHEN total_transformations > 0 AND
             (self_transformations::numeric / total_transformations::numeric) * 100 > 5
        THEN '🟡 WARNING'
        ELSE '🟢 HEALTHY'
    END as status
FROM transformation_stats;

\echo ''

-- ============================================================================
-- METRIC 2: Routing Confidence Distribution
-- ============================================================================
-- Description: Distribution of routing confidence scores by confidence bucket
-- Alert: WARNING if average confidence <0.7
-- ============================================================================

\echo '=== METRIC 2: Routing Confidence Distribution ==='

WITH confidence_buckets AS (
    SELECT
        CASE
            WHEN confidence_score >= 0.9 THEN '0.90-1.00 (High)'
            WHEN confidence_score >= 0.8 THEN '0.80-0.89 (Good)'
            WHEN confidence_score >= 0.7 THEN '0.70-0.79 (Fair)'
            WHEN confidence_score >= 0.6 THEN '0.60-0.69 (Low)'
            ELSE '0.00-0.59 (Critical)'
        END as confidence_bucket,
        confidence_score
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '7 days'
    AND confidence_score IS NOT NULL
)
SELECT
    confidence_bucket,
    COUNT(*) as count,
    ROUND(AVG(confidence_score), 3) as avg_confidence,
    ROUND(MIN(confidence_score), 3) as min_confidence,
    ROUND(MAX(confidence_score), 3) as max_confidence,
    ROUND((COUNT(*)::numeric / SUM(COUNT(*)) OVER ()) * 100, 2) as percentage
FROM confidence_buckets
GROUP BY confidence_bucket
ORDER BY
    CASE confidence_bucket
        WHEN '0.90-1.00 (High)' THEN 1
        WHEN '0.80-0.89 (Good)' THEN 2
        WHEN '0.70-0.79 (Fair)' THEN 3
        WHEN '0.60-0.69 (Low)' THEN 4
        ELSE 5
    END;

\echo ''
\echo 'Overall Confidence Statistics:'

SELECT
    COUNT(*) as total_routing_decisions,
    ROUND(AVG(confidence_score), 3) as avg_confidence,
    ROUND(CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY confidence_score) AS numeric), 3) as median_confidence,
    ROUND(CAST(STDDEV(confidence_score) AS numeric), 3) as stddev_confidence,
    CASE
        WHEN AVG(confidence_score) < 0.7 THEN '🟡 WARNING'
        WHEN AVG(confidence_score) < 0.8 THEN '🟢 HEALTHY'
        ELSE '🟢 EXCELLENT'
    END as status
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
AND confidence_score IS NOT NULL;

\echo ''

-- ============================================================================
-- METRIC 3: Top 10 Agent Selections
-- ============================================================================
-- Description: Most frequently selected agents with performance metrics
-- ============================================================================

\echo '=== METRIC 3: Top 10 Agent Selections ==='

SELECT
    selected_agent,
    COUNT(*) as selection_count,
    ROUND(AVG(confidence_score), 3) as avg_confidence,
    ROUND(AVG(routing_time_ms), 2) as avg_routing_ms,
    COUNT(*) FILTER (WHERE execution_succeeded = true) as executions_succeeded,
    COUNT(*) FILTER (WHERE execution_succeeded = false) as executions_failed,
    ROUND(
        CASE
            WHEN COUNT(*) FILTER (WHERE execution_succeeded IS NOT NULL) > 0
            THEN (COUNT(*) FILTER (WHERE execution_succeeded = true)::numeric /
                  COUNT(*) FILTER (WHERE execution_succeeded IS NOT NULL)::numeric) * 100
            ELSE NULL
        END,
        2
    ) as success_rate_pct
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY selected_agent
ORDER BY selection_count DESC
LIMIT 10;

\echo ''

-- ============================================================================
-- METRIC 4: Bypass Attempt Count (TARGET: 0)
-- ============================================================================
-- Description: Count of routing decisions with suspicious bypass patterns
-- Alert: CRITICAL if >0
-- ============================================================================

\echo '=== METRIC 4: Bypass Attempt Count ==='

WITH bypass_patterns AS (
    SELECT
        id,
        selected_agent,
        user_request,
        confidence_score,
        routing_strategy,
        created_at,
        CASE
            -- Pattern 1: Direct selection without routing strategy
            WHEN routing_strategy IS NULL OR routing_strategy = '' THEN 'no_strategy'
            -- Pattern 2: Very high confidence without alternatives
            WHEN confidence_score > 0.99 AND alternatives = '[]'::jsonb THEN 'suspicious_confidence'
            -- Pattern 3: Routing time unusually low
            WHEN routing_time_ms < 1 THEN 'instant_routing'
            ELSE NULL
        END as bypass_pattern
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '7 days'
)
SELECT
    COUNT(*) as total_bypass_attempts,
    COUNT(*) FILTER (WHERE bypass_pattern = 'no_strategy') as no_strategy_count,
    COUNT(*) FILTER (WHERE bypass_pattern = 'suspicious_confidence') as suspicious_confidence_count,
    COUNT(*) FILTER (WHERE bypass_pattern = 'instant_routing') as instant_routing_count,
    CASE
        WHEN COUNT(*) > 0 THEN '🔴 CRITICAL'
        ELSE '🟢 HEALTHY'
    END as status
FROM bypass_patterns
WHERE bypass_pattern IS NOT NULL;

\echo ''
\echo 'Sample Bypass Attempts (if any):'

SELECT
    selected_agent,
    LEFT(user_request, 100) as user_request_preview,
    confidence_score,
    routing_strategy,
    routing_time_ms,
    created_at
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
AND (
    routing_strategy IS NULL
    OR routing_strategy = ''
    OR (confidence_score > 0.99 AND alternatives = '[]'::jsonb)
    OR routing_time_ms < 1
)
ORDER BY created_at DESC
LIMIT 5;

\echo ''

-- ============================================================================
-- METRIC 5: Frontend Task Routing Accuracy (TARGET: 100%)
-- ============================================================================
-- Description: Accuracy of routing frontend-related tasks to agent-frontend-developer
-- Alert: WARNING if <100%
-- ============================================================================

\echo '=== METRIC 5: Frontend Task Routing Accuracy ==='

WITH frontend_tasks AS (
    SELECT
        id,
        selected_agent,
        user_request,
        confidence_score,
        created_at,
        CASE
            WHEN selected_agent IN ('agent-frontend-developer', 'frontend-developer')
            THEN true
            ELSE false
        END as routed_to_frontend
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '7 days'
    AND (
        LOWER(user_request) LIKE '%frontend%'
        OR LOWER(user_request) LIKE '%react%'
        OR LOWER(user_request) LIKE '%vue%'
        OR LOWER(user_request) LIKE '%angular%'
        OR LOWER(user_request) LIKE '%ui component%'
        OR LOWER(user_request) LIKE '%css%'
        OR LOWER(user_request) LIKE '%html%'
        OR LOWER(user_request) LIKE '%javascript%'
        OR LOWER(user_request) LIKE '%typescript%'
        OR LOWER(user_request) LIKE '%browser%'
    )
)
SELECT
    COUNT(*) as total_frontend_tasks,
    COUNT(*) FILTER (WHERE routed_to_frontend = true) as correctly_routed,
    COUNT(*) FILTER (WHERE routed_to_frontend = false) as incorrectly_routed,
    ROUND(
        CASE
            WHEN COUNT(*) > 0
            THEN (COUNT(*) FILTER (WHERE routed_to_frontend = true)::numeric / COUNT(*)::numeric) * 100
            ELSE 0
        END,
        2
    ) as accuracy_pct,
    CASE
        WHEN COUNT(*) = 0 THEN '⚪ NO DATA'
        WHEN COUNT(*) > 0 AND
             (COUNT(*) FILTER (WHERE routed_to_frontend = true)::numeric / COUNT(*)::numeric) * 100 = 100
        THEN '🟢 PERFECT'
        WHEN COUNT(*) > 0 AND
             (COUNT(*) FILTER (WHERE routed_to_frontend = true)::numeric / COUNT(*)::numeric) * 100 >= 90
        THEN '🟡 WARNING'
        ELSE '🔴 CRITICAL'
    END as status
FROM frontend_tasks;

\echo ''
\echo 'Incorrectly Routed Frontend Tasks (if any):'

SELECT
    selected_agent,
    LEFT(user_request, 100) as user_request_preview,
    confidence_score,
    created_at
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
AND selected_agent NOT IN ('agent-frontend-developer', 'frontend-developer')
AND (
    LOWER(user_request) LIKE '%frontend%'
    OR LOWER(user_request) LIKE '%react%'
    OR LOWER(user_request) LIKE '%vue%'
    OR LOWER(user_request) LIKE '%angular%'
    OR LOWER(user_request) LIKE '%ui component%'
    OR LOWER(user_request) LIKE '%css%'
    OR LOWER(user_request) LIKE '%html%'
)
ORDER BY created_at DESC
LIMIT 5;

\echo ''

-- ============================================================================
-- METRIC 6: Routing Failures and Fallbacks
-- ============================================================================
-- Description: Count and patterns of routing failures
-- Alert: WARNING if failure rate >5%
-- ============================================================================

\echo '=== METRIC 6: Routing Failures and Fallbacks ==='

WITH routing_failures AS (
    SELECT
        COUNT(*) as total_decisions,
        COUNT(*) FILTER (
            WHERE selected_agent = 'polymorphic-agent'
            AND confidence_score < 0.5
        ) as low_confidence_fallbacks,
        COUNT(*) FILTER (
            WHERE execution_succeeded = false
        ) as execution_failures,
        COUNT(*) FILTER (
            WHERE actual_success = false
        ) as actual_failures
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '7 days'
)
SELECT
    total_decisions,
    low_confidence_fallbacks,
    execution_failures,
    actual_failures,
    ROUND(
        CASE
            WHEN total_decisions > 0
            THEN (low_confidence_fallbacks::numeric / total_decisions::numeric) * 100
            ELSE 0
        END,
        2
    ) as low_confidence_fallback_rate_pct,
    ROUND(
        CASE
            WHEN total_decisions > 0
            THEN (execution_failures::numeric / total_decisions::numeric) * 100
            ELSE 0
        END,
        2
    ) as execution_failure_rate_pct,
    CASE
        WHEN total_decisions > 0 AND
             ((low_confidence_fallbacks::numeric + execution_failures::numeric) / total_decisions::numeric) * 100 > 5
        THEN '🟡 WARNING'
        ELSE '🟢 HEALTHY'
    END as status
FROM routing_failures;

\echo ''
\echo 'Recent Failures:'

SELECT
    selected_agent,
    LEFT(user_request, 80) as user_request_preview,
    confidence_score,
    routing_strategy,
    execution_succeeded,
    actual_success,
    created_at
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
AND (
    execution_succeeded = false
    OR actual_success = false
    OR (selected_agent = 'polymorphic-agent' AND confidence_score < 0.5)
)
ORDER BY created_at DESC
LIMIT 10;

\echo ''

-- ============================================================================
-- METRIC 7: Transformations Per Hour Trend
-- ============================================================================
-- Description: Hourly transformation volume for trend analysis
-- ============================================================================

\echo '=== METRIC 7: Transformations Per Hour (Last 24h) ==='

SELECT
    DATE_TRUNC('hour', started_at) as hour,
    COUNT(*) as total_transformations,
    COUNT(*) FILTER (
        WHERE source_agent = 'polymorphic-agent'
        AND target_agent != 'polymorphic-agent'
    ) as specialized_transformations,
    COUNT(*) FILTER (
        WHERE source_agent = 'polymorphic-agent'
        AND target_agent = 'polymorphic-agent'
    ) as self_transformations,
    ROUND(AVG(transformation_duration_ms), 2) as avg_duration_ms
FROM agent_transformation_events
WHERE started_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', started_at)
ORDER BY hour DESC;

\echo ''

-- ============================================================================
-- METRIC 8: Router Performance Metrics
-- ============================================================================
-- Description: Performance metrics from router_performance_metrics table
-- ============================================================================

\echo '=== METRIC 8: Router Performance Metrics ==='

SELECT
    COUNT(*) as total_queries,
    COUNT(*) FILTER (WHERE cache_hit = true) as cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) as cache_misses,
    ROUND(
        CASE
            WHEN COUNT(*) > 0
            THEN (COUNT(*) FILTER (WHERE cache_hit = true)::numeric / COUNT(*)::numeric) * 100
            ELSE 0
        END,
        2
    ) as cache_hit_rate_pct,
    ROUND(AVG(total_routing_time_us / 1000.0), 2) as avg_routing_time_ms,
    ROUND(CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_routing_time_us / 1000.0) AS numeric), 2) as p50_routing_ms,
    ROUND(CAST(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_routing_time_us / 1000.0) AS numeric), 2) as p95_routing_ms,
    ROUND(CAST(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_routing_time_us / 1000.0) AS numeric), 2) as p99_routing_ms,
    ROUND(AVG(alternatives_count), 2) as avg_alternatives_evaluated
FROM router_performance_metrics
WHERE measured_at > NOW() - INTERVAL '7 days';

\echo ''
\echo 'Performance by Selection Strategy:'

SELECT
    selection_strategy,
    COUNT(*) as count,
    ROUND(AVG(total_routing_time_us / 1000.0), 2) as avg_duration_ms,
    ROUND(CAST(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_routing_time_us / 1000.0) AS numeric), 2) as p95_duration_ms,
    ROUND(AVG(alternatives_count), 2) as avg_alternatives
FROM router_performance_metrics
WHERE measured_at > NOW() - INTERVAL '7 days'
AND selection_strategy IS NOT NULL
GROUP BY selection_strategy
ORDER BY count DESC;

\echo ''

-- ============================================================================
-- SUMMARY DASHBOARD
-- ============================================================================

\echo '=== ROUTING HEALTH SUMMARY DASHBOARD ==='

WITH metrics AS (
    SELECT
        -- Self-transformation rate
        ROUND(
            (COUNT(*) FILTER (
                WHERE source_agent = 'polymorphic-agent'
                AND target_agent = 'polymorphic-agent'
            )::numeric / NULLIF(COUNT(*) FILTER (WHERE source_agent = 'polymorphic-agent'), 0)) * 100,
            2
        ) as self_transformation_rate
    FROM agent_transformation_events
    WHERE started_at > NOW() - INTERVAL '7 days'
),
routing_metrics AS (
    SELECT
        ROUND(AVG(confidence_score), 3) as avg_confidence,
        COUNT(*) as total_decisions,
        COUNT(*) FILTER (WHERE execution_succeeded = false) as failures
    FROM agent_routing_decisions
    WHERE created_at > NOW() - INTERVAL '7 days'
)
SELECT
    metrics.self_transformation_rate as self_transformation_pct,
    CASE
        WHEN metrics.self_transformation_rate > 10 THEN '🔴 CRITICAL'
        WHEN metrics.self_transformation_rate > 5 THEN '🟡 WARNING'
        ELSE '🟢 HEALTHY'
    END as self_transformation_status,
    routing_metrics.avg_confidence,
    CASE
        WHEN routing_metrics.avg_confidence < 0.7 THEN '🟡 WARNING'
        ELSE '🟢 HEALTHY'
    END as confidence_status,
    routing_metrics.total_decisions as routing_decisions_7d,
    routing_metrics.failures as routing_failures,
    ROUND(
        CASE
            WHEN routing_metrics.total_decisions > 0
            THEN (routing_metrics.failures::numeric / routing_metrics.total_decisions::numeric) * 100
            ELSE 0
        END,
        2
    ) as failure_rate_pct
FROM metrics, routing_metrics;

\echo ''
\echo '=== END OF ROUTING METRICS REPORT ==='
\echo ''
