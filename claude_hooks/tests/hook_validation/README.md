# Hook Validation Test Framework

Comprehensive testing and validation framework for the Claude Code hook system.

## Overview

This framework provides automated testing and validation for all hook enhancements:
- **SessionStart/SessionEnd hooks** - Session lifecycle management
- **Stop hook** - Response completion tracking
- **Enhanced metadata** - Enriched event metadata across all hooks
- **Performance validation** - Performance target verification
- **Integration testing** - End-to-end correlation flow testing

## Test Structure

```
hook_validation/
├── run_all_tests.sh                    # Master test runner
├── test_session_hooks.sh               # SessionStart/SessionEnd tests
├── test_stop_hook.sh                   # Stop hook tests
├── test_enhanced_metadata.sh           # Enhanced metadata tests
├── test_performance.py                 # Performance validation tests
├── test_integration.py                 # End-to-end integration tests
├── generate_validation_report.py       # Validation report generator
├── results/                            # Test results directory
└── README.md                           # This file
```

## Performance Targets

| Hook | Average | P95 | Target |
|------|---------|-----|--------|
| SessionStart | <50ms | <75ms | ✅ |
| SessionEnd | <50ms | <75ms | ✅ |
| Stop | <30ms | <45ms | ✅ |
| Metadata Overhead | <15ms | - | ✅ |
| Database Write | <10ms | - | ✅ |

## Quick Start

### Run All Tests

```bash
cd ~/.claude/hooks/tests/hook_validation
./run_all_tests.sh
```

This will:
1. Run all test suites
2. Generate test logs in `results/`
3. Generate validation report
4. Display test summary

### Run Individual Tests

```bash
# Session hooks only
./test_session_hooks.sh

# Stop hook only
./test_stop_hook.sh

# Enhanced metadata only
./test_enhanced_metadata.sh

# Performance tests only
python3 test_performance.py

# Integration tests only
python3 test_integration.py
```

### Generate Validation Report

```bash
# Markdown format (default)
python3 generate_validation_report.py > validation_report.md

# JSON format
python3 generate_validation_report.py --format json > validation_report.json
```

## Test Categories

### 1. Session Hooks Tests (`test_session_hooks.sh`)

Tests SessionStart and SessionEnd hook functionality:

- ✅ SessionStart basic functionality
- ✅ SessionStart database insertion
- ✅ SessionStart performance (<50ms avg)
- ✅ SessionEnd basic functionality
- ✅ SessionEnd session aggregation
- ✅ SessionEnd statistics calculation

**Example output:**
```
==========================================
Session Hooks Test Suite
==========================================

ℹ Test: SessionStart basic functionality
✓ SessionStart basic functionality
ℹ Test: SessionStart performance (<50ms)
✓ SessionStart performance: 35ms avg (target <50ms)
...
==========================================
Test Summary
==========================================
Tests Run:    5
Tests Passed: 5
Tests Failed: 0
```

### 2. Stop Hook Tests (`test_stop_hook.sh`)

Tests Stop hook functionality:

- ✅ Stop hook basic functionality
- ✅ Stop hook performance (<30ms avg)
- ✅ Stop hook correlation tracking
- ✅ Stop hook response metadata
- ✅ Stop hook graceful handling

**Performance target:** <30ms average, <45ms p95

### 3. Enhanced Metadata Tests (`test_enhanced_metadata.sh`)

Tests enhanced metadata tracking:

- ✅ PreToolUse enhanced metadata
- ✅ PostToolUse enhanced metadata
- ✅ UserPromptSubmit enhanced metadata
- ✅ Metadata overhead performance (<15ms)
- ✅ Metadata preservation across hooks

**Overhead target:** <15ms additional latency

### 4. Performance Tests (`test_performance.py`)

Comprehensive performance validation:

- ✅ SessionStart hook performance (100 iterations)
- ✅ SessionEnd hook performance (100 iterations)
- ✅ Stop hook performance (100 iterations)
- ✅ Metadata overhead measurement
- ✅ Concurrent operations (10 concurrent workers)

**Example output:**
```
==================================================
Hook Performance Test Suite
==================================================

ℹ Test: SessionStart hook performance
✓ SessionStart avg: 35.24ms (target <50ms)
✓ SessionStart p95: 48.52ms (target <75ms)

ℹ Test: SessionEnd hook performance
✓ SessionEnd avg: 42.81ms (target <50ms)
⚠ SessionEnd p95: 56.23ms (target <75ms)

Performance Results:
  ✓ session_start_avg: 35.24ms (threshold: 50ms)
  ✓ session_start_p95: 48.52ms (threshold: 75ms)
  ✓ session_end_avg: 42.81ms (threshold: 50ms)
  ⚠ session_end_p95: 56.23ms (threshold: 75ms)
```

### 5. Integration Tests (`test_integration.py`)

End-to-end integration validation:

- ✅ Full correlation flow (UserPromptSubmit → PreToolUse → PostToolUse → Stop)
- ✅ Correlation ID propagation
- ✅ Timeline verification (correct event ordering)
- ✅ Session lifecycle integration
- ✅ Graceful degradation

**Example output:**
```
==================================================
Hook Integration Test Suite
==================================================

ℹ Test: Full correlation flow
✓ Full correlation flow: All 4 hooks executed in correct order

ℹ Test: Correlation ID propagation
✓ Correlation ID propagation: All events share same correlation ID

ℹ Test: Timeline verification
✓ Timeline verification: Events ordered correctly
```

### 6. Validation Report (`generate_validation_report.py`)

Generates comprehensive validation report:

```markdown
# Hook System Validation Report

**Generated:** 2025-10-10 12:00:00 UTC

## Performance Validation

### Session Start
- **Status:** ✅
- **Average:** 35.24ms (target <50ms)
- **P95:** 48.52ms (target <75ms)

### Stop Hook
- **Status:** ✅
- **Average:** 28.31ms (target <30ms)
- **P95:** 42.10ms (target <45ms)

## Integration Validation
- **Status:** ✅
- **Events Logged:** 1,234
- **Full Traces:** 145
- **Coverage Rate:** 92%

## Recommendations

### 1. Optimize SessionEnd aggregation query
- **Category:** performance
- **Severity:** medium
- **Recommendation:** Add database index on metadata->>'session_id'

## Summary
- **Performance:** ✅ PASS
- **Integration:** ✅ PASS
- **Database:** ✅ PASS

🎉 **Overall Status:** All systems validated successfully!
```

## Requirements

### System Requirements

- PostgreSQL database (localhost:5436)
- Python 3.7+ with psycopg2
- Bash 4.0+

### Database Setup

The tests require the following database tables:
- `hook_events` - Hook event storage
- `service_sessions` - Session lifecycle tracking
- `event_metrics` - Event metrics (optional)

**Connection details:**
```
Host: localhost
Port: 5436
Database: omninode_bridge
User: postgres
Password: Set via PGPASSWORD environment variable
```

### Python Dependencies

```bash
pip install psycopg2-binary
```

## Test Results

Test results are stored in the `results/` directory:

```
results/
├── test_run_20251010_120000.log       # Master test log
├── session_hooks.log                  # Session hooks test log
├── stop_hook.log                      # Stop hook test log
├── enhanced_metadata.log              # Enhanced metadata test log
├── performance.log                    # Performance test log
├── integration.log                    # Integration test log
├── validation_report.md               # Validation report (markdown)
└── validation_report.json             # Validation report (JSON)
```

## Continuous Integration

### Running in CI/CD

```bash
#!/bin/bash
# ci-test-hooks.sh

set -e

# Run test suite
cd ~/.claude/hooks/tests/hook_validation
./run_all_tests.sh

# Generate reports
python3 generate_validation_report.py --format json > validation_report.json
python3 generate_validation_report.py > validation_report.md

# Check exit code
if [ $? -eq 0 ]; then
    echo "✅ All hook tests passed"
    exit 0
else
    echo "❌ Some hook tests failed"
    exit 1
fi
```

### GitHub Actions Example

```yaml
name: Hook Validation Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: ${PGPASSWORD}  # Set in GitHub Secrets
        ports:
          - 5436:5432

    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: pip install psycopg2-binary

      - name: Run hook validation tests
        run: |
          cd ~/.claude/hooks/tests/hook_validation
          ./run_all_tests.sh

      - name: Generate validation report
        run: |
          python3 generate_validation_report.py > validation_report.md

      - name: Upload test results
        uses: actions/upload-artifact@v2
        with:
          name: test-results
          path: results/
```

## Troubleshooting

### Database Connection Errors

If you see database connection errors:

```bash
# Check if PostgreSQL is running
PGPASSWORD="${PGPASSWORD}" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"

# If not running, start it:
# (command depends on your PostgreSQL setup)
```

### Performance Test Failures

If performance tests are failing:

1. Check system load: `top` or `htop`
2. Check database performance: `EXPLAIN ANALYZE` queries
3. Run tests during off-peak hours
4. Adjust thresholds in test files if needed

### Missing Python Dependencies

```bash
# Install required packages
pip install psycopg2-binary

# Or using requirements.txt
pip install -r requirements.txt
```

## Contributing

When adding new tests:

1. Follow existing naming conventions
2. Add test to `run_all_tests.sh`
3. Update this README
4. Ensure tests clean up after themselves
5. Use appropriate performance targets

## License

Part of the Claude Code hook system framework.
