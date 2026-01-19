---
name: check-kafka-topics
description: Kafka topic existence, partition counts, and wildcard pattern matching
---

# Check Kafka Topics

Verify Kafka topic existence and partition configuration using exact names or wildcard patterns.

## What It Checks

- Kafka broker connectivity
- Topic existence (single topic or wildcard patterns)
- Partition counts (optional with `--include-partitions`)
<!-- Future: Consumer group status, message activity, topic health metrics -->

## How to Use

```bash
python3 ~/.claude/skills/system-status/check-kafka-topics/execute.py \
  --topics agent-actions,agent.routing.*
```

### Arguments

- `--topics`: Comma-separated list of topic patterns [default: all]
- `--include-partitions`: Include partition details

## Example Output

```json
{
  "broker": "192.168.86.200:29092",
  "status": "healthy",
  "total_topics": 15,
  "topics": {
    "agent-actions": {
      "partitions": 3,
      "exists": true
    },
    "agent.routing.requested.v1": {
      "partitions": 1,
      "exists": true
    }
  }
}
```

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling
