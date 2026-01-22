---
name: check-database-health
description: PostgreSQL database health including table stats, connection pool, and query performance
---

# Check Database Health

Monitor PostgreSQL database health, activity, and performance.

## What It Checks

- Table counts and row counts
- Recent insert activity (5min, 1hr, 24hr)
- Connection pool status
- Query performance metrics
- Table sizes

## How to Use

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-database-health/execute.py \
  --tables agent_manifest_injections,agent_routing_decisions
```

### Arguments

- `--tables`: Comma-separated list of tables to check [default: all main tables]
- `--include-sizes`: Include table size information

## Example Output

```json
{
  "connection": "healthy",
  "total_tables": 34,
  "connections": {
    "active": 8,
    "idle": 2,
    "total": 10
  },
  "recent_activity": {
    "agent_manifest_injections": {
      "5m": 12,
      "1h": 85,
      "24h": 452
    },
    "agent_routing_decisions": {
      "5m": 18,
      "1h": 142,
      "24h": 890
    }
  }
}
```
