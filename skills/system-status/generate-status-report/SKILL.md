---
name: generate-status-report
description: Comprehensive system status report with services, infrastructure, performance metrics, and recommendations
---

# Generate Status Report

Generate comprehensive system status report with complete metrics and analysis.

## What It Generates

- Complete system overview
- All services status
- Infrastructure health
- Performance metrics (1hr, 24hr, 7d)
- Recent activity summary
- Top agents and patterns
- Issues and recommendations
- Trend analysis
- Export formats: JSON, Markdown, HTML

## When to Use

- **Daily reports**: Automated daily status reports
- **Weekly reviews**: Comprehensive system review
- **Post-incident**: Document system state
- **Audits**: Compliance and audit documentation
- **Stakeholder updates**: Share system health status

## How to Use

```bash
# Generate JSON report
python3 ~/.claude/skills/system-status/generate-status-report/execute.py

# Generate Markdown report
python3 ~/.claude/skills/system-status/generate-status-report/execute.py \
  --format markdown \
  --output /tmp/system-status-report.md

# Include detailed trends
python3 ~/.claude/skills/system-status/generate-status-report/execute.py \
  --include-trends \
  --timeframe 7d
```

### Arguments

- `--format`: Output format (json, markdown, text) [default: json]
- `--output`: Output file path (stdout if not specified)
- `--include-trends`: Include trend analysis
- `--timeframe`: Data timeframe (1h, 24h, 7d) [default: 24h]

## Output Sections

1. **Executive Summary** - Overall system health and key metrics
2. **Service Health Matrix** - All services with status indicators
3. **Infrastructure Status** - Kafka, PostgreSQL, Qdrant health
4. **Performance Metrics** - Routing times, query latencies, throughput
5. **Recent Activity** - Agent executions, routing decisions, actions
6. **Top Agents** - Most frequently routed agents
7. **Pattern Discovery** - Collection stats and vector counts
8. **Issues & Recommendations** - Problems found and suggestions
9. **Trends** (optional) - Historical comparison and trends

## Example Markdown Output

```markdown
# System Status Report

**Generated**: 2025-11-12T14:30:00Z
**Timeframe**: 24 hours

## Executive Summary

- **System Health**: Healthy
- **Services Running**: 12/12
- **Agent Executions**: 452
- **Routing Decisions**: 890
- **Average Confidence**: 89%

## Service Health

| Service | Status | Uptime |
|---------|--------|--------|
| archon-intelligence | ✓ Healthy | 5d 3h |
| archon-qdrant | ✓ Healthy | 5d 3h |
...

## Issues

No critical issues found.

## Recommendations

1. Consider increasing Qdrant collection size
2. Monitor connection pool usage
```

## See Also

- **check-system-health** - Quick health check
- **diagnose-issues** - Detailed issue diagnosis
