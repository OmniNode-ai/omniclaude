---
description: Unified agent observability — action logging, tracking, execution logging, and trace correlation
version: 1.0.0
level: intermediate
debug: false
category: observability
tags: [observability, logging, tracking, tracing, kafka, postgresql]
author: OmniClaude Team
composable: true
args:
  - name: subcommand
    description: "Mode: log-action, track-routing, track-detection, track-transformation, track-performance, start-execution, complete-execution, or trace"
    required: true
  - name: --id
    description: "Correlation ID for trace subcommand"
    required: false
mode: full
---

# Observability

## Overview

Unified agent observability skill consolidating action logging, agent tracking,
execution logging, and trace correlation.

## Subcommands

| Subcommand | Store | Former skill |
|---|---|---|
| `log-action` | Kafka | action-logging |
| `track-routing` | PostgreSQL | agent-tracking |
| `track-detection` | PostgreSQL | agent-tracking |
| `track-transformation` | PostgreSQL | agent-tracking |
| `track-performance` | PostgreSQL | agent-tracking |
| `start-execution` | PostgreSQL | log-execution |
| `complete-execution` | PostgreSQL | log-execution |
| `trace --id <cid>` | PostgreSQL+Kafka | trace-correlation-id |

---

### log-action

<!-- Absorbed from action-logging -->

Reusable action logging framework for agents. Provides a convenient wrapper around the action event publishing system with automatic timing, context management, and graceful degradation.

Publishes all agent actions to Kafka (topic: `agent-actions`) with:

- **Automatic Timing**: Context manager tracks duration automatically
- **Correlation ID Management**: Automatic generation and tracking
- **Graceful Degradation**: Failures don't break workflows
- **Type-Safe API**: Clear method signatures for each action type
- **Non-Blocking**: <5ms publish latency (Kafka async)

#### Quick Start

```python
from action_logger import ActionLogger

# Initialize logger
action_logger = ActionLogger(
    agent_name="agent-my-agent",
    correlation_id=correlation_id,
    project_name="omniclaude",
    project_path=os.getcwd(),
    working_directory=os.getcwd(),
    debug_mode=True
)

# Context manager (automatic timing)
async with action_logger.tool_call("Read", {"file_path": "..."}) as action:
    result = await read_file("...")
    action.set_result({"line_count": len(result)})
```

#### Core API

**ActionLogger Class**:
```python
ActionLogger(
    agent_name: str,
    correlation_id: Optional[str] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    working_directory: Optional[str] = None,
    debug_mode: bool = True
)
```

**Tool Call Logging** (context manager):
```python
async with action_logger.tool_call(tool_name, tool_parameters) as action:
    result = await execute_tool(...)
    action.set_result({"success": True, "data": result})
```

**Manual Logging**:
```python
await action_logger.log_tool_call(tool_name, tool_parameters, tool_result, duration_ms)
```

**Decision Logging**:
```python
await action_logger.log_decision(decision_name, decision_context, decision_result, duration_ms)
```

**Error Logging**:
```python
await action_logger.log_error(error_type, error_message, error_context)
```

**Success Logging**:
```python
await action_logger.log_success(success_name, success_details, duration_ms)
```

#### Action Types

| Type | When | Key Fields |
|------|------|------------|
| `tool_call` | Agent invokes a tool | file_path, command, pattern, success |
| `decision` | Routing/strategy decisions | selected_agent, confidence, reasoning |
| `error` | Exceptions and failures | error type, stack_trace, recovery_action |
| `success` | Task completions | quality_score, files_processed |

#### Kafka Integration

- **Topic**: `agent-actions`
- **Consumers**: Database Writer, Analytics Consumer, Audit Logger
- **Performance**: <5ms publish latency, non-blocking async I/O

#### Database Schema

Events are persisted to PostgreSQL table `agent_actions`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `agent_name` | VARCHAR | Agent identifier |
| `action_type` | VARCHAR | tool_call, decision, error, success |
| `action_name` | VARCHAR | Specific action name |
| `action_details` | JSONB | Structured action metadata |
| `correlation_id` | UUID | Correlation tracking |
| `duration_ms` | INTEGER | Action duration |
| `created_at` | TIMESTAMP | Event timestamp |

---

### track-routing / track-detection / track-transformation / track-performance

<!-- Absorbed from agent-tracking -->

PostgreSQL-backed observability for tracking agent routing decisions, detection failures, transformations, and performance metrics.

#### Sub-commands

- **track-routing** -- Track successful routing decisions (agent selected, confidence, method)
- **track-detection** -- Track detection failures for gap analysis
- **track-transformation** -- Record agent transformation events
- **track-performance** -- Record latency and throughput metrics

#### Database Tables

| Table | Tracked By |
|-------|-----------|
| `agent_routing_decisions` | track-routing |
| `agent_detection_failures` | track-detection |
| `agent_execution_logs` | track-performance |

---

### start-execution / complete-execution

<!-- Absorbed from log-execution -->

Track agent execution lifecycle in PostgreSQL for observability and intelligence gathering.

#### Usage

**Start Execution** -- call at the beginning of your task:
```bash
/observability start-execution --agent agent-research --description "Research Claude Code skills"
```

Returns:
```json
{
  "success": true,
  "execution_id": "uuid-here",
  "started_at": "2025-10-20T18:38:44Z",
  "correlation_id": "uuid-here"
}
```

Save the `execution_id` for completion updates.

**Complete Execution** -- call when your task finishes:
```bash
/observability complete-execution --execution-id <uuid> --status success --quality-score 0.95
```

For errors:
```bash
/observability complete-execution --execution-id <uuid> --status error --error-message "API timeout"
```

#### Parameters

**start-execution**:
- `--agent` (required): Agent name
- `--description` (optional): Task description
- `--session-id` (optional): Session ID (auto-generated if omitted)
- `--metadata` (optional): JSON metadata

**complete-execution**:
- `--execution-id` (required): UUID from start command
- `--status` (optional): success | error | cancelled (default: success)
- `--error-message` (optional): Error description
- `--quality-score` (optional): Quality score 0.0-1.0
- `--metadata` (optional): Final JSON metadata

#### Database Schema

Logs are stored in `agent_execution_logs` table with:
- execution_id, correlation_id, session_id
- agent_name, user_prompt
- started_at, completed_at, duration_ms
- status (in_progress, success, error, cancelled)
- error_message, error_type
- quality_score (0.0-1.0)
- metadata (JSONB)

#### Performance

- Execution time: <50ms per call
- Token cost: ~20 tokens per invocation
- Error resilient: graceful fallback if database unavailable

---

### trace

<!-- Absorbed from trace-correlation-id -->

End-to-end execution tracing by correlation ID for debugging and observability.

#### Usage

```bash
/observability trace --id <correlation-id>
```

Given a correlation ID, traces all events, routing decisions, tool calls, and outcomes associated with that execution across both PostgreSQL and Kafka stores.

---

## Integration Checklist

When integrating observability into an agent:

- [ ] Import `ActionLogger` from `action_logger`
- [ ] Initialize logger at agent startup with correlation_id
- [ ] Use context manager for tool calls (automatic timing)
- [ ] Log routing decisions with confidence scores
- [ ] Log errors with full context
- [ ] Log success milestones with quality scores
- [ ] Verify events in Kafka topic `agent-actions`
- [ ] Check database table `agent_actions` for persistence

## Prerequisites

**Infrastructure**:
- Kafka/Redpanda: Port 19092 (external) / 9092 (internal Docker)
- PostgreSQL: Port 5436 (omnibase_infra database)

**Environment Variables**:
```bash
source ~/.omnibase/.env
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
```

## Best Practices

1. **Always use correlation IDs** -- essential for tracing across systems
2. **Prefer context manager** for tool calls -- automatic timing with no boilerplate
3. **Include rich context** in details -- makes queries and debugging productive
4. **Log errors with full context** -- stack traces, attempted operation, recovery action
5. **Log success milestones** -- quality scores enable trend analysis
