---
description: Comprehensive system health monitoring — checks agent performance, database, Kafka topics, pattern discovery, and service status across the ONEX platform
level: advanced
debug: true
index: true
mode: full
---

# System Status

Full platform health monitoring with diagnostics and status reporting.

## Sub-skills

- **check-agent-performance** - Review agent routing performance metrics
- **check-database-health** - Verify PostgreSQL connectivity and schema state
- **check-infrastructure** - Check Docker and infrastructure services
- **check-kafka-topics** - Verify Kafka/Redpanda topic health and consumer groups
- **check-pattern-discovery** - Check pattern discovery pipeline status
- **check-recent-activity** - Review recent agent and system activity
- **check-service-status** - Check individual service health endpoints
- **check-system-health** - Full system health summary
- **diagnose-issues** - Diagnose common platform issues
- **generate-status-report** - Generate a comprehensive status report

## Agent Diagnostics

<!-- Absorbed from agent-observability -->

Agent-specific monitoring and diagnostics capabilities, including alert
thresholds and database-backed profiling.

### Alert Thresholds

| Level | Success Rate | Unprocessed Events | P95 Duration | Error Rate |
|-------|-------------|-------------------|-------------|-----------|
| CRITICAL | < 70% | > 200 | > 120,000ms | > 30% |
| WARNING | < 80% | > 50 | > 60,000ms | > 20% |
| HEALTHY | >= 90% | < 50 | < 30,000ms | < 10% |

### Database Tables Monitored

- **agent_execution_logs** -- Core execution tracking with status, duration, quality scores
- **agent_routing_decisions** -- Agent detection and routing intelligence with confidence scores
- **hook_events** -- Hook event processing status, retry counts, and processing errors
- **agent_detection_failures** -- Failed agent detection attempts for debugging routing issues

### Recommended Workflows

**Daily Monitoring**:
```bash
/system-status check-system-health
/system-status diagnose-issues --time-range 24h    # if issues detected
```

**Incident Investigation**:
```bash
/system-status check-system-health
/system-status diagnose-issues --time-range 1h
/system-status check-agent-performance --agent [failing-agent]
```

**Weekly Review**:
```bash
/system-status generate-status-report --time-range 7d
```
