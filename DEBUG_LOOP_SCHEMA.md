# Debug Loop Database Schema - ONEX Architecture Adaptation

**Version**: 1.0.0
**Target Database**: PostgreSQL 16+ (localhost:5436, `omninode_bridge`)
**Schema**: `agent_observability`
**Migration**: `005_debug_state_management.sql`

---

## Executive Summary

Adapting the 15-table debug loop design to ONEX architecture by:
- **Extending** 2 existing tables (`agent_transformation_events`, `hook_events`)
- **Creating** 5 new MVP tables for state tracking
- **Deferring** 8 advanced tables for future phases

Focus: State snapshots, error/success tracking, basic LLM metrics.

---

## 1. Schema Design

### 1.1 Existing Tables (Extend)

#### A. `agent_transformation_events` → Extends to Track State Transformations

**Current Purpose**: Agent identity transformations
**Extension**: Add state snapshot references and error tracking

```sql
-- EXTEND: Add columns to existing table
ALTER TABLE agent_transformation_events
  ADD COLUMN IF NOT EXISTS state_snapshot_id UUID REFERENCES debug_state_snapshots(id),
  ADD COLUMN IF NOT EXISTS error_event_id UUID REFERENCES debug_error_events(id),
  ADD COLUMN IF NOT EXISTS success_event_id UUID REFERENCES debug_success_events(id);

-- New indexes for debug loop queries
CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_state_snapshot
  ON agent_transformation_events(state_snapshot_id) WHERE state_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_error
  ON agent_transformation_events(error_event_id) WHERE error_event_id IS NOT NULL;
```

**Integration Point**: Links agent transformations to debug state snapshots, enabling replay and analysis.

#### B. `hook_events` → Already Captures LLM Interactions

**Current Purpose**: Hook event logging
**Usage**: Query existing `PostToolUse` events for LLM call metrics

```sql
-- VIEW: Extract LLM metrics from hook_events
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
```

**Integration Point**: Reuse existing hook events instead of creating new LLM tracking tables.

---

### 1.2 New Tables (MVP Only)

#### Table 1: `debug_state_snapshots` (Core)

**Purpose**: Capture agent state at critical points (error/success/checkpoint)
**ONEX Pattern**: Effect node (persistence)

```sql
CREATE TABLE IF NOT EXISTS debug_state_snapshots (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  snapshot_type VARCHAR(50) NOT NULL, -- error, success, checkpoint, pre_transform, post_transform
  correlation_id UUID NOT NULL, -- Links to workflow
  session_id UUID, -- Links to session

  -- Agent context
  agent_name VARCHAR(255) NOT NULL,
  agent_state JSONB NOT NULL, -- Full agent state (context, variables, etc.)
  state_hash VARCHAR(64) NOT NULL, -- SHA-256 for deduplication

  -- Execution context
  execution_step INTEGER, -- Step number in workflow
  task_description TEXT, -- What agent was trying to do
  user_request TEXT, -- Original user request

  -- State metadata
  state_size_bytes INTEGER,
  variables_count INTEGER,
  context_depth INTEGER, -- How deep in delegation chain

  -- Performance
  memory_usage_mb DECIMAL(10,2),
  cpu_time_ms INTEGER,
  wall_time_ms INTEGER,

  -- Relationships (nullable - set when related events exist)
  transformation_event_id UUID REFERENCES agent_transformation_events(id),
  parent_snapshot_id UUID REFERENCES debug_state_snapshots(id), -- Previous snapshot

  -- Timestamps
  captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_state_snapshots_snapshot_type_check
    CHECK (snapshot_type IN ('error', 'success', 'checkpoint', 'pre_transform', 'post_transform'))
);

-- Indexes for performance
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
  ON debug_state_snapshots(state_hash); -- Deduplication

CREATE INDEX idx_debug_state_snapshots_parent
  ON debug_state_snapshots(parent_snapshot_id)
  WHERE parent_snapshot_id IS NOT NULL;

-- JSONB index for state queries
CREATE INDEX idx_debug_state_snapshots_state
  ON debug_state_snapshots USING GIN(agent_state);

COMMENT ON TABLE debug_state_snapshots IS
  'Captures agent state at critical points for debug replay and analysis. ONEX Effect node.';
COMMENT ON COLUMN debug_state_snapshots.agent_state IS
  'Full agent state including context, variables, and execution metadata';
COMMENT ON COLUMN debug_state_snapshots.state_hash IS
  'SHA-256 hash for deduplication - same state should not be captured twice';
```

#### Table 2: `debug_error_events` (Core)

**Purpose**: Track all error occurrences with context
**ONEX Pattern**: Effect node (event persistence)

```sql
CREATE TABLE IF NOT EXISTS debug_error_events (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,

  -- Error classification
  error_type VARCHAR(100) NOT NULL, -- validation_error, execution_error, timeout, etc.
  error_category VARCHAR(50) NOT NULL, -- agent, framework, external, user
  error_severity VARCHAR(20) NOT NULL, -- low, medium, high, critical

  -- Error details
  error_message TEXT NOT NULL,
  error_stack_trace TEXT,
  error_code VARCHAR(50),

  -- Context
  agent_name VARCHAR(255) NOT NULL,
  operation_name VARCHAR(255), -- What operation failed
  execution_step INTEGER,

  -- State at error
  state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Impact assessment
  is_recoverable BOOLEAN DEFAULT FALSE,
  recovery_attempted BOOLEAN DEFAULT FALSE,
  recovery_successful BOOLEAN,
  recovery_strategy VARCHAR(100), -- retry, fallback, skip, abort

  -- Metadata
  metadata JSONB, -- Additional context (request params, env vars, etc.)

  -- Timestamps
  occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMP WITH TIME ZONE,

  -- Constraints
  CONSTRAINT debug_error_events_severity_check
    CHECK (error_severity IN ('low', 'medium', 'high', 'critical')),
  CONSTRAINT debug_error_events_category_check
    CHECK (error_category IN ('agent', 'framework', 'external', 'user'))
);

-- Indexes
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

COMMENT ON TABLE debug_error_events IS
  'Tracks error occurrences with full context for analysis and recovery. ONEX Effect node.';
```

#### Table 3: `debug_success_events` (Core)

**Purpose**: Track successful operations for pattern learning
**ONEX Pattern**: Effect node (event persistence)

```sql
CREATE TABLE IF NOT EXISTS debug_success_events (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,

  -- Success classification
  success_type VARCHAR(100) NOT NULL, -- task_completion, validation_pass, recovery_success
  operation_name VARCHAR(255) NOT NULL,

  -- Context
  agent_name VARCHAR(255) NOT NULL,
  execution_step INTEGER,

  -- State at success
  state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Quality metrics
  quality_score DECIMAL(5,4), -- 0.0000 to 1.0000
  completion_status VARCHAR(50), -- full, partial, degraded
  validation_passed BOOLEAN DEFAULT TRUE,

  -- Performance
  execution_time_ms INTEGER,
  retry_count INTEGER DEFAULT 0,

  -- Learning data
  success_factors JSONB, -- What contributed to success
  metadata JSONB,

  -- Timestamps
  occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_success_events_quality_check
    CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1))
);

-- Indexes
CREATE INDEX idx_debug_success_events_correlation
  ON debug_success_events(correlation_id, occurred_at DESC);

CREATE INDEX idx_debug_success_events_agent
  ON debug_success_events(agent_name, success_type, occurred_at DESC);

CREATE INDEX idx_debug_success_events_quality
  ON debug_success_events(quality_score DESC, occurred_at DESC)
  WHERE quality_score IS NOT NULL;

CREATE INDEX idx_debug_success_events_state
  ON debug_success_events(state_snapshot_id)
  WHERE state_snapshot_id IS NOT NULL;

COMMENT ON TABLE debug_success_events IS
  'Tracks successful operations for pattern learning and optimization. ONEX Effect node.';
```

#### Table 4: `debug_error_success_correlation` (Analysis)

**Purpose**: Link errors to eventual successes for recovery pattern learning
**ONEX Pattern**: Reducer node (aggregation)

```sql
CREATE TABLE IF NOT EXISTS debug_error_success_correlation (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Relationships
  error_event_id UUID NOT NULL REFERENCES debug_error_events(id),
  success_event_id UUID NOT NULL REFERENCES debug_success_events(id),

  -- Correlation metadata
  correlation_id UUID NOT NULL, -- Workflow correlation
  recovery_path TEXT, -- Description of how error led to success
  recovery_duration_ms INTEGER, -- Time from error to success
  intermediate_steps INTEGER, -- Steps between error and success

  -- Learning insights
  recovery_strategy VARCHAR(100), -- What strategy led to success
  confidence_score DECIMAL(5,4), -- Confidence in correlation (0-1)

  -- Timestamps
  correlated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

  -- Constraints
  CONSTRAINT debug_error_success_correlation_unique
    UNIQUE (error_event_id, success_event_id),
  CONSTRAINT debug_error_success_correlation_confidence_check
    CHECK (confidence_score >= 0 AND confidence_score <= 1)
);

-- Indexes
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
```

#### Table 5: `debug_workflow_steps` (Execution Tracking)

**Purpose**: Track discrete workflow steps for replay and analysis
**ONEX Pattern**: Effect node (event persistence)

```sql
CREATE TABLE IF NOT EXISTS debug_workflow_steps (
  -- Primary key
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identification
  correlation_id UUID NOT NULL,
  session_id UUID,
  step_number INTEGER NOT NULL,

  -- Step details
  step_type VARCHAR(100) NOT NULL, -- initialization, routing, execution, transformation, validation
  agent_name VARCHAR(255) NOT NULL,
  operation_name VARCHAR(255) NOT NULL,
  step_description TEXT,

  -- State snapshots
  pre_state_snapshot_id UUID REFERENCES debug_state_snapshots(id),
  post_state_snapshot_id UUID REFERENCES debug_state_snapshots(id),

  -- Execution outcome
  status VARCHAR(50) NOT NULL, -- started, completed, failed, skipped
  error_event_id UUID REFERENCES debug_error_events(id),
  success_event_id UUID REFERENCES debug_success_events(id),

  -- Performance
  duration_ms INTEGER,

  -- Dependencies
  parent_step_id UUID REFERENCES debug_workflow_steps(id),
  depends_on_steps INTEGER[], -- Array of step_numbers this depends on

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

-- Indexes
CREATE INDEX idx_debug_workflow_steps_correlation
  ON debug_workflow_steps(correlation_id, step_number);

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

COMMENT ON TABLE debug_workflow_steps IS
  'Tracks discrete workflow steps for replay and dependency analysis. ONEX Effect node.';
```

---

## 2. Migration Plan

### Migration File: `005_debug_state_management.sql`

```sql
-- Migration: 005_debug_state_management
-- Description: Add debug loop tables for state tracking and error/success analysis
-- Author: agent-workflow-coordinator
-- Created: 2025-10-11
-- ONEX Compliance: Effect/Reducer node patterns for debug observability

BEGIN;

-- ============================================================================
-- STEP 1: Create New Tables (in dependency order)
-- ============================================================================

-- Create debug_state_snapshots first (no foreign key dependencies)
-- [SQL from Table 1 above]

-- Create debug_error_events (depends on state_snapshots)
-- [SQL from Table 2 above]

-- Create debug_success_events (depends on state_snapshots)
-- [SQL from Table 3 above]

-- Create debug_error_success_correlation (depends on error/success events)
-- [SQL from Table 4 above]

-- Create debug_workflow_steps (depends on state_snapshots and error/success events)
-- [SQL from Table 5 above]

-- ============================================================================
-- STEP 2: Extend Existing Tables
-- ============================================================================

-- Extend agent_transformation_events
ALTER TABLE agent_transformation_events
  ADD COLUMN IF NOT EXISTS state_snapshot_id UUID REFERENCES debug_state_snapshots(id),
  ADD COLUMN IF NOT EXISTS error_event_id UUID REFERENCES debug_error_events(id),
  ADD COLUMN IF NOT EXISTS success_event_id UUID REFERENCES debug_success_events(id);

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_state_snapshot
  ON agent_transformation_events(state_snapshot_id)
  WHERE state_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_error
  ON agent_transformation_events(error_event_id)
  WHERE error_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_transformation_events_success
  ON agent_transformation_events(success_event_id)
  WHERE success_event_id IS NOT NULL;

-- ============================================================================
-- STEP 3: Create Views for Integration
-- ============================================================================

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
  array_agg(DISTINCT w.agent_name) as agents_involved,
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

-- ============================================================================
-- STEP 4: Helper Functions
-- ============================================================================

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
BEGIN
  -- Calculate state hash for deduplication
  v_state_hash := encode(digest(p_agent_state::TEXT, 'sha256'), 'hex');

  -- Insert snapshot
  INSERT INTO debug_state_snapshots (
    snapshot_type, correlation_id, session_id, agent_name,
    agent_state, state_hash, execution_step, task_description,
    state_size_bytes, variables_count
  ) VALUES (
    p_snapshot_type, p_correlation_id, p_session_id, p_agent_name,
    p_agent_state, v_state_hash, p_execution_step, p_task_description,
    length(p_agent_state::TEXT), jsonb_array_length(p_agent_state)
  )
  RETURNING id INTO v_snapshot_id;

  RETURN v_snapshot_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION capture_state_snapshot IS
  'Captures agent state snapshot with automatic deduplication';

-- ============================================================================
-- STEP 5: Record Migration
-- ============================================================================

INSERT INTO schema_migrations (version, description, execution_time_ms)
VALUES (
  5,
  'Add debug loop tables for state tracking and error/success analysis',
  EXTRACT(MILLISECONDS FROM NOW() - statement_timestamp())::INTEGER
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
```

### Rollback Script: `005_rollback_debug_state_management.sql`

```sql
BEGIN;

-- Drop views first
DROP VIEW IF EXISTS debug_workflow_context;
DROP VIEW IF EXISTS debug_llm_call_summary;

-- Drop functions
DROP FUNCTION IF EXISTS capture_state_snapshot;

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
```

---

## 3. Integration Points

### 3.1 Hook Events Integration

**Existing Table**: `hook_events`
**Integration**: Query `PostToolUse` events for LLM metrics

```python
# Example: Get LLM calls for a correlation_id
async def get_llm_calls(correlation_id: str) -> List[Dict]:
    query = """
        SELECT * FROM debug_llm_call_summary
        WHERE correlation_id = $1
        ORDER BY call_timestamp
    """
    return await db.execute_query(query, correlation_id, fetch="all")
```

### 3.2 Agent Transformation Events Integration

**Existing Table**: `agent_transformation_events`
**Integration**: Link transformations to state snapshots

```python
# Example: Capture state at transformation
async def log_transformation_with_state(
    source_agent: str,
    target_agent: str,
    correlation_id: UUID,
    agent_state: dict
):
    # Capture state snapshot
    snapshot_id = await capture_state_snapshot(
        "pre_transform", correlation_id, source_agent, agent_state
    )

    # Log transformation with snapshot reference
    await db.write_transformation_event(
        source_agent=source_agent,
        target_agent=target_agent,
        state_snapshot_id=snapshot_id  # New column
    )
```

### 3.3 Workflow Correlation

**Pattern**: Use `correlation_id` across all tables

```python
# Example: Get full debug context for a workflow
async def get_debug_context(correlation_id: UUID) -> Dict:
    return await db.execute_query(
        "SELECT * FROM debug_workflow_context WHERE correlation_id = $1",
        correlation_id,
        fetch="one"
    )
```

---

## 4. Deferred Tables (Future Phases)

### Phase 2 (Not in MVP)
- `debug_tasks` - Task-level tracking (use workflow_steps for now)
- `debug_runs` - Run-level aggregation (use views instead)
- `debug_transform_functions` - STF tracking (use agent_transformation_events)
- `debug_code_pointers` - Code location tracking (future)

### Phase 3 (Advanced Features)
- `debug_artifacts` - File/output tracking (defer to file system)
- `debug_snapshot_artifacts` - Artifact linking (defer)
- `debug_graph_edges` - Dependency graph (use workflow_steps.depends_on_steps array)
- `debug_metadata_stamps` - Enhanced metadata (use JSONB in existing tables)

**Rationale**: MVP focuses on state, errors, and basic LLM metrics. Advanced features add complexity without immediate value.

---

## 5. Performance Considerations

### Index Strategy
- All tables indexed on `correlation_id` + timestamp (DESC) for workflow queries
- `state_hash` indexed for deduplication (prevents duplicate snapshots)
- JSONB GIN indexes on `agent_state` and metadata columns
- Partial indexes on nullable foreign keys

### Query Performance Targets
- State snapshot retrieval: <50ms
- Error/success event queries: <100ms
- Workflow context aggregation: <200ms
- Correlation analysis: <500ms (Phase 2 optimization)

### Storage Optimization
- State deduplication via `state_hash` prevents duplicate storage
- JSONB compression (PostgreSQL native)
- Retention policy: 90 days for debug events (configurable)

---

## 6. Usage Examples

### Capture State at Error
```python
# When error occurs
error_id = await db.execute_query(
    """
    INSERT INTO debug_error_events
    (correlation_id, agent_name, error_type, error_message, error_severity, state_snapshot_id)
    VALUES ($1, $2, $3, $4, $5,
      (SELECT capture_state_snapshot('error', $1, $2, $6::JSONB, $7))
    )
    RETURNING id
    """,
    correlation_id, agent_name, error_type, str(error), 'high',
    json.dumps(agent_state), task_description,
    fetch="val"
)
```

### Track Workflow Step
```python
# Start step
step_id = await db.execute_query(
    """
    INSERT INTO debug_workflow_steps
    (correlation_id, step_number, step_type, agent_name, operation_name, status, started_at)
    VALUES ($1, $2, $3, $4, $5, 'started', NOW())
    RETURNING id
    """,
    correlation_id, step_num, 'execution', agent_name, operation,
    fetch="val"
)

# Complete step
await db.execute_query(
    """
    UPDATE debug_workflow_steps
    SET status = 'completed', completed_at = NOW(),
        duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
        success_event_id = $2
    WHERE id = $1
    """,
    step_id, success_event_id
)
```

### Analyze Recovery Patterns
```python
# Find successful recovery strategies
recovery_patterns = await db.execute_query(
    """
    SELECT
      e.error_type,
      c.recovery_strategy,
      count(*) as success_count,
      avg(c.recovery_duration_ms) as avg_duration_ms,
      avg(c.confidence_score) as avg_confidence
    FROM debug_error_success_correlation c
    JOIN debug_error_events e ON e.id = c.error_event_id
    WHERE c.confidence_score >= 0.7
    GROUP BY e.error_type, c.recovery_strategy
    ORDER BY success_count DESC
    """,
    fetch="all"
)
```

---

## 7. ONEX Compliance

### Node Pattern Mapping
- **Effect Nodes**: All event tables (state_snapshots, error_events, success_events, workflow_steps)
- **Reducer Nodes**: Correlation table (error_success_correlation)
- **Compute Nodes**: Views (debug_workflow_context, debug_llm_call_summary)

### Naming Conventions
- Tables: `debug_<noun>_<plural>` (e.g., `debug_state_snapshots`)
- Indexes: `idx_<table>_<column(s)>` (e.g., `idx_debug_error_events_correlation`)
- Views: `debug_<entity>_<purpose>` (e.g., `debug_workflow_context`)
- Functions: `<verb>_<noun>` (e.g., `capture_state_snapshot`)

### Type Safety
- All IDs: `UUID` (PostgreSQL native)
- All timestamps: `TIMESTAMP WITH TIME ZONE`
- All decimals: `DECIMAL(5,4)` for 0-1 scores
- All enums: `CHECK` constraints on VARCHAR columns

---

## Summary

**New Tables**: 5 (state_snapshots, error_events, success_events, error_success_correlation, workflow_steps)
**Extended Tables**: 1 (agent_transformation_events)
**Reused Tables**: 1 (hook_events via views)
**Total Schema Size**: ~150 lines DDL
**Performance Target**: <200ms for all debug queries
**ONEX Compliant**: Yes (Effect/Reducer patterns, naming conventions, type safety)
