# Diagnostic Scripts Guide

Comprehensive guide to observability diagnostic tools for agent execution debugging, performance analysis, and system health monitoring.

## Table of Contents

1. [Overview](#overview)
2. [Agent History Browser](#agent-history-browser)
3. [Health Check Script](#health-check-script)
4. [Common Troubleshooting Workflows](#common-troubleshooting-workflows)
5. [Performance Analysis](#performance-analysis)
6. [Debugging Failed Executions](#debugging-failed-executions)

---

## Overview

OmniClaude provides three primary diagnostic tools for observability:

| Tool | Purpose | Location | Type |
|------|---------|----------|------|
| **Agent History Browser** | Interactive execution history explorer | `agents/lib/agent_history_browser.py` | Python CLI |
| **Health Check Script** | System health monitoring | `scripts/health_check.sh` | Bash script |
| **Database Queries** | Direct SQL analysis | PostgreSQL @ 192.168.86.200:5436 | SQL |

### Quick Start

```bash
# Check system health
./scripts/health_check.sh

# Browse agent execution history
python3 agents/lib/agent_history_browser.py

# Direct database access
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

---

## Agent History Browser

Interactive CLI tool to browse complete agent execution history with manifest injection traceability.

### Installation

**Requirements**:
- Python 3.9+
- `psycopg2-binary` (required)
- `rich` (optional, for enhanced UI)

```bash
# Install required dependencies
pip install psycopg2-binary

# Install optional rich library for better formatting
pip install rich
```

### Configuration

The browser requires database connection configuration via environment variables or `.env` file:

```bash
# .env file (in project root or up to 5 parent levels)
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=omninode-bridge-postgres-dev-2024
```

**Note**: The tool searches for `.env` in the current directory and up to 5 parent directories.

### Basic Usage

#### Interactive Mode

Launch interactive browser:

```bash
python3 agents/lib/agent_history_browser.py
```

**Interactive Commands**:
```
[number]           View detailed history for agent run
search [name]      Filter by agent name (partial match)
clear              Clear filter
limit [N]          Set list limit (current: 50)
export [number]    Export manifest JSON
h, help            Show help
q, quit            Quit browser
```

#### Command-Line Options

```bash
# Filter by agent name
python3 agents/lib/agent_history_browser.py --agent test-agent

# Show more results
python3 agents/lib/agent_history_browser.py --limit 100

# Show recent runs (last N hours)
python3 agents/lib/agent_history_browser.py --since-hours 24

# View specific execution (non-interactive)
python3 agents/lib/agent_history_browser.py \
    --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd

# Export manifest JSON
python3 agents/lib/agent_history_browser.py \
    --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd \
    --export manifest.json
```

### Example Session

```
=================================================== =========================
AGENT EXECUTION HISTORY BROWSER
========================================================================

Recent Agent Runs
┌────┬──────────────────────────────────────┬─────────────────────────┬──────────────────────┬──────────┬────────────┬──────────────┐
│ #  │ Correlation ID                       │ Agent Name              │ Time                 │ Patterns │ Query Time │ Debug Intel  │
├────┼──────────────────────────────────────┼─────────────────────────┼──────────────────────┼──────────┼────────────┼──────────────┤
│ 1  │ 8b57ec39-45b5-467b-939c-dd1439219f69 │ agent-devops-infra      │ 2h ago               │      120 │     1842ms │ ✓12/✗3       │
│ 2  │ 7a44dc28-34a1-456c-8ef6-1cb03ded02ad │ agent-test-generator    │ 3h ago               │       95 │     1523ms │ ✓8/✗1        │
│ 3  │ 6c33cb17-23b0-345b-7de5-0ba92cdc91bc │ polymorphic-agent       │ 4h ago               │      108 │     1678ms │ ✓15/✗2       │
└────┴──────────────────────────────────────┴─────────────────────────┴──────────────────────┴──────────┴────────────┴──────────────┘

Total: 50 agent runs

╭─ Commands ────────────────────────────────────────────────────────────────╮
│ [number]           View detailed history for agent run                     │
│ search [name]      Filter by agent name                                    │
│ clear              Clear filter                                            │
│ limit [N]          Set list limit (current: 50)                            │
│ export [number]    Export manifest JSON                                    │
│ h, help            Show help                                               │
│ q, quit            Quit browser                                            │
╰───────────────────────────────────────────────────────────────────────────╯

Command [q]: 1
```

### Detail View

Selecting a run shows complete details:

```
╭─ Agent Execution Details ────────────────────────────────────────────────╮
│                                                                           │
│ Correlation ID: 8b57ec39-45b5-467b-939c-dd1439219f69                     │
│ Agent: agent-devops-infra                                                 │
│ Timestamp: 2025-10-29 14:30:00 UTC                                       │
│ Source: archon-intelligence-adapter (full)                                │
│                                                                           │
╰───────────────────────────────────────────────────────────────────────────╯

Performance Metrics
┌──────────────────────┬───────────┐
│ Section              │ Time (ms) │
├──────────────────────┼───────────┤
│ Patterns             │       450 │
│ Infrastructure       │       200 │
│ Models               │       150 │
│ Database Schemas     │       300 │
│ Debug Intelligence   │       742 │
│ Total                │      1842 │
└──────────────────────┴───────────┘

Manifest Content
┌─────────────────────────┬─────────┐
│ Category                │   Count │
├─────────────────────────┼─────────┤
│ Patterns                │     120 │
│ Infrastructure Services │       7 │
│ Models                  │      15 │
│ Database Schemas        │      34 │
│ Manifest Size           │  45,678 bytes │
└─────────────────────────┴─────────┘

╭─ Debug Intelligence ──────────────────────────────────────────────────────╮
│                                                                           │
│ ✓ Successful Approaches: 12 examples                                     │
│ ✗ Failed Approaches: 3 examples to avoid                                 │
│                                                                           │
╰───────────────────────────────────────────────────────────────────────────╯

Successful Approaches (what worked):
  • Read: Successfully read file before editing
  • Bash: Used parallel tool calls for independent operations
  • Edit: Preserved exact indentation from Read output

Failed Approaches (avoid retrying):
  • Write: Attempted to write without reading first (permission error)
  • Bash: Sequential commands caused timeout (use parallel instead)
  • Edit: Tried to edit non-existent file

╭─ Formatted Manifest Preview ──────────────────────────────────────────────╮
│ ======================================================================    │
│ SYSTEM MANIFEST - Dynamic Context via Event Bus                          │
│ ======================================================================    │
│                                                                           │
│ Version: 2.0.0                                                            │
│ Generated: 2025-10-29T14:30:00Z                                          │
│ Source: archon-intelligence-adapter                                       │
│                                                                           │
│ AVAILABLE PATTERNS:                                                       │
│   Collections: execution_patterns (120), code_patterns (856)             │
│   ...                                                                     │
│                                                                           │
│                                                                (first 20 lines) │
╰───────────────────────────────────────────────────────────────────────────╯

Press Enter to return...
```

### Interpreting Results

#### Agent Name Indicators

- **Agent name = "unknown"** → Check `manifest_loader.py` reads `AGENT_NAME` env var
- **Agent name with marker "⚠"** → Fallback manifest (intelligence unavailable)
- **Agent name in green** → Full manifest with intelligence

#### Query Time Interpretation

| Time | Status | Action |
|------|--------|--------|
| <2000ms | ✅ Excellent | No action needed |
| 2000-5000ms | ⚠️ Acceptable | Monitor for degradation |
| >5000ms | ❌ Poor | Check logs, Qdrant connectivity |
| >10000ms | 🚨 Critical | Check archon-intelligence service |

#### Debug Intelligence

**✓ Successful Approaches**: What worked in similar situations
- Use these patterns in current execution
- Learn from past successes

**✗ Failed Approaches**: What to avoid
- Don't retry these approaches
- Different strategy required

#### Fallback Indicators

- **is_fallback = true**: Minimal manifest due to intelligence unavailable
- **patterns_count = 0**: No patterns discovered (check Qdrant)
- **Query failures**: Specific service failures in query_failures JSON

### Export Functionality

Export complete manifest for analysis:

```bash
# Export from interactive mode
Command [q]: export 1

# Export from command line
python3 agents/lib/agent_history_browser.py \
    --correlation-id 8b57ec39-45b5-467b-939c-dd1439219f69 \
    --export manifest_8b57ec39.json
```

**Exported JSON includes**:
- Complete manifest snapshot
- Formatted manifest text
- Performance metrics
- Debug intelligence
- Query times breakdown
- All metadata

### Troubleshooting

#### Connection Failed

```bash
# Error: Database connection failed
# Solution: Check environment variables

# Verify configuration
echo "POSTGRES_HOST: $POSTGRES_HOST"
echo "POSTGRES_PORT: $POSTGRES_PORT"
echo "POSTGRES_PASSWORD: $POSTGRES_PASSWORD"

# Test connection manually
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

#### No Runs Found

```bash
# Error: No agent runs found matching criteria

# Check database directly
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT COUNT(*) FROM agent_manifest_injections;
"

# Check filters
python3 agents/lib/agent_history_browser.py --agent "" --limit 100
```

#### Rich Library Not Found

```bash
# Warning: Install 'rich' for better formatting
pip install rich

# Or continue with basic formatting (works without rich)
```

---

## Health Check Script

Comprehensive system health monitoring script that checks all observability infrastructure.

### Location

```bash
./scripts/health_check.sh
```

### Usage

```bash
# Run health check
./scripts/health_check.sh

# Check exit code
echo $?  # 0 = healthy, 1 = issues found

# View latest results
cat /tmp/health_check_latest.txt

# View history
tail -100 /tmp/health_check_history.log
```

### What It Checks

#### 1. Docker Services

```
Services:
  ✅ archon-intelligence (healthy)
  ✅ archon-qdrant (healthy)
  ✅ archon-bridge (healthy)
  ✅ archon-search (healthy)
  ✅ archon-memgraph (healthy)
  ✅ archon-kafka-consumer (healthy)
  ✅ archon-server (healthy)
```

#### 2. Infrastructure Connectivity

```
Infrastructure:
  ✅ Kafka: 192.168.86.200:9092 (connected, 15 topics)
  ✅ Qdrant: http://localhost:6333 (connected, 3 collections)
  📊 Collections: code_patterns (856 vectors), execution_patterns (229 vectors)
  ✅ PostgreSQL: 192.168.86.200:5436/omninode_bridge (connected)
  📊 Tables: 34 in public schema
  📊 Manifest Injections (24h): 142
```

#### 3. Intelligence Collection Status

```
Intelligence Collection (Last 5 min):
  ✅ Pattern Discovery: 12 manifest injections with patterns
  📊 Avg Query Time: 1842ms
```

### Output Files

```bash
# Latest check results (overwritten each run)
/tmp/health_check_latest.txt

# Historical log (appended)
/tmp/health_check_history.log
```

### Configuration

Environment variables (from `.env`):

```bash
# Kafka
KAFKA_HOST=192.168.86.200:9092

# PostgreSQL
TRACEABILITY_DB_HOST=192.168.86.200
TRACEABILITY_DB_PORT=5436
TRACEABILITY_DB_NAME=omninode_bridge
TRACEABILITY_DB_USER=postgres
TRACEABILITY_DB_PASSWORD=omninode-remote_2024_secure

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

### Exit Codes

```bash
0 - All systems healthy
1 - Issues found (see summary)
```

### Example Output

```
=== System Health Check ===
Timestamp: 2025-10-29 14:30:00

Services:
  ✅ archon-intelligence (healthy)
  ✅ archon-qdrant (healthy)
  ✅ archon-bridge (healthy)
  ✅ archon-search (healthy)
  ✅ archon-memgraph (healthy)
  ✅ archon-kafka-consumer (healthy)
  ✅ archon-server (healthy)

Infrastructure:
  ✅ Kafka: 192.168.86.200:9092 (connected, 15 topics)
  ✅ Qdrant: http://localhost:6333 (connected, 3 collections)
  📊 Collections: code_patterns (856 vectors), execution_patterns (229 vectors)
  ✅ PostgreSQL: 192.168.86.200:5436/omninode_bridge (connected)
  📊 Tables: 34 in public schema
  📊 Manifest Injections (24h): 142

Intelligence Collection (Last 5 min):
  ✅ Pattern Discovery: 12 manifest injections with patterns
  📊 Avg Query Time: 1842ms

=== Summary ===
✅ All systems healthy

=== End Health Check ===
```

### Automated Monitoring

Run health checks on schedule:

```bash
# Add to crontab
# Run every 5 minutes
*/5 * * * * /path/to/omniclaude/scripts/health_check.sh >> /var/log/health_check.log 2>&1

# Alert on failure
*/5 * * * * /path/to/omniclaude/scripts/health_check.sh || echo "Health check failed!" | mail -s "OmniClaude Alert" admin@example.com
```

### Troubleshooting

#### Service Not Running

```bash
# Error: archon-intelligence (not running)
# Solution: Start the service

docker start archon-intelligence

# Or restart all services
cd /path/to/Archon
docker-compose up -d
```

#### Kafka Connection Failed

```bash
# Error: Kafka connection failed
# Solution: Check Kafka service and network

# Check Kafka container
docker ps | grep redpanda

# Test connectivity
nc -zv 192.168.86.200 9092

# Check logs
docker logs omninode-bridge-redpanda
```

#### PostgreSQL Connection Failed

```bash
# Error: PostgreSQL connection failed
# Solution: Check password and connectivity

# Verify credentials
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# Check service
docker ps | grep archon-bridge

# Check logs
docker logs archon-bridge
```

#### Qdrant Connection Failed

```bash
# Error: Qdrant connection failed
# Solution: Check Qdrant service

# Test HTTP endpoint
curl http://localhost:6333/collections

# Check service
docker ps | grep archon-qdrant

# Check logs
docker logs archon-qdrant
```

---

## Common Troubleshooting Workflows

### Workflow 1: Debug Failed Agent Execution

**Scenario**: Agent execution failed, need to understand why.

```bash
# Step 1: Find recent failures
python3 agents/lib/agent_history_browser.py

# Step 2: Search for agent name
Command [q]: search my-agent

# Step 3: Select failed execution
Command [q]: 1

# Step 4: Review details
# - Check debug intelligence (what failed before)
# - Check manifest content (was intelligence available?)
# - Note patterns_count (0 indicates fallback)
# - Note query_time (>5000ms indicates timeout)

# Step 5: Export for deeper analysis
Command [q]: export 1

# Step 6: Analyze manifest JSON
jq '.full_manifest_snapshot.debug_intelligence' manifest_*.json

# Step 7: Check database for error details
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    execution_id,
    error_message,
    error_type,
    metadata
FROM agent_execution_logs
WHERE correlation_id = '8b57ec39-45b5-467b-939c-dd1439219f69';
"
```

### Workflow 2: Investigate Slow Performance

**Scenario**: Agent execution is slower than expected.

```bash
# Step 1: Run health check
./scripts/health_check.sh

# Look for:
# - High avg query time (>3000ms)
# - Kafka connection issues
# - Qdrant performance problems

# Step 2: Check recent execution times
python3 agents/lib/agent_history_browser.py --limit 20

# Look for:
# - Increasing query times (trend)
# - High fallback rate (indicator)

# Step 3: Analyze performance in database
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    agent_name,
    AVG(total_query_time_ms) AS avg_query_time,
    MAX(total_query_time_ms) AS max_query_time,
    COUNT(*) AS total_executions,
    COUNT(CASE WHEN is_fallback THEN 1 END) AS fallback_count
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name
ORDER BY avg_query_time DESC;
"

# Step 4: Check Qdrant performance
curl http://localhost:6333/metrics

# Step 5: Check archon-intelligence logs
docker logs --tail 100 archon-intelligence | grep -i "slow\|timeout\|error"
```

### Workflow 3: Validate Routing Accuracy

**Scenario**: Need to verify agent routing is working correctly.

```bash
# Step 1: Check routing accuracy view
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT * FROM v_routing_decision_accuracy
ORDER BY accuracy_percent DESC;
"

# Step 2: Find misrouted requests
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    user_request,
    selected_agent,
    confidence_score,
    routing_strategy,
    reasoning
FROM agent_routing_decisions
WHERE confidence_score < 0.7
ORDER BY created_at DESC
LIMIT 20;
"

# Step 3: Analyze specific routing decision
python3 agents/lib/agent_history_browser.py \
    --correlation-id [correlation-id-from-step2]

# Step 4: Review alternatives and reasoning
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    user_request,
    selected_agent,
    alternatives,
    reasoning,
    matched_triggers
FROM agent_routing_decisions
WHERE correlation_id = '[correlation-id]';
"
```

### Workflow 4: Analyze Pattern Discovery Issues

**Scenario**: Agents are getting fallback manifests (0 patterns).

```bash
# Step 1: Check recent fallback rate
python3 agents/lib/agent_history_browser.py --limit 50

# Look for:
# - Agents with ⚠ marker (fallback)
# - patterns_count = 0

# Step 2: Check Qdrant collections
curl http://localhost:6333/collections | jq '.result.collections'

# Verify:
# - code_patterns exists and has vectors
# - execution_patterns exists and has vectors

# Step 3: Check archon-intelligence logs
docker logs --tail 100 archon-intelligence | grep "PATTERN_EXTRACTION"

# Step 4: Test manifest injection directly
python3 -c "
from agents.lib.manifest_injector import inject_manifest
import json

manifest = inject_manifest()
print(json.dumps(manifest, indent=2))
"

# Step 5: Check query failures in database
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    correlation_id,
    agent_name,
    is_fallback,
    query_failures,
    warnings
FROM agent_manifest_injections
WHERE is_fallback = TRUE
ORDER BY created_at DESC
LIMIT 10;
"
```

---

## Performance Analysis

### Query Performance Metrics

```sql
-- Average query times by section
SELECT
    jsonb_object_keys(query_times) AS section,
    AVG((query_times->>jsonb_object_keys(query_times))::int) AS avg_time_ms,
    MAX((query_times->>jsonb_object_keys(query_times))::int) AS max_time_ms,
    MIN((query_times->>jsonb_object_keys(query_times))::int) AS min_time_ms
FROM agent_manifest_injections
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY section
ORDER BY avg_time_ms DESC;
```

### Routing Performance

```sql
-- Routing time distribution
SELECT
    CASE
        WHEN routing_time_ms < 100 THEN '<100ms (target)'
        WHEN routing_time_ms < 200 THEN '100-200ms (acceptable)'
        WHEN routing_time_ms < 500 THEN '200-500ms (warning)'
        ELSE '>500ms (critical)'
    END AS time_bucket,
    COUNT(*) AS count,
    (COUNT(*) * 100.0 / SUM(COUNT(*)) OVER ()) AS percent
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY time_bucket
ORDER BY
    CASE time_bucket
        WHEN '<100ms (target)' THEN 1
        WHEN '100-200ms (acceptable)' THEN 2
        WHEN '200-500ms (warning)' THEN 3
        ELSE 4
    END;
```

### Execution Success Rates

```sql
-- Success rates by agent
SELECT
    agent_name,
    COUNT(*) AS total_executions,
    COUNT(CASE WHEN status = 'success' THEN 1 END) AS successes,
    (COUNT(CASE WHEN status = 'success' THEN 1 END) * 100.0 / COUNT(*)) AS success_rate,
    AVG(duration_ms) AS avg_duration_ms,
    AVG(CASE WHEN quality_score IS NOT NULL THEN quality_score END) AS avg_quality_score
FROM agent_execution_logs
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name
ORDER BY total_executions DESC;
```

---

## Debugging Failed Executions

### Complete Trace Analysis

```sql
-- Get complete trace for failed execution
SELECT * FROM v_agent_execution_trace
WHERE agent_execution_success = FALSE
ORDER BY routing_time DESC
LIMIT 10;
```

### Error Pattern Analysis

```sql
-- Common error types
SELECT
    error_type,
    COUNT(*) AS occurrences,
    ARRAY_AGG(DISTINCT agent_name) AS affected_agents,
    MIN(created_at) AS first_seen,
    MAX(created_at) AS last_seen
FROM agent_execution_logs
WHERE status = 'failed'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY error_type
ORDER BY occurrences DESC;
```

### Debug Intelligence Review

```sql
-- Failed approaches to avoid
SELECT
    ami.agent_name,
    ami.full_manifest_snapshot->'debug_intelligence'->'similar_workflows'->'failures' AS failed_approaches
FROM agent_manifest_injections ami
WHERE ami.debug_intelligence_failures > 0
ORDER BY ami.created_at DESC
LIMIT 10;
```

---

## See Also

- [AGENT_TRACEABILITY.md](./AGENT_TRACEABILITY.md) - Architecture and database schemas
- [LOGGING_PIPELINE.md](./LOGGING_PIPELINE.md) - Event flow and pipeline
- [../../CLAUDE.md](../../CLAUDE.md#troubleshooting-guide) - Main troubleshooting guide

---

**Last Updated**: 2025-10-29
**Tools Version**: 1.0.0
**Database**: omninode_bridge @ 192.168.86.200:5436
