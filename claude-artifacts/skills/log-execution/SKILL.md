---
name: "log-execution"
description: "Track agent execution in PostgreSQL for observability and intelligence gathering"
version: "1.0.0"
author: "OmniClaude Team"
category: "observability"
tags:
  - logging
  - execution-tracking
  - observability
  - postgresql
  - correlation-tracking
dependencies:
  - psql
usage: |
  /log-execution start --agent AGENT_NAME --description "DESCRIPTION"
  /log-execution progress --execution-id UUID --stage STAGE --percent PERCENT
  /log-execution complete --execution-id UUID --status STATUS [--quality-score SCORE]
examples:
  - "/log-execution start --agent agent-research --description 'Research Claude Code skills'"
  - "/log-execution progress --execution-id uuid --stage analyzing --percent 50"
  - "/log-execution complete --execution-id uuid --status success --quality-score 0.95"
---

# Log Execution Skill

Track your agent execution in PostgreSQL for observability and intelligence gathering.

## Purpose
This skill allows agents to log their execution progress, making it easy to track what agents are doing, measure performance, and debug issues.

## Usage

### 1. Start Execution
Call this at the beginning of your task:

```bash
/log-execution start --agent agent-research --description "Research Claude Code skills implementation"
```

**Returns:**
```json
{
  "success": true,
  "execution_id": "uuid-here",
  "started_at": "2025-10-20T18:38:44Z",
  "correlation_id": "uuid-here",
  "session_id": "uuid-here"
}
```

**Save the `execution_id` for progress and completion updates!**

### 2. Log Progress (Optional)
Update progress during execution:

```bash
/log-execution progress --execution-id <uuid> --stage "gathering-docs" --percent 50
```

**Returns:**
```json
{
  "success": true,
  "execution_id": "uuid-here",
  "agent_name": "agent-research",
  "stage": "gathering-docs",
  "progress": {
    "stage": "gathering-docs",
    "percent": 50,
    "updated_at": "2025-10-20T18:39:00Z"
  }
}
```

### 3. Complete Execution
Call this when your task finishes:

```bash
/log-execution complete --execution-id <uuid> --status success --quality-score 0.95
```

**For errors:**
```bash
/log-execution complete --execution-id <uuid> --status error --error-message "API timeout"
```

**Returns:**
```json
{
  "success": true,
  "execution_id": "uuid-here",
  "agent_name": "agent-research",
  "status": "success",
  "duration_ms": 11000,
  "started_at": "2025-10-20T18:38:44Z",
  "completed_at": "2025-10-20T18:38:55Z"
}
```

## Parameters

### start
- `--agent` (required): Your agent name (e.g., agent-research)
- `--description` (optional): Task description
- `--session-id` (optional): Session ID (auto-generated if omitted)
- `--metadata` (optional): JSON metadata `'{"key": "value"}'`

### progress
- `--execution-id` (required): UUID from start command
- `--stage` (required): Current stage name (e.g., "analyzing", "generating")
- `--percent` (optional): Progress percentage (0-100)
- `--metadata` (optional): Additional JSON metadata

### complete
- `--execution-id` (required): UUID from start command
- `--status` (optional): success|error|cancelled (default: success)
- `--error-message` (optional): Error description (if status=error)
- `--quality-score` (optional): Quality score 0.0-1.0
- `--metadata` (optional): Final JSON metadata

## Benefits

**For You (The Agent):**
- ✅ **Simple API**: Just 3 commands (start, progress, complete)
- ✅ **No SQL needed**: Skill handles all database operations
- ✅ **Automatic tracking**: Correlation IDs handled automatically
- ✅ **Error resilient**: Graceful fallback if database unavailable
- ✅ **Saves tokens**: ~500 tokens saved vs manual SQL

**For Intelligence System:**
- ✅ **Real-time observability**: See what agents are doing
- ✅ **Performance metrics**: Track duration, quality scores
- ✅ **Debugging**: Trace execution paths via correlation IDs
- ✅ **Analytics**: Query patterns and success rates

## Example Workflow

```python
# At task start
result = execute_skill("/log-execution start --agent agent-code-generator --description 'Generate ONEX node'")
exec_id = result['execution_id']

# During task (optional)
execute_skill(f"/log-execution progress --execution-id {exec_id} --stage analyzing --percent 30")
execute_skill(f"/log-execution progress --execution-id {exec_id} --stage generating --percent 70")

# At completion
execute_skill(f"/log-execution complete --execution-id {exec_id} --status success --quality-score 0.90")
```

## Database Schema

Logs are stored in `agent_execution_logs` table with:
- execution_id, correlation_id, session_id
- agent_name, user_prompt
- started_at, completed_at, duration_ms
- status (in_progress, success, error, cancelled)
- error_message, error_type
- quality_score (0.0-1.0)
- metadata (JSONB for custom data)

## Error Handling

If database is unavailable, skill will:
- Print error to stderr
- Return JSON with `success: false`
- **Not crash your task** - graceful degradation

## Performance

- **Execution time**: <50ms per call
- **Token cost**: ~20 tokens per invocation
- **Database load**: Minimal (uses connection pooling)
