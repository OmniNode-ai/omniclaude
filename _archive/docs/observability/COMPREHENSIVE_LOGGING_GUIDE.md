# Comprehensive Logging Guide

**Purpose**: Complete guide to agent action logging, tool call tracking, error monitoring, and success tracking in OmniClaude.

**Last Updated**: 2025-11-09
**Status**: ✅ COMPLETE - All logging infrastructure operational

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration](#configuration)
4. [Tool Call Logging](#tool-call-logging)
5. [Error Logging](#error-logging)
6. [Success Logging](#success-logging)
7. [Decision Logging](#decision-logging)
8. [Hook Integration](#hook-integration)
9. [Python API](#python-api)
10. [Querying Logged Data](#querying-logged-data)
11. [Troubleshooting](#troubleshooting)
12. [Performance](#performance)

---

## Overview

OmniClaude provides comprehensive observability through a multi-tier logging system that captures:

- **Tool Calls**: All tool invocations (Read, Write, Edit, Bash, Grep, Glob, WebFetch, etc.)
- **Errors**: Tool failures, agent errors, database errors, Kafka errors
- **Successes**: Task completions, workflow milestones, quality gate passes
- **Decisions**: Agent selection, routing decisions, transformation events

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: HOOKS                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ PreToolUse │  │ PostToolUse│  │ UserPrompt │            │
│  │   Hook     │  │   Hook     │  │ Submit Hook│            │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘            │
│        │                │                │                   │
│        └────────────────┴────────────────┘                   │
│                         │                                    │
└─────────────────────────┼────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: LOGGING HELPERS                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │ action_logging_helpers.py                          │     │
│  │  - log_error()                                     │     │
│  │  - log_success()                                   │     │
│  │  - log_tool_call()                                 │     │
│  │  - log_decision()                                  │     │
│  └────────────────────────┬───────────────────────────┘     │
└────────────────────────────┼────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3: KAFKA PUBLISHER                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │ execute_kafka.py                                   │     │
│  │  - Publishes to Kafka topic: agent-actions         │     │
│  │  - Handles correlation IDs, timing, formatting     │     │
│  │  - Graceful degradation if Kafka unavailable       │     │
│  └────────────────────────┬───────────────────────────┘     │
└────────────────────────────┼────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4: KAFKA EVENT BUS                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Kafka Topic: agent-actions                         │     │
│  │  - Partition by correlation_id                     │     │
│  │  - Persistent event log                            │     │
│  │  - Multiple consumers                              │     │
│  └────────────────────────┬───────────────────────────┘     │
└────────────────────────────┼────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 5: CONSUMERS & STORAGE                               │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ PostgreSQL │  │ Dashboards │  │ Analytics  │            │
│  │  Consumer  │  │  Consumer  │  │  Consumer  │            │
│  │            │  │            │  │            │            │
│  │ agent_     │  │ Grafana    │  │ Prometheus │            │
│  │ actions    │  │ Metrics    │  │ Metrics    │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Components

**1. Hooks** (`~/.claude/hooks/`)
- `user-prompt-submit.sh` - Logs routing decisions, agent dispatch
- `pre-tool-use-quality.sh` - Logs tool call starts, quality checks
- `post-tool-use-quality.sh` - Logs tool call completions, errors

**2. Logging Helpers** (`~/.claude/hooks/lib/`)
- `action_logging_helpers.py` - Python API for logging
- `log_action.sh` - Bash wrapper for logging

**3. Kafka Publisher** (`~/.claude/skills/agent-tracking/log-agent-action/`)
- `execute_kafka.py` - Publishes events to Kafka

**4. Kafka Event Bus** (`192.168.86.200:29092`)
- Topic: `agent-actions`
- Partitioned by `correlation_id` for ordering

**5. Consumers**
- `agent_actions_consumer.py` - Writes to PostgreSQL `agent_actions` table
- Grafana/Prometheus consumers - Metrics and dashboards

### Database Schema

**Table**: `agent_actions`

```sql
CREATE TABLE agent_actions (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('tool_call', 'decision', 'error', 'success')),
    action_name VARCHAR(255) NOT NULL,
    action_details JSONB,
    debug_mode BOOLEAN DEFAULT FALSE,
    duration_ms INTEGER,
    project_path TEXT,
    project_name VARCHAR(255),
    working_directory TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Indexes
    INDEX idx_correlation_id (correlation_id),
    INDEX idx_agent_name (agent_name),
    INDEX idx_action_type (action_type),
    INDEX idx_created_at (created_at),
    INDEX idx_correlation_agent (correlation_id, agent_name)
);
```

---

## Configuration

### 1. Enable DEBUG Mode

**Required**: Set `DEBUG=true` in `.env` file to enable logging.

```bash
# In /Volumes/PRO-G40/Code/omniclaude/.env
DEBUG=true
```

**Effect**: Enables all action logging to Kafka and PostgreSQL.

**Verification**:
```bash
source .env
echo "DEBUG: ${DEBUG}"
```

### 2. Kafka Configuration

**Required**: Kafka broker must be accessible.

```bash
# In .env
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
```

**Verification**:
```bash
# Check Kafka connectivity
docker exec -it omninode-bridge-redpanda rpk topic list | grep agent-actions
```

### 3. PostgreSQL Configuration

**Required**: PostgreSQL database for storing logged events.

```bash
# In .env
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>
```

**Verification**:
```bash
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT COUNT(*) FROM agent_actions;"
```

---

## Tool Call Logging

### Automatic Logging (via Hooks)

**PreToolUse Hook** - Logs tool call START:
- Captures tool name, input parameters
- Logs correlation ID for traceability
- Action name: `{ToolName}_start` (e.g., `Read_start`, `Write_start`)

**PostToolUse Hook** - Logs tool call COMPLETION:
- Captures tool name, input parameters, output result
- Logs execution duration
- Action name: `{ToolName}` (e.g., `Read`, `Write`)
- Detects and logs errors automatically

### Tools Logged Automatically

All Claude Code tools are logged when DEBUG=true:

- **File Operations**: Read, Write, Edit, MultiEdit, NotebookEdit
- **Search**: Grep, Glob
- **Execution**: Bash
- **Web**: WebFetch, WebSearch
- **UI**: AskUserQuestion, TodoWrite
- **Skills**: Skill invocations

### Example Log Entries

**Tool Call Start** (PreToolUse):
```json
{
  "correlation_id": "abc-123-def-456",
  "agent_name": "polymorphic-agent",
  "action_type": "tool_call",
  "action_name": "Read_start",
  "action_details": {
    "file_path": "/path/to/file.py",
    "offset": null,
    "limit": null,
    "stage": "start"
  },
  "duration_ms": null,
  "created_at": "2025-11-09T14:30:00Z"
}
```

**Tool Call Completion** (PostToolUse):
```json
{
  "correlation_id": "abc-123-def-456",
  "agent_name": "polymorphic-agent",
  "action_type": "tool_call",
  "action_name": "Read",
  "action_details": {
    "file_path": "/path/to/file.py",
    "content": "...",
    "line_range": {"start": 1, "end": 100}
  },
  "duration_ms": 45,
  "created_at": "2025-11-09T14:30:00.045Z"
}
```

### Manual Logging (Python)

```python
from action_logging_helpers import log_tool_call

log_tool_call(
    tool_name="CustomTool",
    tool_parameters={"param1": "value1"},
    tool_result={"result_key": "result_value"},
    duration_ms=125,
)
```

### Manual Logging (Bash)

```bash
source ~/.claude/hooks/lib/log_action.sh

log_tool_call "CustomTool" '{"param1": "value1"}' '{"result": "success"}' 125
```

---

## Error Logging

### Automatic Error Detection

**PostToolUse Hook** automatically detects and logs tool execution errors:

```bash
# Detects errors in tool_response
TOOL_ERROR=$(echo "$TOOL_INFO" | jq -r '.tool_response.error // .error // empty')
```

**Example Error Log**:
```json
{
  "correlation_id": "abc-123-def-456",
  "agent_name": "polymorphic-agent",
  "action_type": "error",
  "action_name": "ToolExecutionError",
  "action_details": {
    "error_type": "FileNotFoundError",
    "error_message": "Tool Read execution failed: File not found",
    "error_context": {
      "tool_name": "Read",
      "file_path": "/nonexistent/file.py"
    },
    "traceback": "..."
  },
  "created_at": "2025-11-09T14:30:00Z"
}
```

### Manual Error Logging (Python)

```python
from action_logging_helpers import log_error

log_error(
    error_type="DatabaseConnectionError",
    error_message="Failed to connect to PostgreSQL",
    error_context={
        "host": "192.168.86.200",
        "port": 5436,
        "database": "omninode_bridge"
    },
    duration_ms=5000,
)
```

### Manual Error Logging (Bash)

```bash
source ~/.claude/hooks/lib/log_action.sh

log_error "DatabaseConnectionError" \
  "Failed to connect to PostgreSQL" \
  '{"host": "192.168.86.200", "port": 5436}'
```

### Common Error Types

- `ToolExecutionError` - Tool failed to execute
- `DatabaseConnectionError` - Database connection failed
- `KafkaPublishError` - Failed to publish to Kafka
- `ValidationError` - Input validation failed
- `TimeoutError` - Operation timed out
- `AuthenticationError` - Authentication failed
- `PermissionError` - Insufficient permissions

---

## Success Logging

### Manual Success Logging (Python)

```python
from action_logging_helpers import log_success

log_success(
    success_type="TaskCompleted",
    success_message="Code generation completed successfully",
    success_context={
        "files_created": 5,
        "tests_passed": 12,
        "quality_score": 0.95
    },
    duration_ms=15000,
    quality_score=0.95,
)
```

### Manual Success Logging (Bash)

```bash
source ~/.claude/hooks/lib/log_action.sh

log_success "TaskCompleted" \
  "Code generation completed" \
  '{"files_created": 5, "tests_passed": 12}' \
  15000 \
  0.95
```

### Example Success Log

```json
{
  "correlation_id": "abc-123-def-456",
  "agent_name": "agent-coder",
  "action_type": "success",
  "action_name": "TaskCompleted",
  "action_details": {
    "success_type": "TaskCompleted",
    "success_message": "Code generation completed successfully",
    "success_context": {
      "files_created": 5,
      "tests_passed": 12
    },
    "quality_score": 0.95
  },
  "duration_ms": 15000,
  "created_at": "2025-11-09T14:30:15Z"
}
```

### Common Success Types

- `TaskCompleted` - Individual task finished
- `WorkflowCompleted` - Multi-step workflow finished
- `QualityGatePassed` - Quality validation passed
- `TestsPassed` - All tests passed
- `CodeGenerationCompleted` - Code generation finished
- `DeploymentSucceeded` - Deployment completed

---

## Decision Logging

### Automatic Decision Logging

**UserPromptSubmit Hook** automatically logs routing decisions:

```json
{
  "correlation_id": "abc-123-def-456",
  "agent_name": "polymorphic-agent",
  "action_type": "decision",
  "action_name": "agent_selected",
  "action_details": {
    "selected_agent": "agent-researcher",
    "confidence": 0.95,
    "selection_method": "event-based-routing",
    "domain": "research",
    "reasoning": "User request involves literature review and analysis"
  },
  "duration_ms": 8,
  "created_at": "2025-11-09T14:30:00Z"
}
```

### Manual Decision Logging (Python)

```python
from action_logging_helpers import log_decision

log_decision(
    decision_type="route_chosen",
    decision_details={
        "route": "parallel_execution",
        "reason": "Multiple independent tasks detected",
        "confidence": 0.85
    },
    duration_ms=12,
)
```

### Manual Decision Logging (Bash)

```bash
source ~/.claude/hooks/lib/log_action.sh

log_decision "route_chosen" \
  '{"route": "parallel_execution", "confidence": 0.85}' \
  12
```

---

## Hook Integration

### Integration Points

**1. UserPromptSubmit Hook** (`user-prompt-submit.sh`):
- Line 235-273: Logs routing decision via `execute_unified.py`
- Line 252-273: Logs agent dispatch action

**2. PreToolUse Hook** (`pre-tool-use-quality.sh`):
- Line 162-231: Logs tool call START via `execute_kafka.py`

**3. PostToolUse Hook** (`post-tool-use-quality.sh`):
- Line 135-168: Detects and logs errors
- Line 170-243: Logs tool call COMPLETION via `execute_kafka.py`

### Hook Execution Flow

```
User Request
  ↓
UserPromptSubmit Hook
  ├→ Agent routing decision logged
  └→ Agent dispatch action logged
  ↓
PreToolUse Hook (for each tool)
  └→ Tool call START logged
  ↓
Tool Execution (by Claude Code)
  ↓
PostToolUse Hook (for each tool)
  ├→ Error detection & logging (if failed)
  └→ Tool call COMPLETION logged
```

---

## Python API

### Import

```python
from action_logging_helpers import log_error, log_success, log_tool_call, log_decision
```

### Function Signatures

```python
def log_error(
    agent_name: Optional[str] = None,
    error_type: str = "UnknownError",
    error_message: str = "",
    error_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
) -> bool

def log_success(
    agent_name: Optional[str] = None,
    success_type: str = "TaskCompleted",
    success_message: str = "",
    success_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    quality_score: Optional[float] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
) -> bool

def log_tool_call(
    tool_name: str,
    tool_parameters: Optional[Dict[str, Any]] = None,
    tool_result: Optional[Dict[str, Any]] = None,
    agent_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
) -> bool

def log_decision(
    decision_type: str,
    decision_details: Dict[str, Any],
    agent_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
) -> bool
```

### Auto-Detection Features

- **correlation_id**: Auto-generated if not provided
- **agent_name**: Auto-detected from environment or correlation context
- **project_path/project_name**: Auto-detected from environment

---

## Querying Logged Data

### PostgreSQL Queries

**Count events by type**:
```sql
SELECT action_type, COUNT(*) as count
FROM agent_actions
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY action_type
ORDER BY count DESC;
```

**Recent errors**:
```sql
SELECT
    correlation_id,
    agent_name,
    action_name,
    action_details->>'error_message' as error_message,
    created_at
FROM agent_actions
WHERE action_type = 'error'
ORDER BY created_at DESC
LIMIT 20;
```

**Tool call durations**:
```sql
SELECT
    action_name,
    AVG(duration_ms) as avg_duration,
    MAX(duration_ms) as max_duration,
    COUNT(*) as call_count
FROM agent_actions
WHERE action_type = 'tool_call'
  AND duration_ms IS NOT NULL
GROUP BY action_name
ORDER BY avg_duration DESC;
```

**Trace by correlation ID**:
```sql
SELECT
    action_type,
    action_name,
    duration_ms,
    created_at
FROM agent_actions
WHERE correlation_id = 'abc-123-def-456'
ORDER BY created_at ASC;
```

### Agent History Browser

**Interactive CLI tool**:
```bash
python3 agents/lib/agent_history_browser.py

# Filter by agent
python3 agents/lib/agent_history_browser.py --agent polymorphic-agent

# Export manifest
python3 agents/lib/agent_history_browser.py --correlation-id abc-123 --export manifest.json
```

---

## Troubleshooting

### Issue: No events logged

**Check**:
1. DEBUG mode enabled: `grep "^DEBUG=" .env`
2. Kafka connectivity: `docker exec -it omninode-bridge-redpanda rpk topic list`
3. Hook logs: `tail -f ~/.claude/hooks/logs/post-tool-use.log`
4. PostgreSQL connectivity: `source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}`

**Fix**:
```bash
# Enable DEBUG mode
echo "DEBUG=true" >> .env
source .env

# Verify Kafka topic exists
docker exec -it omninode-bridge-redpanda rpk topic create agent-actions --partitions 3
```

### Issue: Events not appearing in database

**Check**:
1. Consumer running: `docker ps | grep agent-actions-consumer`
2. Consumer logs: `docker logs -f agent-actions-consumer`
3. Kafka topic has events: `docker exec -it omninode-bridge-redpanda rpk topic consume agent-actions --num 10`

**Fix**:
```bash
# Restart consumer
docker restart agent-actions-consumer

# Check for consumer lag
docker exec -it omninode-bridge-redpanda rpk group describe agent-actions-consumer-group
```

### Issue: High latency

**Check**:
1. Kafka broker health: `docker exec -it omninode-bridge-redpanda rpk cluster health`
2. Database connection pool: `SELECT count(*) FROM pg_stat_activity;`
3. Hook execution time: `grep "duration" ~/.claude/hooks/logs/post-tool-use.log`

**Fix**:
```bash
# Reduce logging overhead - disable DEBUG in production
DEBUG=false

# Increase Kafka batch settings (in execute_kafka.py)
linger_ms=100  # Batch messages for 100ms
batch_size=32768  # 32KB batches
```

---

## Performance

### Benchmarks

**Tool Call Logging Overhead**:
- PreToolUse logging: ~10-20ms (non-blocking)
- PostToolUse logging: ~10-20ms (non-blocking)
- Total overhead: ~20-40ms per tool call

**Kafka Publishing**:
- Publish latency: <5ms (async, fire-and-forget)
- Throughput: >1000 events/second

**PostgreSQL Writing** (via consumer):
- Insert latency: <10ms per event
- Throughput: >500 events/second

### Optimization Tips

**1. Reduce logging volume**:
```bash
# Disable DEBUG in production
DEBUG=false
```

**2. Increase Kafka batching**:
```python
# In execute_kafka.py
linger_ms=100  # Wait 100ms to batch messages
batch_size=65536  # 64KB batches
```

**3. Tune PostgreSQL consumer**:
```python
# Batch inserts
batch_size = 100
flush_interval = 1.0  # seconds
```

**4. Use compression**:
```python
# Already enabled in execute_kafka.py
compression_type="gzip"
```

---

## Summary

**✅ Tool Call Logging**: Automatically logs all tool invocations (start + completion)
**✅ Error Logging**: Automatically detects and logs tool execution errors
**✅ Success Logging**: Manual API for logging task completions
**✅ Decision Logging**: Automatically logs routing decisions
**✅ Correlation Tracking**: Full traceability via correlation IDs
**✅ Performance**: <50ms overhead per tool call (non-blocking)
**✅ Reliability**: Graceful degradation if Kafka unavailable

**Next Steps**:
1. Enable DEBUG mode: `echo "DEBUG=true" >> .env`
2. Verify logging: `python3 agents/lib/agent_history_browser.py`
3. Query data: `psql ... -c "SELECT * FROM agent_actions LIMIT 10;"`
4. Monitor metrics: Grafana dashboard at `http://localhost:3000`

---

**Documentation Version**: 1.0.0
**Last Updated**: 2025-11-09
**Status**: ✅ COMPLETE
