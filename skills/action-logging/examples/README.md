# Action Logging Examples

Copy-paste ready examples for integrating action logging into agents.

## Quick Reference

| Example File | What It Demonstrates | When to Use |
|--------------|---------------------|-------------|
| `basic_usage.py` | Complete integration example | First-time integration |
| `tool_call_patterns.py` | Different tool call logging patterns | Logging Read, Write, Edit, Bash, etc. |
| `decision_logging.py` | Agent decision logging | Routing, strategy selection |
| `error_handling.py` | Error and success logging | Error handling, recovery, milestones |

## Running Examples

```bash
# Basic usage
cd /Volumes/PRO-G40/Code/omniclaude
python3 ~/.claude/skills/action-logging/examples/basic_usage.py

# Tool call patterns
python3 ~/.claude/skills/action-logging/examples/tool_call_patterns.py

# Decision logging
python3 ~/.claude/skills/action-logging/examples/decision_logging.py

# Error handling
python3 ~/.claude/skills/action-logging/examples/error_handling.py
```

## Example Outputs

All examples log to:
- **Kafka Topic**: `agent-actions`
- **Database Table**: `agent_actions`

### Verify in Kafka

```bash
kcat -C -b 192.168.86.200:29092 -t agent-actions
```

### Verify in Database

```bash
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT agent_name, action_type, action_name, created_at
      FROM agent_actions
      ORDER BY created_at DESC
      LIMIT 20;"
```

## Key Patterns

### Context Manager (Automatic Timing)

```python
async with logger.tool_call("Read", {"file_path": "..."}) as action:
    result = await read_file("...")
    action.set_result({"line_count": len(result)})
```

### Manual Timing

```python
start = time.time()
result = await operation()
await logger.log_tool_call(
    tool_name="Write",
    tool_parameters={...},
    tool_result={...},
    duration_ms=int((time.time() - start) * 1000)
)
```

### Decision with Confidence

```python
await logger.log_decision(
    decision_name="select_agent",
    decision_context={"candidates": [...]},
    decision_result={
        "selected": "agent-api",
        "confidence": 0.92,
        "reasoning": "..."
    }
)
```

### Error with Context

```python
try:
    result = await operation()
except Exception as e:
    await logger.log_error(
        error_type=type(e).__name__,
        error_message=str(e),
        error_context={"file": __file__, "operation": "..."}
    )
```

## Integration Checklist

When copying these examples:

- [ ] Update `agent_name` to your agent's name
- [ ] Get `correlation_id` from agent context
- [ ] Update `project_path` and `project_name`
- [ ] Adjust file paths for your use case
- [ ] Replace simulated operations with real code
- [ ] Keep `action.set_result()` calls in context managers
- [ ] Include rich context in decision logging
- [ ] Add stack traces to error logging
- [ ] Verify events appear in Kafka and database

## Performance Notes

- Context manager overhead: <1ms
- Kafka publish latency: <5ms
- Non-blocking: Yes
- Graceful degradation: Yes (failures don't break workflows)

## See Also

- **Complete API**: `../skill.md`
- **Quick Start**: `../README.md`
- **Implementation**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/action_logger.py`

---

**Last Updated**: 2025-11-06
