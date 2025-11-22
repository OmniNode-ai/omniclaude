---
name: check-infrastructure
description: Infrastructure component connectivity and health checks for Kafka, PostgreSQL, and Qdrant
---

# Check Infrastructure

Check connectivity and health of core infrastructure components supporting the OmniClaude agent system.

## Current Features

- ✅ **Kafka**: Broker connectivity and topic count
- ✅ **PostgreSQL**: Database connectivity, table count, connection pool stats (with `--detailed`)
- ✅ **Qdrant**: Collection stats, vector counts, and per-collection breakdowns (with `--detailed`)
- ✅ **Component filtering**: Check specific components only
- ✅ **Detailed mode**: Extended statistics for capacity planning

## When to Use

- **Infrastructure verification**: Confirm all components are accessible
- **Deployment validation**: After infrastructure changes
- **Troubleshooting connectivity**: Isolate infrastructure issues
- **Capacity planning**: Review vector counts and table sizes

## How to Use

```bash
# Check all components
python3 ~/.claude/skills/system-status/check-infrastructure/execute.py

# Check specific components
python3 ~/.claude/skills/system-status/check-infrastructure/execute.py \
  --components kafka,postgres,qdrant
```

### Optional Arguments

- `--components`: Comma-separated list of components to check [default: all]
- `--detailed`: Include detailed statistics

## Example Output

```json
{
  "kafka": {
    "status": "connected",
    "broker": "192.168.86.200:29092",
    "topics": 15,
    "reachable": true
  },
  "postgres": {
    "status": "connected",
    "host": "192.168.86.200:5436",
    "database": "omninode_bridge",
    "tables": 34,
    "connections": 8
  },
  "qdrant": {
    "status": "connected",
    "url": "http://localhost:6333",
    "collections": 4,
    "total_vectors": 15689,
    "collections_detail": {
      "archon_vectors": 7118,
      "code_generation_patterns": 8571
    }
  }
}
```

## Future Enhancements

- ⏳ **Valkey cache**: Redis-compatible cache connectivity and stats
- ⏳ **Memgraph**: Graph database connectivity and node/edge counts
- ⏳ **Kafka consumer groups**: Consumer lag and group coordination status
- ⏳ **PostgreSQL query performance**: Slow query analysis and index utilization
- ⏳ **Qdrant search performance**: Benchmark search latency and throughput
- ⏳ **Health scoring**: Aggregate health score across all components
- ⏳ **Alerting thresholds**: Configurable thresholds for capacity warnings

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling
