# Observability Scripts Exit Code Standard

**Version**: 1.0.0
**Last Updated**: 2025-11-23

## Purpose

This document defines the standardized exit code system for all observability scripts in `scripts/observability/` and related monitoring scripts.

**Why standardized exit codes matter**:
- ✅ Enables automation and CI/CD integration
- ✅ Allows programmatic detection of failures
- ✅ Supports monitoring and alerting systems
- ✅ Provides consistent behavior across all scripts
- ✅ Facilitates error handling in calling scripts

## Exit Code Standard

All observability scripts MUST use the following exit codes:

| Exit Code | Name | Meaning | When to Use |
|-----------|------|---------|-------------|
| **0** | Success | All checks passed, system healthy | All validation checks passed, no issues detected |
| **1** | Degraded | Some checks failed, system degraded | Non-critical issues found, system partially functional |
| **2** | Critical | Critical failure, system unavailable | Critical services down, data loss risk, security issues |
| **3** | Config Error | Configuration error, can't run checks | Missing .env file, invalid config, missing required variables |
| **4** | Dependency Missing | Required dependency not installed | psql, kcat, docker, or other required tool not found |

## Implementation Guidelines

### Exit Code Selection Logic

Use this decision tree to determine the appropriate exit code:

```
Can the script run?
  ├─ No → Check why
  │   ├─ Missing .env or config → exit 3
  │   └─ Missing psql/kcat/docker → exit 4
  │
  └─ Yes → Run checks
      ├─ All checks passed → exit 0
      ├─ Some non-critical issues → exit 1
      └─ Critical services down → exit 2
```

### Exit Code Examples

#### Exit 0: Success
```bash
✅ All systems healthy
✅ PostgreSQL: connected
✅ Kafka: connected
✅ All services running
exit 0
```

#### Exit 1: Degraded
```bash
❌ Issues Found: 2
  - Qdrant has no collections (warning)
  - Query time above target (3500ms > 2000ms)
exit 1
```

#### Exit 2: Critical
```bash
❌ Critical Issues: 1
  - PostgreSQL: connection failed (database unavailable)
exit 2
```

#### Exit 3: Configuration Error
```bash
❌ ERROR: .env file not found
❌ ERROR: Required variables not set: POSTGRES_PASSWORD
exit 3
```

#### Exit 4: Dependency Missing
```bash
❌ ERROR: psql command not found
   Please install PostgreSQL client
exit 4
```

## Implementation Pattern

### Basic Template

```bash
#!/bin/bash
# Exit codes:
#   0 - All checks passed
#   1 - Some checks failed (degraded)
#   2 - Critical failure
#   3 - Configuration error
#   4 - Dependency missing

set -euo pipefail

# Track results
exit_code=0
checks_passed=0
checks_failed=0
critical_failures=0

# Check prerequisites first
if [ ! -f ".env" ]; then
    echo "❌ Configuration error: .env not found"
    exit 3
fi

if ! command -v psql &> /dev/null; then
    echo "❌ Dependency missing: psql not installed"
    exit 4
fi

# Perform checks (disable exit on error)
set +e

if some_critical_check; then
    checks_passed=$((checks_passed + 1))
else
    checks_failed=$((checks_failed + 1))
    critical_failures=$((critical_failures + 1))
    exit_code=2  # Critical failure
fi

if some_normal_check; then
    checks_passed=$((checks_passed + 1))
else
    checks_failed=$((checks_failed + 1))
    if [ $exit_code -eq 0 ]; then
        exit_code=1  # Degraded (only if not already critical)
    fi
fi

# Re-enable exit on error
set -e

# Print summary
echo "=== SUMMARY ==="
echo "Passed: $checks_passed"
echo "Failed: $checks_failed"

if [ $critical_failures -gt 0 ]; then
    echo "❌ CRITICAL: System unavailable"
elif [ $exit_code -eq 1 ]; then
    echo "⚠️  DEGRADED: Some checks failed"
else
    echo "✅ HEALTHY: All checks passed"
fi

exit $exit_code
```

### Critical vs Non-Critical Checks

**Critical Checks** (exit 2 on failure):
- Database connectivity failure
- Kafka broker unreachable
- Core services completely down
- Data corruption detected
- Security vulnerabilities found

**Non-Critical Checks** (exit 1 on failure):
- Performance degradation (query time above target)
- Warning thresholds exceeded
- Optional services down
- Empty collections (if system is new)
- Missing non-essential data

### Help Text Documentation

All scripts MUST document exit codes in their help text:

```bash
show_help() {
    cat << EOF
Usage: ./script_name.sh [options]

Exit Codes:
  0 - All checks passed, system healthy
  1 - Some checks failed, system degraded
  2 - Critical failure, system unavailable
  3 - Configuration error, can't run checks
  4 - Dependency missing (psql, kcat, etc.)

Examples:
  ./script_name.sh              # Run all checks
  ./script_name.sh --verbose    # Detailed output
EOF
}
```

## Script-Specific Guidelines

### Health Check Scripts

**Examples**: `health_check.sh`, `monitor_routing_health.sh`, `diagnose_agent_logging.sh`

**Exit Code Logic**:
- Exit 0: All services healthy, all metrics within thresholds
- Exit 1: Some services degraded, metrics above warning thresholds
- Exit 2: Critical services down (PostgreSQL, Kafka unreachable)
- Exit 3: Missing .env file or required variables
- Exit 4: psql, kcat, docker not installed

### Dashboard Scripts

**Examples**: `dashboard_stats.sh`, `agent_activity_dashboard.sh`

**Exit Code Logic**:
- Exit 0: Dashboard displayed successfully
- Exit 1: Invalid mode/argument, database query failed (non-fatal)
- Exit 3: Missing .env file or database credentials
- Exit 4: psql not installed

**Note**: Dashboards typically don't use exit 2 (critical) unless database is completely unreachable.

### Diagnostic Scripts

**Examples**: `diagnose_traceability.sh`, `diagnose_agent_logging.sh`

**Exit Code Logic**:
- Exit 0: All diagnostic checks passed
- Exit 1: Issues found but system functional
- Exit 2: Critical issues preventing system operation
- Exit 3: Configuration error
- Exit 4: Diagnostic tools missing

## Testing Exit Codes

### Manual Testing

```bash
# Test all exit codes
./script_name.sh && echo "Exit 0: Success"
./script_name.sh || echo "Exit $?: Failure"

# Test in automation
if ./script_name.sh; then
    echo "Health check passed"
else
    exit_code=$?
    case $exit_code in
        1) echo "System degraded, investigate" ;;
        2) echo "CRITICAL: System down, alert team" ;;
        3) echo "Configuration error, check .env" ;;
        4) echo "Install missing dependencies" ;;
    esac
fi
```

### CI/CD Integration

```yaml
# Example GitHub Actions workflow
- name: Run health check
  run: ./scripts/health_check.sh
  continue-on-error: false  # Fail build on any non-zero exit

- name: Run with conditional failure
  run: |
    ./scripts/health_check.sh || exit_code=$?
    if [ $exit_code -eq 2 ]; then
      echo "Critical failure, failing build"
      exit 1
    elif [ $exit_code -eq 1 ]; then
      echo "Degraded, continuing with warning"
    fi
```

### Monitoring Integration

```bash
#!/bin/bash
# Monitoring wrapper script

./scripts/health_check.sh
exit_code=$?

case $exit_code in
    0)
        echo "status=healthy|exit_code=0"
        # Send metrics to monitoring system
        ;;
    1)
        echo "status=degraded|exit_code=1"
        # Send alert to ops team
        ;;
    2)
        echo "status=critical|exit_code=2"
        # Send page to on-call
        ;;
    *)
        echo "status=error|exit_code=$exit_code"
        ;;
esac
```

## Migration Checklist

When updating existing scripts to use this standard:

- [ ] Add exit code documentation to script header comments
- [ ] Add exit code table to help text
- [ ] Implement exit code 3 for configuration errors
- [ ] Implement exit code 4 for dependency checks
- [ ] Distinguish between exit 1 (degraded) and exit 2 (critical)
- [ ] Add summary output before exit
- [ ] Test all exit code paths
- [ ] Update any wrapper scripts or CI/CD that call this script

## Compliance

**Required for**:
- All scripts in `scripts/observability/`
- `scripts/health_check.sh`
- Any script intended for automation or monitoring

**Recommended for**:
- All maintenance scripts
- All diagnostic tools
- CI/CD integration scripts

## References

- POSIX Exit Codes: https://www.gnu.org/software/bash/manual/html_node/Exit-Status.html
- Standard Exit Codes: 0 (success), 1-125 (errors), 126-255 (special meanings)
- This standard uses: 0-4 (compatible with POSIX and automation tools)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-11-23 | Initial standard created |

---

**Questions or Issues**: Contact the observability team or file an issue in the repository.
