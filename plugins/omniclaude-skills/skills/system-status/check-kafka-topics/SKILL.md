---
name: check-kafka-topics
description: Kafka topic existence, partition counts, and wildcard pattern matching
---

# Check Kafka Topics

Verify Kafka topic existence and partition configuration using exact names or wildcard patterns.

## Description

This skill checks whether specific Kafka topics exist and retrieves their partition counts. It supports wildcard pattern matching (e.g., `agent.*`) to check multiple related topics at once. Useful for verifying topic creation, checking partition configuration, and validating topic naming conventions.

## Current Features

- ✅ **Topic existence**: Verify topics exist by exact name
- ✅ **Wildcard matching**: Pattern-based topic discovery (e.g., `agent.*`, `test-*`)
- ✅ **Partition counts**: View partition configuration (with `--include-partitions`)
- ✅ **Bulk checking**: Check multiple topics in a single call
- ✅ **Total topic count**: View all topics on the broker

## When to Use

- **Topic verification**: Confirm expected topics exist after deployment
- **Pattern validation**: Check all topics matching a naming convention
- **Partition planning**: Review partition configuration for scaling
- **Troubleshooting**: Verify topic creation and naming

## Usage

```bash
# List all topics (count only)
python3 ./check-kafka-topics/execute.py

# Check specific topics
python3 ./check-kafka-topics/execute.py \
  --topics agent-actions,agent.routing.requested.v1

# Check topics with wildcard patterns
python3 ./check-kafka-topics/execute.py \
  --topics "agent.*,test-*"

# Include partition details
python3 ./check-kafka-topics/execute.py \
  --topics agent-actions --include-partitions
```

## Arguments

- `--topics`: Comma-separated list of topic names or patterns
  - Supports exact names: `agent-actions`
  - Supports wildcards: `agent.*`, `test-*`, `*.v1`
  - Default: None (returns only total topic count)
- `--include-partitions`: Include partition counts for each topic
  - Default: False (existence check only)

## Output Format

**Without `--topics`** (default):
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15
}
```

**With `--topics`** (exact match):
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "agent-actions": {
      "exists": true
    },
    "nonexistent-topic": {
      "exists": false
    }
  }
}
```

**With `--topics` and `--include-partitions`**:
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "agent-actions": {
      "exists": true,
      "partitions": 3
    },
    "agent.routing.requested.v1": {
      "exists": true,
      "partitions": 1
    }
  }
}
```

**With wildcard pattern** (`--topics "agent.*"`):
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "agent-actions": {
      "exists": true
    },
    "agent.routing.requested.v1": {
      "exists": true
    },
    "agent.routing.completed.v1": {
      "exists": true
    }
  }
}
```

**Unmatched wildcard pattern**:
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "nonexistent-*": {
      "exists": false,
      "matched": 0,
      "message": "No topics match pattern: nonexistent-*"
    }
  }
}
```

**Stats query failure** (e.g., permission denied):
```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "agent-actions": {
      "exists": true,
      "error": "Stats query failed: Permission denied"
    }
  }
}
```

## Exit Codes

- `0` - Kafka reachable and topics checked successfully
- `1` - Kafka unreachable or error occurred (see `error` field in output)

## Examples

**Check if agent routing topics exist**:
```bash
python3 ./check-kafka-topics/execute.py \
  --topics "agent.routing.requested.v1,agent.routing.completed.v1"
```

**Find all agent-related topics with partition counts**:
```bash
python3 ./check-kafka-topics/execute.py \
  --topics "agent*" --include-partitions
```

**Verify topic creation in CI/CD pipeline**:
```bash
python3 ./check-kafka-topics/execute.py \
  --topics "my-new-topic" | jq -e '.topics["my-new-topic"].exists'
# Exit code 0 if exists, 1 if not
```

**Get all topics count**:
```bash
python3 ./check-kafka-topics/execute.py | jq '.total_topics'
```

## Future Enhancements

- ⏳ **Consumer group status**: Consumer lag, group state, and member counts
- ⏳ **Recent message activity**: Message rate (messages/sec) and throughput (bytes/sec)
- ⏳ **Topic health metrics**: Replication factor, under-replicated partitions, leader distribution
- ⏳ **Offset monitoring**: Earliest/latest offsets per partition, total message count
- ⏳ **Retention policy**: TTL and size-based retention configuration
- ⏳ **Consumer lag analysis**: Per-consumer lag and lag trends
- ⏳ **Topic configuration**: Compression, cleanup policy, segment size
- ⏳ **Partition rebalancing**: Identify unbalanced partitions across brokers

## Troubleshooting

**Connection failures** (`"status": "unreachable"`):
- Verify Kafka is running: `docker ps | grep kafka`
- Check bootstrap servers: `echo $KAFKA_BOOTSTRAP_SERVERS`
- Test connectivity: `nc -zv 192.168.86.200 29092`

**Stats query failures** (`"error": "Stats query failed"`):
- Verify `kafkacat`/`kcat` is installed: `which kcat`
- Check permissions: Ensure user has topic describe permissions
- Try manual query: `kcat -L -b 192.168.86.200:29092 -t agent-actions`

**Wildcard not matching expected topics**:
- List all topics manually: `kcat -L -b 192.168.86.200:29092`
- Verify pattern syntax: Use shell glob patterns (`*`, `?`, `[]`)
- Check topic naming: Topics might use different delimiter (e.g., `-` vs `.`)

**Performance issues with large topic lists**:
- Use `--include-partitions` sparingly (requires additional API calls per topic)
- Filter with specific patterns instead of broad wildcards
- Consider caching results if checking frequently
