-- seed_observability.sql
-- Generates ~300 synthetic routing decisions with correlated manifest injections
-- and transformation events for dashboard development
--
-- Usage:
--   docker exec -i omniclaude_postgres psql -U omniclaude -d omniclaude < scripts/seed_observability.sql
--
-- To clear:
--   TRUNCATE agent_routing_decisions CASCADE;

BEGIN;

-- ============================================================================
-- Seed agent_routing_decisions (~300 rows)
-- ============================================================================

INSERT INTO agent_routing_decisions (
    correlation_id,
    session_id,
    user_request,
    user_request_hash,
    selected_agent,
    confidence_score,
    routing_strategy,
    trigger_confidence,
    context_confidence,
    capability_confidence,
    historical_confidence,
    alternatives,
    alternatives_count,
    reasoning,
    matched_triggers,
    matched_capabilities,
    routing_time_ms,
    cache_hit,
    selection_validated,
    actual_success,
    actual_quality_score,
    created_at
)
SELECT
    gen_random_uuid() AS correlation_id,
    -- Group into ~30 sessions (10 requests per session on average)
    (ARRAY(SELECT gen_random_uuid() FROM generate_series(1, 30)))[1 + (i % 30)] AS session_id,
    -- Realistic user requests
    (ARRAY[
        'Help me refactor the authentication module to use JWT tokens',
        'Fix the bug in the payment processing flow',
        'Create a new API endpoint for user preferences',
        'Write unit tests for the order service',
        'Optimize the database queries in the reporting module',
        'Add logging to the notification service',
        'Review the PR for the new feature branch',
        'Debug the memory leak in the background worker',
        'Implement caching for the product catalog',
        'Set up CI/CD pipeline for the microservice',
        'Analyze the performance bottleneck in search',
        'Create a dashboard for monitoring metrics',
        'Migrate the legacy code to TypeScript',
        'Add error handling to the file upload service',
        'Document the API endpoints for the mobile app',
        'Implement rate limiting for the public API',
        'Fix the flaky integration tests',
        'Add validation to the user registration form',
        'Optimize the image processing pipeline',
        'Create a webhook handler for Stripe events'
    ])[1 + (i % 20)] AS user_request,
    encode(sha256(('request-' || i)::bytea), 'hex') AS user_request_hash,
    -- Agent distribution: polymorphic gets ~30%, others distributed
    (ARRAY[
        'polymorphic-agent',
        'polymorphic-agent',
        'polymorphic-agent',
        'python-fastapi-expert',
        'python-fastapi-expert',
        'debug-intelligence',
        'debug-intelligence',
        'testing-agent',
        'pr-review-agent',
        'ticket-manager'
    ])[1 + (i % 10)] AS selected_agent,
    -- Confidence scores: mostly high (0.75-0.98) with some lower
    ROUND((0.75 + random() * 0.23)::numeric, 4) AS confidence_score,
    -- Routing strategies
    (ARRAY[
        'enhanced_fuzzy_matching',
        'enhanced_fuzzy_matching',
        'enhanced_fuzzy_matching',
        'explicit',
        'fallback'
    ])[1 + (i % 5)] AS routing_strategy,
    -- Component confidences
    ROUND((0.70 + random() * 0.28)::numeric, 4) AS trigger_confidence,
    ROUND((0.65 + random() * 0.30)::numeric, 4) AS context_confidence,
    ROUND((0.75 + random() * 0.23)::numeric, 4) AS capability_confidence,
    ROUND((0.80 + random() * 0.18)::numeric, 4) AS historical_confidence,
    -- Alternatives JSON
    jsonb_build_array(
        jsonb_build_object(
            'agent', (ARRAY['debug-intelligence', 'testing-agent', 'pr-review-agent'])[1 + (i % 3)],
            'confidence', ROUND((0.60 + random() * 0.25)::numeric, 4),
            'reason', 'Secondary match based on capability overlap'
        ),
        jsonb_build_object(
            'agent', (ARRAY['ticket-manager', 'polymorphic-agent', 'python-fastapi-expert'])[1 + (i % 3)],
            'confidence', ROUND((0.50 + random() * 0.20)::numeric, 4),
            'reason', 'Tertiary match based on historical patterns'
        )
    ) AS alternatives,
    2 AS alternatives_count,
    -- Reasoning
    'Selected based on trigger match and high historical success rate for similar requests' AS reasoning,
    -- Matched triggers (use CASE to return proper text[] type)
    CASE (i % 5)
        WHEN 0 THEN ARRAY['refactor', 'code', 'module']
        WHEN 1 THEN ARRAY['fix', 'bug', 'debug']
        WHEN 2 THEN ARRAY['create', 'api', 'endpoint']
        WHEN 3 THEN ARRAY['test', 'unit', 'coverage']
        ELSE ARRAY['optimize', 'performance', 'query']
    END AS matched_triggers,
    -- Matched capabilities
    CASE (i % 5)
        WHEN 0 THEN ARRAY['code_refactoring', 'python_expert']
        WHEN 1 THEN ARRAY['debugging', 'error_analysis']
        WHEN 2 THEN ARRAY['api_design', 'fastapi']
        WHEN 3 THEN ARRAY['testing', 'pytest']
        ELSE ARRAY['performance_optimization', 'sql']
    END AS matched_capabilities,
    -- Routing time: mostly fast (5-15ms) with some slower
    (5 + (random() * 10)::int + CASE WHEN i % 20 = 0 THEN 50 ELSE 0 END) AS routing_time_ms,
    -- Cache hits: ~40%
    (i % 5 < 2) AS cache_hit,
    -- Validation: ~80% validated
    (i % 5 != 0) AS selection_validated,
    -- Success: ~90% of validated ones succeeded
    CASE WHEN i % 5 != 0 THEN (i % 10 != 0) ELSE NULL END AS actual_success,
    -- Quality scores for successful ones
    CASE WHEN i % 5 != 0 AND i % 10 != 0 THEN ROUND((0.80 + random() * 0.18)::numeric, 4) ELSE NULL END AS actual_quality_score,
    -- Spread over last 7 days
    NOW() - (random() * INTERVAL '7 days') AS created_at
FROM generate_series(1, 300) AS i;

-- ============================================================================
-- Seed agent_manifest_injections (one per routing decision)
-- ============================================================================

INSERT INTO agent_manifest_injections (
    correlation_id,
    session_id,
    routing_decision_id,
    agent_name,
    agent_version,
    manifest_version,
    generation_source,
    is_fallback,
    sections_included,
    patterns_count,
    infrastructure_services,
    models_count,
    database_schemas_count,
    debug_intelligence_successes,
    debug_intelligence_failures,
    query_times,
    total_query_time_ms,
    cache_hit,
    full_manifest_snapshot,
    manifest_size_bytes,
    intelligence_available,
    agent_execution_success,
    agent_execution_time_ms,
    agent_quality_score,
    created_at
)
SELECT
    ard.correlation_id,
    ard.session_id,
    ard.id AS routing_decision_id,
    ard.selected_agent AS agent_name,
    '1.0.0' AS agent_version,
    '2.0.0' AS manifest_version,
    CASE WHEN random() < 0.9 THEN 'archon-intelligence-adapter' ELSE 'fallback' END AS generation_source,
    (random() < 0.1) AS is_fallback,
    ARRAY['patterns', 'infrastructure', 'models', 'schemas', 'debug_intelligence'] AS sections_included,
    (30 + (random() * 70)::int) AS patterns_count,
    (3 + (random() * 5)::int) AS infrastructure_services,
    (2 + (random() * 4)::int) AS models_count,
    (5 + (random() * 10)::int) AS database_schemas_count,
    (5 + (random() * 15)::int) AS debug_intelligence_successes,
    (0 + (random() * 5)::int) AS debug_intelligence_failures,
    jsonb_build_object(
        'patterns', (100 + (random() * 200)::int),
        'infrastructure', (50 + (random() * 100)::int),
        'models', (20 + (random() * 50)::int),
        'schemas', (30 + (random() * 70)::int),
        'debug_intelligence', (100 + (random() * 300)::int)
    ) AS query_times,
    (300 + (random() * 500)::int) AS total_query_time_ms,
    ard.cache_hit,
    jsonb_build_object(
        'version', '2.0.0',
        'agent', ard.selected_agent,
        'patterns', jsonb_build_array('pattern1', 'pattern2', 'pattern3'),
        'infrastructure', jsonb_build_object('services', 5, 'healthy', true),
        'generated_at', NOW()
    ) AS full_manifest_snapshot,
    (8000 + (random() * 4000)::int) AS manifest_size_bytes,
    true AS intelligence_available,
    ard.actual_success AS agent_execution_success,
    CASE WHEN ard.actual_success IS NOT NULL THEN (1000 + (random() * 5000)::int) ELSE NULL END AS agent_execution_time_ms,
    ard.actual_quality_score AS agent_quality_score,
    ard.created_at + INTERVAL '100 milliseconds' AS created_at
FROM agent_routing_decisions ard;

-- ============================================================================
-- Seed agent_transformation_events (one per routing decision)
-- ============================================================================

INSERT INTO agent_transformation_events (
    event_type,
    correlation_id,
    session_id,
    source_agent,
    target_agent,
    transformation_reason,
    context_snapshot,
    routing_confidence,
    routing_strategy,
    transformation_duration_ms,
    initialization_duration_ms,
    total_execution_duration_ms,
    success,
    quality_score,
    started_at,
    completed_at
)
SELECT
    'agent_transformation' AS event_type,
    ard.correlation_id,
    ard.session_id,
    'polymorphic-agent' AS source_agent,
    ard.selected_agent AS target_agent,
    'Routing decision triggered transformation to specialized agent' AS transformation_reason,
    jsonb_build_object(
        'user_request_length', length(ard.user_request),
        'matched_triggers_count', array_length(ard.matched_triggers, 1)
    ) AS context_snapshot,
    ard.confidence_score AS routing_confidence,
    ard.routing_strategy,
    (10 + (random() * 30)::int) AS transformation_duration_ms,
    (50 + (random() * 100)::int) AS initialization_duration_ms,
    CASE WHEN ard.actual_success IS NOT NULL THEN (1000 + (random() * 5000)::int) ELSE NULL END AS total_execution_duration_ms,
    ard.actual_success AS success,
    ard.actual_quality_score AS quality_score,
    ard.created_at + INTERVAL '50 milliseconds' AS started_at,
    CASE WHEN ard.actual_success IS NOT NULL
         THEN ard.created_at + INTERVAL '50 milliseconds' + ((1000 + (random() * 5000)::int) * INTERVAL '1 millisecond')
         ELSE NULL
    END AS completed_at
FROM agent_routing_decisions ard;

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================

SELECT 'agent_routing_decisions' AS table_name, COUNT(*) AS row_count FROM agent_routing_decisions
UNION ALL
SELECT 'agent_manifest_injections', COUNT(*) FROM agent_manifest_injections
UNION ALL
SELECT 'agent_transformation_events', COUNT(*) FROM agent_transformation_events;

-- Sample data check
SELECT
    selected_agent,
    COUNT(*) AS decisions,
    ROUND(AVG(confidence_score), 3) AS avg_confidence,
    ROUND(AVG(routing_time_ms), 1) AS avg_routing_ms
FROM agent_routing_decisions
GROUP BY selected_agent
ORDER BY decisions DESC;
