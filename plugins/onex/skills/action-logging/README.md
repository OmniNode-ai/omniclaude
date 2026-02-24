# Action Logging Skill - Quick Start

Easy-to-use action logging for agents with automatic timing and Kafka integration.

## Quick Usage

### 1. Import and Initialize

```python
import sys
from pathlib import Path

# Add agents/lib to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from action_logger import ActionLogger

# Initialize logger
logger = ActionLogger(
    agent_name="agent-my-agent",
    correlation_id="abc-123",
    project_name="omniclaude"
)
```

### 2. Log Tool Calls (Context Manager)

```python
# Automatic timing
async with logger.tool_call("Read", {"file_path": "..."}) as action:
    result = await read_file("...")
    action.set_result({"line_count": len(result)})
```

### 3. Log Decisions

```python
await logger.log_decision(
    decision_name="select_agent",
    decision_context={"candidates": ["agent-a", "agent-b"]},
    decision_result={"selected": "agent-a", "confidence": 0.92}
)
```

### 4. Log Errors

```python
try:
    result = await operation()
except Exception as e:
    await logger.log_error(
        error_type=type(e).__name__,
        error_message=str(e),
        error_context={"file": __file__}
    )
```

### 5. Log Success

```python
await logger.log_success(
    success_name="task_completed",
    success_details={"files_processed": 5, "quality_score": 0.95}
)
```

## Integration Checklist

- [ ] Add `agents/lib` to Python path
- [ ] Import `ActionLogger`
- [ ] Initialize with correlation_id
- [ ] Log tool calls with context manager
- [ ] Log decisions with confidence scores
- [ ] Log errors with full context
- [ ] Log success milestones
- [ ] Verify events in Kafka topic `agent-actions`

## Prerequisites

**Python Dependencies**:
```bash
pip install kafka-python aiokafka
```

**Infrastructure** (<your-infrastructure-host>):
- Kafka/Redpanda: Port 29092
- PostgreSQL: Port 5436

**Environment Variables**:
```bash
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=5436
POSTGRES_DATABASE=omniclaude
```

## Test Your Integration

```bash
# Run example script
python3 agents/lib/action_logging_example.py

# Verify in Kafka
kcat -C -b <kafka-bootstrap-servers>:9092 -t agent-actions

# Verify in database
source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} \
  -c "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT 10;"
```

## Complete Documentation

See `skill.md` for:
- Complete API reference
- Advanced usage examples
- Troubleshooting guide
- Performance characteristics
- Best practices

## File Locations

- **Skill**: `${CLAUDE_PLUGIN_ROOT}/skills/action-logging/skill.md`
- **Implementation**: `agents/lib/action_logger.py` (in repository root)
- **Example**: `agents/lib/action_logging_example.py` (in repository root)

## Performance

- **Publish Latency**: <5ms (Kafka async)
- **Context Manager Overhead**: <1ms
- **Non-Blocking**: Yes
- **Graceful Degradation**: Yes

---

**Last Updated**: 2025-11-06
