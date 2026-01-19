# Provider Selection Event Integration Guide

**Event**: `omninode.agent.provider.selected.v1`
**Status**: ✅ Implemented
**Linear Ticket**: OMN-32
**Created**: 2025-11-13

## Overview

The `omninode.agent.provider.selected.v1` event tracks AI provider and model selection decisions, enabling analysis of provider usage patterns, cost optimization, and model performance tracking.

## Event Schema

```json
{
  "event_type": "omninode.agent.provider.selected.v1",
  "event_id": "uuid-v4",
  "timestamp": "2025-11-13T14:30:00Z",
  "correlation_id": "uuid-v7",
  "namespace": "omninode",
  "source": "omniclaude",
  "tenant_id": "default",
  "schema_ref": "registry://omninode/agent/provider_selected/v1",
  "payload": {
    "provider_name": "gemini-flash",
    "model_name": "gemini-1.5-flash-002",
    "correlation_id": "correlation-id-here",
    "selection_reason": "Cost-effective for high-volume pattern matching",
    "selection_criteria": {
      "cost_per_token": 0.000001,
      "latency_ms": 50,
      "quality_score": 0.85
    },
    "selected_at": "2025-11-13T14:30:00Z"
  }
}
```

## Partition Key Policy

- **Partition Key**: `correlation_id`
- **Reason**: Track provider/model choices per request
- **Cardinality**: Medium (per agent execution, ~100-1000 unique keys/day)
- **Event Family**: `AGENT_PROVIDER`

All provider selection events with the same `correlation_id` land on the same Kafka partition, ensuring ordering.

## Integration Points

### 1. Python Code Integration

For programmatic integration in Python code:

```python
from agents.lib.provider_selection_publisher import publish_provider_selection

# Async context
await publish_provider_selection(
    provider_name="gemini-flash",
    model_name="gemini-1.5-flash-002",
    correlation_id=correlation_id,
    selection_reason="Cost-effective for high-volume pattern matching",
    selection_criteria={
        "cost_per_token": 0.000001,
        "latency_ms": 50,
        "quality_score": 0.85
    }
)

# Synchronous context (e.g., hooks, scripts)
from agents.lib.provider_selection_publisher import publish_provider_selection_sync

publish_provider_selection_sync(
    provider_name="claude",
    model_name="claude-3-5-sonnet-20241022",
    correlation_id=correlation_id,
    selection_reason="High quality",
    selection_criteria={}
)
```

### 2. Shell Script Integration

For bash scripts like `toggle-claude-provider.sh`:

```bash
#!/bin/bash

# After successfully switching provider:
PROVIDER_NAME="gemini-flash"
MODEL_NAME="gemini-1.5-flash-002"
SELECTION_REASON="User requested switch to Gemini Flash"

# Publish provider selection event (non-blocking, failure won't stop script)
python3 scripts/publish_provider_selection.py \
    --provider "$PROVIDER_NAME" \
    --model "$MODEL_NAME" \
    --reason "$SELECTION_REASON" \
    --criteria '{"cost_per_token": 0.000001, "latency_ms": 50}' \
    || true  # Don't fail script if event publish fails
```

### 3. Claude Hooks Integration

For integration in `~/.claude/hooks/`:

```python
# In UserPromptSubmit or similar hook
from agents.lib.provider_selection_publisher import publish_provider_selection_sync

def on_provider_selected(provider_name: str, model_name: str, correlation_id: str):
    """Called when a provider/model is selected."""
    publish_provider_selection_sync(
        provider_name=provider_name,
        model_name=model_name,
        correlation_id=correlation_id,
        selection_reason="Hook-based provider selection",
        selection_criteria={}
    )
```

## CLI Tool

### Basic Usage

```bash
# Simple provider selection
python3 scripts/publish_provider_selection.py \
    --provider gemini-flash \
    --model gemini-1.5-flash-002 \
    --reason "Cost-effective for pattern matching"

# With selection criteria
python3 scripts/publish_provider_selection.py \
    --provider claude \
    --model claude-3-5-sonnet-20241022 \
    --reason "High quality" \
    --criteria '{"quality_score": 0.95, "cost_per_token": 0.003}'

# With correlation ID (for request tracking)
python3 scripts/publish_provider_selection.py \
    --provider openai \
    --model gpt-4 \
    --reason "Testing" \
    --correlation-id abc-123-def-456
```

### Integration Example: toggle-claude-provider.sh

Add event publishing to each provider switch function:

```bash
# In switch_to_gemini_flash() function (after successful switch):
switch_to_gemini_flash() {
    echo -e "${YELLOW}Switching to Google Gemini Flash models...${NC}"

    # ... existing switch logic ...

    # Publish provider selection event
    python3 scripts/publish_provider_selection.py \
        --provider "gemini-flash" \
        --model "gemini-1.5-flash-002" \
        --reason "User requested switch to Gemini Flash" \
        --criteria '{"cost_per_token": 0.000001, "latency_ms": 50, "quality_score": 0.85}' \
        --quiet || true  # Non-blocking, don't fail script

    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Similarly for other switch functions:
# - switch_to_claude()
# - switch_to_zai()
# - switch_to_together()
# - switch_to_openrouter()
# - switch_to_gemini_pro()
# - switch_to_gemini_2_5_flash()
```

## Event Consumer

Events are published to Kafka topic `omninode.agent.provider.selected.v1` and can be consumed for:

1. **Usage Analytics**: Track provider/model usage patterns
2. **Cost Analysis**: Calculate cost per provider/model over time
3. **Performance Monitoring**: Correlate provider choices with latency/quality
4. **Optimization**: Identify opportunities for cost savings or performance improvements

### Consumer Example

```python
from aiokafka import AIOKafkaConsumer
import json

async def consume_provider_selection_events():
    """Consume and process provider selection events."""
    consumer = AIOKafkaConsumer(
        'omninode.agent.provider.selected.v1',
        bootstrap_servers='localhost:29092',
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )

    await consumer.start()
    try:
        async for message in consumer:
            event = message.value
            payload = event['payload']

            # Process event
            print(f"Provider selected: {payload['provider_name']}")
            print(f"Model: {payload['model_name']}")
            print(f"Reason: {payload['selection_reason']}")
            print(f"Criteria: {payload['selection_criteria']}")

            # Store in database, update analytics, etc.

    finally:
        await consumer.stop()
```

## Testing

### Unit Tests

Run comprehensive test suite:

```bash
pytest agents/tests/test_provider_selection_publisher.py -v
```

Tests cover:
- Event envelope structure (OnexEnvelopeV1 format)
- Partition key policy compliance
- Kafka publishing (success and error cases)
- Graceful degradation (when Kafka unavailable)
- Payload schema validation
- Synchronous wrapper functionality

### Manual Testing

```bash
# Test CLI tool
python3 scripts/publish_provider_selection.py \
    --provider test-provider \
    --model test-model \
    --reason "Manual test" \
    --verbose

# Verify event in Kafka
kcat -C -b localhost:29092 -t omninode.agent.provider.selected.v1 -o end
```

## Database Schema

Provider selection events can be logged to PostgreSQL for persistence:

```sql
CREATE TABLE provider_selection_events (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    correlation_id UUID NOT NULL,
    provider_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(200) NOT NULL,
    selection_reason TEXT,
    selection_criteria JSONB,
    selected_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes
    INDEX idx_correlation_id (correlation_id),
    INDEX idx_provider_name (provider_name),
    INDEX idx_selected_at (selected_at DESC)
);
```

## Monitoring

### Metrics

Track provider selection metrics:

```python
from prometheus_client import Counter, Histogram

provider_selection_count = Counter(
    'provider_selection_total',
    'Total provider selections',
    ['provider', 'model']
)

provider_selection_duration = Histogram(
    'provider_selection_duration_seconds',
    'Provider selection event publish duration',
    ['provider']
)
```

### Grafana Dashboard

Create dashboard with:
- Provider selection frequency (time series)
- Model distribution (pie chart)
- Selection criteria trends (cost, latency, quality)
- Correlation with request latency/errors

## Troubleshooting

### Event Not Published

**Issue**: `publish_provider_selection` returns `False`

**Causes**:
1. Kafka broker unavailable → Check `KAFKA_BOOTSTRAP_SERVERS` in `.env`
2. Network connectivity → Test with `kcat -L -b localhost:29092`
3. Missing environment variable → Verify `KAFKA_BOOTSTRAP_SERVERS` is set

**Solution**:
```bash
# Check Kafka connectivity
kcat -L -b localhost:29092

# Verify environment
source .env
echo "KAFKA_BOOTSTRAP_SERVERS: ${KAFKA_BOOTSTRAP_SERVERS}"

# Test producer manually
python3 -c "from agents.lib.provider_selection_publisher import publish_provider_selection_sync; print(publish_provider_selection_sync('test', 'test', 'abc-123', 'test'))"
```

### Partition Key Not Found

**Issue**: Warning about missing partition key

**Cause**: `correlation_id` not in event envelope or payload

**Solution**: Ensure `correlation_id` is passed to publisher:
```python
# Always provide correlation_id
await publish_provider_selection(
    provider_name="...",
    model_name="...",
    correlation_id=correlation_id,  # Required!
    selection_reason="...",
    selection_criteria={}
)
```

## References

- **Linear Ticket**: [OMN-32](https://linear.app/omninode/issue/OMN-32)
- **Event Alignment Plan**: `docs/events/EVENT_ALIGNMENT_PLAN.md` lines 251-269
- **Partition Key Policy**: `agents/lib/partition_key_policy.py`
- **Event Validation**: `agents/lib/event_validation.py`
- **Publisher Implementation**: `agents/lib/provider_selection_publisher.py`
- **CLI Tool**: `scripts/publish_provider_selection.py`
- **Tests**: `agents/tests/test_provider_selection_publisher.py`

## Changelog

### 2025-11-13 - Initial Implementation (OMN-32)
- ✅ Created `provider_selection_publisher.py` with async/sync publishing
- ✅ Added `AGENT_PROVIDER` event family to partition key policy
- ✅ Created CLI tool `publish_provider_selection.py`
- ✅ Added comprehensive test suite (16 tests, 100% pass rate)
- ✅ Documented integration patterns for Python, shell, and hooks
- ✅ Created integration guide with examples
