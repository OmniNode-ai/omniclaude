---
name: check-recent-activity
description: Recent agent executions, routing decisions, and system activity with correlation tracking
---

# Check Recent Activity

View recent agent executions, routing decisions, and agent actions with correlation tracking.

## What It Checks

- Recent agent executions with manifest injection stats
- Recent routing decisions
- Recent agent actions (tool calls, decisions, errors)
- Activity trends
- Error summaries

## How to Use

```bash
python3 ./check-recent-activity/execute.py \
  --limit 20 \
  --since 5m
```

### Arguments

- `--limit`: Number of records to show [default: 20]
- `--since`: Time period (5m, 15m, 1h, 24h) [default: 5m]
- `--include-errors`: Include recent errors

## Example Output

```json
{
  "timeframe": "5m",
  "manifest_injections": {
    "count": 12,
    "avg_query_time_ms": 1842,
    "avg_patterns_count": 45,
    "fallbacks": 0
  },
  "routing_decisions": {
    "count": 18,
    "avg_routing_time_ms": 7.5,
    "avg_confidence": 0.88
  },
  "agent_actions": {
    "tool_calls": 156,
    "decisions": 18,
    "errors": 2,
    "successes": 12
  }
}
```
