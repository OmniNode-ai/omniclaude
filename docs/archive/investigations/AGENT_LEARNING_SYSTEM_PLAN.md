# Agent Learning and Outcome Tracking System - Implementation Plan

**Version**: 1.0.0
**Created**: 2025-10-20
**Correlation ID**: ed28eebe-1a72-447d-9b2f-6ac0a5cae824
**Status**: Design Phase

---

## ⚠️ CRITICAL IMPLEMENTATION NOTE

**SQL Statements in This Document**: The CREATE TABLE statements in this plan are for **documentation and DBA reference only**.

**Agents MUST NOT execute SQL directly**. Instead:
- ✅ **Use skills**: All database operations must use skills (e.g., `/log-agent-action`, `/capture-task-execution`)
- ✅ **Migration scripts**: DBAs run migration scripts to create tables
- ✅ **Skills handle all data**: Skills abstract database operations from agents

**Why**: This ensures:
- Security: No SQL injection vulnerabilities
- Maintainability: Database changes don't break agents
- Consistency: All operations follow same patterns
- Observability: All database operations are tracked

---

## Executive Summary

This plan defines a comprehensive agent learning system that enables "prompt → success shortcut" learning by tracking execution outcomes, extracting reusable patterns, and providing similarity-based recommendations. Each time an agent performs a task, it can query the database for similar past executions and reuse successful patterns, significantly reducing execution time and improving quality consistency.

### Key Benefits
- **Execution Shortcuts**: Reuse successful approaches for similar tasks (30-70% time reduction)
- **Pattern Recognition**: Automatically extract reusable templates and validation criteria
- **Quality Consistency**: Learn from high-quality outcomes and avoid known failure patterns
- **Continuous Improvement**: System learns from every execution, improving over time
- **Intelligent Routing**: Enhance polymorphic agent routing with historical success data

### Success Metrics
- **Pattern Reuse Rate**: Target 40% of tasks reuse learned patterns within 90 days
- **Quality Improvement**: Average quality score increase of 15% using pattern reuse
- **Time Reduction**: Average 45% reduction in execution time for pattern-matched tasks
- **Failure Prevention**: 60% reduction in repeated failure patterns

---

## Table of Contents

1. [Database Schema Design](#1-database-schema-design)
2. [Skills Specifications](#2-skills-specifications)
3. [Integration Points](#3-integration-points)
4. [Implementation Phases](#4-implementation-phases)
5. [Success Metrics & Validation](#5-success-metrics--validation)
6. [Migration Strategy](#6-migration-strategy)
7. [Appendices](#7-appendices)

---

## 1. Database Schema Design

### 1.1 Core Tables Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Learning System                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐     ┌──────────────────┐                 │
│  │ task_fingerprints│────→│ execution_paths  │                 │
│  └──────────────────┘     └──────────────────┘                 │
│          │                        │                              │
│          ├─────────────┬──────────┴───────────┬────────┐       │
│          ↓             ↓                      ↓        ↓       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│        │
│  │code_artifacts│  │success_patterns│  │failure_patterns│      │
│  └──────────────┘  └──────────────┘  └──────────────┘│        │
│          │                 │                    │               │
│          └─────────────────┴────────────────────┘               │
│                            │                                     │
│                   ┌────────────────┐                            │
│                   │pattern_templates│                           │
│                   └────────────────┘                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Integration Layer:
├── agent_execution_logs (existing)
├── agent_routing_decisions (existing)
└── Archon MCP RAG (hybrid intelligence)
```

### 1.2 Table: `task_fingerprints`

**Purpose**: Unique identification of tasks for similarity matching and deduplication.

```sql
CREATE TABLE task_fingerprints (
    -- Identity
    fingerprint_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_hash TEXT NOT NULL UNIQUE,  -- SHA256 of normalized task description

    -- Classification
    task_type VARCHAR(100) NOT NULL,  -- 'code_generation', 'refactoring', 'debugging', 'testing', 'documentation'
    domain VARCHAR(100) NOT NULL,     -- 'api_development', 'database', 'frontend', 'infrastructure', etc.
    complexity_score NUMERIC(3,2) CHECK (complexity_score >= 0.0 AND complexity_score <= 1.0),

    -- Task Content
    original_prompt TEXT NOT NULL,
    normalized_prompt TEXT NOT NULL,  -- Cleaned, tokenized version for matching
    prompt_tokens TEXT[],             -- Array of extracted keywords

    -- Context
    file_patterns TEXT[],             -- File extensions/patterns involved (e.g., ['*.py', '*.yaml'])
    technology_stack TEXT[],          -- Technologies mentioned (e.g., ['fastapi', 'postgresql', 'docker'])
    framework_context JSONB,          -- Framework-specific context (e.g., ONEX node types)

    -- Similarity Features
    embedding_vector VECTOR(1536),   -- OpenAI ada-002 embedding for semantic similarity
    keyword_vector TSVECTOR,          -- PostgreSQL full-text search vector

    -- Metadata
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_count INTEGER DEFAULT 1,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_execution_time_ms INTEGER,

    -- Indexes
    CONSTRAINT valid_complexity CHECK (complexity_score IS NULL OR complexity_score BETWEEN 0.0 AND 1.0)
);

-- Indexes for performance
CREATE INDEX idx_task_fingerprints_hash ON task_fingerprints(task_hash);
CREATE INDEX idx_task_fingerprints_type_domain ON task_fingerprints(task_type, domain);
CREATE INDEX idx_task_fingerprints_embedding ON task_fingerprints USING ivfflat (embedding_vector vector_cosine_ops);
CREATE INDEX idx_task_fingerprints_keyword ON task_fingerprints USING gin(keyword_vector);
CREATE INDEX idx_task_fingerprints_success_rate ON task_fingerprints((success_count::float / NULLIF(execution_count, 0)));
```

### 1.3 Table: `execution_paths`

**Purpose**: Track step-by-step execution paths for pattern extraction and replay.

```sql
CREATE TABLE execution_paths (
    -- Identity
    path_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint_id UUID NOT NULL REFERENCES task_fingerprints(fingerprint_id) ON DELETE CASCADE,
    execution_id UUID NOT NULL REFERENCES agent_execution_logs(execution_id) ON DELETE CASCADE,
    correlation_id UUID NOT NULL,

    -- Execution Context
    agent_name VARCHAR(255) NOT NULL,
    agent_chain TEXT[],               -- Sequence of agents involved (e.g., ['polly', 'api-architect', 'testing'])

    -- Execution Steps
    steps JSONB NOT NULL,             -- Array of execution steps with actions and outcomes
    step_count INTEGER NOT NULL,
    total_duration_ms INTEGER NOT NULL,

    -- Quality Metrics
    success BOOLEAN NOT NULL DEFAULT false,
    quality_score NUMERIC(3,2) CHECK (quality_score >= 0.0 AND quality_score <= 1.0),
    user_acceptance BOOLEAN,          -- Did user accept the outcome?

    -- Performance
    tools_used TEXT[],                -- Tools invoked during execution
    api_calls_count INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,

    -- Temporal
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_quality_score CHECK (quality_score IS NULL OR quality_score BETWEEN 0.0 AND 1.0)
);

-- Example steps JSONB structure:
-- [
--   {
--     "step_number": 1,
--     "step_type": "rag_query",
--     "description": "Gathered API design patterns from knowledge base",
--     "tool": "perform_rag_query",
--     "duration_ms": 1250,
--     "outcome": "success",
--     "artifacts": ["pattern_ids": ["uuid1", "uuid2"]]
--   },
--   {
--     "step_number": 2,
--     "step_type": "code_generation",
--     "description": "Generated FastAPI endpoint with ONEX Effect pattern",
--     "tool": "Write",
--     "files_modified": ["api/endpoints/users.py"],
--     "duration_ms": 850,
--     "outcome": "success"
--   }
-- ]

-- Indexes
CREATE INDEX idx_execution_paths_fingerprint ON execution_paths(fingerprint_id);
CREATE INDEX idx_execution_paths_execution ON execution_paths(execution_id);
CREATE INDEX idx_execution_paths_success ON execution_paths(success, quality_score DESC);
CREATE INDEX idx_execution_paths_agent ON execution_paths(agent_name);
CREATE INDEX idx_execution_paths_steps ON execution_paths USING gin(steps);
```

### 1.4 Table: `code_artifacts`

**Purpose**: Track code artifacts created during execution for quality analysis and reuse.

```sql
CREATE TABLE code_artifacts (
    -- Identity
    artifact_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_id UUID NOT NULL REFERENCES execution_paths(path_id) ON DELETE CASCADE,
    fingerprint_id UUID NOT NULL REFERENCES task_fingerprints(fingerprint_id) ON DELETE CASCADE,

    -- Artifact Details
    file_path TEXT NOT NULL,
    artifact_type VARCHAR(50) NOT NULL,  -- 'source_code', 'test', 'config', 'documentation'
    language VARCHAR(50),                -- 'python', 'typescript', 'yaml', 'markdown'

    -- Content
    content_hash TEXT NOT NULL,          -- SHA256 of artifact content
    content_preview TEXT,                -- First 500 chars for quick inspection
    lines_added INTEGER DEFAULT 0,
    lines_modified INTEGER DEFAULT 0,
    lines_deleted INTEGER DEFAULT 0,

    -- Quality Metrics
    quality_score NUMERIC(3,2) CHECK (quality_score >= 0.0 AND quality_score <= 1.0),
    onex_compliance_score NUMERIC(3,2),
    complexity_metrics JSONB,            -- Cyclomatic complexity, nesting depth, etc.

    -- Testing
    test_coverage NUMERIC(5,2),          -- Percentage (0-100)
    tests_passed INTEGER,
    tests_failed INTEGER,

    -- Validation
    lint_passed BOOLEAN,
    type_check_passed BOOLEAN,
    security_scan_passed BOOLEAN,

    -- ONEX Patterns
    onex_node_type VARCHAR(50),          -- 'Effect', 'Compute', 'Reducer', 'Orchestrator'
    pattern_compliance JSONB,            -- Specific pattern adherence metrics

    -- Temporal
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Metadata
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_quality_score CHECK (quality_score IS NULL OR quality_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT valid_onex_score CHECK (onex_compliance_score IS NULL OR onex_compliance_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT valid_coverage CHECK (test_coverage IS NULL OR test_coverage BETWEEN 0.0 AND 100.0)
);

-- Indexes
CREATE INDEX idx_code_artifacts_path ON code_artifacts(path_id);
CREATE INDEX idx_code_artifacts_fingerprint ON code_artifacts(fingerprint_id);
CREATE INDEX idx_code_artifacts_quality ON code_artifacts(quality_score DESC) WHERE quality_score IS NOT NULL;
CREATE INDEX idx_code_artifacts_onex_type ON code_artifacts(onex_node_type) WHERE onex_node_type IS NOT NULL;
CREATE INDEX idx_code_artifacts_hash ON code_artifacts(content_hash);
```

### 1.5 Table: `success_patterns`

**Purpose**: Capture and catalog successful execution patterns for reuse.

```sql
CREATE TABLE success_patterns (
    -- Identity
    pattern_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint_id UUID NOT NULL REFERENCES task_fingerprints(fingerprint_id) ON DELETE CASCADE,
    path_id UUID NOT NULL REFERENCES execution_paths(path_id) ON DELETE CASCADE,

    -- Pattern Classification
    pattern_name VARCHAR(255) NOT NULL,
    pattern_type VARCHAR(100) NOT NULL,  -- 'workflow', 'code_template', 'validation_sequence', 'tool_chain'

    -- Pattern Content
    pattern_template JSONB NOT NULL,     -- Reusable template with placeholders
    applicability_criteria JSONB,        -- When this pattern should be applied

    -- Execution Blueprint
    recommended_steps JSONB NOT NULL,    -- Step-by-step execution plan
    required_tools TEXT[],               -- Tools needed for this pattern
    estimated_duration_ms INTEGER,

    -- Quality Gates
    validation_criteria JSONB NOT NULL,  -- Success criteria for this pattern
    quality_thresholds JSONB,            -- Minimum quality scores required

    -- Reuse Metrics
    reuse_count INTEGER DEFAULT 0,
    success_rate NUMERIC(5,2) DEFAULT 0.0,  -- Percentage (0-100)
    avg_quality_improvement NUMERIC(3,2),   -- Quality delta when using pattern

    -- Context
    applicable_domains TEXT[],           -- Domains where pattern works well
    technology_requirements TEXT[],      -- Required technologies/frameworks

    -- Temporal
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_success_rate CHECK (success_rate BETWEEN 0.0 AND 100.0)
);

-- Example pattern_template structure:
-- {
--   "name": "FastAPI CRUD Endpoint Pattern",
--   "description": "Standard CRUD endpoint with ONEX Effect pattern",
--   "steps": [
--     {
--       "action": "rag_query",
--       "query": "FastAPI CRUD best practices {{domain}}",
--       "expected_results": 5
--     },
--     {
--       "action": "generate_code",
--       "template": "onex_effect_crud",
--       "placeholders": ["entity_name", "schema_fields", "database_table"]
--     },
--     {
--       "action": "validate",
--       "checks": ["type_safety", "onex_compliance", "test_coverage"]
--     }
--   ],
--   "placeholders": {
--     "entity_name": "string",
--     "domain": "string",
--     "schema_fields": "array"
--   }
-- }

-- Indexes
CREATE INDEX idx_success_patterns_fingerprint ON success_patterns(fingerprint_id);
CREATE INDEX idx_success_patterns_type ON success_patterns(pattern_type);
CREATE INDEX idx_success_patterns_success_rate ON success_patterns(success_rate DESC);
CREATE INDEX idx_success_patterns_reuse_count ON success_patterns(reuse_count DESC);
```

### 1.6 Table: `failure_patterns`

**Purpose**: Track failure patterns to avoid repeated mistakes and guide debugging.

```sql
CREATE TABLE failure_patterns (
    -- Identity
    failure_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fingerprint_id UUID NOT NULL REFERENCES task_fingerprints(fingerprint_id) ON DELETE CASCADE,
    path_id UUID REFERENCES execution_paths(path_id) ON DELETE CASCADE,

    -- Failure Classification
    failure_type VARCHAR(100) NOT NULL,  -- 'compilation_error', 'runtime_error', 'validation_failure', 'timeout', 'quality_gate_failure'
    error_category VARCHAR(100),         -- 'type_error', 'import_error', 'dependency_missing', etc.

    -- Failure Details
    error_message TEXT NOT NULL,
    error_stack_trace TEXT,
    failed_step JSONB,                   -- Step where failure occurred

    -- Root Cause
    root_cause_analysis TEXT,            -- AI-generated or manual analysis
    contributing_factors TEXT[],         -- Environmental or contextual factors

    -- Resolution
    resolution_applied TEXT,             -- How the failure was resolved
    resolution_steps JSONB,              -- Step-by-step resolution process
    time_to_resolve_ms INTEGER,

    -- Pattern Recognition
    occurrence_count INTEGER DEFAULT 1,
    first_occurrence_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_occurrence_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevention
    prevention_strategy JSONB,           -- How to prevent this failure in the future
    automated_fix_available BOOLEAN DEFAULT false,
    fix_success_rate NUMERIC(5,2),       -- Percentage (0-100) if automated fix exists

    -- Context
    context_at_failure JSONB,            -- State/context when failure occurred

    -- Metadata
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_fix_success_rate CHECK (fix_success_rate IS NULL OR fix_success_rate BETWEEN 0.0 AND 100.0)
);

-- Indexes
CREATE INDEX idx_failure_patterns_fingerprint ON failure_patterns(fingerprint_id);
CREATE INDEX idx_failure_patterns_type ON failure_patterns(failure_type);
CREATE INDEX idx_failure_patterns_occurrence ON failure_patterns(occurrence_count DESC);
CREATE INDEX idx_failure_patterns_resolution ON failure_patterns(resolution_applied) WHERE resolution_applied IS NOT NULL;
```

### 1.7 Table: `pattern_templates`

**Purpose**: Store reusable templates extracted from successful executions.

```sql
CREATE TABLE pattern_templates (
    -- Identity
    template_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_name VARCHAR(255) NOT NULL UNIQUE,
    template_version VARCHAR(50) NOT NULL DEFAULT '1.0.0',

    -- Classification
    category VARCHAR(100) NOT NULL,      -- 'onex_node', 'workflow', 'validation', 'api_design'
    subcategory VARCHAR(100),

    -- Template Content
    template_content JSONB NOT NULL,     -- The actual template with placeholders
    placeholder_schema JSONB NOT NULL,   -- Schema defining required/optional placeholders

    -- Usage Instructions
    description TEXT NOT NULL,
    usage_example JSONB,                 -- Example of template usage
    prerequisites TEXT[],                -- Requirements before using template

    -- Quality
    quality_score NUMERIC(3,2) CHECK (quality_score >= 0.0 AND quality_score <= 1.0),
    validation_rules JSONB,              -- Rules to validate template instantiation

    -- Lineage
    derived_from_pattern_id UUID REFERENCES success_patterns(pattern_id),
    derived_from_execution_id UUID REFERENCES agent_execution_logs(execution_id),

    -- Usage Metrics
    usage_count INTEGER DEFAULT 0,
    success_rate NUMERIC(5,2) DEFAULT 0.0,
    avg_quality_score NUMERIC(3,2),

    -- Temporal
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deprecated_at TIMESTAMPTZ,

    -- Metadata
    tags TEXT[],
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_quality_score CHECK (quality_score IS NULL OR quality_score BETWEEN 0.0 AND 1.0),
    CONSTRAINT valid_success_rate CHECK (success_rate BETWEEN 0.0 AND 100.0)
);

-- Indexes
CREATE INDEX idx_pattern_templates_category ON pattern_templates(category, subcategory);
CREATE INDEX idx_pattern_templates_usage ON pattern_templates(usage_count DESC);
CREATE INDEX idx_pattern_templates_quality ON pattern_templates(quality_score DESC) WHERE quality_score IS NOT NULL;
CREATE INDEX idx_pattern_templates_tags ON pattern_templates USING gin(tags);
```

### 1.8 Supporting Functions

```sql
-- Function: Compute task similarity score
CREATE OR REPLACE FUNCTION compute_task_similarity(
    p_fingerprint_id UUID,
    p_comparison_fingerprint_id UUID
) RETURNS NUMERIC AS $$
DECLARE
    v_semantic_similarity NUMERIC;
    v_keyword_similarity NUMERIC;
    v_domain_match NUMERIC;
    v_type_match NUMERIC;
    v_final_score NUMERIC;
BEGIN
    -- Semantic similarity (embedding cosine distance)
    SELECT 1 - (t1.embedding_vector <=> t2.embedding_vector) INTO v_semantic_similarity
    FROM task_fingerprints t1, task_fingerprints t2
    WHERE t1.fingerprint_id = p_fingerprint_id
      AND t2.fingerprint_id = p_comparison_fingerprint_id;

    -- Keyword similarity (full-text search)
    SELECT ts_rank(t2.keyword_vector, to_tsquery(
        array_to_string((SELECT prompt_tokens FROM task_fingerprints WHERE fingerprint_id = p_fingerprint_id), ' | ')
    )) INTO v_keyword_similarity
    FROM task_fingerprints t2
    WHERE t2.fingerprint_id = p_comparison_fingerprint_id;

    -- Domain and type matching
    SELECT
        CASE WHEN t1.domain = t2.domain THEN 1.0 ELSE 0.0 END,
        CASE WHEN t1.task_type = t2.task_type THEN 1.0 ELSE 0.0 END
    INTO v_domain_match, v_type_match
    FROM task_fingerprints t1, task_fingerprints t2
    WHERE t1.fingerprint_id = p_fingerprint_id
      AND t2.fingerprint_id = p_comparison_fingerprint_id;

    -- Weighted combination
    v_final_score := (
        v_semantic_similarity * 0.40 +
        v_keyword_similarity * 0.30 +
        v_domain_match * 0.20 +
        v_type_match * 0.10
    );

    RETURN ROUND(v_final_score::numeric, 4);
END;
$$ LANGUAGE plpgsql;

-- Function: Find similar tasks
CREATE OR REPLACE FUNCTION find_similar_tasks(
    p_prompt TEXT,
    p_task_type VARCHAR DEFAULT NULL,
    p_domain VARCHAR DEFAULT NULL,
    p_limit INTEGER DEFAULT 10,
    p_min_similarity NUMERIC DEFAULT 0.6
) RETURNS TABLE (
    fingerprint_id UUID,
    similarity_score NUMERIC,
    original_prompt TEXT,
    success_rate NUMERIC,
    avg_execution_time_ms INTEGER,
    execution_count INTEGER
) AS $$
BEGIN
    -- This is a simplified version; production would use embeddings + keyword search
    RETURN QUERY
    SELECT
        tf.fingerprint_id,
        0.0::NUMERIC as similarity_score,  -- Placeholder for actual similarity computation
        tf.original_prompt,
        CASE WHEN tf.execution_count > 0
            THEN ROUND((tf.success_count::NUMERIC / tf.execution_count) * 100, 2)
            ELSE 0.0
        END as success_rate,
        tf.avg_execution_time_ms,
        tf.execution_count
    FROM task_fingerprints tf
    WHERE (p_task_type IS NULL OR tf.task_type = p_task_type)
      AND (p_domain IS NULL OR tf.domain = p_domain)
      AND tf.success_count > 0
    ORDER BY tf.success_count DESC, tf.execution_count DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
```

---

## 2. Skills Specifications

### 2.1 Overview

Create 5 new skills following the established pattern from `agent-tracking`:

| Skill | Purpose | Primary Table(s) |
|-------|---------|------------------|
| `/capture-task-execution` | Log complete execution after agent finishes | task_fingerprints, execution_paths, code_artifacts |
| `/check-similar-tasks` | Query for similar past executions before starting | task_fingerprints, success_patterns |
| `/log-code-quality` | Track quality scores and acceptance criteria | code_artifacts |
| `/record-failure-pattern` | Capture debugging journey and resolution | failure_patterns |
| `/record-success-pattern` | Extract reusable patterns from successful execution | success_patterns, pattern_templates |

### 2.2 Skill: `/capture-task-execution`

**Purpose**: Comprehensive capture of task execution for learning and pattern extraction.

**Database Tables**:
- `task_fingerprints` (create or update)
- `execution_paths` (insert)
- `code_artifacts` (insert for each artifact)

**Usage**:
```bash
/capture-task-execution \
  --prompt "Create FastAPI CRUD endpoint for users" \
  --task-type "code_generation" \
  --domain "api_development" \
  --agent "agent-api-architect" \
  --success true \
  --quality-score 0.92 \
  --duration-ms 15400 \
  --steps-json '[
    {"step": 1, "action": "rag_query", "duration_ms": 1200, "outcome": "success"},
    {"step": 2, "action": "code_generation", "files": ["api/users.py"], "duration_ms": 850, "outcome": "success"}
  ]' \
  --artifacts '[
    {"file": "api/users.py", "type": "source_code", "language": "python", "lines_added": 145}
  ]'
```

**Required Arguments**:
- `--prompt` - Original user prompt/request
- `--task-type` - Task classification (code_generation, refactoring, debugging, testing, documentation)
- `--domain` - Domain classification (api_development, database, frontend, infrastructure)
- `--agent` - Primary agent that executed the task
- `--success` - Boolean execution success flag
- `--quality-score` - Overall quality score (0.0-1.0)
- `--duration-ms` - Total execution duration in milliseconds
- `--steps-json` - JSON array of execution steps

**Optional Arguments**:
- `--correlation-id` - Correlation ID for tracking
- `--execution-id` - Link to agent_execution_logs
- `--artifacts` - JSON array of code artifacts created
- `--user-acceptance` - Boolean user acceptance flag
- `--complexity-score` - Task complexity (0.0-1.0)
- `--agent-chain` - Array of agents involved in sequence
- `--tools-used` - Array of tools invoked
- `--file-patterns` - Array of file patterns involved
- `--technology-stack` - Array of technologies used

**Output**:
```json
{
  "success": true,
  "fingerprint_id": "uuid",
  "fingerprint_hash": "sha256_hash",
  "path_id": "uuid",
  "artifacts_created": 3,
  "similar_tasks_found": 5,
  "pattern_candidates": 2,
  "created_at": "2025-10-20T16:30:00Z"
}
```

**Implementation Notes**:
1. Compute task hash from normalized prompt
2. Check for existing fingerprint or create new
3. Update execution counts and averages
4. Insert execution path with steps
5. Insert code artifacts (if provided)
6. Query for similar tasks and suggest patterns
7. Return fingerprint ID for follow-up operations

### 2.3 Skill: `/check-similar-tasks`

**Purpose**: Query for similar past executions before starting a task to provide shortcuts.

**Database Tables**:
- `task_fingerprints` (query)
- `execution_paths` (query)
- `success_patterns` (query)
- `pattern_templates` (query)

**Usage**:
```bash
/check-similar-tasks \
  --prompt "Create FastAPI CRUD endpoint for products" \
  --task-type "code_generation" \
  --domain "api_development" \
  --min-similarity 0.7 \
  --limit 5
```

**Required Arguments**:
- `--prompt` - User prompt/request to match against
- `--task-type` - Task type filter
- `--domain` - Domain filter

**Optional Arguments**:
- `--min-similarity` - Minimum similarity score (default: 0.7)
- `--limit` - Maximum results to return (default: 5)
- `--min-quality-score` - Filter by minimum quality score
- `--min-success-rate` - Filter by minimum success rate
- `--technologies` - Array of required technologies

**Output**:
```json
{
  "success": true,
  "query_fingerprint": "computed_hash",
  "matches_found": 3,
  "matches": [
    {
      "fingerprint_id": "uuid",
      "similarity_score": 0.92,
      "original_prompt": "Create FastAPI CRUD endpoint for users",
      "task_type": "code_generation",
      "domain": "api_development",
      "success_rate": 95.5,
      "avg_quality_score": 0.91,
      "avg_execution_time_ms": 14200,
      "execution_count": 12,
      "recommended_pattern_id": "uuid",
      "pattern_template_id": "uuid",
      "estimated_time_saving_pct": 45.0
    }
  ],
  "recommended_patterns": [
    {
      "pattern_id": "uuid",
      "pattern_name": "FastAPI CRUD Endpoint Pattern",
      "pattern_type": "workflow",
      "success_rate": 96.2,
      "reuse_count": 47,
      "applicability_score": 0.88
    }
  ],
  "available_templates": [
    {
      "template_id": "uuid",
      "template_name": "ONEX Effect CRUD Template",
      "category": "onex_node",
      "usage_count": 89,
      "avg_quality_score": 0.93
    }
  ]
}
```

**Implementation Notes**:
1. Normalize and hash input prompt
2. Compute embeddings for semantic search (if available)
3. Query task_fingerprints with similarity function
4. Filter by success rate, quality, and execution count
5. Fetch associated success patterns and templates
6. Rank results by applicability score
7. Return top matches with actionable recommendations

### 2.4 Skill: `/log-code-quality`

**Purpose**: Track quality scores and acceptance criteria for code artifacts.

**Database Tables**:
- `code_artifacts` (insert or update)
- `task_fingerprints` (update quality metrics)

**Usage**:
```bash
/log-code-quality \
  --path-id "uuid" \
  --file-path "api/users.py" \
  --artifact-type "source_code" \
  --language "python" \
  --quality-score 0.92 \
  --onex-compliance 0.95 \
  --lines-added 145 \
  --test-coverage 87.5 \
  --lint-passed true \
  --type-check-passed true
```

**Required Arguments**:
- `--path-id` - Execution path UUID
- `--file-path` - File path of artifact
- `--artifact-type` - Type of artifact (source_code, test, config, documentation)
- `--language` - Programming language

**Optional Arguments**:
- `--quality-score` - Overall quality score (0.0-1.0)
- `--onex-compliance` - ONEX compliance score (0.0-1.0)
- `--complexity-metrics` - JSON object with complexity data
- `--lines-added` - Lines of code added
- `--lines-modified` - Lines of code modified
- `--lines-deleted` - Lines of code deleted
- `--test-coverage` - Test coverage percentage (0-100)
- `--tests-passed` - Number of tests passed
- `--tests-failed` - Number of tests failed
- `--lint-passed` - Boolean lint check result
- `--type-check-passed` - Boolean type check result
- `--security-scan-passed` - Boolean security scan result
- `--onex-node-type` - ONEX node type (Effect, Compute, Reducer, Orchestrator)

**Output**:
```json
{
  "success": true,
  "artifact_id": "uuid",
  "content_hash": "sha256_hash",
  "quality_score": 0.92,
  "onex_compliance_score": 0.95,
  "quality_issues": [],
  "recommendations": [
    "Consider adding docstrings for public methods",
    "Test coverage could be improved to 90%+"
  ],
  "created_at": "2025-10-20T16:30:00Z"
}
```

### 2.5 Skill: `/record-failure-pattern`

**Purpose**: Capture debugging journey and resolution for failure learning.

**Database Tables**:
- `failure_patterns` (insert)
- `task_fingerprints` (update failure count)

**Usage**:
```bash
/record-failure-pattern \
  --fingerprint-id "uuid" \
  --failure-type "validation_failure" \
  --error-category "type_error" \
  --error-message "Expected str, got int for field 'user_id'" \
  --resolution "Updated field type annotation to Union[str, int]" \
  --time-to-resolve-ms 3400
```

**Required Arguments**:
- `--fingerprint-id` - Task fingerprint UUID
- `--failure-type` - Type of failure (compilation_error, runtime_error, validation_failure, timeout, quality_gate_failure)
- `--error-message` - Error message text

**Optional Arguments**:
- `--path-id` - Execution path UUID
- `--error-category` - Specific error category
- `--error-stack-trace` - Full stack trace
- `--failed-step` - JSON of step where failure occurred
- `--root-cause` - Root cause analysis text
- `--contributing-factors` - Array of contributing factors
- `--resolution` - How failure was resolved
- `--resolution-steps` - JSON array of resolution steps
- `--time-to-resolve-ms` - Time to resolve in milliseconds
- `--prevention-strategy` - JSON prevention strategy
- `--automated-fix-available` - Boolean flag
- `--context-at-failure` - JSON context snapshot

**Output**:
```json
{
  "success": true,
  "failure_id": "uuid",
  "occurrence_count": 3,
  "similar_failures_found": 2,
  "automated_fix_available": false,
  "prevention_recommendations": [
    "Add type validation before processing user input",
    "Use Pydantic models for strict type checking"
  ],
  "created_at": "2025-10-20T16:30:00Z"
}
```

### 2.6 Skill: `/record-success-pattern`

**Purpose**: Extract reusable patterns from successful executions.

**Database Tables**:
- `success_patterns` (insert)
- `pattern_templates` (insert if template-worthy)
- `task_fingerprints` (link pattern)

**Usage**:
```bash
/record-success-pattern \
  --fingerprint-id "uuid" \
  --path-id "uuid" \
  --pattern-name "FastAPI CRUD Endpoint Pattern" \
  --pattern-type "workflow" \
  --recommended-steps '[
    {"action": "rag_query", "query": "FastAPI CRUD best practices"},
    {"action": "generate_code", "template": "onex_effect_crud"},
    {"action": "validate", "checks": ["type_safety", "onex_compliance"]}
  ]' \
  --validation-criteria '{"min_quality_score": 0.85, "test_coverage": 80}'
```

**Required Arguments**:
- `--fingerprint-id` - Task fingerprint UUID
- `--path-id` - Execution path UUID
- `--pattern-name` - Human-readable pattern name
- `--pattern-type` - Type of pattern (workflow, code_template, validation_sequence, tool_chain)
- `--recommended-steps` - JSON array of execution steps

**Optional Arguments**:
- `--pattern-template` - JSON template with placeholders
- `--applicability-criteria` - JSON criteria for when to apply
- `--validation-criteria` - JSON validation rules
- `--quality-thresholds` - JSON quality thresholds
- `--required-tools` - Array of required tools
- `--estimated-duration-ms` - Estimated execution time
- `--applicable-domains` - Array of applicable domains
- `--technology-requirements` - Array of required technologies
- `--create-template` - Boolean flag to also create a template

**Output**:
```json
{
  "success": true,
  "pattern_id": "uuid",
  "pattern_name": "FastAPI CRUD Endpoint Pattern",
  "template_created": true,
  "template_id": "uuid",
  "applicability_score": 0.92,
  "estimated_reuse_potential": "high",
  "similar_patterns_found": 3,
  "created_at": "2025-10-20T16:30:00Z"
}
```

---

## 3. Integration Points

### 3.1 Kafka Event Bus Integration

**Architecture**: All agent actions and learning events flow through Kafka before database persistence.

```
┌─────────────────────────────────────────────────────────────────┐
│                   Kafka-Based Event Architecture                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Agent Layer (Producers)                                        │
│  ├─ Skills publish events to Kafka topics                       │
│  ├─ Non-blocking, async operations                              │
│  └─ Zero direct database interaction                            │
│                                                                  │
│  ↓ [Kafka Topics]                                               │
│  ├─ agent-actions                    (tool calls, decisions)    │
│  ├─ agent-routing-decisions          (routing choices)          │
│  ├─ agent-transformation-events      (identity changes)         │
│  ├─ router-performance-metrics       (performance data)         │
│  ├─ task-executions                  (execution capture)        │
│  ├─ code-quality-metrics             (quality scores)           │
│  ├─ success-patterns                 (pattern extraction)       │
│  └─ failure-patterns                 (failure analysis)         │
│                                                                  │
│  ↓ [Consumer Layer]                                             │
│  ├─ Database Writer (persistence)                               │
│  ├─ Metrics Aggregator (analytics)                              │
│  ├─ Alert Manager (real-time monitoring)                        │
│  ├─ Pattern Extractor (ML learning)                             │
│  └─ Audit Logger (compliance)                                   │
│                                                                  │
│  ↓ [Storage Layer]                                              │
│  ├─ PostgreSQL (structured data)                                │
│  ├─ Redis (real-time cache)                                     │
│  └─ S3/Object Storage (event replay)                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Benefits**:
- **Async Non-Blocking**: Agents never wait for database writes (<5ms publish latency)
- **Multiple Consumers**: Same events power DB persistence, analytics, alerts, ML
- **Event Replay**: Complete audit trail with time-travel debugging capability
- **Scalability**: Kafka handles 1M+ events/sec, horizontally scalable
- **Fault Tolerance**: Events persisted even if consumers fail temporarily

**Topic Schema**:

| Topic | Partitions | Retention | Key | Consumers |
|-------|-----------|-----------|-----|-----------|
| `agent-actions` | 12 | 7 days | correlation_id | DB Writer, Metrics, Audit |
| `agent-routing-decisions` | 6 | 30 days | correlation_id | DB Writer, Analytics |
| `agent-transformation-events` | 6 | 30 days | correlation_id | DB Writer, Monitoring |
| `router-performance-metrics` | 6 | 30 days | agent_name | DB Writer, Performance |
| `task-executions` | 12 | 90 days | fingerprint_id | DB Writer, Learning |
| `code-quality-metrics` | 6 | 90 days | path_id | DB Writer, Quality |
| `success-patterns` | 6 | 365 days | pattern_id | DB Writer, Pattern ML |
| `failure-patterns` | 6 | 365 days | failure_id | DB Writer, Alert Mgr |

**Partitioning Strategy**:
- **By correlation_id**: Maintains event ordering per execution trace
- **By fingerprint_id**: Co-locates similar task executions for pattern analysis
- **By agent_name**: Enables agent-specific consumer groups for parallel processing

**Consumer Specifications**:

1. **Database Writer Consumer**:
   - Consumes all topics
   - Batch inserts (100 events/batch, max 500ms latency)
   - Transactional writes with exactly-once semantics
   - Dead-letter queue for failed writes

2. **Metrics Aggregator Consumer**:
   - Real-time metrics computation (5-second windows)
   - Publishes to Redis for dashboard queries
   - Rollup hourly/daily aggregates to PostgreSQL

3. **Alert Manager Consumer**:
   - Monitors failure-patterns topic
   - Triggers alerts on repeated failures (>3 occurrences)
   - Integration with PagerDuty/Slack

4. **Pattern Extractor Consumer**:
   - ML-based pattern recognition from success-patterns topic
   - Generates reusable templates automatically
   - Publishes extracted patterns back to Kafka

5. **Audit Logger Consumer**:
   - Compliance logging to immutable storage
   - Event replay for debugging and analysis
   - S3 archival with Parquet compression

### 3.2 Polymorphic Agent Workflow Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                  Polymorphic Agent Workflow                      │
│                         (Polly)                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. User Request Received                                       │
│     ↓                                                            │
│  2. /check-similar-tasks (BEFORE execution)                     │
│     ├─ Query fingerprints for similar tasks                     │
│     ├─ Fetch success patterns and templates                     │
│     └─ Present "shortcut" options to user or auto-apply         │
│     ↓                                                            │
│  3. Decision: Use Pattern or Execute Fresh                      │
│     │                                                            │
│     ├─ [Pattern Available] ──→ Apply pattern template           │
│     │                         └─ Estimated 30-70% time saving   │
│     │                                                            │
│     └─ [No Pattern] ──→ Standard execution flow                 │
│                         └─ Learn new pattern for future         │
│     ↓                                                            │
│  4. Execute Task (with selected agent)                          │
│     ├─ Track execution steps (publish to Kafka)                 │
│     ├─ Monitor quality gates (async logging)                    │
│     └─ Capture failures with /record-failure-pattern (→Kafka)   │
│     ↓                                                            │
│  5. Post-Execution Capture                                      │
│     ├─ /capture-task-execution (publish to task-executions)     │
│     ├─ /log-code-quality (publish to code-quality-metrics)      │
│     └─ /record-success-pattern (publish to success-patterns)    │
│     ↓                                                            │
│  6. Learning Feedback Loop (Consumer-Driven)                    │
│     ├─ Pattern Extractor processes events asynchronously        │
│     ├─ Database Writer persists to PostgreSQL                   │
│     ├─ Metrics Aggregator updates real-time dashboards          │
│     └─ Alert Manager triggers on quality/failure thresholds     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Note**: Skills now publish to Kafka topics instead of direct database writes. Consumers handle all persistence and processing asynchronously.

### 3.3 Integration with Existing Agent Execution Logs

**Approach**: Extend existing `agent_execution_logs` with learning system linkage via Kafka event enrichment.

```sql
-- Add columns to existing table (migration)
ALTER TABLE agent_execution_logs
ADD COLUMN fingerprint_id UUID REFERENCES task_fingerprints(fingerprint_id),
ADD COLUMN path_id UUID REFERENCES execution_paths(path_id),
ADD COLUMN pattern_used_id UUID REFERENCES success_patterns(pattern_id),
ADD COLUMN template_used_id UUID REFERENCES pattern_templates(template_id);

-- Indexes for performance
CREATE INDEX idx_agent_execution_logs_fingerprint ON agent_execution_logs(fingerprint_id);
CREATE INDEX idx_agent_execution_logs_path ON agent_execution_logs(path_id);
```

**Workflow**:
1. Agent starts execution → Create entry in `agent_execution_logs`
2. Check similar tasks → Store `fingerprint_id` if pattern available
3. Apply pattern → Store `pattern_used_id` and `template_used_id`
4. Complete execution → Create `execution_paths` entry, link via `path_id`
5. Capture artifacts → Link artifacts to execution via `path_id`

### 3.4 Integration with Archon MCP RAG

**Hybrid Intelligence Approach**: Combine database pattern matching with RAG semantic search.

```python
# Pseudo-code for hybrid pattern matching
async def find_execution_shortcuts(user_prompt: str, task_type: str, domain: str):
    """
    Combine database similarity search with RAG intelligence.
    """

    # Step 1: Database similarity search
    db_matches = await check_similar_tasks(
        prompt=user_prompt,
        task_type=task_type,
        domain=domain,
        min_similarity=0.7,
        limit=5
    )

    # Step 2: RAG semantic search for broader context
    rag_results = await perform_rag_query(
        query=f"{task_type} {domain} best practices similar to: {user_prompt}",
        top_k=5,
        include_quality_filter=True
    )

    # Step 3: Synthesize recommendations
    recommendations = []

    for db_match in db_matches:
        # Fetch execution path and artifacts for context
        execution_path = await get_execution_path(db_match['path_id'])
        artifacts = await get_code_artifacts(db_match['path_id'])

        # Enrich with RAG insights
        relevant_rag = find_relevant_rag_results(rag_results, db_match)

        recommendations.append({
            'source': 'database_pattern',
            'similarity': db_match['similarity_score'],
            'pattern_id': db_match['pattern_id'],
            'execution_path': execution_path,
            'artifacts': artifacts,
            'rag_context': relevant_rag,
            'estimated_time_saving': db_match['avg_execution_time_ms'] * 0.6,  # 60% faster
            'quality_confidence': db_match['avg_quality_score']
        })

    # Step 4: Rank by combined score
    ranked = rank_recommendations(recommendations, weights={
        'similarity': 0.35,
        'quality_confidence': 0.30,
        'execution_count': 0.20,
        'rag_relevance': 0.15
    })

    return ranked
```

**Benefits**:
- **Database patterns**: Fast, precise matches for known scenarios (< 100ms)
- **RAG intelligence**: Broader context, novel insights, cross-project learning (< 1500ms)
- **Hybrid ranking**: Best of both worlds with confidence scoring

### 3.5 Integration with Agent Routing Decisions

**Enhanced Routing**: Use historical success patterns to improve agent selection.

```python
# Pseudo-code for routing enhancement
async def enhanced_agent_routing(user_request: str, context: dict):
    """
    Enhance routing decisions with historical success data.
    """

    # Standard routing (existing)
    recommendations = router.route(user_request, context)

    # Check historical success rates for recommended agents
    for recommendation in recommendations:
        agent_name = recommendation.agent_name

        # Query historical success for this agent + task type
        historical_data = await query_agent_task_success(
            agent_name=agent_name,
            task_type=context.get('task_type'),
            domain=context.get('domain')
        )

        # Adjust confidence based on historical performance
        if historical_data['execution_count'] > 5:
            success_rate = historical_data['success_rate'] / 100.0
            avg_quality = historical_data['avg_quality_score']

            # Boost confidence if agent has proven track record
            historical_confidence = (success_rate * 0.6) + (avg_quality * 0.4)

            # Weighted blend with routing confidence
            recommendation.confidence = (
                recommendation.confidence * 0.7 +
                historical_confidence * 0.3
            )

            recommendation.metadata['historical_executions'] = historical_data['execution_count']
            recommendation.metadata['historical_success_rate'] = historical_data['success_rate']

    # Re-rank recommendations
    recommendations.sort(key=lambda r: r.confidence, reverse=True)

    return recommendations
```

### 3.6 Hook Integration Points

**UserPromptSubmit Hook**: Check for similar tasks before execution.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/check-similar-tasks --prompt \"{{user_prompt}}\" --task-type auto --domain auto --limit 3"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/capture-task-execution --auto-detect true"
          }
        ]
      }
    ]
  }
}
```

**Benefits**:
- Automatic pattern checking before every execution
- Zero-overhead learning capture at session end
- Seamless integration with existing workflow

---

## 4. Implementation Phases

### Phase 1: Foundation (Weeks 1-2)

**Objective**: Establish core database schema and basic capture capabilities.

**Deliverables**:
1. ✅ Database schema creation
   - Create all 7 tables with indexes
   - Add similarity functions
   - Create migration scripts
   - Test schema with sample data

2. ✅ Basic skills implementation
   - `/capture-task-execution` (minimal version)
   - `/check-similar-tasks` (database-only, no embeddings)
   - Shared helper libraries
   - Unit tests for each skill

3. ✅ Integration with existing logs
   - Add columns to `agent_execution_logs`
   - Create linking functions
   - Test data flow

**Success Criteria**:
- All tables created and indexed
- Basic capture and query working end-to-end
- Sample data captured successfully
- Unit tests passing (>85% coverage)

**Estimated Effort**: 60-80 hours

### Phase 2: Core Learning (Weeks 3-5)

**Objective**: Implement pattern extraction and quality tracking.

**Deliverables**:
1. ✅ Advanced skills
   - `/log-code-quality` with ONEX compliance
   - `/record-failure-pattern` with root cause analysis
   - `/record-success-pattern` with template extraction

2. ✅ Pattern extraction logic
   - Automatic pattern detection from successful executions
   - Template generation with placeholder identification
   - Quality threshold validation

3. ✅ Similarity matching enhancement
   - Implement embedding generation (OpenAI ada-002)
   - Semantic similarity search
   - Hybrid ranking (database + semantic)

**Success Criteria**:
- Pattern extraction working automatically
- Similarity matching >70% accuracy on test set
- Quality tracking integrated with Archon MCP
- Templates generated from high-quality executions

**Estimated Effort**: 80-100 hours

### Phase 3: Integration & Intelligence (Weeks 6-8)

**Objective**: Integrate with Archon MCP RAG and agent routing.

**Deliverables**:
1. ✅ Archon MCP integration
   - Hybrid search (database + RAG)
   - Multi-service orchestration
   - Confidence scoring fusion

2. ✅ Agent routing enhancement
   - Historical success rate boosting
   - Agent performance tracking
   - Confidence adjustment logic

3. ✅ Hook integration
   - UserPromptSubmit hook for similarity checking
   - SessionEnd hook for automatic capture
   - Tool execution hooks for step tracking

**Success Criteria**:
- Hybrid search latency < 2000ms
- Routing confidence improvement measurable
- Hooks triggering correctly
- End-to-end workflow functional

**Estimated Effort**: 60-80 hours

### Phase 4: Optimization & Production (Weeks 9-12)

**Objective**: Performance optimization, user experience, and production readiness.

**Deliverables**:
1. ✅ Performance optimization
   - Query optimization and indexing
   - Connection pooling tuning
   - Caching layer for frequent queries
   - Batch operations support

2. ✅ User experience
   - Pattern recommendation UI/CLI
   - Execution shortcuts with time estimates
   - Quality feedback loop
   - Failure prevention alerts

3. ✅ Monitoring & observability
   - Dashboard for pattern reuse metrics
   - Quality trend analysis
   - Failure pattern alerts
   - Template usage analytics

4. ✅ Documentation & training
   - Comprehensive skill documentation
   - Integration guide for agents
   - Pattern creation best practices
   - Troubleshooting guide

**Success Criteria**:
- Query latency < 100ms for pattern lookup
- Pattern reuse rate > 25% within first month
- Quality improvement measurable (>10%)
- Production monitoring in place
- Documentation complete

**Estimated Effort**: 80-100 hours

**Total Implementation Timeline**: 10-12 weeks (280-360 hours)

---

## 5. Success Metrics & Validation

### 5.1 Primary Success Metrics

| Metric | Target | Measurement Method | Timeline |
|--------|--------|-------------------|----------|
| **Pattern Reuse Rate** | 40% | (Tasks using patterns / Total tasks) × 100 | 90 days |
| **Quality Improvement** | +15% | Avg quality score (with patterns) - Avg quality score (without) | 60 days |
| **Time Reduction** | 45% | Avg execution time reduction for pattern-matched tasks | 60 days |
| **Failure Prevention** | 60% | Reduction in repeated failure patterns | 90 days |
| **Pattern Extraction Rate** | 30% | (Successful patterns extracted / High-quality executions) × 100 | 30 days |

### 5.2 Secondary Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Similarity Matching Accuracy** | >80% | User validation of suggested similar tasks |
| **Template Adoption Rate** | >50% | Templates used in executions |
| **Agent Routing Improvement** | +10% | Routing confidence increase with historical data |
| **Pattern Library Growth** | 100 patterns | Count of unique success patterns after 90 days |
| **User Acceptance Rate** | >85% | User accepts pattern recommendation vs. rejects |

### 5.3 Performance Validation

| Operation | Target Latency | Validation Method |
|-----------|---------------|-------------------|
| `/check-similar-tasks` | < 150ms | P95 latency monitoring |
| `/capture-task-execution` | < 200ms | P95 latency monitoring |
| Similarity computation | < 50ms | Direct measurement |
| Pattern template retrieval | < 100ms | Cache hit rate >70% |

### 5.4 Quality Gates

**Before Phase 1 Completion**:
- [ ] All database tables created with proper constraints
- [ ] Schema validated with 100+ sample executions
- [ ] Basic skills executable and tested
- [ ] Integration with agent_execution_logs verified

**Before Phase 2 Completion**:
- [ ] Pattern extraction producing valid templates
- [ ] Similarity matching >70% accuracy on validation set
- [ ] Quality tracking integrated with Archon MCP
- [ ] At least 20 patterns extracted from test executions

**Before Phase 3 Completion**:
- [ ] Hybrid search (DB + RAG) functional
- [ ] Agent routing using historical data
- [ ] Hooks integrated and triggering correctly
- [ ] End-to-end workflow tested with real agents

**Before Phase 4 Completion (Production)**:
- [ ] All performance targets met
- [ ] Monitoring dashboards operational
- [ ] Documentation complete and reviewed
- [ ] Security audit passed
- [ ] User acceptance testing completed

---

## 6. Migration Strategy

### 6.1 Backward Compatibility

**Approach**: Additive changes only, no breaking modifications to existing tables.

1. **Existing Tables**: No columns removed or renamed
2. **New Columns**: Added with NULL defaults where needed
3. **Skills**: New skills don't replace existing ones
4. **Hooks**: Optional integration, existing hooks unchanged

### 6.2 Data Migration Plan

**Phase 1: Schema Deployment**
```sql
-- Run in transaction for safety
BEGIN;

-- Create new tables (see section 1.2-1.7)
\i schema/task_fingerprints.sql
\i schema/execution_paths.sql
\i schema/code_artifacts.sql
\i schema/success_patterns.sql
\i schema/failure_patterns.sql
\i schema/pattern_templates.sql

-- Add linking columns to existing tables
ALTER TABLE agent_execution_logs
ADD COLUMN fingerprint_id UUID REFERENCES task_fingerprints(fingerprint_id),
ADD COLUMN path_id UUID REFERENCES execution_paths(path_id),
ADD COLUMN pattern_used_id UUID REFERENCES success_patterns(pattern_id),
ADD COLUMN template_used_id UUID REFERENCES pattern_templates(template_id);

CREATE INDEX idx_agent_execution_logs_fingerprint ON agent_execution_logs(fingerprint_id);
CREATE INDEX idx_agent_execution_logs_path ON agent_execution_logs(path_id);

-- Verify schema
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('task_fingerprints', 'execution_paths', 'code_artifacts', 'success_patterns', 'failure_patterns', 'pattern_templates')
ORDER BY table_name, ordinal_position;

COMMIT;
```

**Phase 2: Historical Data Backfill** (Optional)
```sql
-- Backfill fingerprints from existing executions
INSERT INTO task_fingerprints (task_hash, original_prompt, normalized_prompt, task_type, domain, first_seen_at, last_seen_at, execution_count, success_count)
SELECT
    MD5(user_prompt) as task_hash,
    user_prompt as original_prompt,
    LOWER(TRIM(user_prompt)) as normalized_prompt,
    'unknown' as task_type,  -- Would need classification
    'general' as domain,
    MIN(started_at) as first_seen_at,
    MAX(started_at) as last_seen_at,
    COUNT(*) as execution_count,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
FROM agent_execution_logs
WHERE user_prompt IS NOT NULL
GROUP BY user_prompt
ON CONFLICT (task_hash) DO NOTHING;

-- Link existing executions to fingerprints
UPDATE agent_execution_logs ael
SET fingerprint_id = tf.fingerprint_id
FROM task_fingerprints tf
WHERE MD5(ael.user_prompt) = tf.task_hash;
```

**Rollback Plan**:
```sql
-- Emergency rollback if issues detected
BEGIN;

-- Remove linking columns
ALTER TABLE agent_execution_logs
DROP COLUMN IF EXISTS fingerprint_id,
DROP COLUMN IF EXISTS path_id,
DROP COLUMN IF EXISTS pattern_used_id,
DROP COLUMN IF EXISTS template_used_id;

-- Drop new tables (CASCADE will remove all foreign keys)
DROP TABLE IF EXISTS pattern_templates CASCADE;
DROP TABLE IF EXISTS failure_patterns CASCADE;
DROP TABLE IF EXISTS success_patterns CASCADE;
DROP TABLE IF EXISTS code_artifacts CASCADE;
DROP TABLE IF EXISTS execution_paths CASCADE;
DROP TABLE IF EXISTS task_fingerprints CASCADE;

COMMIT;
```

### 6.3 Incremental Rollout

**Week 1-2**: Shadow mode
- Deploy schema and skills
- Capture executions without affecting workflow
- Validate data quality
- No pattern recommendations yet

**Week 3-4**: Read-only mode
- Enable `/check-similar-tasks` for agents
- Display pattern suggestions (informational only)
- Collect user feedback on relevance
- Don't auto-apply patterns

**Week 5-6**: Opt-in mode
- Allow agents to opt-in to pattern application
- Track adoption rate and outcomes
- Monitor quality and performance
- Identify issues and refine

**Week 7+**: Full production
- Enable automatic pattern suggestions by default
- Full integration with routing and hooks
- Continuous monitoring and optimization
- Pattern library growth and maintenance

---

## 7. Appendices

### Appendix A: Example Workflows

#### A.1 Complete Execution Capture Workflow

```bash
#!/bin/bash
# Complete workflow: Check similar tasks → Execute → Capture learning

# Step 1: Check for similar tasks before execution
CORRELATION_ID=$(uuidgen)
echo "Correlation ID: $CORRELATION_ID"

SIMILAR_TASKS=$(/check-similar-tasks \
  --prompt "Create FastAPI CRUD endpoint for products with authentication" \
  --task-type "code_generation" \
  --domain "api_development" \
  --min-similarity 0.7 \
  --limit 3)

echo "Similar tasks found:"
echo "$SIMILAR_TASKS" | jq '.matches'

# Step 2: User decision or auto-apply pattern
PATTERN_AVAILABLE=$(echo "$SIMILAR_TASKS" | jq -r '.matches[0].pattern_template_id')

if [ "$PATTERN_AVAILABLE" != "null" ]; then
    echo "Pattern available! Estimated time saving: 45%"
    # Apply pattern (simplified - actual implementation would be more complex)
    # pattern_apply "$PATTERN_AVAILABLE"
fi

# Step 3: Execute task (agent execution happens here)
# ... agent performs work ...
EXECUTION_SUCCESS=true
QUALITY_SCORE=0.92
DURATION_MS=14500

# Step 4: Capture execution for learning
CAPTURE_RESULT=$(/capture-task-execution \
  --correlation-id "$CORRELATION_ID" \
  --prompt "Create FastAPI CRUD endpoint for products with authentication" \
  --task-type "code_generation" \
  --domain "api_development" \
  --agent "agent-api-architect" \
  --success "$EXECUTION_SUCCESS" \
  --quality-score "$QUALITY_SCORE" \
  --duration-ms "$DURATION_MS" \
  --steps-json '[
    {"step": 1, "action": "rag_query", "query": "FastAPI CRUD authentication", "duration_ms": 1200, "outcome": "success"},
    {"step": 2, "action": "code_generation", "files": ["api/products.py"], "duration_ms": 850, "outcome": "success"},
    {"step": 3, "action": "test_generation", "files": ["tests/test_products.py"], "duration_ms": 640, "outcome": "success"},
    {"step": 4, "action": "validation", "checks": ["type_safety", "onex_compliance", "security"], "duration_ms": 420, "outcome": "success"}
  ]' \
  --artifacts '[
    {"file": "api/products.py", "type": "source_code", "language": "python", "lines_added": 187, "quality_score": 0.94},
    {"file": "tests/test_products.py", "type": "test", "language": "python", "lines_added": 145, "test_coverage": 92.5}
  ]' \
  --agent-chain '["agent-workflow-coordinator", "agent-api-architect", "agent-testing"]' \
  --user-acceptance true)

echo "Capture result:"
echo "$CAPTURE_RESULT" | jq '.'

# Step 5: Log quality for each artifact
PATH_ID=$(echo "$CAPTURE_RESULT" | jq -r '.path_id')

/log-code-quality \
  --path-id "$PATH_ID" \
  --file-path "api/products.py" \
  --artifact-type "source_code" \
  --language "python" \
  --quality-score 0.94 \
  --onex-compliance 0.96 \
  --lines-added 187 \
  --test-coverage 92.5 \
  --lint-passed true \
  --type-check-passed true \
  --security-scan-passed true \
  --onex-node-type "Effect"

# Step 6: Record success pattern if quality exceeds threshold
if (( $(echo "$QUALITY_SCORE > 0.85" | bc -l) )); then
    FINGERPRINT_ID=$(echo "$CAPTURE_RESULT" | jq -r '.fingerprint_id')

    /record-success-pattern \
      --fingerprint-id "$FINGERPRINT_ID" \
      --path-id "$PATH_ID" \
      --pattern-name "Authenticated FastAPI CRUD Pattern" \
      --pattern-type "workflow" \
      --recommended-steps '[
        {"action": "rag_query", "query": "FastAPI CRUD {{entity}} authentication best practices", "expected_results": 5},
        {"action": "generate_code", "template": "onex_effect_crud_auth", "placeholders": ["entity_name", "auth_scheme"]},
        {"action": "generate_tests", "template": "crud_auth_tests", "coverage_target": 90},
        {"action": "validate", "checks": ["type_safety", "onex_compliance", "security"]}
      ]' \
      --validation-criteria '{
        "min_quality_score": 0.85,
        "min_test_coverage": 85,
        "required_security_checks": ["authentication", "authorization", "input_validation"]
      }' \
      --applicable-domains '["api_development", "backend_services"]' \
      --create-template true

    echo "Success pattern recorded and template created!"
fi

echo "Complete workflow finished!"
```

#### A.2 Failure Pattern Capture Workflow

```bash
#!/bin/bash
# Capture failure pattern for learning

CORRELATION_ID=$(uuidgen)

# Execution failed during type checking
FINGERPRINT_ID="uuid-from-capture"
ERROR_MESSAGE="Type error: Expected str, got int for field 'product_id' in Product model"
STACK_TRACE="..."
RESOLUTION="Changed product_id field type from str to Union[str, int] to handle both legacy and new ID formats"

/record-failure-pattern \
  --fingerprint-id "$FINGERPRINT_ID" \
  --correlation-id "$CORRELATION_ID" \
  --failure-type "validation_failure" \
  --error-category "type_error" \
  --error-message "$ERROR_MESSAGE" \
  --error-stack-trace "$STACK_TRACE" \
  --failed-step '{
    "step_number": 4,
    "step_type": "validation",
    "description": "Type safety validation",
    "tool": "mypy",
    "duration_ms": 340
  }' \
  --root-cause "Inconsistent ID format between legacy and new database records" \
  --contributing-factors '["database_migration_incomplete", "mixed_data_types"]' \
  --resolution "$RESOLUTION" \
  --resolution-steps '[
    {"action": "identify_root_cause", "duration_ms": 1200},
    {"action": "update_type_annotations", "files_modified": ["models/product.py"], "duration_ms": 450},
    {"action": "re_validate", "outcome": "success", "duration_ms": 320}
  ]' \
  --time-to-resolve-ms 3400 \
  --prevention-strategy '{
    "strategy": "Add runtime type coercion in Pydantic model validators",
    "implementation": "Use @validator decorator to normalize IDs on input",
    "automated_fix_possible": true
  }' \
  --automated-fix-available true

echo "Failure pattern recorded for future prevention!"
```

### Appendix B: Query Examples

#### B.1 Find Top Reusable Patterns

```sql
-- Find most successful and reusable patterns
SELECT
    sp.pattern_name,
    sp.pattern_type,
    sp.reuse_count,
    sp.success_rate,
    sp.avg_quality_improvement,
    array_length(sp.applicable_domains, 1) as domain_coverage,
    pt.template_name,
    pt.usage_count as template_usage
FROM success_patterns sp
LEFT JOIN pattern_templates pt ON sp.pattern_id = pt.derived_from_pattern_id
WHERE sp.success_rate > 85.0
  AND sp.reuse_count > 5
ORDER BY sp.reuse_count DESC, sp.success_rate DESC
LIMIT 20;
```

#### B.2 Identify Frequent Failure Patterns

```sql
-- Find most common failure patterns needing attention
SELECT
    fp.failure_type,
    fp.error_category,
    fp.occurrence_count,
    fp.error_message,
    fp.resolution_applied,
    CASE
        WHEN fp.automated_fix_available THEN 'Yes'
        ELSE 'No'
    END as auto_fix_available,
    fp.fix_success_rate,
    DATE_TRUNC('day', fp.last_occurrence_at) as last_seen
FROM failure_patterns fp
WHERE fp.occurrence_count > 3
  AND fp.last_occurrence_at > NOW() - INTERVAL '30 days'
ORDER BY fp.occurrence_count DESC
LIMIT 20;
```

#### B.3 Pattern Reuse Impact Analysis

```sql
-- Measure impact of pattern reuse on execution time and quality
WITH pattern_executions AS (
    SELECT
        ep.path_id,
        ep.fingerprint_id,
        ep.success,
        ep.quality_score,
        ep.total_duration_ms,
        ael.pattern_used_id IS NOT NULL as used_pattern
    FROM execution_paths ep
    JOIN agent_execution_logs ael ON ep.execution_id = ael.execution_id
    WHERE ep.completed_at > NOW() - INTERVAL '30 days'
)
SELECT
    used_pattern,
    COUNT(*) as execution_count,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality,
    ROUND(AVG(total_duration_ms)::numeric, 0) as avg_duration_ms,
    ROUND((SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*)) * 100, 2) as success_rate_pct
FROM pattern_executions
GROUP BY used_pattern
ORDER BY used_pattern DESC;

-- Expected output:
-- used_pattern | execution_count | avg_quality | avg_duration_ms | success_rate_pct
-- true         | 147             | 0.921       | 8450            | 96.60
-- false        | 283             | 0.857       | 15230           | 89.40
-- Time saving: (15230 - 8450) / 15230 * 100 = 44.5% faster with patterns!
```

#### B.4 Agent Performance with Learned Patterns

```sql
-- Compare agent performance with and without learned patterns
SELECT
    ael.agent_name,
    COUNT(CASE WHEN ael.pattern_used_id IS NOT NULL THEN 1 END) as executions_with_pattern,
    COUNT(CASE WHEN ael.pattern_used_id IS NULL THEN 1 END) as executions_without_pattern,
    ROUND(AVG(CASE WHEN ael.pattern_used_id IS NOT NULL THEN ael.quality_score END)::numeric, 3) as avg_quality_with_pattern,
    ROUND(AVG(CASE WHEN ael.pattern_used_id IS NULL THEN ael.quality_score END)::numeric, 3) as avg_quality_without_pattern,
    ROUND(AVG(CASE WHEN ael.pattern_used_id IS NOT NULL THEN ael.duration_ms END)::numeric, 0) as avg_time_with_pattern_ms,
    ROUND(AVG(CASE WHEN ael.pattern_used_id IS NULL THEN ael.duration_ms END)::numeric, 0) as avg_time_without_pattern_ms
FROM agent_execution_logs ael
WHERE ael.completed_at > NOW() - INTERVAL '30 days'
  AND ael.status = 'success'
GROUP BY ael.agent_name
HAVING COUNT(*) > 10
ORDER BY executions_with_pattern DESC;
```

### Appendix C: Security Considerations

#### C.1 Data Privacy

**Sensitive Data Handling**:
- User prompts may contain sensitive information (API keys, credentials, PII)
- Code artifacts may contain proprietary business logic
- Execution paths may reveal internal architecture

**Mitigation Strategies**:
1. **Prompt Sanitization**: Implement pre-processing to detect and redact sensitive patterns
2. **Content Hash Only**: Store content hashes instead of full code in some cases
3. **Access Control**: Implement row-level security on pattern tables
4. **Encryption**: Encrypt sensitive columns at rest
5. **Retention Policy**: Auto-delete old execution data after configurable period

#### C.2 SQL Injection Prevention

All skills use parameterized queries via `psycopg2`:

```python
# GOOD: Parameterized query
cursor.execute(
    "INSERT INTO task_fingerprints (task_hash, original_prompt) VALUES (%s, %s)",
    (task_hash, user_prompt)
)

# BAD: String concatenation (NEVER DO THIS)
cursor.execute(
    f"INSERT INTO task_fingerprints (task_hash, original_prompt) VALUES ('{task_hash}', '{user_prompt}')"
)
```

#### C.3 Rate Limiting

Implement rate limiting on skill execution to prevent abuse:

```python
# Rate limiting configuration
RATE_LIMITS = {
    '/check-similar-tasks': {'max_calls': 100, 'window_seconds': 60},
    '/capture-task-execution': {'max_calls': 50, 'window_seconds': 60},
    '/record-success-pattern': {'max_calls': 20, 'window_seconds': 60}
}
```

### Appendix D: Performance Optimization Tips

#### D.1 Indexing Strategy

**Critical Indexes** (already included in schema):
- `task_fingerprints.task_hash` - Uniqueness and fast lookup
- `task_fingerprints.embedding_vector` - IVFFlat for vector similarity
- `task_fingerprints.keyword_vector` - GIN for full-text search
- `execution_paths.fingerprint_id` - Foreign key joins
- `code_artifacts.quality_score DESC` - Sorting by quality

**Monitoring Index Usage**:
```sql
-- Check index usage statistics
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
```

#### D.2 Connection Pooling Configuration

```python
# Optimal connection pool settings for learning system
from psycopg2 import pool

connection_pool = pool.ThreadedConnectionPool(
    minconn=2,              # Minimum connections
    maxconn=10,             # Maximum connections
    host="localhost",
    port=5436,
    database="omninode_bridge",
    user="postgres",
    password="omninode-bridge-postgres-dev-2024",
    connect_timeout=5,      # Connection timeout
    keepalives=1,           # Enable TCP keepalives
    keepalives_idle=30,     # Idle time before keepalive
    keepalives_interval=10, # Interval between keepalives
    keepalives_count=5      # Max keepalive probes
)
```

#### D.3 Caching Strategy

**Cache Frequently Accessed Patterns**:
```python
from functools import lru_cache
import time

# Cache pattern templates for 1 hour
@lru_cache(maxsize=100)
def get_pattern_template_cached(template_id: str, cache_time: int = None):
    """
    Cached pattern template retrieval.
    cache_time parameter forces cache refresh every hour.
    """
    if cache_time is None:
        cache_time = int(time.time() / 3600)  # Hour bucket

    return get_pattern_template(template_id)

# Usage
template = get_pattern_template_cached(
    template_id="uuid",
    cache_time=int(time.time() / 3600)  # Refreshes every hour
)
```

### Appendix E: Glossary

| Term | Definition |
|------|------------|
| **Task Fingerprint** | Unique identifier for a task based on normalized prompt, type, and domain |
| **Execution Path** | Step-by-step sequence of actions taken during task execution |
| **Success Pattern** | Reusable execution template extracted from successful task completions |
| **Failure Pattern** | Documented failure scenario with root cause and resolution |
| **Pattern Template** | Parameterized template for code generation or workflow execution |
| **Similarity Score** | Numeric measure (0.0-1.0) of how similar two tasks are |
| **Quality Score** | Numeric measure (0.0-1.0) of execution quality based on multiple criteria |
| **Pattern Reuse Rate** | Percentage of tasks that leverage existing patterns |
| **ONEX Compliance** | Adherence to ONEX architectural standards (node types, patterns) |
| **Hybrid Search** | Combination of database similarity search and RAG semantic search |

---

## Conclusion

This comprehensive plan provides a complete roadmap for implementing an agent learning and outcome tracking system that enables "prompt → success shortcut" learning. By capturing execution outcomes, extracting reusable patterns, and providing intelligent recommendations, the system will significantly improve agent efficiency, quality consistency, and continuous learning capabilities.

**Next Steps**:
1. Review and approve this plan with stakeholders
2. Allocate development resources (estimated 280-360 hours over 10-12 weeks)
3. Begin Phase 1 implementation: Database schema and basic skills
4. Establish monitoring and metrics collection from day one
5. Iterate based on real-world usage and feedback

**Questions or Feedback**: Contact the polymorphic agent team or create an issue in the project repository.

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-20
**Authors**: Polymorphic Agent (Polly) with Archon MCP Intelligence
**Status**: Ready for Review and Approval
