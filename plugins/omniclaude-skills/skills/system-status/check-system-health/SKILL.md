---
name: check-system-health
description: Fast overall system health snapshot - checks Docker services, infrastructure connectivity, and recent activity in under 5 seconds
---

# Check System Health

Quick system health check that provides a comprehensive snapshot of the entire OmniClaude agent system.

## What It Checks

- **Docker Services**: All archon-*, omninode-*, and app containers
- **Infrastructure**: Kafka, PostgreSQL, Qdrant connectivity
- **Recent Activity**: Agent executions, routing decisions (last 5 minutes)
- **Overall Status**: healthy, degraded, or critical

## When to Use

- **Quick health check**: Before starting work
- **After deployment**: Verify all services are running
- **Troubleshooting**: First step in diagnosing issues
- **Monitoring**: Periodic automated health checks
- **Dashboard**: Real-time system status

## How to Use

```bash
python3 ./check-system-health/execute.py
```

### Optional Arguments

```bash
python3 ./check-system-health/execute.py \
  --format json \
  --verbose
```

**Arguments**:
- `--format`: Output format (json, text, summary) [default: json]
- `--verbose`: Include detailed information

## Example Output

```json
{
  "status": "healthy",
  "timestamp": "2025-11-12T14:30:00Z",
  "check_duration_ms": 2450,
  "services": {
    "total": 12,
    "running": 12,
    "stopped": 0,
    "unhealthy": 0,
    "healthy": 12
  },
  "infrastructure": {
    "kafka": {
      "status": "connected",
      "broker": "192.168.86.200:29092",
      "topics": 15
    },
    "postgres": {
      "status": "connected",
      "host": "192.168.86.200:5436",
      "tables": 34
    },
    "qdrant": {
      "status": "connected",
      "collections": 4,
      "total_vectors": 15689
    }
  },
  "recent_activity": {
    "timeframe": "5m",
    "agent_executions": 15,
    "routing_decisions": 23,
    "agent_actions": 156
  },
  "issues": [],
  "recommendations": []
}
```

## Exit Codes

- `0` - All systems healthy
- `1` - Degraded (warnings found)
- `2` - Critical (errors found)
- `3` - Execution error

## Performance

- **Target**: < 5 seconds
- **Typical**: 2-3 seconds
- **Checks**: 3 services + 3 infrastructure components + 3 database queries

## Integration Examples

### In Agent Workflows

```python
import subprocess
import json

# Check system health before starting work
result = subprocess.run(
    ["python3", "./check-system-health/execute.py"],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    health = json.loads(result.stdout)
    print(f"System status: {health['status']}")
    print(f"Issues: {len(health['issues'])}")
```

### Automated Monitoring

```bash
#!/bin/bash
# Run health check every 5 minutes
while true; do
  python3 ./check-system-health/execute.py
  sleep 300
done
```

### Pre-Deployment Check

```bash
# Check health before deployment
python3 ./check-system-health/execute.py
if [ $? -eq 0 ]; then
  echo "System healthy, proceeding with deployment"
  docker-compose up -d
else
  echo "System unhealthy, aborting deployment"
  exit 1
fi
```

## See Also

- **check-service-status** - Detailed status for specific services
- **check-infrastructure** - Infrastructure component details
- **diagnose-issues** - In-depth issue diagnosis
- **generate-status-report** - Comprehensive system report
