# Transformation Event Logging - Quick Start Guide

**Status**: ✅ Production Ready
**Date**: 2025-11-06

## TL;DR

Transformation events are now automatically logged to Kafka and PostgreSQL. Use the new `transform_with_logging()` method instead of `transform()` for full observability.

## Quick Start (30 seconds)

### 1. Use the New API

**Before** (no logging):
```python
from agents.lib.agent_transformer import AgentTransformer

transformer = AgentTransformer()
prompt = transformer.transform("agent-api-architect")
```

**After** (with logging) - **RECOMMENDED**:
```python
from agents.lib.agent_transformer import AgentTransformer

transformer = AgentTransformer()
prompt = await transformer.transform_with_logging(
    agent_name="agent-api-architect",
    source_agent="polymorphic-agent",
    transformation_reason="API design task",
    correlation_id=correlation_id,  # For tracing
    routing_confidence=0.92
)
```

### 2. Test It Works

```bash
# Load environment
source .env

# Run test suite (30 seconds)
python tests/test_transformation_event_logging.py

# Should see: ✓ ALL TESTS PASSED
```

### 3. Query Events

```bash
source .env

# See recent transformations
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
  -c "SELECT source_agent, target_agent, transformation_reason, success, created_at
      FROM agent_transformation_events
      ORDER BY created_at DESC
      LIMIT 10;"
```

## What Gets Logged

Every transformation now captures:

**Required**:
- `source_agent` - Original agent (e.g., "polymorphic-agent")
- `target_agent` - Transformed agent (e.g., "agent-api-architect")
- `transformation_reason` - Why transformation occurred
- `correlation_id` - For distributed tracing

**Optional but Recommended**:
- `user_request` - Original user request
- `routing_confidence` - Router confidence score (0.0-1.0)
- `routing_strategy` - How agent was selected
- `transformation_duration_ms` - Performance tracking

**Automatic**:
- `event_type` - transformation_start/complete/failed
- `success` - Boolean success flag
- `started_at` - Timestamp

## API Reference

### Async Methods (Recommended)

```python
# Complete transformation
await publish_transformation_complete(
    source_agent="polymorphic-agent",
    target_agent="agent-api-architect",
    transformation_reason="API design task",
    correlation_id=correlation_id,
    routing_confidence=0.92,
    transformation_duration_ms=45
)

# Failed transformation
await publish_transformation_failed(
    source_agent="polymorphic-agent",
    target_agent="agent-nonexistent",
    transformation_reason="Attempted unknown agent",
    error_message="Agent not found",
    correlation_id=correlation_id
)

# Start transformation (optional)
await publish_transformation_start(
    source_agent="polymorphic-agent",
    target_agent="agent-api-architect",
    transformation_reason="Beginning transformation",
    correlation_id=correlation_id
)
```

### AgentTransformer Methods

```python
from agents.lib.agent_transformer import AgentTransformer

transformer = AgentTransformer()

# Async version (recommended)
prompt = await transformer.transform_with_logging(
    agent_name="agent-api-architect",
    source_agent="polymorphic-agent",
    transformation_reason="API design",
    correlation_id=correlation_id,
    user_request="Design REST API",
    routing_confidence=0.92,
    routing_strategy="fuzzy_match"
)

# Sync version (backward compatible)
prompt = transformer.transform_sync_with_logging(
    agent_name="agent-api-architect",
    source_agent="polymorphic-agent",
    transformation_reason="API design",
    correlation_id=correlation_id
)

# Old method (still works, but no logging)
prompt = transformer.transform("agent-api-architect")
```

## Key Metrics

### Self-Transformation Rate
**Target**: 0% (routing should always be used)

```sql
SELECT
    COUNT(*) FILTER (WHERE source_agent = target_agent) AS self_transformations,
    COUNT(*) AS total_transformations,
    ROUND(
        COUNT(*) FILTER (WHERE source_agent = target_agent)::DECIMAL /
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS self_transformation_rate_pct
FROM agent_transformation_events
WHERE created_at >= NOW() - INTERVAL '24 hours';
```

### Transformation Success Rate
```sql
SELECT
    COUNT(*) FILTER (WHERE success = true) AS successful,
    COUNT(*) FILTER (WHERE success = false) AS failed
FROM agent_transformation_events
WHERE created_at >= NOW() - INTERVAL '24 hours';
```

### Most Common Transformations
```sql
SELECT source_agent, target_agent, COUNT(*) AS count
FROM agent_transformation_events
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY source_agent, target_agent
ORDER BY count DESC
LIMIT 10;
```

## Troubleshooting

### No events appearing?

**1. Check consumer is running**:
```bash
ps aux | grep agent_actions_consumer
docker ps | grep agent-actions-consumer
```

**2. Check Kafka connectivity**:
```bash
docker exec omninode-bridge-redpanda rpk topic list | grep transformation
docker exec omninode-bridge-redpanda rpk topic consume agent-transformation-events --num 5
```

**3. Check database**:
```bash
source .env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE \
  -c "SELECT COUNT(*) FROM agent_transformation_events;"
```

### Events in Kafka but not database?

**Check consumer logs**:
```bash
docker logs -f <consumer-container> 2>&1 | grep transformation
```

**Common issues**:
- Consumer not subscribed to `agent-transformation-events` topic
- Database credentials incorrect
- Schema mismatch (run migration: `002_create_agent_transformation_events.sql`)

### Import errors?

**Install dependencies**:
```bash
pip install aiokafka
```

## Performance Impact

- **Kafka Publishing**: ~1-5ms (async, non-blocking)
- **Transformation Overhead**: <50ms
- **Impact on Agent**: <5% overhead

**Result**: Negligible impact on agent performance.

## Files

**Publisher**: `agents/lib/transformation_event_publisher.py`
**Transformer**: `agents/lib/agent_transformer.py`
**Consumer**: `consumers/agent_actions_consumer.py`
**Tests**: `tests/test_transformation_event_logging.py`
**Docs**: `docs/transformation-event-logging.md` (detailed guide)

## Example: Full Integration

```python
import asyncio
from uuid import uuid4
from agents.lib.agent_router import EnhancedRouter
from agents.lib.agent_transformer import AgentTransformer

async def execute_with_observability(user_request: str):
    """Complete workflow with full observability."""

    # Generate correlation ID
    correlation_id = str(uuid4())

    # 1. Route request
    router = EnhancedRouter()
    routing_result = await router.route(user_request)

    # 2. Transform with logging
    transformer = AgentTransformer()
    transformation_prompt = await transformer.transform_with_logging(
        agent_name=routing_result.selected_agent,
        source_agent="polymorphic-agent",
        transformation_reason=f"Routing selected {routing_result.selected_agent}",
        correlation_id=correlation_id,
        user_request=user_request,
        routing_confidence=routing_result.confidence_score,
        routing_strategy=routing_result.strategy,
    )

    # 3. Execute agent (transformation logged automatically)
    # ... agent execution logic ...

    return transformation_prompt

# Run
asyncio.run(execute_with_observability("Design a REST API"))
```

## Success Indicators

✅ Test suite passes: `python tests/test_transformation_event_logging.py`
✅ Events in Kafka: `docker exec omninode-bridge-redpanda rpk topic consume agent-transformation-events --num 1`
✅ Events in database: `SELECT COUNT(*) FROM agent_transformation_events;`
✅ Self-transformation rate = 0%: `SELECT COUNT(*) FROM agent_transformation_events WHERE source_agent = target_agent;`

## Need Help?

- **Full Documentation**: `docs/transformation-event-logging.md`
- **Implementation Summary**: `TRANSFORMATION_EVENT_LOGGING_COMPLETE.md`
- **Test Script**: `tests/test_transformation_event_logging.py`
- **Data Flow Analysis**: `docs/observability/DATA_FLOW_ANALYSIS.md`

---

**Status**: Production Ready
**Last Updated**: 2025-11-06
**Quick Start Time**: ~30 seconds
