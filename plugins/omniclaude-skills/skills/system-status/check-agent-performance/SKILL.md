---
name: check-agent-performance
description: Agent routing and execution performance metrics including routing times, confidence scores, and transformation success rates
---

# Check Agent Performance

Analyze agent routing and execution performance metrics over specified timeframes.

## What It Checks

- Recent routing decisions (5min, 1hr, 24hr)
- Average routing time and confidence scores
- Agent selection frequency
- Transformation success rates
- Performance threshold violations

## How to Use

```bash
python3 ./check-agent-performance/execute.py \
  --timeframe 1h
```

### Arguments

- `--timeframe`: Time period (5m, 15m, 1h, 24h, 7d) [default: 1h]
- `--top-agents`: Number of top agents to show [default: 10]

## Example Output

```json
{
  "timeframe": "1h",
  "routing": {
    "total_decisions": 145,
    "avg_routing_time_ms": 7.8,
    "avg_confidence": 0.89,
    "threshold_violations": 0
  },
  "top_agents": [
    {"agent": "agent-api-architect", "count": 42, "avg_confidence": 0.92},
    {"agent": "agent-debug-intelligence", "count": 38, "avg_confidence": 0.87}
  ],
  "transformations": {
    "total": 120,
    "success_rate": 0.98,
    "avg_duration_ms": 85
  }
}
```
