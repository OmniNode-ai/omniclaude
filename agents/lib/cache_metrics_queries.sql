-- Cache Metrics Database Queries
-- ===============================
-- Common queries for analyzing router cache performance

-- 1. Overall Cache Hit Rate (Last 24 Hours)
-- -----------------------------------------
SELECT
    COUNT(*) as total_routes,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    SUM(CASE WHEN NOT cache_hit THEN 1 ELSE 0 END) as cache_misses,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '24 hours';

-- 2. Cache Hit Rate by Time Period
-- --------------------------------
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as total_routes,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

-- 3. Routing Performance by Strategy
-- ----------------------------------
SELECT
    trigger_match_strategy,
    COUNT(*) as count,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY routing_duration_ms), 2) as median_duration_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY routing_duration_ms), 2) as p95_duration_ms,
    MIN(routing_duration_ms) as min_duration_ms,
    MAX(routing_duration_ms) as max_duration_ms
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY trigger_match_strategy
ORDER BY count DESC;

-- 4. Most Common Queries (Last 7 Days)
-- ------------------------------------
SELECT
    query_text,
    COUNT(*) as frequency,
    BOOL_OR(cache_hit) as ever_cached,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms,
    ROUND(AVG(candidates_evaluated), 2) as avg_candidates
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY query_text
ORDER BY frequency DESC
LIMIT 20;

-- 5. Cache Effectiveness by Query Pattern
-- ---------------------------------------
WITH query_patterns AS (
    SELECT
        query_text,
        COUNT(*) as total_requests,
        SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
        ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct
    FROM router_performance_metrics
    WHERE created_at > NOW() - INTERVAL '24 hours'
    GROUP BY query_text
    HAVING COUNT(*) > 1
)
SELECT *
FROM query_patterns
ORDER BY total_requests DESC, hit_rate_pct DESC
LIMIT 20;

-- 6. Slowest Queries (Last 24 Hours)
-- ----------------------------------
SELECT
    query_text,
    routing_duration_ms,
    trigger_match_strategy,
    candidates_evaluated,
    cache_hit,
    created_at
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY routing_duration_ms DESC
LIMIT 20;

-- 7. Confidence Score Distribution
-- --------------------------------
SELECT
    trigger_match_strategy,
    COUNT(*) as count,
    ROUND(AVG((confidence_components->>'total')::numeric), 3) as avg_confidence,
    ROUND(MIN((confidence_components->>'total')::numeric), 3) as min_confidence,
    ROUND(MAX((confidence_components->>'total')::numeric), 3) as max_confidence
FROM router_performance_metrics
WHERE
    created_at > NOW() - INTERVAL '24 hours'
    AND confidence_components ? 'total'
GROUP BY trigger_match_strategy
ORDER BY count DESC;

-- 8. Daily Cache Performance Trend
-- --------------------------------
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_routes,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- 9. Recent Cache Misses Analysis
-- -------------------------------
SELECT
    query_text,
    trigger_match_strategy,
    candidates_evaluated,
    routing_duration_ms,
    confidence_components->>'total' as confidence,
    created_at
FROM router_performance_metrics
WHERE
    cache_hit = false
    AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 50;

-- 10. Cache Performance Summary (All Time)
-- ----------------------------------------
SELECT
    'Overall' as metric,
    COUNT(*) as total_routes,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms,
    MIN(created_at) as first_logged,
    MAX(created_at) as last_logged
FROM router_performance_metrics;

-- 11. Hourly Request Volume
-- -------------------------
SELECT
    EXTRACT(HOUR FROM created_at) as hour_of_day,
    COUNT(*) as total_requests,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY EXTRACT(HOUR FROM created_at)
ORDER BY hour_of_day;

-- 12. Queries That Never Hit Cache
-- --------------------------------
SELECT
    query_text,
    COUNT(*) as attempts,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms,
    ROUND(AVG(candidates_evaluated), 2) as avg_candidates
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY query_text
HAVING BOOL_OR(cache_hit) = false AND COUNT(*) > 1
ORDER BY attempts DESC
LIMIT 20;

-- 13. Cache Hit Rate by Confidence Score Range
-- --------------------------------------------
SELECT
    CASE
        WHEN (confidence_components->>'total')::numeric >= 0.9 THEN '0.9-1.0 (High)'
        WHEN (confidence_components->>'total')::numeric >= 0.7 THEN '0.7-0.9 (Medium)'
        WHEN (confidence_components->>'total')::numeric >= 0.5 THEN '0.5-0.7 (Low)'
        ELSE '<0.5 (Very Low)'
    END as confidence_range,
    COUNT(*) as count,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_pct
FROM router_performance_metrics
WHERE
    created_at > NOW() - INTERVAL '24 hours'
    AND confidence_components ? 'total'
GROUP BY confidence_range
ORDER BY confidence_range;

-- 14. Performance Impact of Cache Hits vs Misses
-- ----------------------------------------------
SELECT
    cache_hit,
    COUNT(*) as count,
    ROUND(AVG(routing_duration_ms), 2) as avg_duration_ms,
    ROUND(STDDEV(routing_duration_ms), 2) as stddev_duration_ms,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY routing_duration_ms), 2) as median_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY routing_duration_ms), 2) as p95_ms,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY routing_duration_ms), 2) as p99_ms
FROM router_performance_metrics
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY cache_hit
ORDER BY cache_hit DESC;

-- 15. Recent Activity (Last 100 Routes)
-- -------------------------------------
SELECT
    query_text,
    cache_hit,
    routing_duration_ms,
    trigger_match_strategy,
    candidates_evaluated,
    TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as timestamp
FROM router_performance_metrics
ORDER BY created_at DESC
LIMIT 100;
