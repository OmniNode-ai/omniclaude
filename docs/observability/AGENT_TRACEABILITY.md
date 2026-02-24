> ⚠️ **DEPRECATED**: This document describes the pre-DB-split database schema (agent_execution_logs, agent_actions tables). Current observability uses Kafka event emission via the emit daemon. Kept because it is referenced by `plugins/onex/skills/routing/request-agent-routing/SKILL.md`.

---

# Agent Traceability System

Complete observability and traceability for polymorphic agent executions with Kafka-based event logging and PostgreSQL persistence.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Database Schema](#database-schema)
3. [Correlation ID Tracking](#correlation-id-tracking)
4. [Event Flow](#event-flow)
5. [Query Examples](#query-examples)
6. [Integration Points](#integration-points)
7. [Performance Targets](#performance-targets)

---

## Architecture Overview

### Three-Layer Traceability

The agent traceability system provides complete observability through three interconnected layers:

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER REQUEST                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  LAYER 1: ROUTING    │
                    │  agent_routing_      │
                    │  decisions           │
                    │  - Which agent?      │
                    │  - Why?              │
                    │  - Confidence?       │
                    └──────────┬───────────┘
                               │ correlation_id
                               ▼
                    ┌──────────────────────┐
                    │  LAYER 2: MANIFEST   │
                    │  agent_manifest_     │
                    │  injections          │
                    │  - What context?     │
                    │  - Which patterns?   │
                    │  - Debug intel?      │
                    └──────────┬───────────┘
                               │ correlation_id
                               ▼
                    ┌──────────────────────┐
                    │  LAYER 3: EXECUTION  │
                    │  agent_execution_    │
                    │  logs                │
                    │  - Start/progress    │
                    │  - Completion        │
                    │  - Quality score     │
                    └──────────────────────┘
```

### Key Components

#### 1. AgentExecutionLogger (`agents/lib/agent_execution_logger.py`)

Comprehensive execution logger with dual-path logging:
- **Primary**: PostgreSQL database (async via asyncpg pool)
- **Fallback**: Structured JSON files (when database unavailable)
- **Features**:
  - Non-blocking (never fails agent execution)
  - Exponential backoff retry (1m, 2m, 5m, 10m)
  - Platform-aware logging (uses tempfile.gettempdir())
  - Correlation ID tracking
  - Quality score capture

#### 2. ManifestInjector (`agents/lib/manifest_injector.py`)

Dynamic system context injection via event bus:
- Queries archon-intelligence via Kafka
- Parallel query execution (<2000ms total)
- Complete traceability with correlation IDs
- Stores complete snapshots for replay

#### 3. AgentHistoryBrowser (`agents/lib/agent_history_browser.py`)

Interactive CLI tool for browsing execution history:
- List recent agent executions
- Drill down into manifest details
- View debug intelligence
- Export manifest JSON
- Rich terminal UI (falls back to basic)

---

## Database Schema

### Table: agent_routing_decisions

Tracks routing decisions with confidence scoring and full reasoning.

```sql
CREATE TABLE agent_routing_decisions (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL,
    session_id UUID,

    -- User input
    user_request TEXT NOT NULL,
    user_request_hash VARCHAR(64),
    context_snapshot JSONB,

    -- Routing decision
    selected_agent VARCHAR(255) NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    routing_strategy VARCHAR(100) NOT NULL,

    -- Confidence breakdown (4-component scoring)
    trigger_confidence NUMERIC(5,4),
    context_confidence NUMERIC(5,4),
    capability_confidence NUMERIC(5,4),
    historical_confidence NUMERIC(5,4),

    -- Alternative recommendations
    alternatives JSONB,
    alternatives_count INTEGER DEFAULT 0,

    -- Decision reasoning
    reasoning TEXT,
    matched_triggers TEXT[],
    matched_capabilities TEXT[],

    -- Performance metrics
    routing_time_ms INTEGER NOT NULL,
    cache_hit BOOLEAN DEFAULT FALSE,
    cache_key VARCHAR(255),

    -- Outcome validation (filled in after execution)
    selection_validated BOOLEAN DEFAULT FALSE,
    actual_success BOOLEAN,
    actual_quality_score NUMERIC(5,4),
    prediction_error NUMERIC(5,4),

    -- Metadata and timestamps
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    validated_at TIMESTAMP WITH TIME ZONE
);
```

**Key Fields**:
- `correlation_id`: Links routing → manifest → execution → outcome
- `confidence_score`: Weighted sum of 4 components (trigger 40%, context 30%, capability 20%, historical 10%)
- `routing_strategy`: "enhanced_fuzzy_matching", "explicit", "fallback"
- `routing_time_ms`: Target <100ms for routing decision

**Indexes**:
- `correlation_id` - Join with manifest injections and executions
- `selected_agent, created_at` - Agent-specific analysis
- `routing_strategy, created_at` - Strategy performance
- `confidence_score DESC, created_at DESC` - High-confidence decisions
- `user_request_hash, context_snapshot` - Deduplication and caching

### Table: agent_manifest_injections

Complete record of manifest injections for full execution replay.

```sql
CREATE TABLE agent_manifest_injections (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL,
    session_id UUID,
    routing_decision_id UUID REFERENCES agent_routing_decisions(id),

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,
    agent_version VARCHAR(50) DEFAULT '1.0.0',

    -- Manifest generation metadata
    manifest_version VARCHAR(50) NOT NULL,
    generation_source VARCHAR(100) NOT NULL,
    is_fallback BOOLEAN DEFAULT FALSE,

    -- Manifest sections included
    sections_included TEXT[] NOT NULL,
    sections_requested TEXT[],

    -- Query results summary
    patterns_count INTEGER DEFAULT 0,
    infrastructure_services INTEGER DEFAULT 0,
    models_count INTEGER DEFAULT 0,
    database_schemas_count INTEGER DEFAULT 0,
    debug_intelligence_successes INTEGER DEFAULT 0,
    debug_intelligence_failures INTEGER DEFAULT 0,

    -- Collections queried
    collections_queried JSONB,

    -- Performance metrics
    query_times JSONB NOT NULL,
    total_query_time_ms INTEGER NOT NULL,
    cache_hit BOOLEAN DEFAULT FALSE,
    cache_age_seconds INTEGER,

    -- Complete manifest snapshot
    full_manifest_snapshot JSONB NOT NULL,
    formatted_manifest_text TEXT,
    manifest_size_bytes INTEGER,

    -- Quality indicators
    intelligence_available BOOLEAN DEFAULT TRUE,
    query_failures JSONB,
    warnings TEXT[],

    -- Outcome tracking (filled in after agent execution)
    agent_execution_success BOOLEAN,
    agent_execution_time_ms INTEGER,
    agent_quality_score NUMERIC(5,4),

    -- Metadata and timestamps
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);
```

**Key Fields**:
- `full_manifest_snapshot`: Complete manifest data structure - enables exact replay
- `formatted_manifest_text`: Exact text injected into agent prompt
- `query_times`: Breakdown of query performance per section (JSON: `{"patterns": 450, "infrastructure": 200, ...}`)
- `total_query_time_ms`: Target <2000ms for complete manifest generation
- `debug_intelligence_successes/failures`: Count of similar past workflows

**Indexes**:
- `correlation_id` - Join with routing decisions and executions
- `agent_name, created_at DESC` - Agent-specific history
- `generation_source, is_fallback` - Fallback analysis
- `total_query_time_ms, patterns_count` - Performance optimization
- GIN indexes on JSONB fields for complex queries

### Table: agent_execution_logs

Tracks complete execution lifecycle with progress updates.

```sql
CREATE TABLE agent_execution_logs (
    -- Primary key
    execution_id UUID PRIMARY KEY,

    -- Correlation and tracing
    correlation_id UUID NOT NULL,
    session_id UUID NOT NULL,

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,
    user_prompt TEXT,

    -- Execution status
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    quality_score NUMERIC(5,4),

    -- Error details (if failed)
    error_message TEXT,
    error_type VARCHAR(255),

    -- Performance
    duration_ms INTEGER,

    -- Project context
    project_path TEXT,
    project_name VARCHAR(255),
    claude_session_id VARCHAR(255),
    terminal_id VARCHAR(255),

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);
```

**Key Fields**:
- `execution_id`: Unique identifier for this execution
- `correlation_id`: Links to routing and manifest
- `status`: "in_progress", "success", "failed", "cancelled"
- `metadata`: Progress updates stored as JSONB

### Analytical Views

#### v_agent_execution_trace

Complete execution trace from routing to completion:

```sql
CREATE VIEW v_agent_execution_trace AS
SELECT
    ard.correlation_id,
    ard.user_request,
    ard.selected_agent,
    ard.confidence_score,
    ard.routing_strategy,
    ard.reasoning AS routing_reasoning,
    ard.routing_time_ms,
    ami.manifest_version,
    ami.generation_source,
    ami.is_fallback,
    ami.patterns_count,
    ami.debug_intelligence_successes,
    ami.debug_intelligence_failures,
    ami.total_query_time_ms,
    ami.agent_execution_success,
    ami.agent_quality_score,
    ate.transformation_duration_ms,
    ate.total_execution_duration_ms,
    ard.created_at AS routing_time,
    ami.created_at AS manifest_time,
    ate.started_at AS execution_start_time,
    ate.completed_at AS execution_end_time
FROM agent_routing_decisions ard
LEFT JOIN agent_manifest_injections ami
    ON ard.correlation_id = ami.correlation_id
LEFT JOIN agent_transformation_events ate
    ON ard.correlation_id = ate.correlation_id
ORDER BY ard.created_at DESC;
```

#### v_manifest_injection_performance

Performance metrics by agent and source:

```sql
CREATE VIEW v_manifest_injection_performance AS
SELECT
    agent_name,
    generation_source,
    COUNT(*) AS total_injections,
    AVG(total_query_time_ms) AS avg_query_time_ms,
    AVG(patterns_count) AS avg_patterns_count,
    COUNT(CASE WHEN is_fallback = TRUE THEN 1 END) AS fallback_count,
    (COUNT(CASE WHEN is_fallback = TRUE THEN 1 END)::numeric * 100) /
        NULLIF(COUNT(*), 0) AS fallback_percent,
    COUNT(CASE WHEN agent_execution_success = TRUE THEN 1 END) AS success_count,
    AVG(agent_quality_score) AS avg_quality_score
FROM agent_manifest_injections
GROUP BY agent_name, generation_source
ORDER BY total_injections DESC;
```

#### v_routing_decision_accuracy

Routing accuracy analysis:

```sql
CREATE VIEW v_routing_decision_accuracy AS
SELECT
    selected_agent,
    routing_strategy,
    COUNT(*) AS total_decisions,
    AVG(confidence_score) AS avg_confidence,
    COUNT(CASE WHEN selection_validated = TRUE THEN 1 END) AS validated_count,
    COUNT(CASE WHEN actual_success = TRUE THEN 1 END) AS success_count,
    (COUNT(CASE WHEN actual_success = TRUE THEN 1 END)::numeric * 100) /
        NULLIF(COUNT(CASE WHEN selection_validated = TRUE THEN 1 END), 0) AS accuracy_percent,
    AVG(prediction_error) AS avg_prediction_error,
    AVG(routing_time_ms) AS avg_routing_time_ms
FROM agent_routing_decisions
GROUP BY selected_agent, routing_strategy
ORDER BY total_decisions DESC;
```

---

## Correlation ID Tracking

### Complete Trace Flow

Every agent execution is tracked with a unique correlation ID that links:

```
┌─────────────────────────────────────────────────────────────────┐
│ Correlation ID: 8b57ec39-45b5-467b-939c-dd1439219f69            │
└─────────────────────────────────────────────────────────────────┘

1. USER REQUEST
   user_request = "optimize database queries"
   ↓
2. ROUTING DECISION (agent_routing_decisions)
   selected_agent = "agent-performance"
   confidence_score = 0.92
   routing_strategy = "enhanced_fuzzy_matching"
   routing_time_ms = 45
   ↓
3. MANIFEST INJECTION (agent_manifest_injections)
   patterns_count = 120
   debug_intelligence_successes = 12
   total_query_time_ms = 1842
   ↓
4. AGENT EXECUTION (agent_execution_logs)
   status = "success"
   quality_score = 0.89
   duration_ms = 15420
   ↓
5. VALIDATION (agent_routing_decisions.actual_success)
   actual_success = true
   prediction_error = 0.03
```

### Correlation ID Generation

```python
from uuid import uuid4

# Generate correlation ID at entry point
correlation_id = uuid4()

# Pass through entire execution chain
logger = AgentExecutionLogger(
    agent_name="agent-performance",
    correlation_id=correlation_id  # Same ID propagated
)

# Manifest injection uses same ID
manifest = inject_manifest(correlation_id=correlation_id)

# Routing decision uses same ID
log_routing_decision(
    agent="agent-performance",
    correlation_id=correlation_id
)
```

---

## Event Flow

### Kafka Event Bus Integration

Complete flow from agent spawn to database persistence:

```
┌──────────────────────────────────────────────────────────────────┐
│                     AGENT EXECUTION START                         │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ AgentExecutionLogger     │
    │ - Generate execution_id  │
    │ - Log to PostgreSQL      │
    │ - Fallback to file       │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ ManifestInjector         │
    │ - Publish to Kafka       │
    │   intelligence.requests  │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Kafka Event Bus          │
    │ - Route to consumer      │
    │ - Persist to disk        │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ archon-intelligence      │
    │ - Query Qdrant           │
    │ - Query Memgraph         │
    │ - Query PostgreSQL       │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Kafka Event Bus          │
    │ - Publish response       │
    │   intelligence.responses │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ ManifestInjector         │
    │ - Format manifest        │
    │ - Store to PostgreSQL    │
    │   agent_manifest_        │
    │   injections             │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Agent Execution          │
    │ - Use injected context   │
    │ - Log progress updates   │
    └──────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ AgentExecutionLogger     │
    │ - Complete execution     │
    │ - Log quality score      │
    └──────────────────────────┘
```

### Event Topics

**Intelligence Topics**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1` - Pattern discovery requests
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1` - Successful responses
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1` - Failed requests

**Agent Tracking Topics** (future):
- `onex.evt.omniclaude.routing-decision.v1` - Routing decisions
- `agent-transformation-events` - Agent transformations
- `router-performance-metrics` - Performance metrics
- `agent-actions` - Individual tool calls

---

## Query Examples

### Find Complete Execution Trace

```sql
-- Get complete trace for a correlation ID
SELECT * FROM v_agent_execution_trace
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';

-- Get all executions for specific agent
SELECT * FROM v_agent_execution_trace
WHERE selected_agent = 'agent-performance'
ORDER BY routing_time DESC
LIMIT 20;
```

### Analyze Routing Accuracy

```sql
-- Routing accuracy by agent
SELECT * FROM v_routing_decision_accuracy
ORDER BY accuracy_percent DESC;

-- Find misrouted requests (low confidence, failed execution)
SELECT
    user_request,
    selected_agent,
    confidence_score,
    actual_success,
    routing_reasoning
FROM agent_routing_decisions ard
JOIN agent_manifest_injections ami USING (correlation_id)
WHERE confidence_score < 0.7
  AND actual_success = FALSE
ORDER BY created_at DESC;
```

### Manifest Injection Performance

```sql
-- Performance by agent
SELECT * FROM v_manifest_injection_performance
ORDER BY avg_query_time_ms DESC;

-- Find slow manifest generations
SELECT
    correlation_id,
    agent_name,
    total_query_time_ms,
    query_times,
    patterns_count
FROM agent_manifest_injections
WHERE total_query_time_ms > 5000
ORDER BY total_query_time_ms DESC
LIMIT 20;

-- Fallback analysis
SELECT
    agent_name,
    COUNT(*) AS total,
    COUNT(CASE WHEN is_fallback THEN 1 END) AS fallback_count,
    (COUNT(CASE WHEN is_fallback THEN 1 END)::numeric * 100) / COUNT(*) AS fallback_percent
FROM agent_manifest_injections
GROUP BY agent_name
ORDER BY fallback_percent DESC;
```

### Debug Intelligence Usage

```sql
-- Agents with most debug intelligence
SELECT
    agent_name,
    AVG(debug_intelligence_successes) AS avg_successes,
    AVG(debug_intelligence_failures) AS avg_failures,
    COUNT(*) AS total_executions
FROM agent_manifest_injections
WHERE debug_intelligence_successes > 0
   OR debug_intelligence_failures > 0
GROUP BY agent_name
ORDER BY avg_successes DESC;

-- View complete manifest for debugging
SELECT
    correlation_id,
    agent_name,
    full_manifest_snapshot,
    formatted_manifest_text
FROM agent_manifest_injections
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';
```

### Agent Execution Analysis

```sql
-- Recent executions with status
SELECT
    execution_id,
    agent_name,
    status,
    quality_score,
    duration_ms,
    created_at
FROM agent_execution_logs
ORDER BY created_at DESC
LIMIT 50;

-- Failed executions for debugging
SELECT
    execution_id,
    correlation_id,
    agent_name,
    error_message,
    error_type,
    user_prompt
FROM agent_execution_logs
WHERE status = 'failed'
ORDER BY created_at DESC;
```

---

## Integration Points

### 1. Agent Execution Wrapper

Every agent execution should use AgentExecutionLogger:

```python
from agents.lib.agent_execution_logger import log_agent_execution
from omnibase_core.enums.enum_operation_status import EnumOperationStatus

async def execute_agent_task():
    # Start logging
    logger = await log_agent_execution(
        agent_name="agent-researcher",
        user_prompt="Research ONEX patterns",
        correlation_id=correlation_id,
        project_path="/path/to/project"
    )

    try:
        # Log progress
        await logger.progress(stage="gathering_intelligence", percent=25)

        # Do work...
        result = await do_research()

        await logger.progress(stage="analyzing_results", percent=75)

        # Complete with success
        await logger.complete(
            status=EnumOperationStatus.SUCCESS,
            quality_score=0.92
        )

        return result

    except Exception as e:
        # Complete with error
        await logger.complete(
            status=EnumOperationStatus.FAILED,
            error_message=str(e),
            error_type=type(e).__name__
        )
        raise
```

### 2. Manifest Injection Integration

Manifest injection automatically logs to database:

```python
from agents.lib.manifest_injector import inject_manifest

# Inject manifest with correlation tracking
manifest = inject_manifest(
    correlation_id=correlation_id,
    agent_name="agent-researcher"
)

# Record is automatically created in agent_manifest_injections
# with complete snapshot for replay
```

### 3. History Browser Integration

Browse execution history interactively:

```bash
# Interactive mode
python3 agents/lib/agent_history_browser.py

# Filter by agent
python3 agents/lib/agent_history_browser.py --agent agent-researcher

# View specific execution
python3 agents/lib/agent_history_browser.py --correlation-id 8b57ec39...

# Export manifest
python3 agents/lib/agent_history_browser.py \
    --correlation-id 8b57ec39... \
    --export manifest.json
```

### 4. Health Monitoring Integration

System health check includes observability metrics:

```bash
./scripts/health_check.sh

# Output includes:
# - Recent manifest injections (24h)
# - Average query times
# - Fallback rates
# - Intelligence availability
```

---

## Performance Targets

### Routing Performance

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Routing decision time | <100ms | >200ms | >500ms |
| Cache hit rate | >60% | <40% | <20% |
| Routing accuracy | >95% | <90% | <80% |

### Manifest Injection Performance

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Total query time | <2000ms | >3000ms | >5000ms |
| Pattern discovery | 100+ patterns | <50 patterns | <10 patterns |
| Fallback rate | <5% | >10% | >20% |
| Intelligence availability | >95% | <90% | <80% |

### Execution Logging Performance

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Log write latency | <50ms | >100ms | >500ms |
| Database availability | >99% | <95% | <90% |
| Fallback activation | <1% | >5% | >10% |

### Query Performance

Indexes ensure fast queries:
- Correlation ID lookups: <10ms
- Agent history queries: <50ms
- Time-range queries: <100ms
- Complex analytical queries: <500ms

---

## See Also

- [DIAGNOSTIC_SCRIPTS.md](./DIAGNOSTIC_SCRIPTS.md) - Diagnostic tools usage
- [LOGGING_PIPELINE.md](./LOGGING_PIPELINE.md) - Event flow architecture
- [../../CLAUDE.md](../../CLAUDE.md#diagnostic-tools) - Main documentation

---

**Last Updated**: 2025-10-29
**Schema Version**: 1.0.0 (Migration 008_agent_manifest_traceability.sql)
**Database**: omninode_bridge @ <postgres-host>:5436
