---
name: log-routing-decision
description: Log agent routing decisions to Kafka or PostgreSQL for observability and learning. Records which agent was selected, confidence score, routing strategy, and reasoning.
---

# Log Routing Decision

This skill logs agent routing decisions for tracking, observability, and machine learning.

## When to Use

- After selecting which agent should handle a task
- When the polymorphic agent routes to a specialized agent
- Any time an agent routing decision is made with confidence scoring

## Two Implementation Versions

### Kafka Version (Recommended for Production)

**File**: `execute_kafka.py`

**Benefits**:
- ⚡ **Async Non-Blocking**: <5ms publish latency
- 🔄 **Event Replay**: Complete audit trail
- 📊 **Multiple Consumers**: DB + analytics + alerts
- 🚀 **Scalability**: Handles 1M+ events/sec
- 🛡️ **Fault Tolerance**: Events persisted even if consumers fail

**Kafka Topic**: `onex.evt.omniclaude.routing-decision.v1`

**How to Use (Kafka)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "${SELECTED_AGENT}" \
  --confidence ${CONFIDENCE_SCORE} \
  --strategy "${ROUTING_STRATEGY}" \
  --latency-ms ${ROUTING_TIME_MS} \
  --user-request "${USER_REQUEST}" \
  --reasoning "${REASONING}" \
  --correlation-id "${CORRELATION_ID}"
```

**Variable Substitution**:
- `${SELECTED_AGENT}` - The agent you routed to (e.g., "agent-performance")
- `${CONFIDENCE_SCORE}` - Your confidence 0.0-1.0 (e.g., 0.92)
- `${ROUTING_STRATEGY}` - Strategy used (e.g., "enhanced_fuzzy_matching")
- `${ROUTING_TIME_MS}` - Routing time in milliseconds (e.g., 45)
- `${USER_REQUEST}` - Original user request text
- `${REASONING}` - Why you selected this agent
- `${CORRELATION_ID}` - Correlation ID for this conversation

**Example (Kafka)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms 45 \
  --user-request "optimize my database queries" \
  --reasoning "High confidence match on 'optimize' and 'performance' triggers" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

### Direct Database Version (Fallback)

**File**: `execute.py`

**Use Cases**:
- Kafka service unavailable
- Local development without Kafka
- Testing and debugging
- Simpler deployment scenarios

**Database Table**: `agent_routing_decisions`

**How to Use (Direct DB)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-routing-decision/execute.py \
  --agent "${SELECTED_AGENT}" \
  --confidence ${CONFIDENCE_SCORE} \
  --strategy "${ROUTING_STRATEGY}" \
  --latency-ms ${ROUTING_TIME_MS} \
  --user-request "${USER_REQUEST}" \
  --reasoning "${REASONING}" \
  --correlation-id "${CORRELATION_ID}"
```

**Example (Direct DB)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-routing-decision/execute.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms 45 \
  --user-request "optimize my database queries" \
  --reasoning "High confidence match on 'optimize' and 'performance' triggers" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

## Database Schema

**Table**: `agent_routing_decisions`

Required fields:
- `selected_agent` - Name of the agent selected (e.g., "agent-performance")
- `confidence_score` - Confidence 0.0-1.0 (e.g., 0.92)
- `routing_strategy` - Strategy used (e.g., "enhanced_fuzzy_matching", "explicit_request")
- `routing_time_ms` - Time taken to make decision in milliseconds

Optional fields:
- `user_request` - Original user request text
- `alternatives` - JSON array of alternative agents considered
- `reasoning` - Why this agent was selected
- `context` - JSON object with additional context (including correlation_id)

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/` (symlinked to repository)
**Repository Source**: `skills/`

Skills are version-controlled in the repository and symlinked to `${CLAUDE_PLUGIN_ROOT}/skills/` so Claude Code can access them.

## Required Environment

**For Kafka Version**:
- Kafka brokers: Set via `KAFKA_BOOTSTRAP_SERVERS` env var (no default — must be explicitly configured)
- kafka-python package: `pip install kafka-python`

**For Direct DB Version**:
- PostgreSQL connection via `${CLAUDE_PLUGIN_ROOT}/skills/_shared/db_helper.py`
- Database: `omninode_bridge` on localhost:5436
- Credentials: Set in db_helper.py

## Output

**Success Response (Kafka)**:
```json
{
  "success": true,
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "selected_agent": "agent-performance",
  "confidence_score": 0.92,
  "routing_strategy": "enhanced_fuzzy_matching",
  "routing_time_ms": 45,
  "published_to": "kafka",
  "topic": "onex.evt.omniclaude.routing-decision.v1"
}
```

**Success Response (Direct DB)**:
```json
{
  "success": true,
  "routing_decision_id": "uuid",
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "selected_agent": "agent-performance",
  "confidence_score": 0.92,
  "routing_strategy": "enhanced_fuzzy_matching",
  "routing_time_ms": 45,
  "created_at": "2025-10-21T10:00:00Z"
}
```

## Example Workflow

When the polymorphic agent routes a request:

1. Analyze user request
2. Select best agent (e.g., agent-performance, confidence: 0.92)
3. **Call this skill** to log the decision
4. Execute as the selected agent
5. The logged decision enables:
   - Post-execution summary banner
   - Historical routing analysis
   - Machine learning on routing patterns

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

Logged decisions are:
- Displayed in post-execution summary banners (stop hook)
- Used for routing pattern analysis
- Fed into machine learning for routing optimization
- Queryable for debugging and metrics

## Performance Characteristics

| Version | Publish Latency | Blocking | Fault Tolerance | Scalability |
|---------|----------------|----------|-----------------|-------------|
| Kafka | <5ms | Non-blocking | High | Horizontal |
| Direct DB | 20-100ms | Blocking | Low | Vertical |

**Recommendation**: Use Kafka version for production, Direct DB for local development.

## Notes

- Always include correlation_id for traceability
- Log BEFORE executing as the target agent
- Failures are non-blocking (observability shouldn't break workflows)
- **Multiple Consumers**: Kafka version enables parallel consumption (DB + analytics + alerts)
- **Event Replay**: Kafka version provides complete audit trail with time-travel debugging
