---
name: log-performance-metrics
description: Log router performance metrics to Kafka or PostgreSQL for performance tracking and optimization. Records routing duration, cache hits, trigger strategies, and confidence components.
---

# Log Performance Metrics

This skill logs router performance metrics for tracking routing efficiency, cache effectiveness, and optimization opportunities.

## When to Use

- After completing a routing decision (regardless of cache hit/miss)
- When measuring routing performance and optimization opportunities
- For tracking cache effectiveness and hit rates
- Any time you want to record routing performance data

## Two Implementation Versions

### Kafka Version (Recommended for Production)

**File**: `execute_kafka.py`

**Benefits**:
- ⚡ **Async Non-Blocking**: <5ms publish latency
- 🔄 **Event Replay**: Complete audit trail
- 📊 **Multiple Consumers**: DB + analytics + alerts
- 🚀 **Scalability**: Handles 1M+ events/sec
- 🛡️ **Fault Tolerance**: Events persisted even if consumers fail

**Kafka Topic**: `onex.evt.omniclaude.performance-metrics.v1`

**How to Use (Kafka)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-performance-metrics/execute_kafka.py \
  --query "${QUERY_TEXT}" \
  --duration-ms ${DURATION_MS} \
  --cache-hit ${CACHE_HIT} \
  --candidates ${CANDIDATES_COUNT} \
  --strategy "${MATCH_STRATEGY}" \
  --correlation-id "${CORRELATION_ID}"
```

**Variable Substitution**:
- `${QUERY_TEXT}` - The user request text (e.g., "optimize API performance")
- `${DURATION_MS}` - Routing duration in milliseconds (e.g., 45)
- `${CACHE_HIT}` - Whether cache was hit: true or false
- `${CANDIDATES_COUNT}` - Number of agents considered (e.g., 5)
- `${MATCH_STRATEGY}` - Strategy used (e.g., "enhanced_fuzzy_matching")
- `${CORRELATION_ID}` - Correlation ID for this conversation

**Example (Kafka)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-performance-metrics/execute_kafka.py \
  --query "optimize my database queries" \
  --duration-ms 45 \
  --cache-hit false \
  --candidates 5 \
  --strategy "enhanced_fuzzy_matching" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

### Direct Database Version (Fallback)

**File**: `execute.py`

**Use Cases**:
- Kafka service unavailable
- Local development without Kafka
- Testing and debugging
- Simpler deployment scenarios

**Database Table**: `router_performance_metrics`

**How to Use (Direct DB)**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-performance-metrics/execute.py \
  --query "${QUERY_TEXT}" \
  --duration-ms ${DURATION_MS} \
  --cache-hit ${CACHE_HIT} \
  --candidates ${CANDIDATES_COUNT} \
  --strategy "${MATCH_STRATEGY}" \
  --correlation-id "${CORRELATION_ID}"
```

**Example (Direct DB)**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/log-performance-metrics/execute.py \
  --query "optimize my database queries" \
  --duration-ms 45 \
  --cache-hit false \
  --candidates 5 \
  --strategy "enhanced_fuzzy_matching" \
  --correlation-id "ad12146a-b7d0-4a47-86bf-7ec298ce2c81"
```

## Database Schema

**Table**: `router_performance_metrics`

Required fields:
- `query_text` - User request text that was routed (e.g., "optimize my API performance")
- `routing_duration_ms` - Time taken for routing in milliseconds (0-999, e.g., 45)
- `cache_hit` - Whether result was from cache (true/false)
- `candidates_evaluated` - Number of candidate agents evaluated (e.g., 5)

Optional fields:
- `trigger_match_strategy` - Strategy used (e.g., "enhanced_fuzzy_matching", "explicit_request")
- `confidence_components` - JSON object with confidence breakdown (e.g., {"trigger": 0.9, "context": 0.8})
- `correlation_id` - Correlation ID for tracking (auto-generated if not provided)

Constraints:
- `routing_duration_ms` must be between 0 and 999 milliseconds

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/` (symlinked to repository)
**Repository Source**: `skills/`

Skills are version-controlled in the repository and symlinked to `${CLAUDE_PLUGIN_ROOT}/skills/` so Claude Code can access them.

## Required Environment

**For Kafka Version**:
- Kafka brokers: Set via `KAFKA_BROKERS` env var (default: `localhost:9092`)
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
  "query_text": "optimize my database queries",
  "routing_duration_ms": 45,
  "cache_hit": false,
  "candidates_evaluated": 5,
  "published_to": "kafka",
  "topic": "onex.evt.omniclaude.performance-metrics.v1"
}
```

**Success Response (Direct DB)**:
```json
{
  "success": true,
  "metric_id": "uuid",
  "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
  "query_text": "optimize my database queries",
  "routing_duration_ms": 45,
  "cache_hit": false,
  "candidates_evaluated": 5,
  "created_at": "2025-10-21T10:00:00Z"
}
```

## Example Workflow

When the polymorphic agent completes routing:

1. Analyze user request and measure routing time
2. Select best agent (or retrieve from cache)
3. **Call this skill** to log performance metrics
4. Execute as the selected agent
5. The logged metrics enable:
   - Performance trend analysis
   - Cache effectiveness tracking
   - Routing optimization opportunities
   - Performance degradation detection

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

Logged metrics are:
- Used for performance monitoring dashboards
- Analyzed for routing optimization opportunities
- Tracked for cache hit rate analysis
- Queryable for performance debugging and trends

## Performance Characteristics

| Version | Publish Latency | Blocking | Fault Tolerance | Scalability |
|---------|----------------|----------|-----------------|-------------|
| Kafka | <5ms | Non-blocking | High | Horizontal |
| Direct DB | 20-100ms | Blocking | Low | Vertical |

**Recommendation**: Use Kafka version for production, Direct DB for local development.

## Performance Targets

Target performance metrics:
- Routing duration: <100ms (target)
- Cache hit rate: >60% (target)
- Candidates evaluated: 3-5 typical range
- Performance compliance: >95% of routes within target

## Notes

- Always include correlation_id for traceability across logs
- Log AFTER routing decision completes (success or fallback)
- Duration constraint: 0-999ms (validates against schema constraint)
- Failures are non-blocking (observability shouldn't break workflows)
- Cache hit tracking helps optimize routing performance
- Confidence components are optional but useful for analysis
- **Multiple Consumers**: Kafka version enables parallel consumption (DB + analytics + alerts)
- **Event Replay**: Kafka version provides complete audit trail with time-travel debugging
