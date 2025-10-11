# Phase 4 Pattern Traceability API Reference

**Version**: 1.0.0
**Base URL**: `http://localhost:8053`
**API Prefix**: `/api/pattern-traceability`

---

## Table of Contents

1. [Execution Tracer API](#execution-tracer-api)
2. [PostgreSQL Tracing Client API](#postgresql-tracing-client-api)
3. [Phase 4 REST API](#phase-4-rest-api)
4. [Data Models](#data-models)
5. [Error Codes](#error-codes)

---

## Execution Tracer API

High-level interface for execution tracing in the Intelligence Hook System.

**Module**: `lib/tracing/tracer.py`

### Class: `ExecutionTracer`

#### Constructor

```python
ExecutionTracer(
    postgres_client: Optional[PostgresTracingClient] = None,
    auto_initialize: bool = True
)
```

**Parameters**:
- `postgres_client`: PostgreSQL tracing client. If None, creates new one.
- `auto_initialize`: Whether to auto-initialize database connection

**Example**:
```python
from lib.tracing.tracer import ExecutionTracer

tracer = ExecutionTracer()
```

#### `start_trace()`

Start a new execution trace.

```python
async def start_trace(
    source: str,
    prompt_text: str,
    session_id: str,
    correlation_id: Optional[str] = None,
    root_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> str
```

**Parameters**:
- `source` (str, required): Source of execution (e.g., "pre-tool-use", "user-prompt-submit")
- `prompt_text` (str, required): User's prompt/input text
- `session_id` (str, required): Claude Code session identifier
- `correlation_id` (str, optional): Optional correlation ID (generates if None)
- `root_id` (str, optional): Optional root trace ID (uses correlation_id if None)
- `parent_id` (str, optional): Optional parent trace ID
- `context` (dict, optional): Additional context data
- `user_id` (str, optional): Optional user identifier
- `tags` (list[str], optional): Optional tags for categorization

**Returns**: `str` - Correlation ID as string (for environment propagation)

**Raises**: Never raises - logs errors and returns generated/provided correlation_id

**Example**:
```python
corr_id = await tracer.start_trace(
    source="user-prompt-submit",
    prompt_text="Implement authentication",
    session_id="550e8400-e29b-41d4-a716-446655440000",
    tags=["authentication", "backend"]
)
print(f"Started trace: {corr_id}")
```

#### `track_hook_execution()`

Track a hook execution within a trace.

```python
async def track_hook_execution(
    correlation_id: str,
    hook_name: str,
    tool_name: str,
    duration_ms: float,
    success: bool = True,
    hook_type: Optional[str] = None,
    file_path: Optional[str] = None,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    modifications_made: Optional[Dict[str, Any]] = None,
    rag_query_performed: bool = False,
    rag_results: Optional[Dict[str, Any]] = None,
    quality_check_performed: bool = False,
    quality_results: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None
```

**Parameters**:
- `correlation_id` (str, required): Correlation ID of the parent trace
- `hook_name` (str, required): Name of the hook (e.g., "quality-enforcer")
- `tool_name` (str, required): Name of the tool being used
- `duration_ms` (float, required): Execution duration in milliseconds
- `success` (bool, optional): Whether the hook executed successfully (default: True)
- `hook_type` (str, optional): Type of hook (e.g., "PreToolUse", "PostToolUse")
- `file_path` (str, optional): File path if applicable
- `input_data` (dict, optional): Input data to the hook
- `output_data` (dict, optional): Output data from the hook
- `modifications_made` (dict, optional): Any modifications made by the hook
- `rag_query_performed` (bool, optional): Whether RAG query was performed (default: False)
- `rag_results` (dict, optional): Results from RAG query
- `quality_check_performed` (bool, optional): Whether quality check was performed (default: False)
- `quality_results` (dict, optional): Results from quality check
- `error` (Exception, optional): Exception if hook failed
- `metadata` (dict, optional): Additional metadata

**Returns**: `None`

**Raises**: Never raises - logs errors silently

**Example**:
```python
await tracer.track_hook_execution(
    correlation_id=corr_id,
    hook_name="quality-enforcer",
    tool_name="Write",
    duration_ms=125.5,
    success=True,
    file_path="/path/to/file.py",
    quality_check_performed=True,
    quality_results={
        "violations_found": 3,
        "corrections_applied": 2,
        "quality_score": 0.85
    }
)
```

#### `complete_trace()`

Mark a trace as completed.

```python
async def complete_trace(
    correlation_id: str,
    success: bool,
    error: Optional[Exception] = None
) -> None
```

**Parameters**:
- `correlation_id` (str, required): Correlation ID of the trace to complete
- `success` (bool, required): Whether the execution succeeded overall
- `error` (Exception, optional): Exception if execution failed

**Returns**: `None`

**Raises**: Never raises - logs errors silently

**Example**:
```python
await tracer.complete_trace(corr_id, success=True)
```

#### `trace_execution()` (Context Manager)

Context manager for automatic trace lifecycle management.

```python
@asynccontextmanager
async def trace_execution(
    source: str,
    prompt_text: str,
    session_id: str,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None
)
```

**Parameters**: Same as `start_trace()`

**Yields**: `TraceContext` object with helper methods

**Example**:
```python
async with tracer.trace_execution(
    source="pre-tool-use",
    prompt_text="Write a file",
    session_id=session_id
) as trace_ctx:
    # Do work...
    await trace_ctx.track_hook(
        hook_name="quality-enforcer",
        tool_name="Write",
        duration_ms=45.2
    )
# Automatically completes on exit
```

---

## PostgreSQL Tracing Client API

Async PostgreSQL client for tracing data with connection pooling.

**Module**: `lib/tracing/postgres_client.py`

### Class: `PostgresTracingClient`

#### Constructor

```python
PostgresTracingClient(
    connection_url: Optional[str] = None,
    min_pool_size: int = 5,
    max_pool_size: int = 20,
    command_timeout: float = 10.0,
    max_retry_attempts: int = 3,
    retry_base_delay: float = 0.5
)
```

**Parameters**:
- `connection_url`: PostgreSQL connection URL. If None, uses env var.
- `min_pool_size`: Minimum number of connections in pool (default: 5)
- `max_pool_size`: Maximum number of connections in pool (default: 20)
- `command_timeout`: Query timeout in seconds (default: 10.0)
- `max_retry_attempts`: Maximum retry attempts for failed operations (default: 3)
- `retry_base_delay`: Base delay in seconds for exponential backoff (default: 0.5)

#### `initialize()`

Initialize connection pool with retry logic.

```python
async def initialize() -> bool
```

**Returns**: `bool` - True if successful, False otherwise

**Example**:
```python
client = PostgresTracingClient()
success = await client.initialize()
if success:
    print("Connection pool initialized")
```

#### `create_execution_trace()`

Create a new execution trace record.

```python
async def create_execution_trace(
    correlation_id: UUID,
    root_id: UUID,
    parent_id: Optional[UUID],
    session_id: UUID,
    source: str,
    prompt_text: Optional[str] = None,
    user_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None
) -> Optional[UUID]
```

**Parameters**:
- `correlation_id` (UUID, required): Unique identifier for this execution chain
- `root_id` (UUID, required): Root trace ID in nested execution
- `parent_id` (UUID, optional): Parent execution ID (None for root traces)
- `session_id` (UUID, required): Claude Code session identifier
- `source` (str, required): Source of execution (e.g., "pre-tool-use", "user-prompt-submit")
- `prompt_text` (str, optional): User's prompt text
- `user_id` (str, optional): Optional user identifier
- `context` (dict, optional): Additional context as JSON
- `tags` (list[str], optional): Optional tags for categorization

**Returns**: `UUID` - UUID of the created trace record, or None if failed

**Example**:
```python
from uuid import uuid4

trace_id = await client.create_execution_trace(
    correlation_id=uuid4(),
    root_id=uuid4(),
    parent_id=None,
    session_id=uuid4(),
    source="user-prompt-submit",
    prompt_text="Implement authentication",
    tags=["auth", "backend"]
)
```

#### `complete_execution_trace()`

Mark an execution trace as completed.

```python
async def complete_execution_trace(
    correlation_id: UUID,
    success: bool,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None
) -> bool
```

**Parameters**:
- `correlation_id` (UUID, required): Correlation ID of the trace to complete
- `success` (bool, required): Whether the execution succeeded
- `error_message` (str, optional): Error message if failed
- `error_type` (str, optional): Type of error if failed

**Returns**: `bool` - True if successful, False otherwise

#### `record_hook_execution()`

Record a hook execution.

```python
async def record_hook_execution(
    trace_id: UUID,
    hook_type: str,
    hook_name: str,
    execution_order: int,
    tool_name: Optional[str] = None,
    file_path: Optional[str] = None,
    duration_ms: Optional[float] = None,
    status: str = "completed",
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    modifications_made: Optional[Dict[str, Any]] = None,
    rag_query_performed: bool = False,
    rag_results: Optional[Dict[str, Any]] = None,
    quality_check_performed: bool = False,
    quality_results: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None,
    error_stack: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[UUID]
```

**Parameters**: See [Execution Tracer API - track_hook_execution()](#track_hook_execution) for parameter descriptions

**Returns**: `UUID` - UUID of the created hook execution record, or None if failed

#### `get_trace_with_hooks()`

Retrieve execution trace with all associated hook executions.

```python
async def get_trace_with_hooks(correlation_id: str) -> Optional[Dict[str, Any]]
```

**Parameters**:
- `correlation_id` (str, required): Correlation ID to lookup

**Returns**: `dict` or `None` - Dict containing trace and hooks, or None if not found
```json
{
  "trace": {...},  // Execution trace record
  "hooks": [...]   // List of hook execution records ordered by execution_order
}
```

**Example**:
```python
result = await client.get_trace_with_hooks("550e8400-e29b-41d4-a716-446655440000")
if result:
    print(f"Trace status: {result['trace']['status']}")
    print(f"Hook count: {len(result['hooks'])}")
```

---

## Phase 4 REST API

REST API for pattern lineage tracking, usage analytics, and feedback loops.

**Base URL**: `http://localhost:8053/api/pattern-traceability`

### Pattern Lineage Endpoints

#### `POST /lineage/track`

Track pattern lineage event (creation, modification, merge, etc.)

**Performance**: <50ms for tracking operations

**Request Body**:
```json
{
  "event_type": "pattern_created",
  "pattern_id": "async_db_writer_v3",
  "pattern_name": "Async Database Writer",
  "pattern_type": "code",
  "pattern_version": "3.0.0",
  "pattern_data": {
    "template_code": "async def write_to_db...",
    "language": "python"
  },
  "parent_pattern_ids": ["async_db_writer_v2"],
  "edge_type": "derived_from",
  "transformation_type": "optimization",
  "reason": "Improved connection pooling",
  "triggered_by": "claude_code"
}
```

**Request Parameters**:
- `event_type` (string, required): Event type (pattern_created, pattern_modified, pattern_merged, pattern_applied, pattern_deprecated, pattern_forked)
- `pattern_id` (string, required): Unique pattern identifier
- `pattern_name` (string, optional): Human-readable pattern name (default: "")
- `pattern_type` (string, optional): Pattern type (code, config, template, workflow) (default: "code")
- `pattern_version` (string, optional): Pattern version (semantic versioning) (default: "1.0.0")
- `pattern_data` (object, optional): Pattern content snapshot (default: {})
- `parent_pattern_ids` (array[string], optional): Parent pattern IDs (default: [])
- `edge_type` (string, optional): Relationship type to parent
- `transformation_type` (string, optional): Type of transformation applied
- `reason` (string, optional): Reason for the event
- `triggered_by` (string, optional): Who/what triggered the event (default: "api")

**Response** (200 OK):
```json
{
  "success": true,
  "data": {
    "node_id": "550e8400-e29b-41d4-a716-446655440000",
    "pattern_id": "async_db_writer_v3",
    "generation": 2,
    "event_recorded": true
  },
  "metadata": {
    "processing_time_ms": 35.2,
    "operation": "track_creation"
  }
}
```

**Response** (503 Service Unavailable):
```json
{
  "success": false,
  "error": "Database connection not available - lineage tracking disabled",
  "pattern_id": "async_db_writer_v3",
  "event_type": "pattern_created",
  "message": "Configure TRACEABILITY_DB_URL or DATABASE_URL environment variable",
  "processing_time_ms": 1.5
}
```

**cURL Example**:
```bash
curl -X POST http://localhost:8053/api/pattern-traceability/lineage/track \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "pattern_created",
    "pattern_id": "async_db_writer_v3",
    "pattern_name": "Async Database Writer",
    "pattern_type": "code",
    "pattern_version": "3.0.0",
    "pattern_data": {
      "template_code": "async def write_to_db...",
      "language": "python"
    },
    "parent_pattern_ids": ["async_db_writer_v2"],
    "edge_type": "derived_from",
    "triggered_by": "claude_code"
  }'
```

#### `GET /lineage/{pattern_id}`

Get pattern lineage graph (ancestry or descendants)

**Performance**: <200ms for ancestry query with depth up to 10

**Path Parameters**:
- `pattern_id` (string, required): Pattern ID to query

**Query Parameters**:
- `query_type` (string, optional): Query type: "ancestry" or "descendants" (default: "ancestry")

**Response** (200 OK):
```json
{
  "success": true,
  "data": {
    "pattern_id": "async_db_writer_v3",
    "query_type": "ancestry",
    "ancestors": [
      {
        "pattern_id": "async_db_writer_v2",
        "pattern_name": "Async Database Writer v2",
        "generation": 1,
        "edge_type": "derived_from",
        "distance": 1
      },
      {
        "pattern_id": "async_db_writer_v1",
        "pattern_name": "Async Database Writer v1",
        "generation": 0,
        "edge_type": "derived_from",
        "distance": 2
      }
    ]
  },
  "metadata": {
    "processing_time_ms": 145.3,
    "query_type": "ancestry",
    "total_ancestors": 2
  }
}
```

**Response** (404 Not Found):
```json
{
  "success": false,
  "error": "Pattern not found: unknown_pattern",
  "metadata": {
    "processing_time_ms": 10.5
  }
}
```

**cURL Example**:
```bash
curl http://localhost:8053/api/pattern-traceability/lineage/async_db_writer_v3?query_type=ancestry
```

#### `GET /lineage/{pattern_id}/evolution`

Get evolution path showing how a pattern changed over time.

**Performance**: <200ms target

**Path Parameters**:
- `pattern_id` (string, required): Pattern ID to query

**Response** (200 OK):
```json
{
  "success": true,
  "data": {
    "pattern_id": "async_db_writer_v3",
    "total_versions": 3,
    "evolution_nodes": [
      {
        "node_id": "node-uuid-1",
        "pattern_id": "async_db_writer_v1",
        "pattern_name": "Async Database Writer",
        "version": "1.0.0",
        "generation": 0,
        "created_at": "2025-01-01T10:00:00Z"
      },
      {
        "node_id": "node-uuid-2",
        "pattern_id": "async_db_writer_v2",
        "pattern_name": "Async Database Writer",
        "version": "2.0.0",
        "generation": 1,
        "created_at": "2025-02-01T10:00:00Z"
      },
      {
        "node_id": "node-uuid-3",
        "pattern_id": "async_db_writer_v3",
        "pattern_name": "Async Database Writer",
        "version": "3.0.0",
        "generation": 2,
        "created_at": "2025-03-01T10:00:00Z"
      }
    ],
    "evolution_edges": [
      {
        "edge_id": "edge-uuid-1",
        "source_node_id": "node-uuid-1",
        "target_node_id": "node-uuid-2",
        "source_version": "1.0.0",
        "target_version": "2.0.0",
        "edge_type": "derived_from",
        "transformation_type": "refactoring",
        "created_at": "2025-02-01T10:00:00Z"
      },
      {
        "edge_id": "edge-uuid-2",
        "source_node_id": "node-uuid-2",
        "target_node_id": "node-uuid-3",
        "source_version": "2.0.0",
        "target_version": "3.0.0",
        "edge_type": "derived_from",
        "transformation_type": "optimization",
        "created_at": "2025-03-01T10:00:00Z"
      }
    ]
  },
  "metadata": {
    "processing_time_ms": 180.5,
    "total_nodes": 3,
    "total_edges": 2
  }
}
```

**cURL Example**:
```bash
curl http://localhost:8053/api/pattern-traceability/lineage/async_db_writer_v3/evolution
```

### Usage Analytics Endpoints

#### `POST /analytics/compute`

Compute comprehensive usage analytics for a pattern

**Performance**: <500ms per pattern analytics computation

**Request Body**:
```json
{
  "pattern_id": "async_db_writer_v3",
  "time_window_type": "weekly",
  "include_performance": true,
  "include_trends": true,
  "include_distribution": false,
  "time_window_days": null
}
```

**Request Parameters**:
- `pattern_id` (string, required): Pattern ID to analyze
- `time_window_type` (string, optional): Time window (hourly, daily, weekly, monthly) (default: "weekly")
- `include_performance` (bool, optional): Include performance metrics (default: true)
- `include_trends` (bool, optional): Include trend analysis (default: true)
- `include_distribution` (bool, optional): Include context distribution (default: false)
- `time_window_days` (int, optional): Custom time window in days

**Response** (200 OK):
```json
{
  "success": true,
  "pattern_id": "async_db_writer_v3",
  "time_window": {
    "start": "2025-02-24T10:00:00Z",
    "end": "2025-03-03T10:00:00Z",
    "type": "weekly"
  },
  "usage_metrics": {
    "total_executions": 1250,
    "executions_per_day": 178.5,
    "executions_per_week": 1250,
    "unique_contexts": 45,
    "unique_users": 12
  },
  "success_metrics": {
    "success_rate": 0.96,
    "error_rate": 0.04,
    "avg_quality_score": 0.89
  },
  "performance_metrics": {
    "avg_execution_time_ms": 125.5,
    "p95_execution_time_ms": 245.0,
    "p99_execution_time_ms": 380.0
  },
  "trend_analysis": {
    "trend_type": "growing",
    "velocity": 15.2,
    "growth_percentage": 12.5,
    "confidence_score": 0.92
  },
  "analytics_quality_score": 0.95,
  "total_data_points": 1250,
  "computation_time_ms": 385.2,
  "processing_time_ms": 390.5
}
```

**cURL Example**:
```bash
curl -X POST http://localhost:8053/api/pattern-traceability/analytics/compute \
  -H "Content-Type: application/json" \
  -d '{
    "pattern_id": "async_db_writer_v3",
    "time_window_type": "weekly",
    "include_performance": true,
    "include_trends": true
  }'
```

#### `GET /analytics/{pattern_id}`

Get usage analytics for a specific pattern (convenience endpoint)

**Query Parameters**:
- `time_window` (string, optional): Time window type (default: "weekly")
- `include_trends` (bool, optional): Include trend analysis (default: true)

**Response**: Same as `POST /analytics/compute`

**cURL Example**:
```bash
curl http://localhost:8053/api/pattern-traceability/analytics/async_db_writer_v3?time_window=weekly
```

### Feedback Loop Endpoints

#### `POST /feedback/analyze`

Analyze pattern feedback and identify improvement opportunities

**Performance**: <10s for analysis phase

**Request Body**:
```json
{
  "pattern_id": "async_db_writer_v3",
  "feedback_type": "performance",
  "time_window_days": 7,
  "auto_apply_threshold": 0.95,
  "min_sample_size": 30,
  "significance_level": 0.05,
  "enable_ab_testing": true
}
```

**Request Parameters**:
- `pattern_id` (string, required): Pattern ID to improve
- `feedback_type` (string, optional): Feedback type (performance, quality, usage, all) (default: "performance")
- `time_window_days` (int, optional): Time window for analysis (1-90 days) (default: 7)
- `auto_apply_threshold` (float, optional): Auto-apply confidence threshold (0.0-1.0) (default: 0.95)
- `min_sample_size` (int, optional): Minimum sample size for validation (default: 30)
- `significance_level` (float, optional): Statistical significance level (0.001-0.1) (default: 0.05)
- `enable_ab_testing` (bool, optional): Enable A/B testing (default: true)

**Response** (200 OK):
```json
{
  "success": true,
  "data": {
    "pattern_id": "async_db_writer_v3",
    "improvements_identified": [
      {
        "improvement_id": "imp-001",
        "category": "performance",
        "description": "Connection pooling optimization",
        "confidence_score": 0.92,
        "expected_improvement": "15% faster execution",
        "auto_apply_recommended": false
      }
    ],
    "feedback_summary": {
      "total_executions_analyzed": 850,
      "issues_found": 3,
      "opportunities_identified": 1,
      "confidence_level": 0.88
    }
  },
  "metadata": {
    "processing_time_ms": 8500.5,
    "analysis_phase": "completed",
    "ab_testing_enabled": true
  }
}
```

**cURL Example**:
```bash
curl -X POST http://localhost:8053/api/pattern-traceability/feedback/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "pattern_id": "async_db_writer_v3",
    "feedback_type": "performance",
    "time_window_days": 7,
    "enable_ab_testing": true
  }'
```

#### `POST /feedback/apply`

Apply specific improvements to a pattern

**Query Parameters**:
- `pattern_id` (string, required): Pattern ID to update
- `improvement_ids` (array[string], required): Improvement IDs to apply
- `force` (bool, optional): Force apply without validation (default: false)

**Response** (200 OK):
```json
{
  "success": true,
  "pattern_id": "async_db_writer_v3",
  "improvements_applied": 1,
  "improvement_ids": ["imp-001"],
  "forced": false,
  "processing_time_ms": 125.5,
  "message": "Improvements applied successfully"
}
```

**cURL Example**:
```bash
curl -X POST "http://localhost:8053/api/pattern-traceability/feedback/apply?pattern_id=async_db_writer_v3&improvement_ids=imp-001&force=false"
```

### Health Check Endpoint

#### `GET /health`

Health check for pattern traceability components

**Response** (200 OK):
```json
{
  "status": "healthy",
  "components": {
    "lineage_tracker": "operational",
    "usage_analytics": "operational",
    "feedback_orchestrator": "operational"
  },
  "timestamp": "2025-03-03T10:00:00Z",
  "response_time_ms": 5.2
}
```

**Response** (503 Service Unavailable):
```json
{
  "status": "degraded",
  "components": {
    "lineage_tracker": "database_unavailable",
    "usage_analytics": "operational",
    "feedback_orchestrator": "operational"
  },
  "timestamp": "2025-03-03T10:00:00Z",
  "response_time_ms": 2.5
}
```

**cURL Example**:
```bash
curl http://localhost:8053/api/pattern-traceability/health
```

---

## Data Models

### ExecutionTrace

Master record for all execution traces.

```python
{
  "id": "UUID (auto-generated)",
  "correlation_id": "UUID (unique identifier for this execution chain)",
  "root_id": "UUID (points to the root trace in a nested execution)",
  "parent_id": "UUID | null (parent execution for nested/delegated executions)",
  "session_id": "UUID (session identifier for this execution)",
  "user_id": "string | null (user identifier if available)",
  "source": "string (source of the execution, e.g., 'claude_code', 'api')",
  "prompt_text": "string | null (original user prompt or request text)",
  "started_at": "datetime (when execution started)",
  "completed_at": "datetime | null (when execution completed)",
  "duration_ms": "int | null (execution duration in milliseconds)",
  "status": "string (in_progress | completed | failed | cancelled)",
  "success": "bool | null (whether execution was successful)",
  "error_message": "string | null (error message if execution failed)",
  "error_type": "string | null (type/category of error)",
  "context": "dict | null (additional context as JSON)",
  "tags": "array[string] | null (tags for categorization and filtering)",
  "created_at": "datetime (record creation timestamp)",
  "updated_at": "datetime (record update timestamp)"
}
```

### HookExecution

Track all Claude Code hook executions.

```python
{
  "id": "UUID (auto-generated)",
  "trace_id": "UUID (foreign key to execution_traces)",
  "hook_type": "string (UserPromptSubmit | PreToolUse | PostToolUse | Stop | SessionStart | SessionEnd)",
  "hook_name": "string (specific hook name/identifier)",
  "execution_order": "int (order of execution within the trace, 1, 2, 3...)",
  "started_at": "datetime (when hook started)",
  "completed_at": "datetime | null (when hook completed)",
  "duration_ms": "int | null (hook execution duration in milliseconds)",
  "status": "string (in_progress | completed | failed)",
  "input_data": "dict | null (hook input data as JSON)",
  "output_data": "dict | null (hook output data as JSON)",
  "modifications_made": "dict | null (any file modifications or actions taken)",
  "rag_query_performed": "bool (whether RAG query was performed)",
  "rag_results": "dict | null (RAG query results as JSON)",
  "quality_check_performed": "bool (whether quality check was performed)",
  "quality_results": "dict | null (quality check results as JSON)",
  "error_message": "string | null (error message if hook failed)",
  "error_type": "string | null (type/category of error)",
  "error_stack": "string | null (full error stack trace)",
  "tool_name": "string | null (tool being used, e.g., 'Write', 'Edit', 'Read')",
  "file_path": "string | null (file path being operated on)",
  "metadata": "dict | null (additional metadata as JSON)",
  "created_at": "datetime (record creation timestamp)",
  "updated_at": "datetime (record update timestamp)"
}
```

### PatternLineageNode

Pattern version with metadata.

```python
{
  "id": "UUID (auto-generated)",
  "pattern_id": "string (unique pattern identifier)",
  "pattern_name": "string (human-readable pattern name)",
  "pattern_type": "string (code | config | template | workflow)",
  "pattern_version": "string (semantic versioning)",
  "pattern_data": "dict (pattern content snapshot)",
  "generation": "int (generation number, 0 for root patterns)",
  "metadata": "dict (additional metadata)",
  "created_at": "datetime (record creation timestamp)"
}
```

### PatternLineageEdge

Parent-child relationship between patterns.

```python
{
  "id": "UUID (auto-generated)",
  "source_node_id": "UUID (foreign key to pattern_lineage_nodes)",
  "target_node_id": "UUID (foreign key to pattern_lineage_nodes)",
  "edge_type": "string (derived_from | modified_from | merged_from | forked_from)",
  "transformation_type": "string (refactoring | optimization | bug_fix | feature_addition)",
  "edge_weight": "float (relationship strength, 0.0-1.0, default: 1.0)",
  "metadata": "dict (additional metadata)",
  "created_at": "datetime (record creation timestamp)"
}
```

---

## Error Codes

### HTTP Status Codes

| Code | Name | Description |
|------|------|-------------|
| 200 | OK | Request succeeded |
| 400 | Bad Request | Invalid request parameters |
| 404 | Not Found | Resource not found |
| 500 | Internal Server Error | Server error occurred |
| 503 | Service Unavailable | Service temporarily unavailable (e.g., database down) |

### Error Response Format

```json
{
  "success": false,
  "error": "Error description",
  "metadata": {
    "processing_time_ms": 10.5,
    "error_details": "Additional error context"
  }
}
```

### Common Error Messages

| Error | Meaning | Resolution |
|-------|---------|------------|
| `Database connection not available` | PostgreSQL connection failed | Check `TRACEABILITY_DB_URL` environment variable |
| `Lineage tracker not initialized` | Lineage tracker requires database | Configure database connection and restart service |
| `Pattern not found: {pattern_id}` | Pattern doesn't exist | Verify pattern_id is correct |
| `Invalid correlation_id` | Malformed UUID | Ensure correlation_id is valid UUID format |
| `Missing required fields` | Request missing required parameters | Check request body for required fields |

---

**End of API Reference**

For integration examples, see `PHASE4_INTEGRATION_GUIDE.md`
For troubleshooting, see `TROUBLESHOOTING.md`
