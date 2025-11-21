---
name: check-infrastructure
description: Infrastructure component connectivity and health checks for Kafka, PostgreSQL, Qdrant, Valkey, and Memgraph
---

# Check Infrastructure

Check connectivity and health of all infrastructure components supporting the OmniClaude agent system.

## What It Checks

- **Kafka**: Broker connectivity, topic count, consumer groups
- **PostgreSQL**: Database connectivity, table count, connection pool
- **Qdrant**: Collection stats, vector counts, search performance
- **Valkey**: Cache connectivity and stats (optional)
- **Memgraph**: Graph database connectivity (optional)

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

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling
