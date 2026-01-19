# Observability System Diagnostic Scripts

This directory contains diagnostic and testing scripts for the OmniClaude agent observability system.

## Overview

These scripts help diagnose logging, traceability, and agent execution issues in the OmniClaude observability infrastructure. They provide comprehensive health checks, end-to-end testing, and query capabilities for agent execution history.

## Available Scripts

### 1. diagnose_agent_logging.sh

**Purpose**: Diagnose agent logging system health and identify issues

**What it checks**:
- Database connectivity (PostgreSQL)
- agent_execution_logs table statistics
- Kafka consumer service status
- Event flow verification (Kafka → Consumer → Database)
- Logger functionality test

**Usage**:
```bash
./diagnose_agent_logging.sh
./diagnose_agent_logging.sh --verbose
./diagnose_agent_logging.sh --fix-issues  # Attempt automatic fixes
```

**Example output**:
```
╔═════════════════════════════════════════════════════════════════╗
║       Agent Logging System Diagnostic Tool                      ║
╚═════════════════════════════════════════════════════════════════╝

✅ Database connection successful
✅ agent_execution_logs table exists
✅ Found 11 execution logs
⚠️  Found 3 stuck executions (in_progress > 1 hour)
✅ Event flow working: 2 actions logged in last 5 minutes
```

**Exit codes**:
- `0` - All checks passed
- `1` - Critical issues found
- `2` - Warnings found (non-critical)

---

### 2. diagnose_traceability.sh

**Purpose**: Diagnose agent traceability system health and data integrity

**What it checks**:
- All traceability tables exist and have correct schema
- Recent traceability data and activity patterns
- File operation tracking (Read, Write, Edit operations)
- Intelligence usage tracking (manifest injections, patterns)
- Data relationships and integrity constraints

**Usage**:
```bash
./diagnose_traceability.sh
./diagnose_traceability.sh --verbose
./diagnose_traceability.sh --correlation-id <uuid>  # Check specific execution
```

**Example output**:
```
╔═════════════════════════════════════════════════════════════════╗
║       Agent Traceability System Diagnostic Tool                 ║
╚═════════════════════════════════════════════════════════════════╝

✅ agent_execution_logs: exists (Main execution tracking)
✅ agent_actions: exists (Tool calls and decisions)
✅ agent_manifest_injections: exists (Intelligence context tracking)
✅ Total manifest injections: 32
ℹ️  Average patterns per injection: 37.5
⚠️  Query time >5000ms indicates performance issues
```

**Exit codes**:
- `0` - All checks passed
- `1` - Critical issues found
- `2` - Warnings found (non-critical)

---

### 3. test_agent_execution.sh

**Purpose**: End-to-end test of agent execution logging pipeline

**What it does**:
1. Trigger a test agent execution with generated correlation ID
2. Verify logging works end-to-end (Agent → Kafka → Consumer → DB)
3. Check database receives all expected data
4. Measure end-to-end latency
5. Validate data integrity and completeness

**Usage**:
```bash
./test_agent_execution.sh
./test_agent_execution.sh --keep-data     # Don't clean up test data
./test_agent_execution.sh --timeout 30    # Custom timeout in seconds
```

**Example output**:
```
╔═════════════════════════════════════════════════════════════════╗
║       Agent Execution End-to-End Test                           ║
╚═════════════════════════════════════════════════════════════════╝

Correlation ID: test-exec-1761739408-64281

✅ Action 1/5: analyze_request logged to Kafka
✅ Action 2/5: Read logged to Kafka
✅ Action 3/5: Write logged to Kafka
✅ Action 4/5: Bash logged to Kafka
✅ Action 5/5: task_completed logged to Kafka

✅ All 5 actions persisted to database
ℹ️  End-to-end latency: 1842ms
✅ All actions have valid durations
✅ Full execution trace available
```

**Exit codes**:
- `0` - Test passed successfully
- `1` - Test failed

---

### 4. query_agent_history.sh

**Purpose**: Query and display agent execution history with complete traceability

**What it shows**:
1. Agent execution details (agent name, status, duration)
2. Complete action trace (tool calls, decisions, errors)
3. File operations performed (Read, Write, Edit)
4. Intelligence context used (patterns, manifest data)
5. Human-readable formatted output with colors

**Usage**:
```bash
./query_agent_history.sh
./query_agent_history.sh --correlation-id <uuid>
./query_agent_history.sh --agent <agent-name>
./query_agent_history.sh --last 10
./query_agent_history.sh --since "2025-10-28"
./query_agent_history.sh --status error
./query_agent_history.sh --export json > history.json
```

**Example output**:
```
╔═════════════════════════════════════════════════════════════════╗
║       Agent Execution History Query Tool                        ║
╚═════════════════════════════════════════════════════════════════╝

ℹ️  Found 3 execution(s)

═══════════════════════════════════════════════════════════
EXECUTION #1
═══════════════════════════════════════════════════════════
Correlation ID: 68cd656b-f86a-435f-8888-b76c5ac74be0
Agent: test-agent-3
Status: ✅ SUCCESS
Started: 2025-10-25 12:05:48
Duration: 1.2s

Actions (5):
  🔧 12:05:48.123 | Read (tool_call) - 25ms
     → test.py
  🔧 12:05:48.150 | Write (tool_call) - 45ms
     → output.py
  🔧 12:05:48.200 | Bash (tool_call) - 100ms
     → echo test
  ✓ 12:05:48.310 | task_completed (success) - 10ms

Intelligence Context:
  Patterns discovered: 120
  Query time: 1842ms
```

---

## Prerequisites

All scripts require:
- PostgreSQL credentials in `.env` or environment variables
- Network access to database (192.168.86.200:5436)
- Docker access (for checking Kafka and consumer containers)

## Environment Variables

```bash
# Required
POSTGRES_PASSWORD=your_password_here

# Optional (with defaults)
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_USER=postgres
POSTGRES_DB=omninode_bridge
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092
```

## Common Workflows

### Daily Health Check
```bash
# Quick system health check
./diagnose_agent_logging.sh
./diagnose_traceability.sh

# Review recent activity
./query_agent_history.sh --last 10
```

### Troubleshooting Agent Issues
```bash
# 1. Find the problematic execution
./query_agent_history.sh --status error

# 2. Investigate specific execution
./query_agent_history.sh --correlation-id <uuid> --verbose

# 3. Check traceability
./diagnose_traceability.sh --correlation-id <uuid>
```

### Testing After Deployment
```bash
# Run end-to-end test
./test_agent_execution.sh

# Verify logging pipeline
./diagnose_agent_logging.sh --verbose
```

### Debugging Performance Issues
```bash
# Check for slow queries
./diagnose_traceability.sh --verbose

# Export history for analysis
./query_agent_history.sh --since "2025-10-28" --export json > history.json
```

## Output Features

All scripts feature:
- ✅ **Color-coded output** (green = success, yellow = warning, red = error)
- 📊 **Clear metrics** (counts, durations, percentages)
- 🔍 **Verbose mode** for detailed diagnostics
- 📋 **Structured sections** for easy reading
- 💡 **Troubleshooting tips** when issues are found

## Tested On

- ✅ macOS (Darwin 24.6.0)
- ✅ Bash 5.2.37
- ✅ PostgreSQL 14+
- ✅ Docker Desktop
- ✅ Kafka/Redpanda

## Troubleshooting

### Database Connection Failed
```bash
# Check credentials
echo $POSTGRES_PASSWORD

# Verify database is running
docker ps | grep postgres

# Test connection manually
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

### Kafka Consumer Not Processing Events
```bash
# Check consumer status
docker logs archon-kafka-consumer

# Restart consumer
docker restart archon-kafka-consumer

# Verify Kafka connectivity
./scripts/validate-kafka-setup.sh
```

### No Recent Executions Found
```bash
# This is normal if no agents have run recently
# Check older data
./query_agent_history.sh --since "2025-10-01"
```

## Integration with Other Tools

These scripts complement existing OmniClaude tools:

- **health_check.sh** - Overall system health (services, infrastructure)
- **agent_history_browser.py** - Interactive Python browser with rich UI
- **validate-kafka-setup.sh** - Kafka-specific diagnostics

## Contributing

When adding new diagnostic scripts:
1. Follow the existing naming convention (`*.sh`)
2. Include `--help` flag with usage instructions
3. Use color-coded output for clarity
4. Implement proper error handling
5. Return appropriate exit codes
6. Add documentation to this README

## License

Part of the OmniClaude project.

---

**Created**: 2025-10-29
**Last Updated**: 2025-10-29
**Correlation ID**: accac9a8-a8b8-4793-9dda-6d5ccfceee9f
