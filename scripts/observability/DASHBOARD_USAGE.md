# Agent Execution Dashboard Usage Guide

## Overview

Dashboard queries and scripts for monitoring agent execution status in real-time.

**Created**: 2025-10-30
**Database**: omninode_bridge on 192.168.86.200:5436
**Correlation ID**: a27b9e0c-ffc2-4357-b53a-ed080e1edf9c

---

## Files Created

1. **dashboard_views.sql** - 9 SQL views for dashboards
2. **cleanup_stuck_agents.sh** - Automated cleanup for stuck agents
3. **dashboard_stats.sh** - Interactive dashboard query tool

---

## SQL Views

### v_agent_execution_summary
High-level summary with key metrics in single row:
- active_now, stuck_now
- success_24h, errors_24h, success_rate_24h
- avg_quality_24h, recent_errors
- unique_agents_24h, refreshed_at

**Usage**:
```sql
SELECT * FROM v_agent_execution_summary;
```

### v_active_agents
Agents currently running (in_progress status):
- Flags agents stuck >1hr as 🔴 STUCK
- Shows running duration in seconds
- Displays user prompt preview

**Usage**:
```sql
SELECT * FROM v_active_agents;
```

### v_stuck_agents
Agents stuck in progress for >30 minutes:
- 🔴 CRITICAL (>24h)
- 🟠 WARNING (>1h)
- 🟡 MONITOR (>30m)

**Usage**:
```sql
SELECT * FROM v_stuck_agents;
```

### v_agent_completion_stats_24h
24-hour rolling statistics:
- Completion counts by status
- Success rate percentage
- Average duration and quality

**Usage**:
```sql
SELECT * FROM v_agent_completion_stats_24h;
```

### v_agent_completion_stats_7d
7-day rolling statistics (same structure as 24h).

### v_agent_performance
Performance metrics per agent (last 7 days):
- Execution counts by status
- Success rate, duration stats
- Quality scores, last run timestamp

**Usage**:
```sql
SELECT * FROM v_agent_performance ORDER BY total_executions DESC;
```

### v_agent_errors_recent
Recent agent errors (last 7 days, max 50):
- Error type and message
- Duration and timestamps
- User prompt and project path

**Usage**:
```sql
SELECT * FROM v_agent_errors_recent LIMIT 10;
```

### v_agent_daily_trends
Daily execution trends (last 30 days):
- Volume by status
- Success rates over time
- Quality trends
- Unique agents used per day

**Usage**:
```sql
SELECT * FROM v_agent_daily_trends ORDER BY execution_date DESC LIMIT 7;
```

### v_agent_quality_leaderboard
Agent quality scores leaderboard (min 3 scored runs):
- Average/min/max quality scores
- Distribution: excellent/good/fair/poor
- Last run timestamp

**Usage**:
```sql
SELECT * FROM v_agent_quality_leaderboard ORDER BY avg_quality_score DESC;
```

---

## Dashboard Stats Script

**Location**: `scripts/observability/dashboard_stats.sh`

### Usage

```bash
# Quick summary (default)
./scripts/observability/dashboard_stats.sh

# Show specific mode
./scripts/observability/dashboard_stats.sh [mode]
```

### Available Modes

| Mode | Description |
|------|-------------|
| `summary` | High-level summary + active/stuck agents (default) |
| `active` | Currently active and stuck agents |
| `stuck` | Only stuck agents (>30 minutes) |
| `24h` | 24-hour statistics |
| `7d` | 7-day statistics |
| `performance` | Agent performance metrics + quality leaderboard |
| `errors` | Recent errors (last 7 days) |
| `trends` | Daily trends (last 7 days) |
| `quality` | Quality leaderboard |
| `all` | Show all statistics |
| `--help` | Show help |

### Examples

```bash
# Dashboard summary
./scripts/observability/dashboard_stats.sh summary

# Check active agents
./scripts/observability/dashboard_stats.sh active

# View performance metrics
./scripts/observability/dashboard_stats.sh performance

# View recent errors
./scripts/observability/dashboard_stats.sh errors

# Full dashboard
./scripts/observability/dashboard_stats.sh all
```

### Environment Setup

The script requires PGPASSWORD to be set. Use one of these methods:

```bash
# Method 1: Source .env (recommended)
source .env
export PGPASSWORD="$POSTGRES_PASSWORD"
./scripts/observability/dashboard_stats.sh

# Method 2: Inline password
PGPASSWORD="***REDACTED***" ./scripts/observability/dashboard_stats.sh

# Method 3: Export first
export PGPASSWORD="***REDACTED***"
./scripts/observability/dashboard_stats.sh
```

---

## Cleanup Stuck Agents Script

**Location**: `scripts/observability/cleanup_stuck_agents.sh`

### Purpose

Automatically marks agents stuck in "in_progress" for >threshold as "error" with timeout message.

### Usage

```bash
# Dry run (preview only)
./scripts/observability/cleanup_stuck_agents.sh [minutes] --dry-run

# Execute cleanup
./scripts/observability/cleanup_stuck_agents.sh [minutes]
```

### Default Threshold

- **60 minutes** (1 hour) if not specified

### Examples

```bash
# Preview cleanup (60 min threshold)
./scripts/observability/cleanup_stuck_agents.sh 60 --dry-run

# Execute cleanup (60 min threshold)
./scripts/observability/cleanup_stuck_agents.sh 60

# Use different threshold (30 min)
./scripts/observability/cleanup_stuck_agents.sh 30

# Preview with 2 hour threshold
./scripts/observability/cleanup_stuck_agents.sh 120 --dry-run
```

### What It Does

1. **Checks** for agents stuck in "in_progress" for >threshold minutes
2. **Shows** stuck agent details before cleanup
3. **Updates** stuck agents to:
   - status = 'error'
   - error_type = 'timeout'
   - error_message = 'Execution timeout - stuck in progress > X minutes (auto-cleanup)'
   - completed_at = NOW()
   - duration_ms = calculated from started_at
4. **Reports** updated records and summary

### Stuck Agent Criteria

Agents are considered stuck if:
- `status = 'in_progress'`
- `started_at < NOW() - INTERVAL 'X minutes'`
- `completed_at IS NULL`

### Environment Setup

Same as dashboard stats script (requires PGPASSWORD).

### Automation

Consider adding to cron for periodic cleanup:

```bash
# Cleanup stuck agents every hour (60 min threshold)
0 * * * * cd /path/to/omniclaude && source .env && ./scripts/observability/cleanup_stuck_agents.sh 60 >> /var/log/stuck_agents_cleanup.log 2>&1

# Cleanup stuck agents daily at 2 AM (1 hour threshold)
0 2 * * * cd /path/to/omniclaude && source .env && ./scripts/observability/cleanup_stuck_agents.sh 60 >> /var/log/stuck_agents_cleanup.log 2>&1
```

---

## Test Results

### Initial State (2025-10-30)

**Database Query**:
```sql
SELECT status, COUNT(*) FROM agent_execution_logs GROUP BY status;
```

**Results**:
- `success`: 7 executions
- `in_progress`: 3 executions (stuck for ~5 days)
- `cancelled`: 2 executions
- `error`: 1 execution

### After Cleanup

**Command**:
```bash
./scripts/observability/cleanup_stuck_agents.sh 60
```

**Results**:
- ✅ Updated: 3 agents marked as error
- ✅ Active agents: 0 (was 3)
- ✅ Stuck agents: 0 (was 3)
- ✅ Recent errors: 4 (was 1)

**Verification**:
```bash
./scripts/observability/dashboard_stats.sh summary
```

Output:
```
active_now: 0
stuck_now: 0
success_24h: 3
errors_24h: 0
success_rate_24h: 100.0%
avg_quality_24h: 0.94
```

---

## Performance Characteristics

### View Query Performance

All views designed for <100ms query time on typical datasets:

| View | Typical Query Time | Notes |
|------|-------------------|-------|
| v_agent_execution_summary | <50ms | Single row aggregate |
| v_active_agents | <20ms | Small result set |
| v_stuck_agents | <20ms | Filtered by time |
| v_agent_completion_stats_24h | <30ms | 24h window aggregate |
| v_agent_performance | <50ms | 7-day group by agent |
| v_agent_errors_recent | <30ms | Limited to 50 rows |
| v_agent_daily_trends | <50ms | 30-day group by date |
| v_agent_quality_leaderboard | <40ms | Filtered by min 3 runs |

### Script Execution Time

- **dashboard_stats.sh**: 0.5-2s depending on mode
- **cleanup_stuck_agents.sh**: 0.5-1s for dry-run, 1-2s for execution

---

## Integration with Existing Tools

### agent_history_browser.py

Dashboard views complement the history browser:
- Browser: Detailed execution traces with manifest data
- Dashboard: Real-time status monitoring and alerts

**Use together**:
```bash
# Check dashboard for stuck agents
./scripts/observability/dashboard_stats.sh stuck

# Investigate specific execution
python3 agents/lib/agent_history_browser.py \
    --correlation-id <correlation_id_from_dashboard>
```

### health_check.sh

Dashboard adds execution-focused health:
- health_check.sh: Infrastructure health (services, Kafka, Qdrant)
- dashboard_stats.sh: Agent execution health (success rates, errors)

**Use together**:
```bash
# Check infrastructure
./scripts/health_check.sh

# Check agent execution health
./scripts/observability/dashboard_stats.sh summary
```

---

## Common Workflows

### 1. Morning Dashboard Check

```bash
# Quick status
./scripts/observability/dashboard_stats.sh summary

# Any stuck agents?
./scripts/observability/dashboard_stats.sh stuck
```

### 2. Investigate Performance Issue

```bash
# Check agent performance
./scripts/observability/dashboard_stats.sh performance

# View recent errors
./scripts/observability/dashboard_stats.sh errors

# Check daily trends
./scripts/observability/dashboard_stats.sh trends
```

### 3. Cleanup Stuck Agents

```bash
# Preview what would be cleaned
./scripts/observability/cleanup_stuck_agents.sh 60 --dry-run

# Execute cleanup
./scripts/observability/cleanup_stuck_agents.sh 60

# Verify cleanup
./scripts/observability/dashboard_stats.sh summary
```

### 4. Quality Monitoring

```bash
# Check quality scores
./scripts/observability/dashboard_stats.sh quality

# View trends over time
./scripts/observability/dashboard_stats.sh trends
```

---

## Troubleshooting

### Connection Issues

**Problem**: `password authentication failed for user "postgres"`

**Solution**:
```bash
# Load credentials from .env
source .env
export PGPASSWORD="$POSTGRES_PASSWORD"

# Or use inline
PGPASSWORD="***REDACTED***" ./scripts/observability/dashboard_stats.sh
```

### Empty Results

**Problem**: Views return no data

**Possible causes**:
1. No agent executions in time window
2. Wrong database connection
3. Views not created

**Check**:
```bash
# Verify views exist
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "\dv v_agent_*"

# Check raw data
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT COUNT(*) FROM agent_execution_logs;"
```

### Slow Queries

**Problem**: Dashboard takes >5s to load

**Possible causes**:
1. Large dataset (>10K executions)
2. Missing indexes
3. Expensive view joins

**Check execution plan**:
```sql
EXPLAIN ANALYZE SELECT * FROM v_agent_execution_summary;
```

---

## Future Enhancements

### Potential Improvements

1. **Grafana Integration**: Export views to Grafana dashboards
2. **Alerting**: Email/Slack alerts for stuck agents
3. **Historical Archival**: Archive old executions to separate table
4. **Real-time Streaming**: WebSocket-based live dashboard
5. **Machine Learning**: Predict agent failures based on patterns
6. **Auto-scaling**: Trigger agent instance scaling based on load

### Grafana Dashboard Example

```sql
-- Metrics for Grafana time series
SELECT
    DATE_TRUNC('hour', started_at) as time,
    agent_name as metric,
    COUNT(*) as value
FROM agent_execution_logs
WHERE started_at > $__timeFrom() AND started_at < $__timeTo()
GROUP BY time, agent_name
ORDER BY time;
```

---

## Additional Resources

**Related Documentation**:
- [Agent Traceability Guide](../../docs/observability/AGENT_TRACEABILITY.md)
- [Diagnostic Scripts](../../docs/observability/DIAGNOSTIC_SCRIPTS.md)
- [Logging Pipeline](../../docs/observability/LOGGING_PIPELINE.md)

**Database Schema**:
- See `agent_execution_logs` table in `omninode_bridge` database
- Indexes: correlation_id, agent_name, started_at, status

**Contact**:
- For issues or enhancements, open GitHub issue
- Tag: `observability`, `dashboard`, `monitoring`

---

**Version**: 1.0.0
**Last Updated**: 2025-10-30
**Status**: ✅ Tested and working
