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
python3 ~/.claude/skills/system-status/check-database-health/execute.py \
  --tables agent_manifest_injections,agent_routing_decisions
```

### Arguments

- `--tables`: Comma-separated list of tables to check [default: all main tables]
  - **Security**: Table names validated against whitelist (see SECURITY.md)
  - **Valid tables**: See `VALID_TABLES` in execute.py for complete list
  - **Example**: `agent_routing_decisions,agent_manifest_injections,agent_actions`
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

## Security

**SQL Injection Prevention**: All table names are validated against a whitelist before use in SQL queries.

**Invalid table names are rejected**:
```bash
# Malicious input is blocked
python3 execute.py --tables "agent_actions; DROP TABLE users; --"

# Returns error:
# {
#   "error": "Invalid table name: 'agent_actions; DROP TABLE users; --'.
#             Must be one of: agent_actions, agent_execution_logs, ..."
# }
```

**Valid Table Whitelist** (34 tables):
- Core agent tables: `agent_routing_decisions`, `agent_manifest_injections`, `agent_execution_logs`, `agent_actions`, `agent_transformation_events`, `agent_sessions`
- Workflow tables: `workflow_steps`, `workflow_events`
- Intelligence tables: `llm_calls`, `error_events`, `success_events`, `router_performance_metrics`, `intelligence_queries`, `pattern_discoveries`, `debug_intelligence`, `quality_assessments`, `onex_compliance_checks`
- Infrastructure tables: `correlation_tracking`, `event_log`, `system_metrics`, `performance_snapshots`, `cache_operations`, `database_operations`, `kafka_events`, `service_health_checks`
- Application tables: `api_requests`, `user_sessions`, `authentication_events`, `authorization_checks`
- Deployment tables: `configuration_changes`, `deployment_events`, `migration_history`, `schema_versions`, `audit_log`

**See [SECURITY.md](SECURITY.md)** for complete security documentation and test coverage.

## Testing

**Run validation tests**:
```bash
python3 test_table_validation.py
```

**Test coverage**: 11 tests covering:
- Valid table name acceptance
- Invalid/malicious table name rejection
- SQL injection prevention (14 attack patterns tested)
- Error message clarity
- Whitelist completeness

## Output Format & Exit Codes

For complete details on output structures, exit codes, field standards, and examples, see:

**[Output Format Specification](../OUTPUT_FORMAT_SPECIFICATION.md)**

This includes:
- Detailed JSON schema and field descriptions
- All exit code scenarios with examples
- Status value conventions and indicators
- Error response formats
- Edge case handling
