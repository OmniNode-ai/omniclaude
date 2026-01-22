---
name: action-logging
description: Easy-to-use action logging for agents with automatic timing, context management, and Kafka integration. Track tool calls, decisions, errors, and successes with minimal code.
---

# Action Logging

Reusable action logging framework for agents. Provides a convenient wrapper around the action event publishing system with automatic timing, context management, and graceful degradation.

## What It Does

Provides a high-level API for logging all agent actions to Kafka (topic: `agent-actions`) with:

- **Automatic Timing**: Context manager tracks duration automatically
- **Correlation ID Management**: Automatic generation and tracking
- **Graceful Degradation**: Failures don't break workflows
- **Type-Safe API**: Clear method signatures for each action type
- **Non-Blocking**: <5ms publish latency (Kafka async)
- **Complete Traceability**: Links actions via correlation_id

## When to Use

Use this skill whenever you need to integrate action logging into agent code:

- **Tool Call Tracking**: Log Read, Write, Edit, Bash, Glob, etc.
- **Decision Tracking**: Log routing decisions, agent selection, strategy choices
- **Error Tracking**: Log exceptions, failures, and error states
- **Success Tracking**: Log milestones, task completions, quality scores
- **Custom Actions**: Log any agent action with structured details

**Perfect for**:
- New agent implementations
- Adding observability to existing agents
- Debug tracing in development
- Production monitoring and analytics

## Quick Start

### 1. Import ActionLogger

```python
import sys
from pathlib import Path

# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from action_logger import ActionLogger
```

### 2. Initialize Logger

```python
# At agent startup
action_logger = ActionLogger(
    agent_name="agent-my-agent",
    correlation_id=correlation_id,  # From agent context
    project_name="omniclaude",
    project_path=os.getcwd(),  # Use current working directory
    working_directory=os.getcwd(),
    debug_mode=True
)
```

### 3. Log Actions

```python
# Option A: Context manager (automatic timing)
async with action_logger.tool_call("Read", {"file_path": "..."}) as action:
    result = await read_file("...")
    action.set_result({"line_count": len(result)})

# Option B: Manual logging (with timing)
start_time = time.time()
result = await do_something()
duration_ms = int((time.time() - start_time) * 1000)

await action_logger.log_tool_call(
    tool_name="Write",
    tool_parameters={"file_path": "..."},
    tool_result={"success": True},
    duration_ms=duration_ms
)
```

## Core API

### ActionLogger Class

```python
ActionLogger(
    agent_name: str,                        # Agent identifier
    correlation_id: Optional[str] = None,   # Auto-generated if None
    project_path: Optional[str] = None,     # Defaults to cwd
    project_name: Optional[str] = None,     # Defaults to directory name
    working_directory: Optional[str] = None, # Defaults to cwd
    debug_mode: bool = True                 # Enable debug logging
)
```

### Tool Call Logging

**Context Manager (Recommended)**:
```python
async with action_logger.tool_call(
    tool_name: str,
    tool_parameters: Optional[Dict[str, Any]] = None
) as action:
    # Your tool execution code here
    result = await execute_tool(...)

    # Set result before exiting context
    action.set_result({"success": True, "data": result})
```

**Manual Logging**:
```python
await action_logger.log_tool_call(
    tool_name: str,
    tool_parameters: Optional[Dict[str, Any]] = None,
    tool_result: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None
) -> bool
```

### Decision Logging

```python
await action_logger.log_decision(
    decision_name: str,
    decision_context: Optional[Dict[str, Any]] = None,
    decision_result: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None
) -> bool
```

### Error Logging

```python
await action_logger.log_error(
    error_type: str,
    error_message: str,
    error_context: Optional[Dict[str, Any]] = None
) -> bool
```

### Success Logging

```python
await action_logger.log_success(
    success_name: str,
    success_details: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None
) -> bool
```

## Usage Examples

### Example 1: File Operations

```python
from action_logger import ActionLogger
import asyncio
import time

async def agent_file_operations():
    # Initialize logger
    logger = ActionLogger(
        agent_name="agent-file-manager",
        correlation_id="abc-123",
        project_name="omniclaude"
    )

    # Log file read with context manager
    async with logger.tool_call("Read", {"file_path": "/path/to/file.py"}) as action:
        # Simulate file reading
        await asyncio.sleep(0.02)  # 20ms
        with open("/path/to/file.py", 'r') as f:
            content = f.read()

        action.set_result({
            "line_count": len(content.splitlines()),
            "file_size_bytes": len(content),
            "success": True
        })

    # Log file write manually
    start_time = time.time()
    # ... write file ...
    duration_ms = int((time.time() - start_time) * 1000)

    await logger.log_tool_call(
        tool_name="Write",
        tool_parameters={"file_path": "/tmp/output.txt", "content_length": 2048},
        tool_result={"success": True, "bytes_written": 2048},
        duration_ms=duration_ms
    )
```

### Example 2: Agent Routing Decision

```python
async def agent_routing():
    logger = ActionLogger(
        agent_name="polymorphic-agent",
        correlation_id="routing-456"
    )

    # Log routing decision
    start_time = time.time()

    candidates = ["agent-api", "agent-frontend", "agent-database"]
    # ... perform routing analysis ...
    selected = "agent-api"
    confidence = 0.92

    duration_ms = int((time.time() - start_time) * 1000)

    await logger.log_decision(
        decision_name="select_specialized_agent",
        decision_context={
            "user_request": "Design a REST API for user management",
            "candidates": candidates,
            "routing_strategy": "fuzzy_match"
        },
        decision_result={
            "selected_agent": selected,
            "confidence": confidence,
            "reasoning": "API design keywords detected"
        },
        duration_ms=duration_ms
    )
```

### Example 3: Error Handling

```python
async def agent_with_error_handling():
    logger = ActionLogger(
        agent_name="agent-processor",
        correlation_id="error-789"
    )

    try:
        # Attempt operation
        result = await risky_operation()
    except ImportError as e:
        # Log error with context
        await logger.log_error(
            error_type="ImportError",
            error_message=str(e),
            error_context={
                "file": __file__,
                "line": 42,
                "attempted_import": "nonexistent_module",
                "python_path": sys.path
            }
        )
        raise
```

### Example 4: Task Completion

```python
async def agent_task_completion():
    logger = ActionLogger(
        agent_name="agent-researcher",
        correlation_id="task-101"
    )

    # ... perform task ...

    # Log successful completion
    await logger.log_success(
        success_name="research_task_completed",
        success_details={
            "files_analyzed": 15,
            "patterns_found": 42,
            "quality_score": 0.95,
            "execution_time_ms": 1234
        },
        duration_ms=1234
    )
```

### Example 5: Multiple Tool Calls in Sequence

```python
async def agent_batch_processing():
    logger = ActionLogger(
        agent_name="agent-batch-processor",
        correlation_id="batch-202"
    )

    files = ["file1.py", "file2.py", "file3.py"]

    for file_path in files:
        async with logger.tool_call(
            "Grep",
            tool_parameters={"pattern": "TODO", "file_path": file_path}
        ) as action:
            # Perform grep
            matches = await grep_file(file_path, "TODO")

            action.set_result({
                "matches": len(matches),
                "file_path": file_path,
                "success": True
            })
```

### Example 6: One-Off Action (Convenience Function)

```python
from action_logger import log_action

async def quick_action():
    # For one-off actions without creating logger instance
    await log_action(
        agent_name="agent-quick-task",
        action_type="tool_call",
        action_name="Glob",
        action_details={
            "pattern": "**/*.py",
            "matches": 42
        },
        correlation_id="one-off-123",
        duration_ms=10
    )
```

## Integration Checklist

When integrating action logging into an agent:

- [ ] Add `agents/lib` to Python path
- [ ] Import `ActionLogger` from `action_logger`
- [ ] Initialize logger at agent startup with correlation_id
- [ ] Use context manager for tool calls (automatic timing)
- [ ] Log routing decisions with confidence scores
- [ ] Log errors with full context
- [ ] Log success milestones with quality scores
- [ ] Verify events in Kafka topic `agent-actions`
- [ ] Check database table `agent_actions` for persistence

## Action Types Reference

### tool_call
**When**: Agent invokes a tool (Read, Write, Edit, Bash, Glob, Grep, etc.)

**Details Structure**:
```python
{
    "file_path": "/path/to/file.py",      # For file operations
    "command": "ls -la",                   # For Bash
    "pattern": "**/*.py",                  # For Glob/Grep
    "lines_read": 150,                     # Operation metrics
    "success": True,                       # Operation result
    "exit_code": 0                         # For command execution
}
```

### decision
**When**: Agent makes routing, strategy, or planning decisions

**Details Structure**:
```python
{
    "selected_agent": "agent-api",         # Decision result
    "confidence": 0.92,                    # Confidence score (0.0-1.0)
    "candidates": ["agent-a", "agent-b"],  # Alternatives considered
    "reasoning": "API keywords detected",  # Decision rationale
    "strategy": "fuzzy_match"              # Strategy used
}
```

### error
**When**: Agent encounters errors, exceptions, or failures

**Details Structure**:
```python
{
    "error": "FileNotFoundError",          # Error type/class
    "file_path": "/missing/file.py",       # Context where error occurred
    "stack_trace": "...",                  # Full stack trace
    "attempted_operation": "read_file",    # What was being attempted
    "recovery_action": "skip_file"         # How error was handled
}
```

### success
**When**: Agent completes tasks, milestones, or checkpoints successfully

**Details Structure**:
```python
{
    "tasks_completed": 5,                  # Number of tasks
    "quality_score": 0.95,                 # Quality metric (0.0-1.0)
    "files_processed": 15,                 # Work completed
    "duration_total_ms": 1234,             # Total time
    "patterns_applied": ["onex", "async"]  # Patterns used
}
```

## Database Schema

Events are persisted to PostgreSQL table `agent_actions`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `agent_name` | VARCHAR | Agent identifier |
| `action_type` | VARCHAR | tool_call, decision, error, success |
| `action_name` | VARCHAR | Specific action name |
| `action_details` | JSONB | Structured action metadata |
| `correlation_id` | UUID | Correlation tracking |
| `project_name` | VARCHAR | Project identifier |
| `project_path` | VARCHAR | Project directory |
| `working_directory` | VARCHAR | Working directory |
| `debug_mode` | BOOLEAN | Debug mode flag |
| `duration_ms` | INTEGER | Action duration |
| `created_at` | TIMESTAMP | Event timestamp |

## Kafka Integration

**Topic**: `agent-actions`

**Event Schema**:
```json
{
  "agent_name": "agent-researcher",
  "action_type": "tool_call",
  "action_name": "read_file",
  "action_details": {
    "file_path": "/path/to/file.py",
    "lines_read": 150
  },
  "correlation_id": "abc-123",
  "project_name": "omniclaude",
  "project_path": "/path/to/project",
  "working_directory": "/path/to/project",
  "debug_mode": true,
  "duration_ms": 20,
  "timestamp": "2025-11-06T10:00:00Z"
}
```

**Consumers**:
- **Database Writer**: Persists events to PostgreSQL
- **Analytics Consumer**: Real-time metrics and dashboards
- **Audit Logger**: S3 archival for compliance

## Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Publish Latency | <5ms | Kafka async publish |
| Context Manager Overhead | <1ms | Minimal performance impact |
| Blocking | No | Non-blocking async I/O |
| Failure Impact | None | Graceful degradation |
| Event Durability | High | Kafka persistence |
| Replay Capability | Yes | Complete audit trail |

## Prerequisites

**Python Dependencies**:
```bash
pip install kafka-python aiokafka
```

**Infrastructure** (on 192.168.86.200):
- Kafka/Redpanda: Port 29092 (external) / 9092 (internal)
- PostgreSQL: Port 5436 (omninode_bridge database)

**Environment Variables**:
```bash
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092  # For host scripts
# OR
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # For Docker services

POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>
```

## File Locations

**ActionLogger Implementation**:
```
agents/lib/action_logger.py (in repository root)
```

**Event Publisher** (underlying implementation):
```
agents/lib/action_event_publisher.py (in repository root)
```

**Example Usage**:
```
agents/lib/action_logging_example.py (in repository root)
```

**Skill Location**:
```
${CLAUDE_PLUGIN_ROOT}/skills/action-logging/skill.md
```

## Troubleshooting

### Issue: Events Not Appearing in Kafka

**Check Kafka Connection**:
```bash
# Test Kafka connectivity
kcat -L -b 192.168.86.200:29092

# Check topic exists
kcat -L -b 192.168.86.200:29092 -t agent-actions
```

**Check Environment Variables**:
```python
import os
print(f"KAFKA_BOOTSTRAP_SERVERS: {os.getenv('KAFKA_BOOTSTRAP_SERVERS')}")
```

### Issue: Logger Initialization Fails

**Check Python Path**:
```python
import sys
print("Python path:", sys.path)

# Ensure agents/lib is in path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))
```

### Issue: Context Manager Not Recording Duration

**Ensure set_result() is called**:
```python
async with logger.tool_call("Read", {...}) as action:
    result = await read_file(...)

    # MUST call set_result() before exiting context
    action.set_result({"success": True})
```

### Issue: Events Published But Not in Database

**Check Consumer Status**:
```bash
# Check agent-actions consumer is running
docker ps | grep agent-actions-consumer

# View consumer logs
docker logs -f <consumer_container_name>
```

**Query Database**:
```sql
-- Check if events are being written
SELECT * FROM agent_actions
ORDER BY created_at DESC
LIMIT 20;

-- Check by correlation_id
SELECT * FROM agent_actions
WHERE correlation_id = 'your-correlation-id';
```

## Best Practices

### 1. Always Use Correlation IDs
```python
# Get correlation_id from agent context
correlation_id = context.get("correlation_id") or str(uuid4())

logger = ActionLogger(
    agent_name="agent-name",
    correlation_id=correlation_id  # Essential for tracing
)
```

### 2. Prefer Context Manager for Tool Calls
```python
# Good: Automatic timing
async with logger.tool_call("Read", {...}) as action:
    result = await read_file(...)
    action.set_result({...})

# Also good: Manual timing when context manager doesn't fit
start = time.time()
result = await operation()
await logger.log_tool_call(..., duration_ms=int((time.time() - start) * 1000))
```

### 3. Include Rich Context in Details
```python
# Good: Rich, queryable context
await logger.log_decision(
    decision_name="select_agent",
    decision_context={
        "user_request": "...",
        "candidates": [...],
        "strategy": "fuzzy_match"
    },
    decision_result={
        "selected": "agent-api",
        "confidence": 0.92,
        "reasoning": "..."
    }
)

# Less useful: Minimal context
await logger.log_decision(
    decision_name="select_agent",
    decision_result={"selected": "agent-api"}
)
```

### 4. Log Errors with Full Context
```python
try:
    result = await operation()
except Exception as e:
    await logger.log_error(
        error_type=type(e).__name__,
        error_message=str(e),
        error_context={
            "file": __file__,
            "line": sys.exc_info()[2].tb_lineno,
            "stack_trace": traceback.format_exc(),
            "attempted_operation": "...",
            "input_data": {...}  # Sanitize sensitive data!
        }
    )
    raise
```

### 5. Log Success Milestones
```python
# Log task completion with quality metrics
await logger.log_success(
    success_name="task_completed",
    success_details={
        "files_processed": 15,
        "quality_score": 0.95,
        "patterns_applied": ["onex", "async"],
        "tests_passed": 42
    },
    duration_ms=total_duration
)
```

## Testing

### Test ActionLogger Integration

```python
# Run example script from repository root
python3 agents/lib/action_logging_example.py
```

**Expected Output**:
```
2025-11-06 10:00:00 - INFO - Agent started (correlation_id: abc-123)
2025-11-06 10:00:00 - INFO - ✓ Read action logged with context manager
2025-11-06 10:00:00 - INFO - ✓ Write action logged manually
2025-11-06 10:00:00 - INFO - ✓ Decision action logged
2025-11-06 10:00:00 - INFO - ✓ Bash action logged
2025-11-06 10:00:00 - INFO - ✓ Error action logged
2025-11-06 10:00:00 - INFO - ✓ Success action logged
2025-11-06 10:00:00 - INFO - All actions logged successfully!
```

### Verify in Kafka

```bash
# Consume agent-actions topic
kcat -C -b 192.168.86.200:29092 -t agent-actions
```

### Verify in Database

```bash
# Query recent actions
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT 10;"
```

## Advanced Usage

### Custom Action Types

```python
# Log custom action type
await logger.log_raw_action(
    action_type="custom_validation",
    action_name="onex_compliance_check",
    action_details={
        "node_type": "effect",
        "compliance_score": 0.98,
        "issues_found": 0
    },
    duration_ms=50
)
```

### Batch Action Logging

```python
# Log multiple related actions
files = ["file1.py", "file2.py", "file3.py"]

for file_path in files:
    async with logger.tool_call("Read", {"file_path": file_path}) as action:
        content = await read_file(file_path)
        action.set_result({
            "line_count": len(content.splitlines()),
            "file_path": file_path
        })
```

### Error Recovery Logging

```python
max_retries = 3
for attempt in range(max_retries):
    try:
        result = await operation()

        # Log success after retry
        await logger.log_success(
            success_name="retry_succeeded",
            success_details={
                "attempt": attempt + 1,
                "max_retries": max_retries
            }
        )
        break
    except Exception as e:
        if attempt == max_retries - 1:
            # Log final failure
            await logger.log_error(
                error_type="MaxRetriesExceeded",
                error_message=f"Failed after {max_retries} attempts: {e}",
                error_context={
                    "attempts": max_retries,
                    "last_error": str(e)
                }
            )
            raise
        else:
            # Log retry attempt
            await logger.log_decision(
                decision_name="retry_operation",
                decision_context={
                    "attempt": attempt + 1,
                    "error": str(e)
                }
            )
```

## See Also

- **Action Event Publisher**: Lower-level publishing API
- **Agent Execution Logger**: High-level agent lifecycle logging
- **Agent Tracking Skills**: Other observability skills
- **Kafka Event Bus**: Event-driven architecture documentation
- **Observability Guide**: Complete observability documentation

## Notes

- **Non-Blocking**: Logging failures don't break workflows
- **Automatic Correlation**: All actions linked via correlation_id
- **Graceful Degradation**: Falls back gracefully if Kafka unavailable
- **Type Safety**: Clear API with type hints
- **Minimal Overhead**: <5ms publish latency, <1ms context manager overhead
- **Production Ready**: Used in production agents with 100+ req/s throughput

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/action-logging/`
**Repository Source**: `agents/lib/` (in repository root)

---

**Last Updated**: 2025-11-06
**Version**: 1.0.0
**Maintainer**: OmniClaude Observability Team
