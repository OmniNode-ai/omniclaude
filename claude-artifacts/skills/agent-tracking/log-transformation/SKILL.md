---
name: log-transformation
description: Log agent transformation events to Kafka or PostgreSQL for observability and learning. Records when agents transform from one identity to another, including success status and duration.
---

# Log Transformation

This skill logs agent transformation events for tracking polymorphic agent behavior, observability, and performance analysis.

## When to Use

- After the polymorphic agent transforms into a specialized agent
- When an agent delegates to another agent
- Any time an agent identity transformation occurs during workflow execution

## Two Implementation Versions

### Kafka Version (Recommended for Production)

**File**: `execute_kafka.py`

**Benefits**:
- ⚡ **Async Non-Blocking**: <5ms publish latency
- 🔄 **Event Replay**: Complete audit trail
- 📊 **Multiple Consumers**: DB + analytics + alerts
- 🚀 **Scalability**: Handles 1M+ events/sec
- 🛡️ **Fault Tolerance**: Events persisted even if consumers fail

**Kafka Topic**: `agent-transformation-events`

**How to Use (Kafka)**:

```bash
python3 ~/.claude/skills/agent-tracking/log-transformation/execute_kafka.py \
  --from-agent "${SOURCE_AGENT}" \
  --to-agent "${TARGET_AGENT}" \
  --success ${SUCCESS} \
  --duration-ms ${DURATION_MS} \
  --correlation-id "${CORRELATION_ID}" \
  --reason "${REASON}" \
  --confidence ${CONFIDENCE_SCORE}
```

**Variable Substitution**:
- `${SOURCE_AGENT}` - The agent you're transforming from (e.g., "polymorphic-agent")
- `${TARGET_AGENT}` - The agent you're transforming to (e.g., "agent-performance")
- `${SUCCESS}` - Whether transformation succeeded: true or false
- `${DURATION_MS}` - Transformation time in milliseconds (e.g., 85)
- `${CORRELATION_ID}` - Correlation ID for this conversation
- `${REASON}` - Why the transformation occurred
- `${CONFIDENCE_SCORE}` - Routing confidence 0.0-1.0 (optional)

**Example (Kafka)**:
```bash
python3 ~/.claude/skills/agent-tracking/log-transformation/execute_kafka.py \
  --from-agent "polymorphic-agent" \
  --to-agent "agent-performance" \
  --success true \
  --duration-ms 85 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --reason "High confidence match on 'optimize' and 'performance' triggers" \
  --confidence 0.92
```

### Direct Database Version (Fallback)

**File**: `execute.py`

**Use Cases**:
- Kafka service unavailable
- Local development without Kafka
- Testing and debugging
- Simpler deployment scenarios

**Database Table**: `agent_transformation_events`

**How to Use (Direct DB)**:

```bash
python3 ~/.claude/skills/agent-tracking/log-transformation/execute.py \
  --from-agent "${SOURCE_AGENT}" \
  --to-agent "${TARGET_AGENT}" \
  --success ${SUCCESS} \
  --duration-ms ${DURATION_MS} \
  --correlation-id "${CORRELATION_ID}" \
  --reason "${REASON}" \
  --confidence ${CONFIDENCE_SCORE}
```

**Example (Direct DB)**:
```bash
python3 ~/.claude/skills/agent-tracking/log-transformation/execute.py \
  --from-agent "polymorphic-agent" \
  --to-agent "agent-performance" \
  --success true \
  --duration-ms 85 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81" \
  --reason "High confidence match on 'optimize' and 'performance' triggers" \
  --confidence 0.92
```

## Database Schema

**Table**: `agent_transformation_events`

Required fields:
- `source_agent` - Source agent name (e.g., "polymorphic-agent")
- `target_agent` - Target agent name (e.g., "agent-performance")
- `success` - Whether transformation succeeded (true/false)
- `transformation_duration_ms` - Time taken to transform in milliseconds

Optional fields:
- `transformation_reason` - Why this transformation occurred
- `confidence_score` - Routing confidence that led to transformation (0.0-1.0)
- `correlation_id` - Added to context JSON for tracking (auto-generated if not provided)

## Skills Location

**Claude Code Access**: `~/.claude/skills/` (symlinked to repository)
**Repository Source**: `skills/`

Skills are version-controlled in the repository and symlinked to `~/.claude/skills/` so Claude Code can access them.

## Required Environment

**For Kafka Version**:
- Kafka brokers: Set via `KAFKA_BROKERS` env var (default: `localhost:9092`)
- kafka-python package: `pip install kafka-python`

**For Direct DB Version**:
- PostgreSQL connection via `~/.claude/skills/_shared/db_helper.py`
- Database: `omninode_bridge` on localhost:5436
- Credentials: Set in db_helper.py

## Output

**Success Response (Kafka)**:
```json
{
  "success": true,
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "source_agent": "polymorphic-agent",
  "target_agent": "agent-performance",
  "transformation_success": true,
  "duration_ms": 85,
  "published_to": "kafka",
  "topic": "agent-transformation-events"
}
```

**Success Response (Direct DB)**:
```json
{
  "success": true,
  "transformation_id": "uuid",
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "source_agent": "polymorphic-agent",
  "target_agent": "agent-performance",
  "transformation_success": true,
  "duration_ms": 85,
  "created_at": "2025-10-21T10:00:00Z"
}
```

## Example Workflow

When the polymorphic agent transforms:

1. Analyze user request and select target agent
2. Log routing decision (using log-routing-decision skill)
3. **Call this skill** to log the transformation event
4. Display transformation banner
5. Execute as the selected agent
6. The logged transformation enables:
   - Transformation success rate tracking
   - Performance analysis (duration patterns)
   - Agent usage analytics
   - Correlation with routing decisions

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

Logged transformations are:
- Correlated with routing decisions via correlation_id
- Used for agent performance analysis
- Fed into transformation success rate metrics
- Queryable for debugging and optimization
- Displayed in post-execution summary banners (stop hook)

## Performance Characteristics

| Version | Publish Latency | Blocking | Fault Tolerance | Scalability |
|---------|----------------|----------|-----------------|-------------|
| Kafka | <5ms | Non-blocking | High | Horizontal |
| Direct DB | 20-100ms | Blocking | Low | Vertical |

**Recommendation**: Use Kafka version for production, Direct DB for local development.

## Notes

- Always include correlation_id for traceability across routing and transformation
- Log AFTER routing decision but BEFORE executing as target agent
- Failures are non-blocking (observability shouldn't break workflows)
- Track both successful and failed transformations for analysis
- **Multiple Consumers**: Kafka version enables parallel consumption (DB + analytics + alerts)
- **Event Replay**: Kafka version provides complete audit trail with time-travel debugging
