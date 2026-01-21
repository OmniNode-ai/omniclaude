# Logging Pipeline Architecture

Complete documentation of the agent execution logging pipeline from event generation through Kafka event bus to database persistence with file fallback.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Event Flow](#event-flow)
3. [AgentExecutionLogger](#agentexecutionlogger)
4. [Kafka Integration](#kafka-integration)
5. [Database Persistence](#database-persistence)
6. [Fallback Mechanism](#fallback-mechanism)
7. [Adding Logging to New Agents](#adding-logging-to-new-agents)
8. [Performance Characteristics](#performance-characteristics)
9. [Debugging Logging Issues](#debugging-logging-issues)

---

## Architecture Overview

### Dual-Path Logging System

OmniClaude implements a robust dual-path logging architecture:

```
┌──────────────────────────────────────────────────────────────────┐
│                    AGENT EXECUTION START                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────────┐
              │  AgentExecutionLogger      │
              │  - Generate execution_id   │
              │  - Create correlation_id   │
              └──────────┬─────────────────┘
                         │
                ┌────────┴────────┐
                │                 │
                ▼                 ▼
     ┌──────────────────┐  ┌──────────────────┐
     │ PRIMARY PATH     │  │ FALLBACK PATH    │
     │ PostgreSQL       │  │ JSON Files       │
     │ (async asyncpg)  │  │ (platform temp)  │
     └──────────┬───────┘  └──────────┬───────┘
                │                     │
                ▼                     ▼
     ┌──────────────────┐  ┌──────────────────┐
     │ agent_execution_ │  │ {temp}/          │
     │ logs table       │  │ omniclaude_logs/ │
     │ (34 tables)      │  │ YYYY-MM-DD/      │
     └──────────────────┘  │ {exec_id}.jsonl  │
                           └──────────────────┘
```

### Key Design Principles

1. **Non-Blocking**: Never fails agent execution due to logging issues
2. **Graceful Degradation**: Automatic fallback when database unavailable
3. **Retry Logic**: Exponential backoff (1m, 2m, 5m, 10m)
4. **Platform-Aware**: Uses `tempfile.gettempdir()` for cross-platform compatibility
5. **Correlation Tracking**: Complete trace from user prompt to execution outcome

---

## Event Flow

### Complete Logging Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. AGENT INITIALIZATION                                          │
│    - Generate correlation_id                                     │
│    - Create AgentExecutionLogger instance                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. EXECUTION START (await logger.start())                        │
│    - Generate execution_id                                       │
│    - Record started_at timestamp                                 │
│    - Try PostgreSQL INSERT                                       │
│    - On failure → fallback to JSON file                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. MANIFEST INJECTION                                            │
│    - Publish to Kafka: intelligence.requests                     │
│    - Wait for response: intelligence.responses                   │
│    - Store in agent_manifest_injections table                    │
│    - Link via correlation_id                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. PROGRESS UPDATES (await logger.progress())                    │
│    - Update metadata JSONB in PostgreSQL                         │
│    - On failure → append to JSON file                            │
│    - Log stage and percentage                                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. AGENT EXECUTION                                               │
│    - Use injected manifest context                               │
│    - Execute task                                                │
│    - Calculate quality score                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. EXECUTION COMPLETION (await logger.complete())                │
│    - Calculate duration_ms                                       │
│    - Record status (success/failed/cancelled)                    │
│    - Store quality_score                                         │
│    - Try PostgreSQL UPDATE                                       │
│    - On failure → append to JSON file                            │
└─────────────────────────────────────────────────────────────────┘
```

### Event Types

#### Start Event

```python
{
    "execution_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
    "correlation_id": "7a44dc28-34a1-456c-8ef6-1cb03ded02ad",
    "session_id": "6c33cb17-23b0-345b-7de5-0ba92cdc91bc",
    "agent_name": "agent-researcher",
    "user_prompt": "Research ONEX patterns",
    "started_at": "2025-10-29T14:30:00.123456Z",
    "status": "in_progress",
    "metadata": {},
    "project_path": "/path/to/project",
    "project_name": "omniclaude",
    "claude_session_id": "session_123",
    "terminal_id": "terminal_456"
}
```

#### Progress Event

```python
{
    "execution_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
    "progress": {
        "stage": "gathering_intelligence",
        "percent": 25,
        "updated_at": "2025-10-29T14:30:15.789012Z",
        "source": "qdrant",
        "patterns_found": 120
    }
}
```

#### Complete Event

```python
{
    "execution_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
    "status": "success",  # or "failed", "cancelled"
    "quality_score": 0.92,
    "duration_ms": 15420,
    "completed_at": "2025-10-29T14:30:45.567890Z",
    "metadata": {
        "completed_at": "2025-10-29T14:30:45.567890Z",
        "patterns_used": 15,
        "files_modified": 3
    }
}
```

#### Error Event

```python
{
    "execution_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
    "status": "failed",
    "error_message": "Failed to connect to Qdrant",
    "error_type": "ConnectionError",
    "duration_ms": 5234,
    "completed_at": "2025-10-29T14:30:20.345678Z",
    "metadata": {
        "completed_at": "2025-10-29T14:30:20.345678Z",
        "error_details": "Connection refused: localhost:6333"
    }
}
```

---

## AgentExecutionLogger

### Class Overview

```python
from agents.lib.agent_execution_logger import AgentExecutionLogger
from omnibase_core.enums.enum_operation_status import EnumOperationStatus
from uuid import uuid4

logger = AgentExecutionLogger(
    agent_name="agent-researcher",
    user_prompt="Research ONEX patterns",
    correlation_id=uuid4(),
    session_id=uuid4(),
    metadata={"priority": "high"},
    project_path="/path/to/project",
    project_name="omniclaude"
)
```

### Core Methods

#### await logger.start()

```python
"""
Log execution start.

Returns:
    Execution ID (UUID as string)

Behavior:
    - Generates unique execution_id
    - Records started_at timestamp
    - Tries PostgreSQL INSERT
    - On failure → writes to fallback JSON file
    - Never throws exceptions (non-blocking)
"""

execution_id = await logger.start()
```

#### await logger.progress()

```python
"""
Log execution progress.

Args:
    stage: Current stage name (e.g., "gathering_intelligence")
    percent: Progress percentage 0-100 (optional)
    metadata: Additional progress metadata (optional)

Behavior:
    - Validates percent range (0-100)
    - Tries PostgreSQL UPDATE (metadata JSONB merge)
    - On failure → writes to fallback JSON file
    - Never throws exceptions (non-blocking)
"""

await logger.progress(
    stage="gathering_intelligence",
    percent=25,
    metadata={"source": "qdrant"}
)
```

#### await logger.complete()

```python
"""
Log execution completion.

Args:
    status: EnumOperationStatus.SUCCESS/FAILED/CANCELLED
    quality_score: Quality score 0.0-1.0 (optional)
    error_message: Error description if FAILED (optional)
    error_type: Error type/class name (optional)
    metadata: Final execution metadata (optional)

Behavior:
    - Calculates duration_ms from started_at
    - Tries PostgreSQL UPDATE
    - On failure → writes to fallback JSON file
    - Never throws exceptions (non-blocking)
"""

await logger.complete(
    status=EnumOperationStatus.SUCCESS,
    quality_score=0.92,
    metadata={"patterns_used": 15}
)
```

### Retry Logic

```python
# Exponential backoff configuration
_DB_RETRY_BACKOFF_SECONDS = [60, 120, 300, 600]  # 1m, 2m, 5m, 10m
_MAX_RETRY_ATTEMPTS = 4

# Retry flow
1. Database operation fails
2. Mark _db_available = False
3. Record _last_retry_time
4. Increment _db_retry_count
5. Write to fallback JSON file
6. Wait for backoff duration (1m, 2m, 5m, 10m)
7. Retry database operation
8. On success: Reset retry counters
9. On failure: Repeat until max retries reached
10. After max retries: Stay in fallback mode
```

### Factory Function

```python
from agents.lib.agent_execution_logger import log_agent_execution

# Simplified usage - creates and starts logger
logger = await log_agent_execution(
    agent_name="agent-researcher",
    user_prompt="Research ONEX patterns",
    correlation_id=correlation_id,
    project_path="/path/to/project"
)

# Use logger for progress and completion
await logger.progress(stage="analyzing", percent=50)
await logger.complete(status=EnumOperationStatus.SUCCESS)
```

---

## Kafka Integration

### Manifest Injection via Kafka

```
┌─────────────────────────────────────────────────────────────────┐
│ ManifestInjector.inject_manifest()                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Kafka Topic: dev.archon-intelligence.intelligence.              │
│              code-analysis-requested.v1                          │
│                                                                  │
│ Event: {                                                         │
│   "correlation_id": "8b57ec39...",                              │
│   "operation_type": "PATTERN_EXTRACTION",                       │
│   "collection_name": "execution_patterns",                       │
│   "options": {"limit": 50},                                     │
│   "timeout_ms": 5000                                            │
│ }                                                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ archon-intelligence-adapter                                      │
│ - Consumes request event                                         │
│ - Queries Qdrant (execution_patterns, code_patterns)            │
│ - Queries Memgraph (relationships)                              │
│ - Queries PostgreSQL (schemas, debug intelligence)              │
│ - Parallel execution (~1800ms total)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Kafka Topic: dev.archon-intelligence.intelligence.              │
│              code-analysis-completed.v1                          │
│                                                                  │
│ Response: {                                                      │
│   "correlation_id": "8b57ec39...",                              │
│   "patterns": [...],                                            │
│   "query_time_ms": 450,                                         │
│   "total_count": 120                                            │
│ }                                                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ ManifestInjector                                                 │
│ - Consumes response event                                        │
│ - Formats manifest text                                          │
│ - Stores to agent_manifest_injections table                      │
│ - Returns manifest to agent                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Event Topics

| Topic | Purpose | Producer | Consumer |
|-------|---------|----------|----------|
| `intelligence.code-analysis-requested.v1` | Pattern discovery requests | ManifestInjector | archon-intelligence |
| `intelligence.code-analysis-completed.v1` | Successful responses | archon-intelligence | ManifestInjector |
| `intelligence.code-analysis-failed.v1` | Failed requests | archon-intelligence | ManifestInjector |

### Performance Characteristics

```
Request-Response Latency:
  - Kafka publish: <5ms
  - Event routing: <10ms
  - Intelligence query: 1000-2000ms
    - Qdrant patterns: 400-600ms
    - Memgraph relationships: 200-400ms
    - PostgreSQL schemas: 100-300ms
    - Debug intelligence: 400-800ms
  - Kafka response: <5ms
  - Total: ~1800ms (target <2000ms)
```

---

## Database Persistence

### Connection Pool Management

```python
from agents.lib.db import get_pg_pool

# Get connection pool (lazy initialization)
pool = await get_pg_pool()

# Connection pool configuration
min_size=5
max_size=20
timeout=30.0
command_timeout=30.0
```

### Execution Logs Table

```sql
-- Insert start event
INSERT INTO agent_execution_logs (
    execution_id,
    correlation_id,
    session_id,
    agent_name,
    user_prompt,
    status,
    metadata,
    project_path,
    project_name
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9);

-- Update progress (JSONB merge)
UPDATE agent_execution_logs
SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
WHERE execution_id = $2;

-- Update completion
UPDATE agent_execution_logs
SET
    completed_at = $1,
    status = $2,
    quality_score = $3,
    error_message = $4,
    error_type = $5,
    duration_ms = $6,
    metadata = COALESCE(metadata, '{}'::jsonb) || $7::jsonb
WHERE execution_id = $8;
```

### Manifest Injections Table

```sql
-- Insert manifest injection record
INSERT INTO agent_manifest_injections (
    correlation_id,
    session_id,
    agent_name,
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
    full_manifest_snapshot,
    formatted_manifest_text,
    manifest_size_bytes
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15, $16::jsonb, $17, $18);
```

### Indexes for Performance

```sql
-- Correlation ID lookups (<10ms)
CREATE INDEX idx_agent_execution_logs_correlation
    ON agent_execution_logs(correlation_id);

CREATE INDEX idx_agent_manifest_injections_correlation
    ON agent_manifest_injections(correlation_id);

-- Time-range queries (<100ms)
CREATE INDEX idx_agent_execution_logs_time
    ON agent_execution_logs(created_at DESC);

CREATE INDEX idx_agent_manifest_injections_time
    ON agent_manifest_injections(created_at DESC);

-- Agent-specific queries (<50ms)
CREATE INDEX idx_agent_execution_logs_agent
    ON agent_execution_logs(agent_name, created_at DESC);

CREATE INDEX idx_agent_manifest_injections_agent
    ON agent_manifest_injections(agent_name, created_at DESC);
```

---

## Fallback Mechanism

### File-Based Logging

When PostgreSQL is unavailable, logs are written to structured JSON files:

```
{temp}/omniclaude_logs/
├── 2025-10-29/
│   ├── 8b57ec39-45b5-467b-939c-dd1439219f69.jsonl
│   ├── 7a44dc28-34a1-456c-8ef6-1cb03ded02ad.jsonl
│   └── 6c33cb17-23b0-345b-7de5-0ba92cdc91bc.jsonl
├── 2025-10-28/
│   └── ...
└── 2025-10-27/
    └── ...
```

### Platform-Aware Directory Selection

```python
def get_fallback_log_dir() -> Path:
    """
    Platform-appropriate fallback log directory.

    Priority:
    1. {tempdir}/omniclaude_logs (preferred)
    2. {cwd}/.omniclaude_logs (fallback)

    Platforms:
    - Linux/macOS: /tmp/omniclaude_logs
    - Windows: C:\\Users\\{user}\\AppData\\Local\\Temp\\omniclaude_logs
    """
    base_dir = Path(tempfile.gettempdir()) / "omniclaude_logs"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        # Verify writable
        test_file = base_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return base_dir
    except (PermissionError, OSError):
        # Fallback to current directory
        fallback = Path.cwd() / ".omniclaude_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
```

### JSONL Format

```jsonl
{"timestamp": "2025-10-29T14:30:00.123456Z", "event_type": "start", "agent_name": "agent-researcher", "correlation_id": "8b57ec39...", "execution_id": "8b57ec39...", "user_prompt": "Research ONEX patterns", "status": "in_progress"}
{"timestamp": "2025-10-29T14:30:15.789012Z", "event_type": "progress", "agent_name": "agent-researcher", "correlation_id": "8b57ec39...", "execution_id": "8b57ec39...", "progress": {"stage": "gathering_intelligence", "percent": 25}}
{"timestamp": "2025-10-29T14:30:45.567890Z", "event_type": "complete", "agent_name": "agent-researcher", "correlation_id": "8b57ec39...", "execution_id": "8b57ec39...", "status": "success", "quality_score": 0.92, "duration_ms": 15420}
```

### Security Considerations

```python
# File permissions: owner read/write only
os.chmod(log_file, 0o600)  # -rw-------

# UTF-8 encoding for international characters
with open(log_file, "a", encoding="utf-8") as f:
    f.write(json.dumps(log_entry) + "\n")
```

### Fallback Recovery

```python
# Manual recovery script (import fallback logs to database)
import json
from pathlib import Path
from datetime import datetime

async def recover_fallback_logs(log_dir: Path):
    """Import fallback JSONL logs into PostgreSQL."""
    pool = await get_pg_pool()

    for log_file in log_dir.glob("**/*.jsonl"):
        with open(log_file) as f:
            for line in f:
                event = json.loads(line)
                # Insert into appropriate table based on event_type
                if event["event_type"] == "start":
                    await pool.execute(
                        "INSERT INTO agent_execution_logs (...) VALUES (...)"
                    )
                # ... handle progress and complete events
```

---

## Adding Logging to New Agents

### Basic Integration

```python
from agents.lib.agent_execution_logger import log_agent_execution
from omnibase_core.enums.enum_operation_status import EnumOperationStatus
from uuid import uuid4

async def my_new_agent(user_prompt: str, project_path: str):
    """Example agent with complete logging."""

    # Generate correlation ID
    correlation_id = uuid4()

    # Start logging
    logger = await log_agent_execution(
        agent_name="my-new-agent",
        user_prompt=user_prompt,
        correlation_id=correlation_id,
        project_path=project_path,
        project_name="omniclaude"
    )

    try:
        # Stage 1: Initialization
        await logger.progress(stage="initialization", percent=10)
        # ... do initialization

        # Stage 2: Main work
        await logger.progress(stage="processing", percent=50)
        result = await do_main_work()

        # Stage 3: Finalization
        await logger.progress(stage="finalization", percent=90)
        await finalize_result(result)

        # Complete with success
        await logger.complete(
            status=EnumOperationStatus.SUCCESS,
            quality_score=calculate_quality(result)
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

### Advanced Integration with Manifest Injection

```python
from agents.lib.agent_execution_logger import log_agent_execution
from agents.lib.manifest_injector import inject_manifest
from omnibase_core.enums.enum_operation_status import EnumOperationStatus
from uuid import uuid4

async def my_intelligent_agent(user_prompt: str):
    """Agent with manifest injection and complete logging."""

    # Generate correlation ID (shared across logging and manifest)
    correlation_id = uuid4()

    # Start logging
    logger = await log_agent_execution(
        agent_name="my-intelligent-agent",
        user_prompt=user_prompt,
        correlation_id=correlation_id
    )

    try:
        # Inject manifest with intelligence
        await logger.progress(stage="gathering_intelligence", percent=10)
        manifest = inject_manifest(
            correlation_id=correlation_id,
            agent_name="my-intelligent-agent"
        )

        # Use manifest patterns
        await logger.progress(
            stage="applying_patterns",
            percent=50,
            metadata={
                "patterns_available": manifest.get("patterns_count", 0),
                "debug_intel": manifest.get("debug_intelligence_successes", 0)
            }
        )

        # Execute with intelligence context
        result = await execute_with_intelligence(manifest)

        # Complete with quality score
        await logger.complete(
            status=EnumOperationStatus.SUCCESS,
            quality_score=0.92,
            metadata={
                "patterns_used": 15,
                "files_modified": 3
            }
        )

        return result

    except Exception as e:
        await logger.complete(
            status=EnumOperationStatus.FAILED,
            error_message=str(e),
            error_type=type(e).__name__
        )
        raise
```

### Progress Tracking Best Practices

```python
# Clear stage names
await logger.progress(stage="gathering_intelligence", percent=10)
await logger.progress(stage="analyzing_patterns", percent=30)
await logger.progress(stage="generating_code", percent=60)
await logger.progress(stage="validating_output", percent=90)

# Include useful metadata
await logger.progress(
    stage="processing_files",
    percent=50,
    metadata={
        "files_processed": 15,
        "files_total": 30,
        "current_file": "model_agent.py"
    }
)

# Update percentage regularly (not too frequently)
# Good: Every major step (10-20% increments)
# Bad: Every file (might be hundreds of updates)
```

---

## Performance Characteristics

### Logging Latency

| Operation | Target | Typical | Warning | Critical |
|-----------|--------|---------|---------|----------|
| `start()` | <50ms | 20-30ms | >100ms | >500ms |
| `progress()` | <50ms | 15-25ms | >100ms | >500ms |
| `complete()` | <50ms | 20-30ms | >100ms | >500ms |

### Database Operations

| Query Type | Target | Typical |
|------------|--------|---------|
| INSERT (start) | <30ms | 10-20ms |
| UPDATE (progress) | <20ms | 5-15ms |
| UPDATE (complete) | <30ms | 10-20ms |

### Fallback Operations

| Operation | Target | Typical |
|-----------|--------|---------|
| File write (JSONL) | <10ms | 2-5ms |
| Directory creation | <20ms | 5-10ms |
| Permission check | <5ms | 1-2ms |

### Retry Behavior

```
Database Failure:
  Time 0:00 → Attempt 1 fails → Fallback to file
  Time 1:00 → Retry attempt 2
  Time 3:00 → Retry attempt 3 (if still failing)
  Time 8:00 → Retry attempt 4 (if still failing)
  Time 18:00 → Final retry attempt 5
  After 18:00 → Stay in fallback mode
```

---

## Debugging Logging Issues

### Issue: Logs Not Appearing in Database

**Symptoms**:
- Agent executions not visible in agent_history_browser.py
- Database queries return no results

**Diagnosis**:

```bash
# 1. Check database connectivity
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"

# 2. Check if table exists
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
\dt agent_execution_logs
"

# 3. Check recent logs
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT COUNT(*), MAX(created_at)
FROM agent_execution_logs;
"

# 4. Check fallback log files
ls -lh /tmp/omniclaude_logs/$(date +%Y-%m-%d)/
```

**Solutions**:
1. Database down → Check `docker ps | grep archon-bridge`
2. Table missing → Run migrations from `agents/migrations/`
3. Permission error → Check `POSTGRES_PASSWORD` in `.env`
4. All logs in fallback → Database unreachable, check network

### Issue: Slow Logging Performance

**Symptoms**:
- Agent execution feels sluggish
- Progress updates lag
- Timeout errors

**Diagnosis**:

```bash
# 1. Check database query performance
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    query,
    mean_exec_time,
    calls
FROM pg_stat_statements
WHERE query LIKE '%agent_execution_logs%'
ORDER BY mean_exec_time DESC
LIMIT 10;
"

# 2. Check connection pool status
# (requires application logging)
docker logs archon-bridge | grep "pool"

# 3. Monitor database load
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT * FROM pg_stat_activity
WHERE state = 'active';
"
```

**Solutions**:
1. Slow queries → Check indexes exist (see AGENT_TRACEABILITY.md)
2. Pool exhaustion → Increase `max_size` in connection pool
3. Network latency → Check network between agent and database
4. Lock contention → Review concurrent agent executions

### Issue: Fallback Mode Stuck

**Symptoms**:
- All logs going to files (not database)
- Retry counter maxed out
- Warning messages about fallback

**Diagnosis**:

```python
# Check agent logs
docker logs -f [agent-container] | grep "fallback"

# Should see messages like:
# "Database start failed, using file fallback"
# "Retrying database connection (attempt 2/4)"
# "Database connection restored"
```

**Solutions**:
1. Restart agent process → Resets retry counters
2. Fix database issue → Will auto-recover after backoff
3. Manual recovery → Import fallback logs (see script above)

### Issue: Correlation ID Missing

**Symptoms**:
- Cannot join routing, manifest, and execution records
- Missing links in v_agent_execution_trace view

**Diagnosis**:

```sql
-- Check for orphaned records
SELECT
    'routing' AS source,
    correlation_id,
    COUNT(*) AS count
FROM agent_routing_decisions
WHERE correlation_id NOT IN (SELECT correlation_id FROM agent_manifest_injections)
GROUP BY correlation_id

UNION ALL

SELECT
    'manifest' AS source,
    correlation_id,
    COUNT(*) AS count
FROM agent_manifest_injections
WHERE correlation_id NOT IN (SELECT correlation_id FROM agent_execution_logs)
GROUP BY correlation_id;
```

**Solutions**:
1. Agent not propagating correlation_id → Fix agent code
2. Partial execution → Agent failed before completion
3. Race condition → Check event ordering

---

## See Also

- [AGENT_TRACEABILITY.md](./AGENT_TRACEABILITY.md) - Database schemas and queries
- [DIAGNOSTIC_SCRIPTS.md](./DIAGNOSTIC_SCRIPTS.md) - Diagnostic tools
- [../../CLAUDE.md](../../CLAUDE.md) - Main documentation

---

**Last Updated**: 2025-10-29
**Pipeline Version**: 1.0.0
**Database**: omninode_bridge @ 192.168.86.200:5436
