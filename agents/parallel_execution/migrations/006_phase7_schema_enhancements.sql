-- Migration: 006_phase7_schema_enhancements
-- Description: Phase 7 refinement - Add tables for mixin learning, pattern feedback, performance metrics, template caching, and event processing
-- Author: agent-workflow-coordinator
-- Created: 2025-10-15
-- ONEX Compliance: Effect/Reducer node patterns for ML learning and performance optimization
-- Target: <50ms write performance for all operations

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: Create New Tables (in dependency order)
-- =============================================================================

-- Table 1: mixin_compatibility_matrix
-- Purpose: Track mixin combinations and compatibility for ML learning
-- ONEX Pattern: Reducer node (aggregation and learning)
CREATE TABLE IF NOT EXISTS mixin_compatibility_matrix (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Mixin identification
  mixin_a VARCHAR(100) NOT NULL,
  mixin_b VARCHAR(100) NOT NULL,
  node_type VARCHAR(50) NOT NULL,

  -- Compatibility metrics
  compatibility_score NUMERIC(5,4) CHECK (compatibility_score >= 0.0 AND compatibility_score <= 1.0),
  success_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,

  -- Learning metadata
  last_tested_at TIMESTAMPTZ,
  conflict_reason TEXT,
  resolution_pattern TEXT,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- Constraints
  CONSTRAINT mixin_compatibility_matrix_unique
    UNIQUE(mixin_a, mixin_b, node_type),
  CONSTRAINT mixin_compatibility_matrix_node_type_check
    CHECK (node_type IN ('EFFECT', 'COMPUTE', 'REDUCER', 'ORCHESTRATOR'))
);

-- Indexes for mixin_compatibility_matrix
CREATE INDEX idx_mixin_compat_score
  ON mixin_compatibility_matrix(compatibility_score DESC);

CREATE INDEX idx_mixin_compat_node_type
  ON mixin_compatibility_matrix(node_type);

CREATE INDEX idx_mixin_compat_mixins
  ON mixin_compatibility_matrix(mixin_a, mixin_b);

CREATE INDEX idx_mixin_compat_updated
  ON mixin_compatibility_matrix(updated_at DESC);

COMMENT ON TABLE mixin_compatibility_matrix IS
  'Tracks mixin combinations and compatibility for ML learning. ONEX Reducer node.';
COMMENT ON COLUMN mixin_compatibility_matrix.compatibility_score IS
  'ML-calculated compatibility score (0.0-1.0) based on success/failure patterns';
COMMENT ON COLUMN mixin_compatibility_matrix.resolution_pattern IS
  'Learned pattern for resolving conflicts between these mixins';

-- Table 2: pattern_feedback_log
-- Purpose: Store pattern matching feedback for learning loop
-- ONEX Pattern: Effect node (event persistence)
CREATE TABLE IF NOT EXISTS pattern_feedback_log (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  session_id UUID NOT NULL,
  pattern_name VARCHAR(100) NOT NULL,

  -- Pattern detection
  detected_confidence NUMERIC(5,4) CHECK (detected_confidence IS NULL OR (detected_confidence >= 0.0 AND detected_confidence <= 1.0)),
  actual_pattern VARCHAR(100),
  feedback_type VARCHAR(50) NOT NULL,

  -- Feedback source
  user_provided BOOLEAN DEFAULT FALSE,

  -- Pattern details
  contract_json JSONB,
  capabilities_matched TEXT[],
  false_positives TEXT[],
  false_negatives TEXT[],

  -- Learning weight
  learning_weight NUMERIC(5,4) DEFAULT 1.0 CHECK (learning_weight >= 0.0 AND learning_weight <= 1.0),

  -- Timestamp
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Constraints
  CONSTRAINT pattern_feedback_log_type_check
    CHECK (feedback_type IN ('correct', 'incorrect', 'partial', 'adjusted'))
);

-- Indexes for pattern_feedback_log
CREATE INDEX idx_pattern_feedback_session
  ON pattern_feedback_log(session_id);

CREATE INDEX idx_pattern_feedback_pattern
  ON pattern_feedback_log(pattern_name);

CREATE INDEX idx_pattern_feedback_type
  ON pattern_feedback_log(feedback_type);

CREATE INDEX idx_pattern_feedback_created
  ON pattern_feedback_log(created_at DESC);

CREATE INDEX idx_pattern_feedback_user
  ON pattern_feedback_log(user_provided)
  WHERE user_provided = TRUE;

CREATE INDEX idx_pattern_feedback_contract
  ON pattern_feedback_log USING GIN(contract_json);

COMMENT ON TABLE pattern_feedback_log IS
  'Stores pattern matching feedback for continuous learning. ONEX Effect node.';
COMMENT ON COLUMN pattern_feedback_log.learning_weight IS
  'Weight for ML training (user feedback has higher weight)';

-- Table 3: generation_performance_metrics
-- Purpose: Detailed performance tracking for generation phases
-- ONEX Pattern: Effect node (metrics persistence)
CREATE TABLE IF NOT EXISTS generation_performance_metrics (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  session_id UUID NOT NULL,
  node_type VARCHAR(50) NOT NULL,
  phase VARCHAR(50) NOT NULL,

  -- Performance metrics
  duration_ms INTEGER NOT NULL,
  memory_usage_mb INTEGER,
  cpu_percent NUMERIC(5,2),

  -- Execution context
  cache_hit BOOLEAN DEFAULT FALSE,
  parallel_execution BOOLEAN DEFAULT FALSE,
  worker_count INTEGER DEFAULT 1,

  -- Additional metadata
  metadata JSONB,

  -- Timestamp
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Constraints
  CONSTRAINT generation_performance_metrics_duration_check
    CHECK (duration_ms >= 0),
  CONSTRAINT generation_performance_metrics_workers_check
    CHECK (worker_count >= 1),
  CONSTRAINT generation_performance_metrics_phase_check
    CHECK (phase IN ('prd_analysis', 'template_load', 'code_gen', 'validation', 'persistence', 'total'))
);

-- Indexes for generation_performance_metrics
CREATE INDEX idx_gen_perf_session
  ON generation_performance_metrics(session_id);

CREATE INDEX idx_gen_perf_phase
  ON generation_performance_metrics(phase);

CREATE INDEX idx_gen_perf_duration
  ON generation_performance_metrics(duration_ms DESC);

CREATE INDEX idx_gen_perf_node_type
  ON generation_performance_metrics(node_type);

CREATE INDEX idx_gen_perf_cache
  ON generation_performance_metrics(cache_hit)
  WHERE cache_hit = TRUE;

CREATE INDEX idx_gen_perf_parallel
  ON generation_performance_metrics(parallel_execution)
  WHERE parallel_execution = TRUE;

CREATE INDEX idx_gen_perf_created
  ON generation_performance_metrics(created_at DESC);

CREATE INDEX idx_gen_perf_metadata
  ON generation_performance_metrics USING GIN(metadata);

COMMENT ON TABLE generation_performance_metrics IS
  'Tracks detailed performance metrics for code generation phases. ONEX Effect node.';
COMMENT ON COLUMN generation_performance_metrics.phase IS
  'Generation phase: prd_analysis, template_load, code_gen, validation, persistence, total';

-- Table 4: template_cache_metadata
-- Purpose: Template caching statistics for optimization
-- ONEX Pattern: Effect node (cache metrics)
CREATE TABLE IF NOT EXISTS template_cache_metadata (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Template identification
  template_name VARCHAR(200) NOT NULL UNIQUE,
  template_type VARCHAR(50) NOT NULL,
  cache_key VARCHAR(500) NOT NULL,

  -- File metadata
  file_path TEXT NOT NULL,
  file_hash VARCHAR(64) NOT NULL,
  size_bytes INTEGER,

  -- Performance metrics
  load_time_ms INTEGER,
  last_accessed_at TIMESTAMPTZ,
  access_count INTEGER DEFAULT 0,
  cache_hits INTEGER DEFAULT 0,
  cache_misses INTEGER DEFAULT 0,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- Constraints
  CONSTRAINT template_cache_metadata_counts_check
    CHECK (access_count >= 0 AND cache_hits >= 0 AND cache_misses >= 0),
  CONSTRAINT template_cache_metadata_type_check
    CHECK (template_type IN ('node', 'contract', 'subcontract', 'mixin', 'test'))
);

-- Indexes for template_cache_metadata
CREATE INDEX idx_template_cache_name
  ON template_cache_metadata(template_name);

CREATE INDEX idx_template_cache_type
  ON template_cache_metadata(template_type);

CREATE INDEX idx_template_cache_accessed
  ON template_cache_metadata(last_accessed_at DESC);

CREATE INDEX idx_template_cache_hits
  ON template_cache_metadata(cache_hits DESC);

CREATE INDEX idx_template_cache_hash
  ON template_cache_metadata(file_hash);

COMMENT ON TABLE template_cache_metadata IS
  'Tracks template caching statistics for performance optimization. ONEX Effect node.';
COMMENT ON COLUMN template_cache_metadata.file_hash IS
  'SHA-256 hash for cache invalidation on template changes';

-- Table 5: event_processing_metrics
-- Purpose: Event processing performance data for optimization
-- ONEX Pattern: Effect node (event metrics)
CREATE TABLE IF NOT EXISTS event_processing_metrics (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Event identification
  event_type VARCHAR(100) NOT NULL,
  event_source VARCHAR(100) NOT NULL,

  -- Performance metrics
  processing_duration_ms INTEGER NOT NULL,
  queue_wait_time_ms INTEGER,

  -- Execution outcome
  success BOOLEAN NOT NULL,
  error_type VARCHAR(100),
  error_message TEXT,
  retry_count INTEGER DEFAULT 0,

  -- Batch processing
  batch_size INTEGER DEFAULT 1,

  -- Timestamp
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Constraints
  CONSTRAINT event_processing_metrics_duration_check
    CHECK (processing_duration_ms >= 0),
  CONSTRAINT event_processing_metrics_retry_check
    CHECK (retry_count >= 0),
  CONSTRAINT event_processing_metrics_batch_check
    CHECK (batch_size >= 1)
);

-- Indexes for event_processing_metrics
CREATE INDEX idx_event_proc_type
  ON event_processing_metrics(event_type);

CREATE INDEX idx_event_proc_source
  ON event_processing_metrics(event_source);

CREATE INDEX idx_event_proc_success
  ON event_processing_metrics(success);

CREATE INDEX idx_event_proc_created
  ON event_processing_metrics(created_at DESC);

CREATE INDEX idx_event_proc_duration
  ON event_processing_metrics(processing_duration_ms DESC);

CREATE INDEX idx_event_proc_errors
  ON event_processing_metrics(error_type)
  WHERE error_type IS NOT NULL;

COMMENT ON TABLE event_processing_metrics IS
  'Tracks event processing performance for optimization. ONEX Effect node.';

-- =============================================================================
-- STEP 2: Create Views for Analytics
-- =============================================================================

-- View: Mixin compatibility summary
CREATE OR REPLACE VIEW mixin_compatibility_summary AS
SELECT
  node_type,
  count(*) as total_combinations,
  round(avg(compatibility_score)::numeric, 3) as avg_compatibility,
  sum(success_count) as total_successes,
  sum(failure_count) as total_failures,
  round((sum(success_count)::numeric / NULLIF(sum(success_count + failure_count), 0))::numeric, 3) as success_rate
FROM mixin_compatibility_matrix
GROUP BY node_type
ORDER BY node_type;

COMMENT ON VIEW mixin_compatibility_summary IS
  'Aggregated mixin compatibility statistics by node type';

-- View: Pattern feedback analysis
CREATE OR REPLACE VIEW pattern_feedback_analysis AS
SELECT
  pattern_name,
  feedback_type,
  count(*) as feedback_count,
  round(avg(detected_confidence)::numeric, 3) as avg_confidence,
  sum(CASE WHEN user_provided THEN 1 ELSE 0 END) as user_provided_count,
  round(avg(learning_weight)::numeric, 3) as avg_learning_weight
FROM pattern_feedback_log
GROUP BY pattern_name, feedback_type
ORDER BY pattern_name, feedback_count DESC;

COMMENT ON VIEW pattern_feedback_analysis IS
  'Analyzes pattern matching feedback for learning optimization';

-- View: Performance metrics summary
CREATE OR REPLACE VIEW performance_metrics_summary AS
SELECT
  phase,
  count(*) as execution_count,
  round(avg(duration_ms)::numeric, 2) as avg_duration_ms,
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p95_duration_ms,
  round(percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)::numeric, 2) as p99_duration_ms,
  sum(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
  sum(CASE WHEN parallel_execution THEN 1 ELSE 0 END) as parallel_executions,
  round(avg(worker_count)::numeric, 1) as avg_workers
FROM generation_performance_metrics
GROUP BY phase
ORDER BY phase;

COMMENT ON VIEW performance_metrics_summary IS
  'Aggregated performance metrics with percentiles by phase';

-- View: Template cache efficiency
CREATE OR REPLACE VIEW template_cache_efficiency AS
SELECT
  template_type,
  count(*) as template_count,
  round(avg(cache_hits)::numeric, 1) as avg_cache_hits,
  round(avg(cache_misses)::numeric, 1) as avg_cache_misses,
  round((sum(cache_hits)::numeric / NULLIF(sum(cache_hits + cache_misses), 0))::numeric, 3) as hit_rate,
  round(avg(load_time_ms)::numeric, 2) as avg_load_time_ms,
  round(sum(size_bytes)::numeric / (1024 * 1024), 2) as total_size_mb
FROM template_cache_metadata
GROUP BY template_type
ORDER BY template_type;

COMMENT ON VIEW template_cache_efficiency IS
  'Template cache hit rates and efficiency metrics by type';

-- View: Event processing health
CREATE OR REPLACE VIEW event_processing_health AS
SELECT
  event_type,
  event_source,
  count(*) as total_events,
  sum(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
  sum(CASE WHEN NOT success THEN 1 ELSE 0 END) as failure_count,
  round((sum(CASE WHEN success THEN 1 ELSE 0 END)::numeric / count(*)::numeric)::numeric, 3) as success_rate,
  round(avg(processing_duration_ms)::numeric, 2) as avg_duration_ms,
  round(avg(queue_wait_time_ms)::numeric, 2) as avg_wait_ms,
  round(avg(retry_count)::numeric, 1) as avg_retries
FROM event_processing_metrics
GROUP BY event_type, event_source
ORDER BY total_events DESC;

COMMENT ON VIEW event_processing_health IS
  'Event processing health metrics with success rates and performance';

-- =============================================================================
-- STEP 3: Helper Functions
-- =============================================================================

-- Function: Update mixin compatibility
CREATE OR REPLACE FUNCTION update_mixin_compatibility(
  p_mixin_a VARCHAR,
  p_mixin_b VARCHAR,
  p_node_type VARCHAR,
  p_success BOOLEAN,
  p_conflict_reason TEXT DEFAULT NULL,
  p_resolution_pattern TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_new_score NUMERIC(5,4);
  v_total_tests INTEGER;
BEGIN
  -- Insert or update compatibility record
  INSERT INTO mixin_compatibility_matrix (
    mixin_a, mixin_b, node_type,
    success_count, failure_count,
    last_tested_at, conflict_reason, resolution_pattern
  ) VALUES (
    p_mixin_a, p_mixin_b, p_node_type,
    CASE WHEN p_success THEN 1 ELSE 0 END,
    CASE WHEN p_success THEN 0 ELSE 1 END,
    NOW(), p_conflict_reason, p_resolution_pattern
  )
  ON CONFLICT (mixin_a, mixin_b, node_type) DO UPDATE SET
    success_count = mixin_compatibility_matrix.success_count + CASE WHEN p_success THEN 1 ELSE 0 END,
    failure_count = mixin_compatibility_matrix.failure_count + CASE WHEN p_success THEN 0 ELSE 1 END,
    last_tested_at = NOW(),
    conflict_reason = COALESCE(p_conflict_reason, mixin_compatibility_matrix.conflict_reason),
    resolution_pattern = COALESCE(p_resolution_pattern, mixin_compatibility_matrix.resolution_pattern),
    updated_at = NOW()
  RETURNING id, success_count + failure_count INTO v_id, v_total_tests;

  -- Calculate new compatibility score
  v_new_score := (
    SELECT (success_count::numeric / NULLIF(success_count + failure_count, 0))
    FROM mixin_compatibility_matrix
    WHERE id = v_id
  );

  -- Update compatibility score
  UPDATE mixin_compatibility_matrix
  SET compatibility_score = v_new_score
  WHERE id = v_id;

  RETURN v_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mixin_compatibility IS
  'Updates mixin compatibility matrix with test results and recalculates score';

-- Function: Record pattern feedback
CREATE OR REPLACE FUNCTION record_pattern_feedback(
  p_session_id UUID,
  p_pattern_name VARCHAR,
  p_detected_confidence NUMERIC,
  p_actual_pattern VARCHAR,
  p_feedback_type VARCHAR,
  p_user_provided BOOLEAN DEFAULT FALSE,
  p_contract_json JSONB DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
  v_id UUID;
  v_learning_weight NUMERIC(5,4);
BEGIN
  -- User feedback has higher weight
  v_learning_weight := CASE WHEN p_user_provided THEN 1.0 ELSE 0.5 END;

  -- Insert feedback record
  INSERT INTO pattern_feedback_log (
    session_id, pattern_name, detected_confidence,
    actual_pattern, feedback_type, user_provided,
    contract_json, learning_weight
  ) VALUES (
    p_session_id, p_pattern_name, p_detected_confidence,
    p_actual_pattern, p_feedback_type, p_user_provided,
    p_contract_json, v_learning_weight
  )
  RETURNING id INTO v_id;

  RETURN v_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_pattern_feedback IS
  'Records pattern matching feedback with appropriate learning weight';

-- =============================================================================
-- STEP 4: Performance Optimization
-- =============================================================================

-- Analyze tables for query planner
ANALYZE mixin_compatibility_matrix;
ANALYZE pattern_feedback_log;
ANALYZE generation_performance_metrics;
ANALYZE template_cache_metadata;
ANALYZE event_processing_metrics;

-- =============================================================================
-- STEP 5: Record Migration
-- =============================================================================

-- Create schema_migrations table if it doesn't exist
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  description TEXT NOT NULL,
  execution_time_ms INTEGER,
  applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Record migration application
INSERT INTO schema_migrations (version, description, execution_time_ms)
VALUES (
  6,
  'Phase 7: Add mixin learning, pattern feedback, performance metrics, template caching, and event processing tables',
  EXTRACT(MILLISECONDS FROM NOW() - statement_timestamp())::INTEGER
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
