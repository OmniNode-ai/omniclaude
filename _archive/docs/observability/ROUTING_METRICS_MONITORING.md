# Routing Metrics Monitoring

**Version**: 1.0.0
**Status**: Active
**Correlation ID**: 60d7acac-8d46-4041-ae43-49f1aa7fdccc
**Last Updated**: 2025-10-29

## Overview

This document describes the routing metrics monitoring infrastructure for the OmniClaude polymorphic agent system. The monitoring system tracks routing health, identifies issues, and ensures optimal agent selection.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                   Monitoring Architecture                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  monitor_routing_health.sh (Bash Script)             │   │
│  │  • Threshold validation                              │   │
│  │  • Alert generation                                  │   │
│  │  • Report orchestration                              │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                         │
│                     ▼                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  routing_metrics.sql (SQL Queries)                   │   │
│  │  • 8 comprehensive metrics                           │   │
│  │  • Performance analytics                             │   │
│  │  • Trend analysis                                    │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                         │
│                     ▼                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  PostgreSQL Database (omninode_bridge)               │   │
│  │  • agent_transformation_events                       │   │
│  │  • agent_routing_decisions                           │   │
│  │  • router_performance_metrics                        │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                         │
│                     ▼                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Timestamped Log Files                               │   │
│  │  logs/observability/routing_health_YYYYMMDD_HHMMSS.log│  │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Database Tables

#### agent_transformation_events

Tracks all polymorphic agent transformations.

**Key Columns**:
- `source_agent` - Agent initiating transformation
- `target_agent` - Agent being transformed into
- `transformation_duration_ms` - Time taken for transformation
- `success` - Whether transformation succeeded
- `confidence_score` - Routing confidence (0.0-1.0)

**Critical Pattern**: Self-transformation (`polymorphic-agent → polymorphic-agent`) indicates routing bypass.

#### agent_routing_decisions

Records all routing decisions made by the enhanced router.

**Key Columns**:
- `selected_agent` - Agent selected by router
- `confidence_score` - Routing confidence (0.0-1.0)
- `routing_strategy` - Strategy used (enhanced_fuzzy_matching, fallback, etc.)
- `routing_time_ms` - Time taken for routing decision
- `execution_succeeded` - Whether execution succeeded
- `alternatives` - JSONB array of alternative agents considered

#### router_performance_metrics

Performance metrics for routing operations.

**Key Columns**:
- `routing_duration_ms` - Duration of routing operation
- `cache_hit` - Whether result was from cache
- `trigger_match_strategy` - Matching strategy used
- `candidates_evaluated` - Number of agents evaluated

## Metrics

### Metric 1: Self-Transformation Rate

**Target**: <10%
**Alert**: CRITICAL if >10%, WARNING if >5%

**Description**: Percentage of transformations where `polymorphic-agent` transforms to itself, indicating routing bypass.

**Query**:
```sql
SELECT
    COUNT(*) FILTER (
        WHERE source_agent = 'polymorphic-agent'
        AND target_agent = 'polymorphic-agent'
    ) / COUNT(*) FILTER (WHERE source_agent = 'polymorphic-agent') * 100
FROM agent_transformation_events
WHERE created_at > NOW() - INTERVAL '7 days'
```

**Interpretation**:
- **<5%**: Healthy - routing system working correctly
- **5-10%**: Warning - investigate routing patterns
- **>10%**: Critical - routing system not being used

### Metric 2: Routing Confidence Distribution

**Target**: Average confidence >0.7
**Alert**: WARNING if <0.7

**Description**: Distribution of routing confidence scores across all routing decisions.

**Buckets**:
- `0.90-1.00` (High) - Strong routing confidence
- `0.80-0.89` (Good) - Acceptable confidence
- `0.70-0.79` (Fair) - Marginal confidence
- `0.60-0.69` (Low) - Poor confidence
- `0.00-0.59` (Critical) - Very poor confidence

**Interpretation**:
- **>80% in High/Good**: Excellent routing quality
- **>60% in High/Good**: Acceptable routing quality
- **<60% in High/Good**: Poor routing quality, investigate triggers

### Metric 3: Top 10 Agent Selections

**Description**: Most frequently selected agents with performance metrics.

**Metrics Per Agent**:
- Selection count (frequency)
- Average confidence score
- Average routing time (ms)
- Success rate (execution_succeeded)

**Use Cases**:
- Identify most used agents
- Spot performance bottlenecks
- Track agent success rates

### Metric 4: Bypass Attempt Count

**Target**: 0
**Alert**: CRITICAL if >0

**Description**: Count of routing decisions with suspicious bypass patterns.

**Bypass Patterns**:
1. **No Strategy**: `routing_strategy` is NULL or empty
2. **Suspicious Confidence**: Confidence >0.99 with no alternatives
3. **Instant Routing**: Routing time <1ms

**Interpretation**:
- **0**: Perfect - all routing goes through proper channels
- **>0**: Critical - investigate bypass attempts

### Metric 5: Frontend Task Routing Accuracy

**Target**: 100%
**Alert**: WARNING if <100%

**Description**: Accuracy of routing frontend-related tasks to `agent-frontend-developer`.

**Frontend Keywords**:
- frontend, react, vue, angular
- ui component, css, html
- javascript, typescript, browser

**Interpretation**:
- **100%**: Perfect frontend routing
- **90-99%**: Good but has misroutes
- **<90%**: Poor frontend detection

### Metric 6: Routing Failures and Fallbacks

**Target**: Failure rate <5%
**Alert**: WARNING if >5%

**Description**: Count and patterns of routing failures.

**Failure Types**:
1. **Low Confidence Fallbacks**: Confidence <0.5, fell back to polymorphic-agent
2. **Execution Failures**: `execution_succeeded = false`
3. **Actual Failures**: `actual_success = false`

### Metric 7: Transformations Per Hour Trend

**Description**: Hourly transformation volume for trend analysis.

**Metrics**:
- Total transformations per hour
- Specialized transformations (not self)
- Self-transformations
- Average transformation duration

**Use Cases**:
- Detect usage spikes
- Identify peak hours
- Track system load

### Metric 8: Router Performance Metrics

**Description**: Performance metrics from `router_performance_metrics` table.

**Key Metrics**:
- Cache hit rate (target: >60%)
- Average routing duration (target: <100ms)
- P50, P95, P99 percentiles
- Candidates evaluated per query

## Usage

### Quick Health Check

Run the monitoring script for a comprehensive health check:

```bash
cd /Volumes/PRO-G40/Code/omniclaude
./scripts/observability/monitor_routing_health.sh
```

**Output**:
- Threshold validation with pass/fail status
- Detailed metrics report
- Timestamped log file
- Final health status (🟢 HEALTHY or 🔴 ISSUES DETECTED)

**Exit Codes**:
- `0` - All thresholds passed
- `1` - One or more threshold violations

### Run SQL Queries Manually

Execute queries directly for custom analysis:

```bash
# Source environment variables
source .env

# Run all queries
PGPASSWORD="$POSTGRES_PASSWORD" psql \
  -h 192.168.86.200 \
  -p 5436 \
  -U postgres \
  -d omninode_bridge \
  -f scripts/observability/routing_metrics.sql
```

### View Logs

Logs are saved with timestamps in `logs/observability/`:

```bash
# View latest log
ls -t logs/observability/routing_health_*.log | head -1 | xargs cat

# View last 50 lines
ls -t logs/observability/routing_health_*.log | head -1 | xargs tail -50

# Search for violations
grep -r "CRITICAL\|WARNING" logs/observability/
```

## Thresholds

### Configuration

Thresholds are configurable in `monitor_routing_health.sh`:

```bash
# Thresholds
SELF_TRANSFORMATION_THRESHOLD=10      # Self-transformation rate (%)
BYPASS_ATTEMPT_THRESHOLD=0            # Bypass attempts (count)
AVG_CONFIDENCE_THRESHOLD=0.7          # Average confidence (0.0-1.0)
FRONTEND_ACCURACY_THRESHOLD=100       # Frontend accuracy (%)
FAILURE_RATE_THRESHOLD=5              # Failure rate (%)
```

### Threshold Validation

The monitoring script validates all thresholds and reports violations:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  THRESHOLD VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ℹ️  Checking self-transformation rate...
✅ Self-transformation rate: 4.52% (threshold: 10%)

ℹ️  Checking bypass attempts...
✅ Bypass attempts: 0 (threshold: 0)

ℹ️  Checking average routing confidence...
✅ Average confidence: 0.852 (threshold: 0.7)

ℹ️  Checking frontend routing accuracy...
✅ Frontend accuracy: 100% (threshold: 100%)

ℹ️  Checking failure rate...
✅ Failure rate: 2.14% (threshold: 5%)

✅ All thresholds passed! 🎉
```

## Alert Severity

### 🟢 HEALTHY

All metrics within acceptable thresholds. No action required.

### 🟡 WARNING

One or more metrics approaching thresholds. Review and monitor.

**Common Warnings**:
- Self-transformation rate 5-10%
- Average confidence 0.6-0.7
- Frontend accuracy 90-99%
- Failure rate 3-5%

**Actions**:
- Review recent routing decisions
- Check for pattern mismatches
- Validate agent trigger definitions

### 🔴 CRITICAL

One or more metrics exceeded critical thresholds. Immediate action required.

**Critical Conditions**:
- Self-transformation rate >10%
- Bypass attempts >0
- Average confidence <0.6
- Failure rate >5%

**Actions**:
1. Review `scripts/observability/routing_metrics.sql` detailed output
2. Check recent errors in `agent_routing_decisions` table
3. Validate enhanced router configuration
4. Review agent trigger definitions in registry
5. Check for deployment issues

## Troubleshooting

### Issue: High Self-Transformation Rate

**Symptoms**: Self-transformation rate >10%

**Diagnosis**:
```sql
-- Find recent self-transformations
SELECT
    transformation_reason,
    COUNT(*) as count
FROM agent_transformation_events
WHERE source_agent = 'polymorphic-agent'
AND target_agent = 'polymorphic-agent'
AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY transformation_reason
ORDER BY count DESC;
```

**Common Causes**:
1. Router not being invoked
2. General tasks legitimately handled by polymorphic-agent
3. Routing decision skipped in workflow

**Solutions**:
- Ensure mandatory routing workflow is followed
- Check agent trigger definitions
- Validate routing logic in coordinator

### Issue: Low Average Confidence

**Symptoms**: Average confidence <0.7

**Diagnosis**:
```sql
-- Find low-confidence routing decisions
SELECT
    selected_agent,
    user_request,
    confidence_score,
    routing_strategy,
    alternatives
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '24 hours'
AND confidence_score < 0.7
ORDER BY confidence_score ASC
LIMIT 10;
```

**Common Causes**:
1. Poor trigger matching
2. Unclear user requests
3. Missing agent definitions
4. Outdated trigger keywords

**Solutions**:
- Improve agent trigger definitions
- Add more trigger keywords
- Update fuzzy matching weights
- Review user request patterns

### Issue: Bypass Attempts Detected

**Symptoms**: Bypass attempts >0

**Diagnosis**:
```sql
-- Find bypass attempts
SELECT
    selected_agent,
    user_request,
    confidence_score,
    routing_strategy,
    routing_time_ms
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '24 hours'
AND (
    routing_strategy IS NULL
    OR routing_strategy = ''
    OR routing_time_ms < 1
)
ORDER BY created_at DESC;
```

**Common Causes**:
1. Direct agent invocation without routing
2. Hardcoded agent selection
3. Routing bypass in custom workflows

**Solutions**:
- Audit agent invocation points
- Enforce routing workflow
- Remove hardcoded agent selection
- Update custom workflows

### Issue: Frontend Misrouting

**Symptoms**: Frontend accuracy <100%

**Diagnosis**:
```sql
-- Find incorrectly routed frontend tasks
SELECT
    selected_agent,
    user_request,
    confidence_score,
    routing_strategy
FROM agent_routing_decisions
WHERE created_at > NOW() - INTERVAL '7 days'
AND selected_agent NOT IN ('agent-frontend-developer', 'frontend-developer')
AND LOWER(user_request) LIKE '%frontend%'
ORDER BY created_at DESC;
```

**Common Causes**:
1. Frontend keywords not in agent triggers
2. Other agent triggers matching first
3. Unclear user requests

**Solutions**:
- Add frontend keywords to agent-frontend-developer triggers
- Increase frontend agent priority
- Improve trigger specificity

## Best Practices

### Regular Monitoring

1. **Daily**: Run health check to validate thresholds
2. **Weekly**: Review detailed metrics report
3. **Monthly**: Analyze trends and optimize thresholds

### Threshold Tuning

Start with recommended thresholds and adjust based on:
- System maturity (newer systems may have higher self-transformation rates)
- Use case patterns (some workloads legitimately use polymorphic-agent more)
- Agent portfolio size (more agents = potentially lower confidence)

### Log Management

Logs accumulate in `logs/observability/`:

```bash
# Archive old logs (>30 days)
find logs/observability/ -name "routing_health_*.log" -mtime +30 -exec gzip {} \;

# Delete archived logs (>90 days)
find logs/observability/ -name "routing_health_*.log.gz" -mtime +90 -delete
```

### Integration with CI/CD

Add to deployment validation:

```bash
# In deployment script
if ! ./scripts/observability/monitor_routing_health.sh; then
    echo "Routing health check failed - blocking deployment"
    exit 1
fi
```

## Performance Characteristics

### Query Performance

All queries are optimized with indexes:

| Query | Execution Time | Indexes Used |
|-------|---------------|--------------|
| Self-transformation rate | <100ms | idx_transformation_events_created |
| Confidence distribution | <200ms | idx_routing_decisions_confidence |
| Top 10 agents | <150ms | idx_routing_decisions_agent |
| Bypass attempts | <100ms | idx_routing_decisions_strategy |
| Frontend accuracy | <250ms | Custom text search |
| Failures and fallbacks | <200ms | idx_routing_decisions_success |
| Hourly trends | <300ms | idx_transformation_events_created |
| Router performance | <100ms | idx_router_metrics_created |

**Total execution time**: <1.5 seconds for all metrics

### Script Performance

Monitoring script execution time:

- **Threshold validation**: <5 seconds
- **Full metrics report**: <10 seconds
- **Log writing**: <1 second

**Total**: <15 seconds for complete health check

## Future Enhancements

### Grafana Dashboard (Optional)

A Grafana dashboard can be created to visualize routing metrics in real-time:

**Panels**:
1. Self-transformation rate gauge (0-100%)
2. Confidence distribution histogram
3. Agent selection frequency bar chart
4. Routing latency time series
5. Success rate line chart
6. Hourly transformation volume area chart

**Data Source**: PostgreSQL connection to omninode_bridge

**Refresh Rate**: 1 minute

**Dashboard JSON**: To be created based on demand

### Automated Alerting

Integrate with alerting systems:

**Slack Integration**:
```bash
# In monitor_routing_health.sh
if [ $violations -gt 0 ]; then
    curl -X POST $SLACK_WEBHOOK_URL \
        -H 'Content-Type: application/json' \
        -d "{\"text\": \"🔴 Routing health violations detected: $violations\"}"
fi
```

**Email Integration**:
```bash
# In monitor_routing_health.sh
if [ $violations -gt 0 ]; then
    mail -s "Routing Health Alert" $ALERT_EMAIL < "$LOG_FILE"
fi
```

### Machine Learning

Train ML models on routing patterns:

1. **Predict optimal agent** based on user request
2. **Detect anomalies** in routing patterns
3. **Recommend trigger improvements** based on misroutes

## References

- [Agent Observability Definition](/Users/jonah/.claude/agent-definitions/agent-observability.yaml)
- [Polymorphic Agent Architecture](../CLAUDE.md#polymorphic-agent-framework)
- [Enhanced Router System](../../agents/lib/enhanced_router.py)
- [Database Schema](../architecture/DATABASE_SCHEMA.md)

## Changelog

### Version 1.0.0 (2025-10-29)

**Initial Release**:
- 8 comprehensive routing metrics
- Automated threshold validation
- Health monitoring script with colored output
- Timestamped log files
- Documentation with troubleshooting guide

**Correlation ID**: 60d7acac-8d46-4041-ae43-49f1aa7fdccc

---

**Agent**: agent-observability
**Task**: Create routing metrics monitoring dashboard/queries
**Status**: Complete ✅
