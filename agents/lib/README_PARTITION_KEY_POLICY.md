# Partition Key Policy for OmniClaude Events

**Module**: `agents/lib/partition_key_policy.py`
**Created**: 2025-11-13
**Reference**: EVENT_BUS_INTEGRATION_GUIDE.md Section "Partition Key Policy"

## Overview

The partition key policy module enforces consistent partition key strategies for all omniclaude events published to Kafka. This ensures:

- **Ordering guarantees** - Related events maintain temporal order within partitions
- **Event co-location** - Events from the same workflow stay together
- **Documented cardinality** - Partition key cardinality is tracked and documented
- **Consistent extraction** - Standardized partition key extraction across event families

## Event Families

OmniClaude defines 5 event families, each with its own partition key strategy:

| Event Family | Partition Key | Reason | Cardinality |
|--------------|---------------|--------|-------------|
| **agent.routing** | `correlation_id` | Preserve request→result ordering | Medium (~100-1000/day) |
| **agent.transformation** | `correlation_id` | Workflow coherence across transformations | Medium (~50-500/day) |
| **agent.actions** | `correlation_id` | Execution lifecycle ordering | Medium (~200-2000/day) |
| **intelligence.query** | `correlation_id` | Query request→response ordering | Medium (~50-500/day) |
| **quality.gate** | `correlation_id` | Gate evaluation ordering | Low (~10-100/day) |

### Why correlation_id?

All event families use `correlation_id` as the partition key because:

1. **Request-response pairing** - Requests and responses land on the same partition
2. **Workflow coherence** - All events in a workflow execution stay together
3. **Temporal ordering** - Events maintain their temporal sequence
4. **Distributed tracing** - Enables tracing across services and event families

## Usage

### Basic Usage

```python
from agents.lib.partition_key_policy import (
    get_event_family,
    get_partition_key_for_event,
    validate_partition_key,
)

# Create event envelope
correlation_id = str(uuid4())
event_type = "agent-actions"
envelope = {
    "correlation_id": correlation_id,
    "agent_name": "agent-researcher",
    "action_type": "tool_call",
}

# Extract partition key
partition_key = get_partition_key_for_event(event_type, envelope)
# Returns: correlation_id value

# Validate partition key
is_valid = validate_partition_key(event_type, partition_key)
# Returns: True
```

### Kafka Producer Integration

```python
from aiokafka import AIOKafkaProducer
from agents.lib.partition_key_policy import get_partition_key_for_event

# Create event
event = {
    "correlation_id": correlation_id,
    "agent_name": "agent-researcher",
    "action_type": "tool_call",
}

# Extract partition key
partition_key = get_partition_key_for_event("agent-actions", event)

# Publish to Kafka with partition key
await producer.send_and_wait(
    topic="agent-actions",
    value=event,
    key=partition_key.encode('utf-8')  # Kafka expects bytes
)
```

### Policy Retrieval

```python
from agents.lib.partition_key_policy import (
    EventFamily,
    get_partition_policy,
    get_policy_summary,
)

# Get policy for specific family
policy = get_partition_policy(EventFamily.AGENT_ROUTING)
print(policy["partition_key"])  # "correlation_id"
print(policy["reason"])         # "Preserve request→result ordering..."

# Get complete policy summary
summary = get_policy_summary()
for family_name, policy in summary.items():
    print(f"{family_name}: {policy['partition_key']}")
```

## API Reference

### Functions

#### `get_event_family(event_type: str) -> Optional[EventFamily]`

Extract event family from event type string.

**Supported formats**:
- Full qualified: `"omninode.agent.routing.requested.v1"`
- Short form: `"agent.routing.requested.v1"`
- Topic name: `"agent-transformation-events"`

**Returns**: `EventFamily` enum or `None` if not recognized

**Example**:
```python
family = get_event_family("agent-actions")
# Returns: EventFamily.AGENT_ACTIONS
```

---

#### `get_partition_key_for_event(event_type: str, envelope: Union[Dict, Any]) -> Optional[str]`

Extract partition key from event envelope based on policy.

**Args**:
- `event_type`: Event type or topic name
- `envelope`: Event envelope (dict or Pydantic model)

**Returns**: Partition key value (as string) or `None`

**Example**:
```python
envelope = {"correlation_id": "abc-123", "payload": {...}}
key = get_partition_key_for_event("agent-actions", envelope)
# Returns: "abc-123"
```

---

#### `validate_partition_key(event_type: str, partition_key: Optional[str]) -> bool`

Validate partition key is valid and follows policy.

**Checks**:
- Partition key is not None or empty
- Event type has recognized family
- Partition key is non-empty string

**Returns**: `True` if valid, `False` otherwise

**Example**:
```python
is_valid = validate_partition_key("agent-actions", "abc-123")
# Returns: True
```

---

#### `get_partition_policy(event_family: EventFamily) -> Dict[str, str]`

Get partition policy details for an event family.

**Returns**: Dict with `partition_key`, `reason`, `cardinality`, `example`

**Example**:
```python
policy = get_partition_policy(EventFamily.AGENT_ROUTING)
print(policy["reason"])
# Prints: "Preserve request→result ordering for routing decisions"
```

---

#### `get_all_event_families() -> list[EventFamily]`

Get all defined event families.

**Returns**: List of all `EventFamily` enum values

---

#### `get_policy_summary() -> Dict[str, Dict[str, str]]`

Get complete partition key policy summary for all families.

**Returns**: Dict mapping event family names to their policies

---

### Enums

#### `EventFamily`

Event family classifications:

```python
class EventFamily(str, Enum):
    AGENT_ROUTING = "agent.routing"
    AGENT_TRANSFORMATION = "agent.transformation"
    AGENT_ACTIONS = "agent.actions"
    INTELLIGENCE_QUERY = "intelligence.query"
    QUALITY_GATE = "quality.gate"
```

### Constants

```python
# Default partition key field used by all families
DEFAULT_PARTITION_KEY_FIELD = "correlation_id"

# List of valid event family values
VALID_EVENT_FAMILIES = [
    "agent.routing",
    "agent.transformation",
    "agent.actions",
    "intelligence.query",
    "quality.gate"
]
```

## Event Type Mapping

### Agent Routing

**Event Types**:
- `omninode.agent.routing.requested.v1`
- `omninode.agent.routing.completed.v1`
- `omninode.agent.routing.failed.v1`

**Topics**: `omninode.agent.routing.*`

**Partition Key**: `correlation_id`

**Use Case**: Ensure routing request and response land on same partition for request-response ordering.

---

### Agent Transformation

**Event Types**:
- `agent-transformation-events` (topic name)

**Topics**: `agent-transformation-events`

**Partition Key**: `correlation_id`

**Use Case**: Keep all transformation events from same workflow together (polymorphic→specialized→base).

---

### Agent Actions

**Event Types**:
- `agent-actions` (topic name)

**Topics**: `agent-actions`

**Partition Key**: `correlation_id`

**Use Case**: Maintain temporal order of tool calls, decisions, errors within agent execution.

---

### Intelligence Query

**Event Types**:
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1`

**Topics**: `dev.archon-intelligence.intelligence.*`

**Partition Key**: `correlation_id`

**Use Case**: Pair intelligence queries with their results for pattern discovery and manifest injection.

---

### Quality Gate

**Event Types**:
- `omninode.quality.gate.evaluation.v1` (planned)

**Topics**: `quality.gate.*`

**Partition Key**: `correlation_id`

**Use Case**: Maintain ordering of sequential quality checks in validation session.

## Testing

### Unit Tests

**Location**: `agents/tests/lib/test_partition_key_policy.py`

**Coverage**: 35 unit tests covering:
- Event family extraction (10 tests)
- Partition key extraction (8 tests)
- Partition key validation (6 tests)
- Policy retrieval (3 tests)
- Policy table structure (3 tests)
- Module constants (2 tests)
- Edge cases (3 tests)

**Run tests**:
```bash
python -m pytest agents/tests/lib/test_partition_key_policy.py -v
```

### Integration Tests

**Location**: `agents/tests/lib/test_partition_key_policy_integration.py`

**Coverage**: 10 integration tests with actual event structures:
- Routing events (4 tests - skipped if schemas unavailable)
- Action events (1 test)
- Transformation events (1 test)
- Intelligence query events (2 tests)
- Quality gate events (1 test)
- Cross-event consistency (1 test)

**Run tests**:
```bash
python -m pytest agents/tests/lib/test_partition_key_policy_integration.py -v
```

### Example Script

**Location**: `agents/lib/partition_key_policy_example.py`

**Run examples**:
```bash
cd agents/lib
python partition_key_policy_example.py
```

**Demonstrates**:
- Basic usage for all event families
- Kafka producer integration
- Policy summary retrieval
- Cross-event ordering guarantees

## Design Principles

### 1. Consistency Across Event Families

All event families use `correlation_id` as partition key for consistency. This simplifies:
- Client code (single field to track)
- Debugging (same key used everywhere)
- Documentation (single strategy to understand)

### 2. Request-Response Ordering

Using `correlation_id` guarantees that:
- Request events and their response events land on the same partition
- Consumer sees events in temporal order
- No race conditions in processing request→response pairs

### 3. Workflow Coherence

All events from the same workflow execution (same `correlation_id`) stay together:
- Routing request → Transformation → Action → Quality gate
- Enables sequential processing of workflow events
- Simplifies distributed tracing and debugging

### 4. Cardinality Tracking

Each event family documents expected cardinality:
- **Low** (10-100/day): Quality gates
- **Medium** (50-2000/day): Routing, transformations, actions, intelligence queries
- **High** (>2000/day): Not currently used

This helps with:
- Partition count planning
- Performance monitoring
- Capacity planning

### 5. Graceful Degradation

Functions return `None` or `False` for unrecognized events:
- No exceptions raised
- Logging warnings for debugging
- Allows system to continue operating

## Performance Considerations

### Partition Key Extraction

- **Time Complexity**: O(1) - Dict/object attribute lookup
- **Space Complexity**: O(1) - Returns string reference
- **Overhead**: <1ms per event

### Event Family Detection

- **Time Complexity**: O(n) where n is number of parts in event type (typically 3-5)
- **Space Complexity**: O(1)
- **Overhead**: <1ms per event

### Policy Lookup

- **Time Complexity**: O(1) - Dict lookup
- **Space Complexity**: O(1)
- **Overhead**: <0.1ms per event

## Future Enhancements

### Potential Additions

1. **Custom partition strategies** - Support event families with different partition key fields
2. **Cardinality monitoring** - Track actual cardinality vs documented expectations
3. **Partition count recommendations** - Suggest partition counts based on cardinality
4. **Hot partition detection** - Identify partition keys causing skew
5. **Policy validation on startup** - Ensure all event types have policies defined

### Extensibility

To add a new event family:

1. Add enum value to `EventFamily`
2. Add entry to `PARTITION_KEY_POLICY` table
3. Update `get_event_family()` logic if needed
4. Add tests for new family
5. Update documentation

**Example**:
```python
class EventFamily(str, Enum):
    # ... existing families ...
    NEW_FAMILY = "new.family"

PARTITION_KEY_POLICY[EventFamily.NEW_FAMILY] = {
    "partition_key": "correlation_id",
    "reason": "Why this partition key is used",
    "cardinality": "Expected cardinality",
    "example": "Example event type and usage"
}
```

## Troubleshooting

### Issue: Partition key returns None

**Causes**:
- Event type not recognized by `get_event_family()`
- `correlation_id` field missing from envelope
- Envelope structure doesn't match expected format

**Solutions**:
1. Check event type matches documented formats
2. Ensure `correlation_id` is at top level or in `payload`
3. Verify envelope is dict or has `correlation_id` attribute

---

### Issue: Validation fails

**Causes**:
- Partition key is None or empty string
- Event type not recognized
- Partition key is not a string

**Solutions**:
1. Ensure `correlation_id` is set and non-empty
2. Check event type against `VALID_EVENT_FAMILIES`
3. Convert partition key to string if needed

---

### Issue: Events out of order despite same correlation_id

**Causes**:
- Kafka producer not using partition key
- Partition key encoding issues
- Multiple Kafka topics (different partition spaces)

**Solutions**:
1. Ensure `key` parameter is passed to `producer.send_and_wait()`
2. Encode partition key as bytes: `key=partition_key.encode('utf-8')`
3. Remember: ordering only guaranteed within same topic

## References

- **EVENT_BUS_INTEGRATION_GUIDE.md** - Comprehensive event bus integration guide
- **omninode_bridge/partition_key_policy.py** - Similar module for omninode_bridge events
- **Kafka Partitioning Documentation** - https://kafka.apache.org/documentation/#design_partitioning

## Version History

- **v1.0.0** (2025-11-13) - Initial implementation
  - 5 event families defined
  - All families use correlation_id
  - 35 unit tests + 10 integration tests
  - Complete documentation and examples
