---
name: check-kafka-topics
description: Kafka topic health, consumer status, and message throughput monitoring
---

# Check Kafka Topics

Monitor Kafka topics, partitions, and consumer groups.

## What It Checks

- Topic list and partition counts
- Consumer group status
- Recent message activity
- Topic-specific health

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
