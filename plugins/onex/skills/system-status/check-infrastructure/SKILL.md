---
name: check-infrastructure
description: Infrastructure component connectivity and health checks for Kafka, PostgreSQL, and Qdrant
---

# Check Infrastructure

Check connectivity and health of core infrastructure components supporting the OmniClaude agent system.

## Description

This skill verifies connectivity and collects basic health metrics from the three primary infrastructure components: Kafka (message bus), PostgreSQL (database), and Qdrant (vector store). It provides a quick sanity check that all critical services are reachable and responding.

## Current Features

- ✅ **Kafka**: Broker connectivity and topic count
- ✅ **PostgreSQL**: Database connectivity, table count, connection pool stats (with `--detailed`)
- ✅ **Qdrant**: Collection stats, vector counts, and per-collection breakdowns (with `--detailed`)
- ✅ **Component filtering**: Check specific components only
- ✅ **Detailed mode**: Extended statistics for capacity planning

## When to Use

- **Infrastructure verification**: Confirm all components are accessible
- **Deployment validation**: After infrastructure changes
- **Troubleshooting connectivity**: Isolate which infrastructure component is failing
- **Capacity planning**: Review vector counts and table sizes (use `--detailed`)

## Usage

```bash
# Check all components (basic stats)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py

# Check specific components
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py \
  --components kafka,postgres

# Include detailed statistics
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py --detailed
```

## Arguments

- `--components`: Comma-separated list of components to check
  - Valid values: `kafka`, `postgres`, `qdrant`
  - Default: All components (`kafka,postgres,qdrant`)
- `--detailed`: Include detailed statistics (connection counts, vector counts, collection details)
  - Default: False (basic stats only)

## Output Format

**Basic output** (default):
```json
{
  "kafka": {
    "status": "connected",
    "broker": "192.168.86.200:29092",
    "reachable": true,
    "topics": null,
    "error": null
  },
  "postgres": {
    "status": "connected",
    "host": "192.168.86.200:5436",
    "database": "omniclaude",
    "tables": 34,
    "error": null
  },
  "qdrant": {
    "status": "connected",
    "url": "http://localhost:6333",
    "reachable": true,
    "error": null
  }
}
```

**Detailed output** (with `--detailed`):
```json
{
  "kafka": {
    "status": "connected",
    "broker": "192.168.86.200:29092",
    "reachable": true,
    "topics": 15,
    "error": null
  },
  "postgres": {
    "status": "connected",
    "host": "192.168.86.200:5436",
    "database": "omniclaude",
    "tables": 34,
    "connections": 8,
    "error": null
  },
  "qdrant": {
    "status": "connected",
    "url": "http://localhost:6333",
    "reachable": true,
    "collections": 4,
    "total_vectors": 15689,
    "collections_detail": {
      "archon_vectors": 7118,
      "code_generation_patterns": 8571
    },
    "error": null
  }
}
```

## Exit Codes

- `0` - All requested components checked successfully
- `1` - Error occurred during checks (see `error` field in output)

## Examples

**Check only Kafka and PostgreSQL**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py \
  --components kafka,postgres
```

**Get detailed Qdrant vector counts**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py \
  --components qdrant --detailed
```

**Quick connectivity test for all services**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/check-infrastructure/execute.py | jq -r 'to_entries[] | "\(.key): \(.value.status)"'
# Output:
# kafka: connected
# postgres: connected
# qdrant: connected
```

## Future Enhancements

- ⏳ **Valkey cache**: Redis-compatible cache connectivity and stats
- ⏳ **Memgraph**: Graph database connectivity and node/edge counts
- ⏳ **Kafka consumer groups**: Consumer lag and group coordination status
- ⏳ **PostgreSQL query performance**: Slow query analysis and index utilization
- ⏳ **Qdrant search performance**: Benchmark search latency and throughput
- ⏳ **Health scoring**: Aggregate health score across all components
- ⏳ **Alerting thresholds**: Configurable thresholds for capacity warnings

## Troubleshooting

**Connection failures**:
- Verify environment variables are loaded: `source .env`
- Check Docker containers are running: `docker ps | grep -E "(kafka|postgres|qdrant)"`
- Verify network connectivity: `ping 192.168.86.200`

**Missing collections/tables**:
- Run migrations: `alembic upgrade head`
- Verify Qdrant collections: `curl http://localhost:6333/collections`

**Permission errors (PostgreSQL)**:
- Verify `POSTGRES_PASSWORD` is set: `echo ${POSTGRES_PASSWORD:+SET}`
- Test connection: `psql -h 192.168.86.200 -p 5436 -U postgres -d omniclaude -c "SELECT 1"`
