# Quick Reference: Observability Script Exit Codes

## TL;DR

All observability scripts now return standardized exit codes:

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| **0** | ✅ Success | Continue normally |
| **1** | ⚠️ Degraded | Alert but continue |
| **2** | 🔴 Critical | Halt deployment / page on-call |
| **3** | ❌ Config Error | Fix .env configuration |
| **4** | ❌ Dependency Missing | Install psql/kcat/docker |

## Quick Usage

```bash
# Run health check
./scripts/health_check.sh

# Check exit code
echo $?

# Use in automation
if ./scripts/health_check.sh; then
    echo "System healthy, proceed"
else
    exit_code=$?
    case $exit_code in
        1) echo "System degraded, continue with warning" ;;
        2) echo "CRITICAL: System down, halt"; exit 1 ;;
        3) echo "Configuration error, fix .env"; exit 1 ;;
        4) echo "Install dependencies"; exit 1 ;;
    esac
fi
```

## Updated Scripts

1. **health_check.sh** - System-wide health (0/1/2/3)
2. **dashboard_stats.sh** - Agent execution dashboard (0/1/3/4)
3. **agent_activity_dashboard.sh** - Agent activity stats (0/1/3/4)
4. **monitor_routing_health.sh** - Routing health monitoring (0/1/3/4)
5. **diagnose_agent_logging.sh** - Logging diagnostics (0/1/2/3/4)

## Full Documentation

- **Standard**: `scripts/observability/EXIT_CODES.md`
- **Implementation**: `scripts/observability/EXIT_CODE_IMPLEMENTATION.md`
- **Help**: Run any script with `--help` flag

## Examples

### CI/CD Integration

```yaml
# GitHub Actions
- name: Health Check
  run: |
    if ! ./scripts/health_check.sh; then
      exit_code=$?
      if [ $exit_code -eq 2 ]; then
        echo "Critical failure, failing build"
        exit 1
      fi
    fi
```

### Monitoring Wrapper

```bash
#!/bin/bash
./scripts/health_check.sh
exit_code=$?
curl -X POST "http://monitoring/metrics" -d "exit_code=$exit_code"
exit $exit_code
```

## Testing

```bash
# Verify all scripts have exit code documentation
grep -l "Exit Codes" scripts/observability/*.sh scripts/health_check.sh

# Test exit codes
./scripts/health_check.sh && echo "Exit 0: Healthy"
./scripts/observability/dashboard_stats.sh invalid && echo "Exit $?: Error"
```

---

**Created**: 2025-11-23
**Status**: ✅ Production Ready
