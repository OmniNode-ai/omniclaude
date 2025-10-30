---
name: request-agent-routing
description: Request agent routing via Kafka event bus or direct router fallback. Returns routing recommendations with confidence scores for specialized agent selection.
---

# Request Agent Routing

This skill requests agent routing decisions via the event bus, following the same event-driven pattern as manifest injection.

## When to Use

- At the start of polymorphic agent execution to select specialized agent
- When hooks need to determine which agent should handle a task
- Any time agent routing decisions are needed with confidence scoring
- Replaces direct Python execution of `agent_router.py`

## Two Implementation Versions

### Kafka Version (Recommended for Production)

**File**: `execute_kafka.py`

**Benefits**:
- ⚡ **Service-Level Caching**: >60% cache hit rate (vs 0% with Python exec)
- 🚀 **Faster Routing**: 5-45ms (vs 75-130ms Python startup overhead)
- 🔄 **Event Replay**: Complete audit trail of routing requests
- 📊 **Observability**: All routing requests flow through Kafka
- 🏗️ **Unified Architecture**: Consistent with manifest injection pattern
- 🛡️ **Fault Tolerance**: Falls back to direct routing on timeout

**Event Flow**:
```
Hook/Agent Request
  ↓ (publish)
Kafka Topic: agent.routing.requested.v1
  ↓ (consumed by)
agent-router-service
  ↓ (AgentRouter with warm cache)
Kafka Topic: agent.routing.completed.v1
  ↓ (consumed by)
Hook/Agent receives recommendations
```

**Kafka Topics**:
- Request: `agent.routing.requested.v1`
- Response: `agent.routing.completed.v1`
- Error: `agent.routing.failed.v1`

**How to Use (Kafka)**:

```bash
python3 ~/.claude/skills/routing/request-agent-routing/execute_kafka.py \
  --user-request "${USER_REQUEST}" \
  --max-recommendations 3 \
  --timeout-ms 5000 \
  --correlation-id "${CORRELATION_ID}"
```

**Variable Substitution**:
- `${USER_REQUEST}` - User's task description (required)
- `${CORRELATION_ID}` - Correlation ID for traceability (optional, auto-generated)

**Optional Parameters**:
- `--context` - JSON object with execution context (e.g., `'{"domain": "api_development"}'`)
- `--max-recommendations` - Number of recommendations to return (default: 5)
- `--timeout-ms` - Response timeout in milliseconds (default: 5000)

**Example (Kafka)**:
```bash
python3 ~/.claude/skills/routing/request-agent-routing/execute_kafka.py \
  --user-request "optimize my database queries" \
  --max-recommendations 3 \
  --timeout-ms 5000 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

**With Context**:
```bash
python3 ~/.claude/skills/routing/request-agent-routing/execute_kafka.py \
  --user-request "optimize my database queries" \
  --context '{"domain": "database_optimization", "current_file": "api/database.py"}' \
  --max-recommendations 3
```

### Direct Router Version (Fallback)

**File**: `execute_direct.py`

**Use Cases**:
- Kafka service unavailable
- agent-router-service not running
- Local development without Kafka
- Testing and debugging
- Emergency fallback

**Direct Execution**:
- Spawns Python process to run AgentRouter
- No caching persistence (in-memory only)
- 75-130ms overhead (Python startup + module imports)
- No event-driven observability

**How to Use (Direct)**:

```bash
python3 ~/.claude/skills/routing/request-agent-routing/execute_direct.py \
  --user-request "${USER_REQUEST}" \
  --max-recommendations 3 \
  --correlation-id "${CORRELATION_ID}"
```

**Example (Direct)**:
```bash
python3 ~/.claude/skills/routing/request-agent-routing/execute_direct.py \
  --user-request "optimize my database queries" \
  --max-recommendations 3 \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

## Output Format

**Success Response**:
```json
{
  "success": true,
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "recommendations": [
    {
      "agent_name": "agent-performance",
      "agent_title": "Performance Optimization Specialist",
      "confidence": {
        "total": 0.92,
        "trigger_score": 0.95,
        "context_score": 0.90,
        "capability_score": 0.88,
        "historical_score": 0.95,
        "explanation": "High confidence match on 'optimize' and 'database' triggers"
      },
      "reason": "Strong trigger match with 'optimize' keyword and database context",
      "definition_path": "/Users/jonah/.claude/agent-definitions/agent-performance.yaml"
    }
  ],
  "routing_metadata": {
    "routing_time_ms": 45,
    "cache_hit": false,
    "candidates_evaluated": 5,
    "routing_strategy": "enhanced_fuzzy_matching",
    "method": "kafka"
  }
}
```

**Error Response**:
```json
{
  "success": false,
  "error": "Routing request timeout after 5000ms",
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "fallback_attempted": true,
  "fallback_result": {
    "agent_name": "polymorphic-agent",
    "reason": "Fallback to polymorphic agent due to routing timeout"
  }
}
```

## Event Schema

**Request Event** (`agent.routing.requested.v1`):
```json
{
  "event_id": "uuid",
  "event_type": "AGENT_ROUTING_REQUESTED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T14:30:00Z",
  "service": "polymorphic-agent",
  "payload": {
    "user_request": "optimize my database queries",
    "context": {
      "domain": "database_optimization",
      "previous_agent": "agent-api-architect",
      "current_file": "api/database.py"
    },
    "options": {
      "max_recommendations": 3,
      "min_confidence": 0.6,
      "routing_strategy": "enhanced_fuzzy_matching"
    }
  }
}
```

**Response Event** (`agent.routing.completed.v1`):
```json
{
  "event_id": "uuid",
  "event_type": "AGENT_ROUTING_COMPLETED",
  "correlation_id": "uuid",
  "timestamp": "2025-10-30T14:30:00.045Z",
  "service": "agent-router-service",
  "payload": {
    "recommendations": [...],
    "routing_metadata": {
      "routing_time_ms": 45,
      "cache_hit": false,
      "candidates_evaluated": 5,
      "routing_strategy": "enhanced_fuzzy_matching"
    }
  }
}
```

## Skills Location

**Claude Code Access**: `~/.claude/skills/` (symlinked to repository)
**Repository Source**: `skills/routing/request-agent-routing/`

Skills are version-controlled in the repository and symlinked to `~/.claude/skills/` so Claude Code can access them.

## Required Environment

**For Kafka Version**:
- Kafka brokers: Set via `KAFKA_BOOTSTRAP_SERVERS` env var
- agent-router-service: Running on Docker (consumes routing requests)
- aiokafka package: Included in project dependencies

**For Direct Router Version**:
- Agent registry: `~/.claude/agent-definitions/agent-registry.yaml`
- Python packages: yaml, dataclasses (standard library)
- No external service dependencies

## Performance Comparison

| Metric | Kafka (Event-Driven) | Direct (Python Exec) | Improvement |
|--------|---------------------|---------------------|-------------|
| **Cold Start** | 30-45ms | 75-130ms | **2-3× faster** |
| **Warm Start (cache hit)** | <10ms | 75-130ms | **7-13× faster** |
| **Multi-Agent (3 requests)** | 30ms parallel | 225ms sequential | **7.5× faster** |
| **Cache Hit Rate** | >60% (persistent) | ~0% (lost) | **∞ improvement** |
| **Memory Overhead** | 50MB (shared service) | 150MB (3 processes) | **3× less** |

## Example Workflow

**Polymorphic Agent Routing**:

```bash
#!/bin/bash
# Correlation ID for traceability
CORRELATION_ID=$(uuidgen)

# User request
USER_REQUEST="optimize my database queries"

# Request routing via Kafka (primary)
ROUTING_RESULT=$(python3 ~/.claude/skills/routing/request-agent-routing/execute_kafka.py \
  --user-request "$USER_REQUEST" \
  --max-recommendations 3 \
  --correlation-id "$CORRELATION_ID")

# Parse result
SELECTED_AGENT=$(echo "$ROUTING_RESULT" | jq -r '.recommendations[0].agent_name')
CONFIDENCE=$(echo "$ROUTING_RESULT" | jq -r '.recommendations[0].confidence.total')
REASON=$(echo "$ROUTING_RESULT" | jq -r '.recommendations[0].reason')

echo "✅ Selected Agent: $SELECTED_AGENT"
echo "   Confidence: $CONFIDENCE"
echo "   Reason: $REASON"

# Log routing decision
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute_kafka.py \
  --agent "$SELECTED_AGENT" \
  --confidence "$CONFIDENCE" \
  --strategy "enhanced_fuzzy_matching" \
  --user-request "$USER_REQUEST" \
  --reasoning "$REASON" \
  --correlation-id "$CORRELATION_ID"

# Execute as selected agent
# ... (load agent definition and execute)
```

## Integration

This skill is part of the event-driven intelligence architecture:

**Unified Event Bus**:
- Routing requests → Kafka → agent-router-service
- Manifest requests → Kafka → archon-intelligence
- Database queries → Kafka → omninode-bridge

**Complete Traceability**:
```
User Request (correlation_id: abc123)
  ↓
agent.routing.requested.v1 (correlation_id: abc123)
  ↓
agent.routing.completed.v1 (correlation_id: abc123)
  ↓
intelligence.code-analysis-requested.v1 (correlation_id: abc123)
  ↓
intelligence.code-analysis-completed.v1 (correlation_id: abc123)
  ↓
Agent Execution (correlation_id: abc123)
```

**Database Observability**:
- `agent_routing_requests` - All routing requests logged
- `agent_routing_decisions` - Completed routing decisions
- `agent_manifest_injections` - Manifest generation linked via correlation_id
- `agent_execution_logs` - Agent execution linked via correlation_id

## Graceful Degradation

**Automatic Fallback**:
1. Try Kafka routing (primary)
2. On timeout/error: Fall back to direct routing
3. Log fallback event for monitoring
4. Return recommendations regardless of method

**Timeout Handling**:
- Default timeout: 5000ms (5 seconds)
- Kafka overhead: ~10-15ms (network)
- Routing time: ~20-45ms (service processing)
- Buffer: ~4940ms for service processing

**Error Scenarios**:
- Kafka unavailable → Direct routing fallback
- agent-router-service down → Direct routing fallback
- Timeout → Direct routing fallback
- Invalid request → Error response with details

## Notes

- Always include correlation_id for end-to-end traceability
- Use Kafka version in production for performance and observability
- Direct version automatically used as fallback on Kafka errors
- Routing decisions are cached at service level (persistent across requests)
- No blocking: Returns immediately with recommendations or error
- Compatible with existing polymorphic agent workflow

## Related Documentation

- [Event-Driven Routing Proposal](../../../docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md)
- [Agent Router](../../../agents/lib/agent_router.py)
- [Routing Architecture Comparison](../../../docs/architecture/ROUTING_ARCHITECTURE_COMPARISON.md)
- [Agent Traceability](../../../docs/observability/AGENT_TRACEABILITY.md)
