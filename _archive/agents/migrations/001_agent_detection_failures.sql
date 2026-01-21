-- Migration: Agent Detection Failures Tracking
-- Purpose: Track failed, missed, or low-confidence agent detections for system improvement
-- Created: 2025-10-19

-- ============================================================================
-- Agent Detection Failures Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_detection_failures (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Correlation and Context
    correlation_id UUID NOT NULL,
    session_id VARCHAR(255),
    user_id VARCHAR(255),

    -- User Prompt Information
    user_prompt TEXT NOT NULL,
    prompt_length INTEGER NOT NULL,
    prompt_hash VARCHAR(64),  -- SHA-256 hash for deduplication

    -- Detection Result
    detection_status VARCHAR(50) NOT NULL CHECK (detection_status IN (
        'no_detection',      -- No agent detected at all
        'low_confidence',    -- Agent detected but confidence < threshold
        'wrong_agent',       -- Agent detected but user indicated wrong choice
        'timeout',           -- Detection timed out
        'error'              -- Detection system error
    )),

    -- Detected Agent Info (if any)
    detected_agent VARCHAR(255),
    detection_confidence DECIMAL(5, 4),  -- 0.0000 to 1.0000
    detection_method VARCHAR(100),
    routing_duration_ms INTEGER,

    -- Failure Analysis
    failure_reason TEXT,  -- Why detection failed (from system)
    failure_category VARCHAR(100),  -- Categorize for reporting
    expected_agent VARCHAR(255),  -- What agent SHOULD have been selected (manual review)

    -- Detection Metadata
    trigger_matches JSONB DEFAULT '[]'::jsonb,  -- Triggers that were evaluated
    capability_scores JSONB DEFAULT '{}'::jsonb,  -- Capability matching scores
    fuzzy_match_results JSONB DEFAULT '[]'::jsonb,  -- Fuzzy matching details
    detection_metadata JSONB DEFAULT '{}'::jsonb,  -- Additional debug info

    -- Intelligence Context
    rag_query_performed BOOLEAN DEFAULT FALSE,
    rag_results_count INTEGER DEFAULT 0,
    rag_intelligence_used BOOLEAN DEFAULT FALSE,

    -- Resolution Status
    reviewed BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(255),
    resolution_notes TEXT,

    -- Pattern Improvement
    pattern_updated BOOLEAN DEFAULT FALSE,
    pattern_update_type VARCHAR(100),  -- 'trigger_added', 'capability_enhanced', 'new_agent_created'
    pattern_update_details JSONB,

    -- Indexes for efficient querying
    CONSTRAINT unique_correlation_id_failure UNIQUE (correlation_id)
);

-- ============================================================================
-- Indexes
-- ============================================================================

-- Query by detection status
CREATE INDEX idx_detection_failures_status ON agent_detection_failures(detection_status)
    WHERE reviewed = FALSE;

-- Query by detected agent (to see which agents frequently misfire)
CREATE INDEX idx_detection_failures_agent ON agent_detection_failures(detected_agent)
    WHERE detected_agent IS NOT NULL;

-- Query by confidence (to find borderline cases)
CREATE INDEX idx_detection_failures_confidence ON agent_detection_failures(detection_confidence)
    WHERE detection_confidence IS NOT NULL;

-- Time-based queries
CREATE INDEX idx_detection_failures_created_at ON agent_detection_failures(created_at DESC);

-- Unreviewed failures (for manual review workflow)
CREATE INDEX idx_detection_failures_unreviewed ON agent_detection_failures(reviewed, created_at DESC)
    WHERE reviewed = FALSE;

-- Prompt hash for deduplication
CREATE INDEX idx_detection_failures_prompt_hash ON agent_detection_failures(prompt_hash)
    WHERE prompt_hash IS NOT NULL;

-- GIN index for JSONB searches
CREATE INDEX idx_detection_failures_metadata ON agent_detection_failures USING GIN (detection_metadata);
CREATE INDEX idx_detection_failures_triggers ON agent_detection_failures USING GIN (trigger_matches);

-- ============================================================================
-- Detection Patterns View
-- ============================================================================
CREATE OR REPLACE VIEW agent_detection_failure_patterns AS
SELECT
    detection_status,
    detected_agent,
    failure_category,
    COUNT(*) as failure_count,
    AVG(detection_confidence) as avg_confidence,
    AVG(routing_duration_ms) as avg_routing_ms,
    COUNT(*) FILTER (WHERE reviewed = TRUE) as reviewed_count,
    COUNT(*) FILTER (WHERE pattern_updated = TRUE) as patterns_improved,
    MIN(created_at) as first_occurrence,
    MAX(created_at) as last_occurrence
FROM agent_detection_failures
GROUP BY detection_status, detected_agent, failure_category
ORDER BY failure_count DESC;

-- ============================================================================
-- Unreviewed Failures Summary
-- ============================================================================
CREATE OR REPLACE VIEW agent_detection_failures_to_review AS
SELECT
    id,
    created_at,
    detection_status,
    detected_agent,
    detection_confidence,
    LEFT(user_prompt, 100) as prompt_preview,
    failure_reason,
    correlation_id
FROM agent_detection_failures
WHERE reviewed = FALSE
ORDER BY created_at DESC
LIMIT 100;

-- ============================================================================
-- Low Confidence Detections (Needs Review)
-- ============================================================================
CREATE OR REPLACE VIEW agent_low_confidence_detections AS
SELECT
    id,
    created_at,
    detected_agent,
    detection_confidence,
    detection_method,
    LEFT(user_prompt, 100) as prompt_preview,
    failure_reason,
    correlation_id
FROM agent_detection_failures
WHERE detection_status = 'low_confidence'
  AND detection_confidence < 0.85
  AND reviewed = FALSE
ORDER BY detection_confidence ASC, created_at DESC
LIMIT 50;

-- ============================================================================
-- Helper Functions
-- ============================================================================

-- Function to mark failure as reviewed
CREATE OR REPLACE FUNCTION mark_detection_failure_reviewed(
    p_id BIGINT,
    p_reviewed_by VARCHAR(255),
    p_expected_agent VARCHAR(255) DEFAULT NULL,
    p_resolution_notes TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE agent_detection_failures
    SET
        reviewed = TRUE,
        reviewed_at = NOW(),
        reviewed_by = p_reviewed_by,
        expected_agent = COALESCE(p_expected_agent, expected_agent),
        resolution_notes = p_resolution_notes,
        updated_at = NOW()
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Function to record pattern improvement
CREATE OR REPLACE FUNCTION mark_pattern_improved(
    p_id BIGINT,
    p_update_type VARCHAR(100),
    p_update_details JSONB DEFAULT '{}'::jsonb
)
RETURNS VOID AS $$
BEGIN
    UPDATE agent_detection_failures
    SET
        pattern_updated = TRUE,
        pattern_update_type = p_update_type,
        pattern_update_details = p_update_details,
        updated_at = NOW()
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get similar failed prompts (for pattern identification)
CREATE OR REPLACE FUNCTION find_similar_detection_failures(
    p_prompt_text TEXT,
    p_similarity_threshold DECIMAL DEFAULT 0.7,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    id BIGINT,
    user_prompt TEXT,
    detection_status VARCHAR(50),
    detected_agent VARCHAR(255),
    similarity_score DECIMAL
) AS $$
BEGIN
    -- This is a placeholder - would use pg_trgm or vector similarity in production
    RETURN QUERY
    SELECT
        f.id,
        f.user_prompt,
        f.detection_status,
        f.detected_agent,
        0.8 as similarity_score  -- Placeholder
    FROM agent_detection_failures f
    WHERE f.prompt_hash IS NOT NULL
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Statistics Function
-- ============================================================================
CREATE OR REPLACE FUNCTION get_detection_failure_stats(
    p_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    total_failures BIGINT,
    no_detection_count BIGINT,
    low_confidence_count BIGINT,
    wrong_agent_count BIGINT,
    timeout_count BIGINT,
    error_count BIGINT,
    avg_confidence DECIMAL,
    reviewed_count BIGINT,
    patterns_improved_count BIGINT,
    unreviewed_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*) as total_failures,
        COUNT(*) FILTER (WHERE detection_status = 'no_detection') as no_detection_count,
        COUNT(*) FILTER (WHERE detection_status = 'low_confidence') as low_confidence_count,
        COUNT(*) FILTER (WHERE detection_status = 'wrong_agent') as wrong_agent_count,
        COUNT(*) FILTER (WHERE detection_status = 'timeout') as timeout_count,
        COUNT(*) FILTER (WHERE detection_status = 'error') as error_count,
        AVG(detection_confidence) FILTER (WHERE detection_confidence IS NOT NULL) as avg_confidence,
        COUNT(*) FILTER (WHERE reviewed = TRUE) as reviewed_count,
        COUNT(*) FILTER (WHERE pattern_updated = TRUE) as patterns_improved_count,
        COUNT(*) FILTER (WHERE reviewed = FALSE) as unreviewed_count
    FROM agent_detection_failures
    WHERE created_at > NOW() - (p_hours || ' hours')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Comments
-- ============================================================================
COMMENT ON TABLE agent_detection_failures IS 'Tracks failed, missed, or low-confidence agent detections for system improvement and pattern learning';
COMMENT ON COLUMN agent_detection_failures.detection_status IS 'Type of detection failure: no_detection, low_confidence, wrong_agent, timeout, or error';
COMMENT ON COLUMN agent_detection_failures.expected_agent IS 'Agent that should have been selected (determined during manual review)';
COMMENT ON COLUMN agent_detection_failures.pattern_updated IS 'Whether this failure led to pattern/trigger improvements';
COMMENT ON VIEW agent_detection_failure_patterns IS 'Aggregated view of detection failure patterns for analysis';
COMMENT ON VIEW agent_detection_failures_to_review IS 'Unreviewed detection failures requiring manual analysis';
COMMENT ON VIEW agent_low_confidence_detections IS 'Detections with confidence <85% that need review';

-- ============================================================================
-- Grant Permissions (adjust as needed for your setup)
-- ============================================================================
-- GRANT SELECT, INSERT, UPDATE ON agent_detection_failures TO omninode_app;
-- GRANT SELECT ON agent_detection_failure_patterns TO omninode_app;
-- GRANT SELECT ON agent_detection_failures_to_review TO omninode_app;
-- GRANT SELECT ON agent_low_confidence_detections TO omninode_app;
