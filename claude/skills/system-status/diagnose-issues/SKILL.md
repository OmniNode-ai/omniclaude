---
name: diagnose-issues
description: Identify and diagnose common system problems with actionable recommendations
---

# Diagnose Issues

Comprehensive system diagnostics to identify and diagnose problems across all components.

## What It Checks

- Service health issues (down, unhealthy, high restart count)
- Performance degradation (slow queries, high latency)
- Infrastructure connectivity failures
- Recent error patterns
- Resource constraints
- Configuration issues
- **Provides actionable recommendations**

## When to Use

- **After alerts**: Investigate system alerts
- **Performance issues**: Diagnose slowdowns
- **Service failures**: Find root causes
- **Pre-deployment**: Verify system ready for deployment
- **Regular maintenance**: Weekly health checks

## How to Use

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/diagnose-issues/execute.py
```

### Optional Arguments

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/system-status/diagnose-issues/execute.py \
  --severity critical,warning \
  --format text
```

**Arguments**:
- `--severity`: Filter by severity (critical, warning, info) [default: all]
- `--format`: Output format (json, text) [default: json]

## Example Output

```json
{
  "system_health": "degraded",
  "issues_found": 2,
  "critical": 0,
  "warnings": 2,
  "issues": [
    {
      "severity": "warning",
      "component": "archon-intelligence",
      "issue": "High query latency detected",
      "details": "Avg query time: 5200ms (target: <2000ms)",
      "recommendation": "Check Qdrant collection size and consider optimization",
      "auto_fix_available": false
    },
    {
      "severity": "warning",
      "component": "postgres",
      "issue": "Connection pool near capacity",
      "details": "Active connections: 85/100",
      "recommendation": "Consider increasing max_connections or optimizing queries",
      "auto_fix_available": false
    }
  ],
  "recommendations": [
    "Check Qdrant collection size and consider optimization",
    "Consider increasing max_connections or optimizing queries"
  ]
}
```

## Exit Codes

- `0` - No issues found
- `1` - Warnings found
- `2` - Critical issues found
- `3` - Execution error

## See Also

- **check-system-health** - Quick health overview
- **generate-status-report** - Comprehensive system report
