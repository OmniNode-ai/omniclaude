# Log Agent Action Skill

**Purpose**: Log every action an agent takes (in debug mode) for complete execution tracing.

## When to Use
- **Debug Mode**: When DEBUG=true or debug logging is enabled
- **Every Tool Call**: Read, Write, Edit, Bash, Grep, Glob, etc.
- **Every Decision**: Routing decisions, transformation choices, error handling
- **Failure Analysis**: Complete trace when things go wrong

## Usage

```bash
/log-agent-action \
  --agent "agent-name" \
  --action-type "tool_call|decision|error|success" \
  --action-name "Read|Write|route_to_agent|etc" \
  --details "JSON with action-specific details" \
  --correlation-id "uuid" \
  --debug-mode true
```

## Examples

### Tool Call Logging
```bash
# Log a file read
/log-agent-action \
  --agent "agent-polymorphic-agent" \
  --action-type "tool_call" \
  --action-name "Read" \
  --details '{"file_path": "/path/to/file.py", "lines_read": 150}' \
  --correlation-id "$CORRELATION_ID" \
  --debug-mode true

# Log a file write
/log-agent-action \
  --agent "agent-code-generator" \
  --action-type "tool_call" \
  --action-name "Write" \
  --details '{"file_path": "/path/to/new.py", "lines_written": 50, "success": true}' \
  --correlation-id "$CORRELATION_ID"
```

### Decision Logging
```bash
# Log routing decision
/log-agent-action \
  --agent "agent-polymorphic-agent" \
  --action-type "decision" \
  --action-name "select_target_agent" \
  --details '{"selected": "agent-performance", "confidence": 0.92, "alternatives": ["agent-debug", "agent-code-quality"]}' \
  --correlation-id "$CORRELATION_ID"
```

### Error Logging
```bash
# Log error encountered
/log-agent-action \
  --agent "agent-test-runner" \
  --action-type "error" \
  --action-name "test_execution_failed" \
  --details '{"error_type": "ImportError", "error_message": "No module named requests", "file": "test_api.py"}' \
  --correlation-id "$CORRELATION_ID"
```

## Database Schema

Logs to `agent_actions` table:
- `id` (UUID) - Auto-generated action ID
- `correlation_id` (UUID) - Links related actions
- `agent_name` (TEXT) - Which agent performed action
- `action_type` (TEXT) - tool_call, decision, error, success
- `action_name` (TEXT) - Specific action (Read, Write, route_to_agent, etc.)
- `action_details` (JSONB) - Full details of the action
- `debug_mode` (BOOLEAN) - Whether this was logged in debug mode
- `duration_ms` (INTEGER) - How long the action took (optional)
- `created_at` (TIMESTAMPTZ) - When action occurred

## Integration

The skill automatically:
- Checks `DEBUG` environment variable
- Skips logging if not in debug mode (for performance)
- Links actions via correlation_id for complete trace
- Returns success/failure status

## Performance

- Debug mode only: Minimal overhead in production
- Async logging: Non-blocking action logging
- Indexed by correlation_id: Fast trace reconstruction
- Auto-cleanup: Purge debug logs older than 30 days
