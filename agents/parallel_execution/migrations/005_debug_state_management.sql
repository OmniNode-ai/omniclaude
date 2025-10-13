-- Migration: 005_debug_state_management
-- Description: Add debug loop tables for state tracking and error/success analysis
-- Author: agent-workflow-coordinator
-- Created: 2025-10-11
-- ONEX Compliance: Effect/Reducer node patterns for debug observability
-- Target: <200ms query performance for all debug operations

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: Create New Tables (in dependency order)
-- =============================================================================

-- Table 1: debug_state_snapshots
-- Purpose: Capture agent state at critical points
-- ONEX Pattern: Effect node (persistence)
CREATE TABLE IF NOT EXISTS debug_state_snapshots (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  snapshot_type VARCHAR(50) NOT NULL,
  correlation_id UUID NOT NULL,
  session_id UUID,

  -- Agent context
  agent_name VARCHAR(255) NOT NULL,
  agent_state JSONB NOT NULL,
  state_hash VARCHAR(64) NOT NULL,

  -- Execution context
  execution_step INTEGER,
  task_description TEXT,
  user_request TEXT,

  -- State metadata
  state_size_bytes INTEGER,
  variables_count INTEGER,
  context_depth INTEGER,

  -- Performance
  memory_usage_mb DECIMAL(10,2),
  cpu_time_ms INTEGER,
  wall_time_ms INTEGER,

  -- Relationships
  transformation_event_id UUID,
  parent_snapshot_id UUID,

  -- Timestamps
  captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_state_snapshots_snapshot_type_check
    CHECK (snapshot_type IN ('error', 'success', 'checkpoint', 'pre_transform', 'post_transform'))
);

-- Indexes for debug_state_snapshots
CREATE INDEX idx_debug_state_snapshots_correlation
  ON debug_state_snapshots(correlation_id, captured_at DESC);

CREATE INDEX idx_debug_state_snapshots_session
  ON debug_state_snapshots(session_id, captured_at DESC)
  WHERE session_id IS NOT NULL;

CREATE INDEX idx_debug_state_snapshots_agent
  ON debug_state_snapshots(agent_name, snapshot_type, captured_at DESC);

CREATE INDEX idx_debug_state_snapshots_type_time
  ON debug_state_snapshots(snapshot_type, captured_at DESC);

CREATE INDEX idx_debug_state_snapshots_hash
  ON debug_state_snapshots(state_hash);

CREATE INDEX idx_debug_state_snapshots_parent
  ON debug_state_snapshots(parent_snapshot_id)
  WHERE parent_snapshot_id IS NOT NULL;

CREATE INDEX idx_debug_state_snapshots_state
  ON debug_state_snapshots USING GIN(agent_state);

COMMENT ON TABLE debug_state_snapshots IS
  'Captures agent state at critical points for debug replay and analysis. ONEX Effect node.';
COMMENT ON COLUMN debug_state_snapshots.agent_state IS
  'Full agent state including context, variables, and execution metadata';
COMMENT ON COLUMN debug_state_snapshots.state_hash IS
  'SHA-256 hash for deduplication - same state should not be captured twice';

-- Table 2: debug_error_events
-- Purpose: Track all error occurrences with context
-- ONEX Pattern: Effect node (event persistence)
CREATE TABLE IF NOT EXISTS debug_error_events (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,

  -- Error classification
  error_type VARCHAR(100) NOT NULL,
  error_category VARCHAR(50) NOT NULL,
  error_severity VARCHAR(20) NOT NULL,

  -- Error details
  error_message TEXT NOT NULL,
  error_stack_trace TEXT,
  error_code VARCHAR(50),

  -- Context
  agent_name VARCHAR(255) NOT NULL,
  operation_name VARCHAR(255),
  execution_step INTEGER,

  -- State at error
  state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Impact assessment
  is_recoverable BOOLEAN DEFAULT FALSE,
  recovery_attempted BOOLEAN DEFAULT FALSE,
  recovery_successful BOOLEAN,
  recovery_strategy VARCHAR(100),

  -- Metadata
  metadata JSONB,

  -- Timestamps
  occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMP WITH TIME ZONE,

  -- Constraints
  CONSTRAINT debug_error_events_severity_check
    CHECK (error_severity IN ('low', 'medium', 'high', 'critical')),
  CONSTRAINT debug_error_events_category_check
    CHECK (error_category IN ('agent', 'framework', 'external', 'user'))
);

-- Indexes for debug_error_events
CREATE INDEX idx_debug_error_events_correlation
  ON debug_error_events(correlation_id, occurred_at DESC);

CREATE INDEX idx_debug_error_events_session
  ON debug_error_events(session_id, occurred_at DESC)
  WHERE session_id IS NOT NULL;

CREATE INDEX idx_debug_error_events_agent_type
  ON debug_error_events(agent_name, error_type, occurred_at DESC);

CREATE INDEX idx_debug_error_events_severity
  ON debug_error_events(error_severity, occurred_at DESC);

CREATE INDEX idx_debug_error_events_state
  ON debug_error_events(state_snapshot_id)
  WHERE state_snapshot_id IS NOT NULL;

CREATE INDEX idx_debug_error_events_recovery
  ON debug_error_events(is_recoverable, recovery_successful)
  WHERE recovery_attempted = TRUE;

CREATE INDEX idx_debug_error_events_metadata
  ON debug_error_events USING GIN(metadata);

COMMENT ON TABLE debug_error_events IS
  'Tracks error occurrences with full context for analysis and recovery. ONEX Effect node.';

-- Table 3: debug_success_events
-- Purpose: Track successful operations for pattern learning
-- ONEX Pattern: Effect node (event persistence)
CREATE TABLE IF NOT EXISTS debug_success_events (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,

  -- Success classification
  success_type VARCHAR(100) NOT NULL,
  operation_name VARCHAR(255) NOT NULL,

  -- Context
  agent_name VARCHAR(255) NOT NULL,
  execution_step INTEGER,

  -- State at success
  state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Quality metrics
  quality_score DECIMAL(5,4),
  completion_status VARCHAR(50),
  validation_passed BOOLEAN DEFAULT TRUE,

  -- Performance
  execution_time_ms INTEGER,
  retry_count INTEGER DEFAULT 0,

  -- Learning data
  success_factors JSONB,
  metadata JSONB,

  -- Timestamps
  occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_success_events_quality_check
    CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1))
);

-- Indexes for debug_success_events
CREATE INDEX idx_debug_success_events_correlation
  ON debug_success_events(correlation_id, occurred_at DESC);

CREATE INDEX idx_debug_success_events_session
  ON debug_success_events(session_id, occurred_at DESC)
  WHERE session_id IS NOT NULL;

CREATE INDEX idx_debug_success_events_agent
  ON debug_success_events(agent_name, success_type, occurred_at DESC);

CREATE INDEX idx_debug_success_events_quality
  ON debug_success_events(quality_score DESC, occurred_at DESC)
  WHERE quality_score IS NOT NULL;

CREATE INDEX idx_debug_success_events_state
  ON debug_success_events(state_snapshot_id)
  WHERE state_snapshot_id IS NOT NULL;

CREATE INDEX idx_debug_success_events_metadata
  ON debug_success_events USING GIN(metadata);

COMMENT ON TABLE debug_success_events IS
  'Tracks successful operations for pattern learning and optimization. ONEX Effect node.';

-- Table 4: debug_error_success_correlation
-- Purpose: Link errors to eventual successes for recovery pattern learning
-- ONEX Pattern: Reducer node (aggregation)
CREATE TABLE IF NOT EXISTS debug_error_success_correlation (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Relationships
  error_event_id UUID NOT NULL REFERENCES debug_error_events(id),
  success_event_id UUID NOT NULL REFERENCES debug_success_events(id),

  -- Correlation metadata
  correlation_id UUID NOT NULL,
  recovery_path TEXT,
  recovery_duration_ms INTEGER,
  intermediate_steps INTEGER,

  -- Learning insights
  recovery_strategy VARCHAR(100),
  confidence_score DECIMAL(5,4),

  -- Timestamps
  correlated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_error_success_correlation_unique
    UNIQUE (error_event_id, success_event_id),
  CONSTRAINT debug_error_success_correlation_confidence_check
    CHECK (confidence_score >= 0 AND confidence_score <= 1)
);

-- Indexes for debug_error_success_correlation
CREATE INDEX idx_debug_error_success_correlation_error
  ON debug_error_success_correlation(error_event_id);

CREATE INDEX idx_debug_error_success_correlation_success
  ON debug_error_success_correlation(success_event_id);

CREATE INDEX idx_debug_error_success_correlation_workflow
  ON debug_error_success_correlation(correlation_id, correlated_at DESC);

CREATE INDEX idx_debug_error_success_correlation_strategy
  ON debug_error_success_correlation(recovery_strategy, confidence_score DESC);

COMMENT ON TABLE debug_error_success_correlation IS
  'Links errors to eventual successes for recovery pattern learning. ONEX Reducer node.';

-- Table 5: debug_workflow_steps
-- Purpose: Track discrete workflow steps for replay and analysis
-- ONEX Pattern: Effect node (event persistence)
CREATE TABLE IF NOT EXISTS debug_workflow_steps (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,
  step_number INTEGER NOT NULL,

  -- Step details
  step_type VARCHAR(100) NOT NULL,
  agent_name VARCHAR(255) NOT NULL,
  operation_name VARCHAR(255) NOT NULL,
  step_description TEXT,

  -- State snapshots
  pre_state_snapshot_id UUID REFERENCES debug_state_snapshots(id),
  post_state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Execution outcome
  status VARCHAR(50) NOT NULL,
  error_event_id UUID REFERENCES debug_error_events(id),
  success_event_id UUID REFERENCES debug_success_events(id),

  -- Performance
  duration_ms INTEGER,

  -- Dependencies
  parent_step_id UUID,
  depends_on_steps INTEGER[],

  -- Metadata
  input_data JSONB,
  output_data JSONB,
  metadata JSONB,

  -- Timestamps
  started_at TIMESTAMP WITH TIME ZONE NOT NULL,
  completed_at TIMESTAMP WITH TIME ZONE,

  -- Constraints
  CONSTRAINT debug_workflow_steps_status_check
    CHECK (status IN ('started', 'completed', 'failed', 'skipped')),
  CONSTRAINT debug_workflow_steps_unique_step
    UNIQUE (correlation_id, step_number)
);

-- Add foreign key after table creation
ALTER TABLE debug_workflow_steps
  ADD CONSTRAINT fk_debug_workflow_steps_parent
    FOREIGN KEY (parent_step_id) REFERENCES debug_workflow_steps(id);

-- Indexes for debug_workflow_steps
CREATE INDEX idx_debug_workflow_steps_correlation
  ON debug_workflow_steps(correlation_id, step_number);

CREATE INDEX idx_debug_workflow_steps_session
  ON debug_workflow_steps(session_id, step_number)
  WHERE session_id IS NOT NULL;

CREATE INDEX idx_debug_workflow_steps_agent
  ON debug_workflow_steps(agent_name, started_at DESC);

CREATE INDEX idx_debug_workflow_steps_status
  ON debug_workflow_steps(status, started_at DESC);

CREATE INDEX idx_debug_workflow_steps_error
  ON debug_workflow_steps(error_event_id)
  WHERE error_event_id IS NOT NULL;

CREATE INDEX idx_debug_workflow_steps_parent
  ON debug_workflow_steps(parent_step_id)
  WHERE parent_step_id IS NOT NULL;

CREATE INDEX idx_debug_workflow_steps_metadata
  ON debug_workflow_steps USING GIN(metadata);

COMMENT ON TABLE debug_workflow_steps IS
  'Tracks discrete workflow steps for replay and dependency analysis. ONEX Effect node.';

-- =============================================================================
-- STEP 2: Extend Existing Tables
-- =============================================================================

-- Extend agent_transformation_events with debug references
ALTER TABLE agent_transformation_events
  ADD COLUMN IF NOT EXISTS state_snapshot_id UUID,
  ADD COLUMN IF NOT EXISTS error_event_id UUID,
  ADD COLUMN IF NOT EXISTS success_event_id UUID;

-- Add foreign keys
ALTER TABLE agent_transformation_events
  ADD CONSTRAINT fk_agent_transformation_events_snapshot
    FOREIGN KEY (state_snapshot_id) REFERENCES debug_state_snapshots(id);

ALTER TABLE agent_transformation_events
  ADD CONSTRAINT fk_agent_transformation_events_error
    FOREIGN KEY (error_event_id) REFERENCES debug_error_events(id);

ALTER TABLE agent_transformation_events
  ADD CONSTRAINT fk_agent_transformation_events_success
    FOREIGN KEY (success_event_id) REFERENCES debug_success_events(id);

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_state_snapshot
  ON agent_transformation_events(state_snapshot_id)
  WHERE state_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_error
  ON agent_transformation_events(error_event_id)
  WHERE error_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_success
  ON agent_transformation_events(success_event_id)
  WHERE success_event_id IS NOT NULL;

-- Add transformation_event_id foreign key to debug_state_snapshots
ALTER TABLE debug_state_snapshots
  ADD CONSTRAINT fk_debug_state_snapshots_transformation
    FOREIGN KEY (transformation_event_id) REFERENCES agent_transformation_events(id);

-- Add parent_snapshot_id foreign key to debug_state_snapshots
ALTER TABLE debug_state_snapshots
  ADD CONSTRAINT fk_debug_state_snapshots_parent
    FOREIGN KEY (parent_snapshot_id) REFERENCES debug_state_snapshots(id);

-- =============================================================================
-- STEP 3: Create Views for Integration
-- =============================================================================

-- View: LLM call summary from hook_events
CREATE OR REPLACE VIEW debug_llm_call_summary AS
SELECT
  id as hook_event_id,
  metadata->>'session_id' as session_id,
  metadata->>'correlation_id' as correlation_id,
  resource_id as tool_name,
  payload->'quality_metrics'->>'quality_score' as quality_score,
  (payload->>'success_classification')::TEXT as success_classification,
  created_at as call_timestamp
FROM hook_events
WHERE source = 'PostToolUse'
  AND metadata->>'correlation_id' IS NOT NULL;

COMMENT ON VIEW debug_llm_call_summary IS
  'Extracts LLM call metrics from hook_events for debug analysis';

-- View: Full debug context for correlation_id
CREATE OR REPLACE VIEW debug_workflow_context AS
SELECT
  w.correlation_id,
  w.session_id,
  array_agg(DISTINCT w.agent_name ORDER BY w.agent_name) as agents_involved,
  count(DISTINCT w.id) as total_steps,
  count(DISTINCT e.id) as error_count,
  count(DISTINCT s.id) as success_count,
  count(DISTINCT snap.id) as snapshot_count,
  min(w.started_at) as workflow_started,
  max(w.completed_at) as workflow_completed,
  EXTRACT(EPOCH FROM (max(w.completed_at) - min(w.started_at))) * 1000 as duration_ms
FROM debug_workflow_steps w
LEFT JOIN debug_error_events e ON e.correlation_id = w.correlation_id
LEFT JOIN debug_success_events s ON s.correlation_id = w.correlation_id
LEFT JOIN debug_state_snapshots snap ON snap.correlation_id = w.correlation_id
GROUP BY w.correlation_id, w.session_id;

COMMENT ON VIEW debug_workflow_context IS
  'Aggregated debug context for workflows - entry point for debug analysis';

-- View: Error recovery patterns
CREATE OR REPLACE VIEW debug_error_recovery_patterns AS
SELECT
  e.error_type,
  e.error_category,
  c.recovery_strategy,
  count(*) as success_count,
  round(avg(c.recovery_duration_ms)::numeric, 2) as avg_recovery_ms,
  round(avg(c.confidence_score)::numeric, 3) as avg_confidence,
  round(avg(s.quality_score)::numeric, 3) as avg_quality_after_recovery
FROM debug_error_success_correlation c
JOIN debug_error_events e ON e.id = c.error_event_id
JOIN debug_success_events s ON s.id = c.success_event_id
WHERE c.confidence_score >= 0.5
GROUP BY e.error_type, e.error_category, c.recovery_strategy
ORDER BY success_count DESC;

COMMENT ON VIEW debug_error_recovery_patterns IS
  'Analyzes successful error recovery patterns for learning';

-- =============================================================================
-- STEP 4: Helper Functions
-- =============================================================================

-- Function: Capture state snapshot
CREATE OR REPLACE FUNCTION capture_state_snapshot(
  p_snapshot_type VARCHAR,
  p_correlation_id UUID,
  p_agent_name VARCHAR,
  p_agent_state JSONB,
  p_task_description TEXT DEFAULT NULL,
  p_session_id UUID DEFAULT NULL,
  p_execution_step INTEGER DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
  v_snapshot_id UUID;
  v_state_hash VARCHAR(64);
  v_state_size INTEGER;
  v_variables_count INTEGER;
BEGIN
  -- Calculate state hash for deduplication
  v_state_hash := encode(digest(p_agent_state::TEXT, 'sha256'), 'hex');

  -- Calculate state metrics
  v_state_size := length(p_agent_state::TEXT);
  v_variables_count := CASE
    WHEN jsonb_typeof(p_agent_state) = 'array' THEN jsonb_array_length(p_agent_state)
    WHEN jsonb_typeof(p_agent_state) = 'object' THEN (SELECT count(*) FROM jsonb_object_keys(p_agent_state))
    ELSE 0
  END;

  -- Insert snapshot
  INSERT INTO debug_state_snapshots (
    snapshot_type, correlation_id, session_id, agent_name,
    agent_state, state_hash, execution_step, task_description,
    state_size_bytes, variables_count
  ) VALUES (
    p_snapshot_type, p_correlation_id, p_session_id, p_agent_name,
    p_agent_state, v_state_hash, p_execution_step, p_task_description,
    v_state_size, v_variables_count
  )
  RETURNING id INTO v_snapshot_id;

  RETURN v_snapshot_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION capture_state_snapshot IS
  'Captures agent state snapshot with automatic deduplication';

-- Function: Get workflow debug summary
CREATE OR REPLACE FUNCTION get_workflow_debug_summary(p_correlation_id UUID)
RETURNS TABLE(
  correlation_id UUID,
  session_id UUID,
  agents_involved TEXT[],
  total_steps BIGINT,
  error_count BIGINT,
  success_count BIGINT,
  snapshot_count BIGINT,
  duration_ms NUMERIC,
  workflow_status TEXT
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    ctx.correlation_id,
    ctx.session_id,
    ctx.agents_involved,
    ctx.total_steps,
    ctx.error_count,
    ctx.success_count,
    ctx.snapshot_count,
    ctx.duration_ms,
    CASE
      WHEN ctx.error_count > ctx.success_count THEN 'failed'
      WHEN ctx.error_count > 0 AND ctx.success_count > 0 THEN 'recovered'
      WHEN ctx.success_count > 0 THEN 'successful'
      ELSE 'in_progress'
    END as workflow_status
  FROM debug_workflow_context ctx
  WHERE ctx.correlation_id = p_correlation_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_workflow_debug_summary IS
  'Returns comprehensive debug summary for a workflow correlation_id';

-- =============================================================================
-- STEP 5: Performance Optimization
-- =============================================================================

-- Analyze tables for query planner
ANALYZE debug_state_snapshots;
ANALYZE debug_error_events;
ANALYZE debug_success_events;
ANALYZE debug_error_success_correlation;
ANALYZE debug_workflow_steps;

-- =============================================================================
-- STEP 6: Record Migration
-- =============================================================================

-- Record migration application
INSERT INTO schema_migrations (version, description, execution_time_ms)
VALUES (
  5,
  'Add debug loop tables for state tracking and error/success analysis',
  EXTRACT(MILLISECONDS FROM NOW() - statement_timestamp())::INTEGER
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
/*
BEGIN;

-- Drop views first
DROP VIEW IF EXISTS debug_error_recovery_patterns;
DROP VIEW IF EXISTS debug_workflow_context;
DROP VIEW IF EXISTS debug_llm_call_summary;

-- Drop functions
DROP FUNCTION IF EXISTS get_workflow_debug_summary;
DROP FUNCTION IF EXISTS capture_state_snapshot;

-- Remove foreign keys from agent_transformation_events
ALTER TABLE agent_transformation_events
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_snapshot,
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_error,
  DROP CONSTRAINT IF EXISTS fk_agent_transformation_events_success;

-- Remove columns from agent_transformation_events
ALTER TABLE agent_transformation_events
  DROP COLUMN IF EXISTS state_snapshot_id,
  DROP COLUMN IF EXISTS error_event_id,
  DROP COLUMN IF EXISTS success_event_id;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS debug_workflow_steps CASCADE;
DROP TABLE IF EXISTS debug_error_success_correlation CASCADE;
DROP TABLE IF EXISTS debug_success_events CASCADE;
DROP TABLE IF EXISTS debug_error_events CASCADE;
DROP TABLE IF EXISTS debug_state_snapshots CASCADE;

-- Remove migration record
DELETE FROM schema_migrations WHERE version = 5;

COMMIT;
*/
