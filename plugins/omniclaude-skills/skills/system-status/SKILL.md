---
name: system-status
description: Infrastructure health monitoring and diagnostics for OmniClaude agent systems
version: 1.0.0
category: monitoring
triggers:
  - "check system health"
  - "system status"
  - "infrastructure status"
  - "service status"
  - "health check"
  - "diagnose issues"
  - "database health"
  - "Kafka status"
tags:
  - monitoring
  - infrastructure
  - health-check
  - diagnostics
  - observability
author: OmniClaude Team
dependencies:
  - docker
  - psql (PostgreSQL client)
  - kcat (optional, for Kafka)
---

# System Status

Comprehensive infrastructure health monitoring and diagnostics for OmniClaude agent systems.

## Sub-Skills

| Sub-Skill | Description |
|-----------|-------------|
| **check-system-health** | Fast overall system health snapshot (<5 seconds) |
| **check-agent-performance** | Agent execution metrics and performance analysis |
| **check-database-health** | PostgreSQL connection pool and query performance |
| **check-infrastructure** | Kafka, PostgreSQL, Qdrant connectivity |
| **check-kafka-topics** | Kafka topic status and consumer lag |
| **check-pattern-discovery** | Qdrant pattern discovery health |
| **check-recent-activity** | Recent agent executions and routing decisions |
| **check-service-status** | Docker container status and health |
| **diagnose-issues** | In-depth issue diagnosis |
| **generate-status-report** | Comprehensive system status report |

## Quick Start

```bash
# Fast overall health check
python3 ./check-system-health/execute.py

# Check specific service
python3 ./check-service-status/execute.py

# Check database health
python3 ./check-database-health/execute.py

# Generate comprehensive report
python3 ./generate-status-report/execute.py
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All systems healthy |
| 1 | Degraded (warnings found) |
| 2 | Critical (errors found) |
| 3 | Execution error |

## What Gets Checked

### Infrastructure
- Docker services (archon-*, omninode-*, app containers)
- Kafka/Redpanda broker connectivity and topic health
- PostgreSQL connection pool and query latency
- Qdrant vector database and collection status

### Agent System
- Recent agent executions and success rates
- Routing decision latency and accuracy
- Manifest injection performance
- Pattern discovery effectiveness

### Performance Metrics
- Response times against SLA thresholds
- Connection pool utilization
- Container restart counts
- Query execution times

## Example Output

```json
{
  "status": "healthy",
  "timestamp": "2025-11-12T14:30:00Z",
  "check_duration_ms": 2450,
  "services": {
    "total": 12,
    "running": 12,
    "healthy": 12
  },
  "infrastructure": {
    "kafka": {"status": "connected", "topics": 15},
    "postgres": {"status": "connected", "tables": 34},
    "qdrant": {"status": "connected", "vectors": 15689}
  },
  "issues": [],
  "recommendations": []
}
```

## Configuration

All thresholds are configured in `../_shared/constants.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `QUERY_TIMEOUT_THRESHOLD_MS` | 5000 | Slow query warning |
| `ROUTING_TIMEOUT_THRESHOLD_MS` | 100 | Slow routing warning |
| `MAX_RESTART_COUNT_THRESHOLD` | 5 | Container restart limit |
| `CONN_POOL_WARNING_THRESHOLD_PCT` | 60 | Connection pool warning |

## See Also

- Agent observability: `../agent-observability/`
- Agent tracking: `../agent-tracking/`
- CI failures: `../ci-failures/`
