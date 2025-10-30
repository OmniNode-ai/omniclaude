# Agent Actions Table Analysis & Tool Logging Investigation

**Date**: October 29, 2025
**Correlation ID**: 340ec212-1f96-424f-aae9-53df242213c0
**Investigator**: polymorphic-agent
**Task**: Analyze why tool execution logging stopped on Oct 27th

---

## Executive Summary

**CRITICAL FINDING**: Tool execution logging **never actually started** in production. The `agent_file_operations` table is **completely empty** (0 rows), and all 103 entries in `agent_actions` from October 27th are **mock/test entries** with `"mock": true` in the action_details field.

The logging infrastructure is **fully implemented** but **not being invoked** during actual agent executions.

---

## Database Schema Analysis

### 1. agent_actions Table

**Purpose**: High-level action tracking (tool calls, decisions, errors, successes)

**Schema**:
```sql
Column             Type                      Constraints
------------------+-------------------------+------------------------
id                | uuid                    | PRIMARY KEY, NOT NULL
correlation_id    | uuid                    | NOT NULL
agent_name        | text                    | NOT NULL
action_type       | text                    | NOT NULL (CHECK constraint)
action_name       | text                    | NOT NULL
action_details    | jsonb                   | DEFAULT '{}'::jsonb
debug_mode        | boolean                 | NOT NULL, DEFAULT true
duration_ms       | integer                 |
created_at        | timestamptz             | NOT NULL, DEFAULT now()
project_path      | varchar(500)            |
project_name      | varchar(255)            |
working_directory | varchar(500)            |
```

**CHECK Constraint on action_type**:
```sql
CHECK (action_type IN ('tool_call', 'decision', 'error', 'success'))
```

**Current Data**: 103 tool_call entries (all mock), 922 decisions, 106 successes, 105 errors

**Sample Mock Entry**:
```json
{
  "agent_name": "agent-ui-testing",
  "action_type": "tool_call",
  "action_name": "Read",
  "action_details": {"mock": true, "timestamp": 1761599491004}
}
```

### 2. agent_file_operations Table

**Purpose**: Detailed file operation tracking with content hashes

**Status**: ❌ **COMPLETELY EMPTY** (0 rows)

**Schema**: 27 columns including:
- operation_type: 'read', 'write', 'edit', 'delete', 'create', 'glob', 'grep'
- file_path, file_path_hash (SHA-256)
- content_hash_before, content_hash_after (SHA-256)
- intelligence_file_id, matched_pattern_ids
- tool_name, line_range, operation_params
- success, error_message, bytes_read, bytes_written, duration_ms

---

## Root Cause Analysis

**Why logging "stopped"**: It never started.

1. Oct 27 entries were **test/mock data** (`"mock": true`)
2. `agent_file_operations` table has **never received real data**
3. `AgentTraceabilityLogger` is fully implemented but **never called**
4. No tool execution interceptor/wrapper exists

---

## Logging Infrastructure

### AgentTraceabilityLogger ✅ FULLY IMPLEMENTED

**Location**: `agents/lib/agent_traceability_logger.py`

**Methods**:
- `log_prompt()` → agent_prompts table (currently empty)
- `log_file_operation()` → agent_file_operations table (currently empty)
- `log_intelligence_usage()` → agent_intelligence_usage table

**Not Connected**: No code calls these methods during actual tool use

---

## Expected Data Format Per Tool

### Read Tool
```json
{
  "operation_type": "read",
  "tool_name": "Read",
  "file_path": "/absolute/path",
  "content_after": "file contents",
  "bytes_read": 1234,
  "duration_ms": 45
}
```

### Write Tool
```json
{
  "operation_type": "write",
  "tool_name": "Write",
  "content_before": "old" or null,
  "content_after": "new",
  "bytes_written": 2345,
  "content_changed": true,
  "duration_ms": 120
}
```

### Edit Tool
```json
{
  "operation_type": "edit",
  "tool_name": "Edit",
  "content_before": "old",
  "content_after": "modified",
  "line_range": {"start": 10, "end": 25},
  "operation_params": {"old_string": "...", "new_string": "..."},
  "duration_ms": 85
}
```

### Bash Tool
```json
{
  "operation_type": "read" or "write",
  "tool_name": "Bash",
  "operation_params": {
    "command": "pytest tests/",
    "exit_code": 0,
    "stdout": "...",
    "stderr": ""
  },
  "duration_ms": 3500
}
```

---

## Recommendations

### 1. Implement Tool Execution Interceptor
- Create hook that intercepts Claude Code tool calls
- Call `AgentTraceabilityLogger.log_file_operation()` for each use
- Handle Read, Write, Edit, Bash, Glob, Grep

### 2. Connect to Agent Lifecycle
- Initialize tracer at agent start
- Pass correlation_id throughout
- Log prompt with `log_prompt()`

### 3. Add Tool Logging Wrapper
- Capture start time, content before/after
- Calculate duration and hashes
- Log success/failure and errors

### 4. Testing
- Unit tests per tool type
- Integration test with real agent
- Verify correlation ID tracing
- Check <50ms logging overhead

---

## Database Queries for Monitoring

```sql
-- Check recent file operations (should populate once logging is enabled)
SELECT operation_type, tool_name, COUNT(*)
FROM agent_file_operations
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY operation_type, tool_name;

-- Check logging health
SELECT
  COUNT(*) as total_ops,
  COUNT(CASE WHEN success THEN 1 END) as successful,
  AVG(duration_ms) as avg_duration
FROM agent_file_operations
WHERE created_at > NOW() - INTERVAL '24 hours';
```

---

## Related Tables (13 total)

1. agent_actions (1136 rows - mostly mock)
2. agent_file_operations (0 rows - **TARGET TABLE**)
3. agent_prompts (0 rows - needs integration)
4. agent_execution_logs (13 rows - real data)
5. agent_intelligence_usage (unknown)
6. agent_manifest_injections (has data)
7. agent_routing_decisions (has data)
8. agent_transformation_events (has data)
9-13. Other agent tables (various states)

---

## Conclusion

**Tool logging infrastructure exists but is not connected to actual tool execution.**

**Next Steps**:
1. Implement tool interceptor/wrapper
2. Connect AgentTraceabilityLogger to agent lifecycle
3. Test with real executions
4. Monitor logging health

**Success Criteria**:
- agent_file_operations populated during tool use
- agent_prompts populated at agent start
- Complete trace: prompt → operations → intelligence → result
- <50ms overhead per operation

---

**Database**: postgresql://postgres:***@192.168.86.200:5436/omninode_bridge
**Report Generated**: October 29, 2025
