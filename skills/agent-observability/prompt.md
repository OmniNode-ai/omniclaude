# Agent Observability Skills

Real-time monitoring and diagnostics for the OmniClaude agent execution system. These skills provide comprehensive health monitoring, error analysis, and performance insights.

## Available Skills

### 1. check-health
**Quick 5-second health check**

```bash
/agent-observability/check-health
```

**Output:**
- Overall system health status (🟢 🟡 🔴)
- Last 24 hours execution summary
- Success rate and error count
- Unprocessed hook events
- Routing intelligence stats
- Recent errors (last hour)
- Critical alerts and recommended actions

**Use when:**
- Starting a new work session
- After major system changes
- Before production deployments
- Need quick status check

---

### 2. diagnose-errors
**Deep error pattern analysis**

```bash
/agent-observability/diagnose-errors [--time-range TIME] [--agent AGENT]
```

**Arguments:**
- `--time-range`: 1h, 24h, 7d, 30d (default: 24h)
- `--agent`: Filter by specific agent name (optional)

**Output:**
- Error type distribution
- Failed agent analysis
- Error rate timeline (hourly)
- Recent error examples with messages
- Actionable recommendations

**Use when:**
- Health check shows elevated error rates
- Investigating specific failure patterns
- Root cause analysis needed
- Error rate > 20%

**Examples:**
```bash
# Last 24 hours all agents
/agent-observability/diagnose-errors

# Last 7 days for specific agent
/agent-observability/diagnose-errors --time-range 7d --agent agent-research

# Last hour (real-time issues)
/agent-observability/diagnose-errors --time-range 1h
```

---

### 3. generate-report
**Comprehensive observability analysis**

```bash
/agent-observability/generate-report [--time-range TIME]
```

**Arguments:**
- `--time-range`: 24h, 7d, 30d (default: 7d)

**Output:**
- Executive summary with key metrics
- Success rate and duration analysis (P50, P95, P99)
- Agent usage patterns and rankings
- Routing intelligence distribution
- Hook event processing status
- Daily trends and comparisons
- Correlation tracking stats
- Key insights and recommendations

**Use when:**
- Weekly/monthly reporting
- Comprehensive system analysis
- Before major deployments
- Performance review meetings
- Trend analysis needed

**Examples:**
```bash
# Weekly report (default)
/agent-observability/generate-report

# Last 30 days
/agent-observability/generate-report --time-range 30d

# Last 24 hours only
/agent-observability/generate-report --time-range 24h
```

---

### 4. check-agent
**Agent-specific performance profiling**

```bash
/agent-observability/check-agent --agent AGENT_NAME [--time-range TIME]
```

**Arguments:**
- `--agent`: Agent name (required)
- `--time-range`: 1h, 24h, 7d (default: 24h)

**Output:**
- Agent-specific health status
- Performance metrics (success rate, duration, P50/P95)
- Comparison to system baseline
- Error analysis for this agent
- Hourly activity trend
- Recent execution history
- Performance insights and recommendations

**Use when:**
- Agent-specific troubleshooting
- Performance regression investigation
- Optimizing specific agent
- Agent development and testing

**Examples:**
```bash
# Analyze research agent
/agent-observability/check-agent --agent agent-research

# Check commit agent last hour
/agent-observability/check-agent --agent agent-commit --time-range 1h

# 7-day analysis
/agent-observability/check-agent --agent agent-workflow-coordinator --time-range 7d
```

---

## Database Tables Monitored

### agent_execution_logs
Core execution tracking with status, duration, quality scores, and error details.

### agent_routing_decisions
Agent detection and routing intelligence with confidence scores and methods.

### hook_events
Hook event processing status, retry counts, and processing errors.

### agent_detection_failures
Failed agent detection attempts for debugging routing issues.

---

## Alert Thresholds

### 🔴 CRITICAL
- Success rate < 70%
- Unprocessed hook events > 200
- P95 duration > 120,000ms
- Error rate > 30%

### 🟡 WARNING
- Success rate < 80%
- Unprocessed hook events > 50
- P95 duration > 60,000ms
- Error rate > 20%
- Hook event retry count > 3

### 🟢 HEALTHY
- Success rate ≥ 90%
- Unprocessed events < 50
- P95 duration < 30,000ms
- Error rate < 10%

---

## Recommended Workflow

### Daily Monitoring
```bash
# Morning health check
/agent-observability/check-health

# If issues detected
/agent-observability/diagnose-errors --time-range 24h
```

### Weekly Review
```bash
# Comprehensive weekly report
/agent-observability/generate-report --time-range 7d
```

### Incident Investigation
```bash
# Quick health check
/agent-observability/check-health

# Error diagnosis
/agent-observability/diagnose-errors --time-range 1h

# Agent-specific analysis if needed
/agent-observability/check-agent --agent [failing-agent]
```

### Agent Development
```bash
# Before changes
/agent-observability/check-agent --agent agent-name --time-range 7d

# After changes
/agent-observability/check-agent --agent agent-name --time-range 1h

# Compare metrics to baseline
```

---

## Output Format

All skills output structured markdown optimized for Claude readability:

- **Headers**: Clear section hierarchy
- **Tables**: Metrics in tabular format with units
- **Indicators**: Emoji status (🟢 🟡 🔴 ✅ ⚠️ 🚨)
- **Code blocks**: SQL/JSON when relevant
- **Comparisons**: vs baseline, vs previous period
- **Actionable**: Clear recommendations at end

---

## Performance Targets

- **check-health**: < 5 seconds
- **diagnose-errors**: < 15 seconds
- **generate-report**: < 30 seconds
- **check-agent**: < 10 seconds

---

## Integration with Agent-Observability

The `agent-observability` agent uses these skills automatically when invoked:

```
User: "What's the agent system status?"
→ Dispatches to agent-observability
→ Runs check-health
→ Surfaces findings

User: "Diagnose recent agent failures"
→ Dispatches to agent-observability
→ Runs diagnose-errors --time-range 24h
→ Provides analysis and recommendations
```

---

## Database Connection

Skills use shared database helper with connection pooling:
- **Host**: localhost:5436
- **Database**: omninode_bridge
- **User**: postgres
- **Password**: From environment (DB_PASSWORD)

Connection pooling managed by `skills/_shared/db_helper.py` for optimal performance.
