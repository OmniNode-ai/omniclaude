---
name: log-agent-action
description: Log detailed agent actions to Kafka or PostgreSQL for debug tracing and observability. Tracks every tool call, decision, error, and success event with DEBUG mode support.
---

# Log Agent Action

This skill logs detailed agent actions for debug tracing and observability. It provides complete execution traces when DEBUG mode is enabled.

## When to Use

- **DEBUG Mode Only**: This skill is designed for verbose debug logging
- Track tool calls made by agents
- Record agent decisions and reasoning
- Log errors and exceptions during execution
- Capture success milestones and checkpoints
- Trace complete execution flows for analysis

**Important**: This skill automatically checks the `DEBUG` environment variable. Logging is skipped unless:
- `DEBUG=true` in environment, OR
- `--debug-mode` flag is explicitly provided

## Two Implementation Versions

### Kafka Version (Recommended for Production)

**File**: `execute_kafka.py`

**Benefits**:
- ⚡ **Async Non-Blocking**: <5ms publish latency
- 🔄 **Event Replay**: Complete audit trail
- 📊 **Multiple Consumers**: DB + analytics + alerts
- 🚀 **Scalability**: Handles 1M+ events/sec
- 🛡️ **Fault Tolerance**: Events persisted even if consumers fail

**Kafka Topic**: `agent-actions`

**How to Use (Kafka)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "${AGENT_NAME}" \
  --action-type "${ACTION_TYPE}" \
  --action-name "${ACTION_NAME}" \
  --details '${ACTION_DETAILS_JSON}' \
  --correlation-id "${CORRELATION_ID}" \
  --duration-ms ${DURATION_MS}
```

**Variable Substitution**:
- `${AGENT_NAME}` - Name of agent performing action (e.g., "polymorphic-agent")
- `${ACTION_TYPE}` - One of: `tool_call`, `decision`, `error`, `success`
- `${ACTION_NAME}` - Specific action name (e.g., "route_to_agent", "execute_bash")
- `${ACTION_DETAILS_JSON}` - JSON object with action-specific details
- `${CORRELATION_ID}` - Correlation ID for tracking (auto-generated if omitted)
- `${DURATION_MS}` - How long the action took in milliseconds (optional)

**Example (Kafka)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-agent-action/execute_kafka.py \
  --agent "polymorphic-agent" \
  --action-type "decision" \
  --action-name "route_to_specialized_agent" \
  --details '{"selected_agent":"agent-performance","confidence":0.92}' \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --duration-ms 45
```

### Direct Database Version (Fallback)

**File**: `execute.py`

**Use Cases**:
- Kafka service unavailable
- Local development without Kafka
- Testing and debugging
- Simpler deployment scenarios

**Database Table**: `agent_actions`

**How to Use (Direct DB)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-agent-action/execute.py \
  --agent "${AGENT_NAME}" \
  --action-type "${ACTION_TYPE}" \
  --action-name "${ACTION_NAME}" \
  --details '${ACTION_DETAILS_JSON}' \
  --correlation-id "${CORRELATION_ID}" \
  --duration-ms ${DURATION_MS}
```

**Example (Direct DB)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-agent-action/execute.py \
  --agent "polymorphic-agent" \
  --action-type "tool_call" \
  --action-name "read_file" \
  --details '{"file_path":"/path/to/file.py","lines_read":150}' \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --duration-ms 12
```

## Action Types

- **tool_call**: Agent invokes a tool (Read, Write, Bash, etc.)
- **decision**: Agent makes a routing or strategic decision
- **error**: Error or exception during execution
- **success**: Successful completion of a milestone or task

## Database Schema

**Table**: `agent_actions`

Required fields:
- `agent_name` - Name of agent performing action
- `action_type` - Type of action (tool_call|decision|error|success)
- `action_name` - Specific action name
- `correlation_id` - Correlation ID for tracking

Optional fields:
- `action_details` - JSONB object with action-specific details
- `debug_mode` - Boolean (always true for this skill)
- `duration_ms` - Action duration in milliseconds
- `created_at` - Timestamp (auto-generated)

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/` (symlinked to repository)
**Repository Source**: `skills/`

Skills are version-controlled in the repository and symlinked to `${CLAUDE_PLUGIN_ROOT}/skills/` so Claude Code can access them.

## Required Environment

**For Kafka Version**:
- Kafka brokers: Set via `KAFKA_BROKERS` env var (default: `localhost:9092`)
- kafka-python package: `pip install kafka-python`
- DEBUG mode: Set `DEBUG=true` or use `--debug-mode` flag

**For Direct DB Version**:
- PostgreSQL connection via `${CLAUDE_PLUGIN_ROOT}/skills/_shared/db_helper.py`
- Database: `omninode_bridge` on localhost:5436
- Credentials: Set in db_helper.py
- DEBUG mode: Set `DEBUG=true` or use `--debug-mode` flag

## Output

**Success Response** (Kafka):
```json
{
  "success": true,
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "agent_name": "polymorphic-agent",
  "action_type": "decision",
  "action_name": "route_to_specialized_agent",
  "debug_mode": true,
  "published_to": "kafka",
  "topic": "agent-actions"
}
```

**Success Response** (Direct DB):
```json
{
  "success": true,
  "action_id": "uuid",
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "agent_name": "polymorphic-agent",
  "action_type": "tool_call",
  "action_name": "read_file",
  "debug_mode": true,
  "created_at": "2025-10-21T10:00:00Z"
}
```

**Skipped Response** (DEBUG mode disabled):
```json
{
  "success": true,
  "skipped": true,
  "reason": "debug_mode_disabled",
  "message": "Action logging skipped (DEBUG mode not enabled)"
}
```

## Example Workflow

When an agent performs actions in DEBUG mode:

1. **Tool Call**: Agent uses Read tool
2. **Log Action** (this skill): Record tool call with file path and duration
3. **Decision**: Agent decides to route to specialized agent
4. **Log Action** (this skill): Record decision with confidence score
5. **Error Handling**: Agent encounters an error
6. **Log Action** (this skill): Record error with stack trace
7. **Recovery**: Agent successfully retries
8. **Log Action** (this skill): Record success milestone

The logged actions provide:
- Complete execution trace for debugging
- Performance analysis of individual actions
- Error pattern identification
- Agent behavior analysis

## Integration

This skill is part of the agent observability system:

- **Kafka Consumers** (for Kafka version):
  - Database Writer: Persists events to PostgreSQL
  - Analytics Consumer: Real-time metrics dashboard
  - Audit Logger: S3 archival for compliance

- **Direct DB** (for Direct DB version):
  - Immediate PostgreSQL persistence
  - Queryable via standard SQL
  - Used for post-execution analysis

## Performance Characteristics

| Version | Publish Latency | Blocking | Fault Tolerance | Scalability |
|---------|----------------|----------|-----------------|-------------|
| Kafka | <5ms | Non-blocking | High | Horizontal |
| Direct DB | 20-100ms | Blocking | Low | Vertical |

**Recommendation**: Use Kafka version for production, Direct DB for local development.

## Notes

- **DEBUG Mode Required**: Logging only occurs when DEBUG=true or --debug-mode flag is set
- **Non-Blocking Observability**: Failures are logged but don't break workflows
- **Correlation Tracking**: Always use correlation_id for complete trace reconstruction
- **Action Details**: Use JSON for structured, queryable action metadata
- **Multiple Consumers**: Kafka version enables parallel consumption (DB + analytics + alerts)
- **Event Replay**: Kafka version provides complete audit trail with time-travel debugging

## Common Action Examples

**Tool Call**:
```bash
--action-type "tool_call" \
--action-name "read_file" \
--details '{"file_path":"/path/to/file.py","lines_read":150}'
```

**Decision**:
```bash
--action-type "decision" \
--action-name "select_agent" \
--details '{"selected_agent":"agent-performance","confidence":0.92,"alternatives":["agent-api","agent-debug"]}'
```

**Error**:
```bash
--action-type "error" \
--action-name "file_read_failed" \
--details '{"error":"FileNotFoundError","file_path":"/missing/file.py","stack_trace":"..."}'
```

**Success**:
```bash
--action-type "success" \
--action-name "task_completed" \
--details '{"tasks_completed":5,"quality_score":0.95,"duration_total_ms":1234}'
```
