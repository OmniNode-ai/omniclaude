# Kafka Topic: `documentation-changed`

**Status**: Optional - Auto-created on first publish
**Created**: 2025-11-10
**Correlation ID**: 54548c78-2fcf-481a-8654-a55d8eb58ce8

---

## Overview

The `documentation-changed` topic is an **optional** Kafka topic designed to notify services when documentation files (CLAUDE.md, README.md, etc.) are modified. Unlike critical infrastructure topics, this topic does not need to be pre-created and will be automatically created by Kafka when the first documentation change event is published.

## Current Status

**Topic Existence**: Not yet created
**Reason**: No documentation change events have been published yet
**Creation Strategy**: Auto-creation on first publish (Kafka default behavior)

## Configuration

### Topic Properties

| Property | Value | Notes |
|----------|-------|-------|
| **Partitions** | 1 | Low volume, ordering not critical |
| **Retention** | 30 days | `2592000000` ms |
| **Replication Factor** | 3 | Fault tolerance |
| **Compression** | snappy | Default cluster setting |
| **Min In-Sync Replicas** | 2 | Data durability |

### Auto-Creation

Kafka/Redpanda clusters are typically configured with `auto.create.topics.enable=true`, which means:

1. **First Publish**: When a producer publishes to `documentation-changed`, Kafka automatically creates the topic
2. **Default Settings**: Topic is created with cluster default settings
3. **No Manual Action Required**: No administrative action needed unless custom settings are desired

### Manual Creation (Optional)

If you want to create the topic manually with custom configuration:

```bash
# Connect to Kafka broker
docker exec omninode-bridge-redpanda rpk topic create documentation-changed \
  --partitions 1 \
  --replicas 3 \
  --topic-config retention.ms=2592000000 \
  --topic-config compression.type=snappy \
  --topic-config min.insync.replicas=2

# Or using kafka-topics command
kafka-topics --create \
    --bootstrap-server 192.168.86.200:29092 \
    --topic documentation-changed \
    --partitions 1 \
    --replication-factor 3 \
    --config retention.ms=2592000000 \
    --config compression.type=snappy \
    --config min.insync.replicas=2
```

## Event Schema

### Example Event

```json
{
  "event_id": "8f4d2a1e-9c3b-4f5a-8d2e-1a3b4c5d6e7f",
  "correlation_id": "54548c78-2fcf-481a-8654-a55d8eb58ce8",
  "file_path": "CLAUDE.md",
  "change_type": "modified",
  "repository": "omniclaude",
  "changed_sections": [
    "Environment Configuration",
    "Type-Safe Configuration Framework"
  ],
  "summary": "Added type-safe configuration framework documentation",
  "affected_services": [
    "archon-intelligence",
    "agent-router-service"
  ],
  "change_metadata": {
    "author": "polymorphic-agent",
    "lines_added": 150,
    "lines_removed": 20
  },
  "timestamp": "2025-11-10T13:24:26Z"
}
```

### Schema Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | UUID | Yes | Unique event identifier |
| `correlation_id` | UUID | Yes | Request correlation ID |
| `file_path` | String | Yes | Path to documentation file |
| `change_type` | Enum | Yes | `created`, `modified`, or `deleted` |
| `repository` | String | Yes | Repository name (e.g., `omniclaude`) |
| `changed_sections` | Array[String] | No | List of section headings changed |
| `summary` | String | Yes | Brief description of changes |
| `affected_services` | Array[String] | No | Services that may be affected |
| `change_metadata` | Object | No | Additional metadata (author, stats, etc.) |
| `timestamp` | ISO 8601 | Yes | Event timestamp (UTC) |

## Use Cases

### Planned Consumers

1. **Documentation Indexer** (`doc-indexer-group`)
   - Updates documentation search indexes (Qdrant)
   - Refreshes context available to agents
   - Enables "what changed recently" queries

2. **Notification Service** (`notification-group`)
   - Sends alerts to relevant teams
   - Notifies affected service owners
   - Updates status dashboards

3. **Intelligence Service** (`intelligence-group`)
   - Updates manifest injector with new patterns
   - Refreshes agent capabilities documentation
   - Indexes new architectural conventions

### Example Producer

```python
from kafka import KafkaProducer
import json
import uuid
from datetime import datetime

def publish_documentation_change(
    file_path: str,
    change_type: str,
    repository: str,
    summary: str,
    changed_sections: list = None,
    affected_services: list = None
):
    """Publish documentation change event to Kafka."""

    producer = KafkaProducer(
        bootstrap_servers=['192.168.86.200:29092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all',
        retries=3
    )

    event = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "file_path": file_path,
        "change_type": change_type,
        "repository": repository,
        "changed_sections": changed_sections or [],
        "summary": summary,
        "affected_services": affected_services or [],
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }

    # Publish to topic (will auto-create if doesn't exist)
    producer.send('documentation-changed', value=event)
    producer.flush()
    producer.close()

    print(f"✅ Published documentation change event for {file_path}")

# Example usage
publish_documentation_change(
    file_path="CLAUDE.md",
    change_type="modified",
    repository="omniclaude",
    summary="Added type-safe configuration framework documentation",
    changed_sections=["Environment Configuration", "Type-Safe Configuration Framework"],
    affected_services=["archon-intelligence", "agent-router-service"]
)
```

## Testing

### Functional Test Status

The `documentation-changed` topic is now correctly marked as **optional** in the Kafka functional test:

```bash
./scripts/tests/test_kafka_functionality.sh
```

**Test Output**:
```
TEST 5: Topic Verification
-----------------------------------
Critical Topics:
✅ agent-actions
✅ agent.routing.requested.v1
✅ agent.routing.completed.v1
✅ agent.routing.failed.v1
✅ dev.archon-intelligence.intelligence.code-analysis-requested.v1
✅ dev.archon-intelligence.intelligence.code-analysis-completed.v1
✅ dev.archon-intelligence.intelligence.code-analysis-failed.v1
✅ agent-transformation-events
✅ router-performance-metrics

Optional Topics (auto-created on first use):
  documentation-changed (not yet created - will auto-create on first publish)
```

**Result**: ✅ All 15 tests pass without warnings

### Manual Verification

Check if topic exists:

```bash
# List all topics
kcat -L -b 192.168.86.200:29092 | grep documentation-changed

# Or using rpk
docker exec omninode-bridge-redpanda rpk topic list | grep documentation-changed
```

**Expected**: No output (topic doesn't exist yet - this is correct!)

## Integration

### Updated Documentation

The following files have been updated to document the `documentation-changed` topic:

1. **`scripts/tests/test_kafka_functionality.sh`**
   - Moved `documentation-changed` from critical to optional topics list
   - Updated test output to show optional status

2. **`docs/KAFKA_INTEGRATION.md`**
   - Added section **9. `documentation-changed` Topic**
   - Documented schema, partitioning, consumers, and creation strategy
   - Added example producer code
   - Updated topic creation script with commented-out optional topic

3. **`CLAUDE.md`**
   - Updated Kafka Configuration section to note topic is optional
   - Updated Event Bus Architecture section with optional notation

## Summary

### What Changed

✅ **Test Updated**: `documentation-changed` moved from critical to optional topics
✅ **Documentation Added**: Complete topic specification in KAFKA_INTEGRATION.md
✅ **CLAUDE.md Updated**: References now indicate optional auto-creation
✅ **Tests Pass**: All 15 Kafka functional tests pass without warnings

### Why This Approach

1. **Auto-creation is standard**: Kafka/Redpanda typically auto-creates topics on first publish
2. **Low volume**: Documentation changes are infrequent, don't need pre-allocation
3. **Non-critical**: System works fine without this topic existing
4. **Future-ready**: When documentation change events are implemented, topic will be created automatically

### Next Steps

**No action required** until documentation change tracking is implemented. When ready:

1. Implement documentation change detection (git hooks, file watchers, etc.)
2. Publish first event using example producer code
3. Topic will be auto-created with default cluster settings
4. Implement consumer services as needed (indexer, notifier, intelligence)

---

**Document Version**: 1.0.0
**Last Updated**: 2025-11-10
**Status**: Complete - No blocking issues
