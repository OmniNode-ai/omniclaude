# Database System Verification Guide

## Overview

The `verify_database_system.sh` script provides comprehensive validation of the entire OmniNode database system, checking all 30 tables, 26 views, and validating schema, data integrity, and performance.

## Quick Start

```bash
# Run from project root
./scripts/verify_database_system.sh

# View generated report
cat /tmp/database_verification_latest.txt
```

## What It Checks

### 1. Connectivity (1 check)
- PostgreSQL connection to `omninode_bridge` database
- Validates credentials from `.env` file
- Uses external IP (192.168.86.200:5436) for host access

### 2. Schema Validation - Tables (29 checks)

**Core Agent Observability Tables (9)**:
- `agent_actions` - All agent tool calls, decisions, errors, successes
- `agent_routing_decisions` - Agent selection with confidence scores
- `agent_transformation_events` - Polymorphic agent transformations
- `agent_manifest_injections` - Complete manifest injection records
- `agent_execution_logs` - Execution lifecycle tracking
- `agent_prompts` - Agent prompts and context
- `agent_intelligence_usage` - Intelligence query tracking
- `agent_file_operations` - File operation history
- `agent_definitions` - Agent registry definitions

**Infrastructure & Metrics Tables (9)**:
- `router_performance_metrics` - Routing performance analytics
- `event_metrics` - Event processing metrics
- `event_processing_metrics` - Event processing performance
- `generation_performance_metrics` - Generation performance tracking
- `connection_metrics` - Connection pool metrics
- `service_sessions` - Service session tracking
- `error_tracking` - Error event tracking
- `alert_history` - Alert history
- `security_audit_log` - Security audit trail

**Pattern & Quality Tables (7)**:
- `pattern_quality_metrics` - Pattern quality scores
- `pattern_lineage_nodes` - Pattern lineage nodes
- `pattern_lineage_edges` - Pattern lineage relationships
- `pattern_lineage_events` - Pattern lineage events
- `pattern_ancestry_cache` - Pattern ancestry cache
- `pattern_feedback_log` - Pattern feedback log
- `template_cache_metadata` - Template cache metadata

**Node & Mixin Tables (4)**:
- `node_registrations` - ONEX node registrations
- `mixin_compatibility_matrix` - Mixin compatibility tracking
- `schema_migrations` - Database schema migrations
- `hook_events` - Hook event tracking

### 3. Schema Validation - Views (9 checks)

**Critical Analytical Views**:
- `v_agent_execution_trace` - Complete execution trace with correlation
- `v_agent_performance` - Agent performance metrics
- `v_manifest_injection_performance` - Manifest injection analytics
- `v_routing_decision_accuracy` - Routing accuracy metrics
- `v_intelligence_effectiveness` - Intelligence query effectiveness
- `v_agent_quality_leaderboard` - Agent quality rankings
- `v_complete_execution_trace` - Complete execution trace with all data
- `active_errors` - Active error summary
- `recent_debug_traces` - Recent debug traces

### 4. Column Validation (3 checks)

Validates critical tables have required columns:
- `agent_actions`: correlation_id, agent_name, action_type, action_name, created_at
- `agent_routing_decisions`: correlation_id, user_request, selected_agent, confidence_score, created_at
- `agent_manifest_injections`: correlation_id, agent_name, manifest_version, patterns_count, created_at

### 5. Data Integrity (4 checks)

- **Primary Keys**: Validates ≥25 primary keys exist
- **Foreign Keys**: Counts foreign key constraints
- **Indexes**: Validates ≥30 indexes for performance
- **Orphaned Records**: Checks for agent_actions without routing decisions (last 7 days)

### 6. Functional Validation - CRUD (5 checks)

Tests actual database operations:
1. **CREATE**: Insert test record
2. **READ**: Retrieve test record
3. **UPDATE**: Modify test record
4. **UPDATE VERIFY**: Verify data integrity after update
5. **DELETE**: Clean up test record

### 7. Action Type Validation (4 checks)

Validates all 4 action types exist in data (last 7 days):
- `tool_call` - Agent tool invocations
- `decision` - Agent decision points
- `error` - Error events
- `success` - Success events

### 8. Recent Activity Validation (5 checks)

Checks database activity (last 24 hours):
- `agent_actions` - Agent actions count
- `agent_routing_decisions` - Routing decisions count
- `agent_manifest_injections` - Manifest injections count
- `agent_transformation_events` - Transformation events count
- **Overall Activity**: Total activity across all tables

### 9. Performance Validation (3 checks)

- **Query Latency**: Measures SELECT COUNT(*) latency
  - <500ms: Excellent
  - <2000ms: Good
  - <5000ms: Acceptable but slow
  - ≥5000ms: Poor performance
- **Connection Pool**: Active connections (<50 healthy)
- **Database Size**: Total database size (info only)

### 10. UUID Handling Validation (3 checks)

- **UUID Types**: Validates correlation_id columns use UUID type
- **UUID INSERT**: Tests UUID insertion
- **UUID RETRIEVE**: Tests UUID retrieval (case-insensitive comparison)

### 11. View Functionality Validation (3 checks)

Tests critical views return data:
- `v_agent_execution_trace`
- `v_agent_performance`
- `v_manifest_injection_performance`

### 12. Edge Case Validation (3 checks)

- **NULL Constraints**: Validates NOT NULL constraints enforced
- **Timestamp Consistency**: Checks for future timestamps
- **Large Text Handling**: Tests storing 10KB text fields

## Health Score Interpretation

| Score | Rating | Meaning |
|-------|--------|---------|
| ≥95% | Excellent | All systems optimal |
| 85-94% | Good | Minor warnings, system healthy |
| 70-84% | Acceptable | Some issues, investigate warnings |
| <70% | Poor | Critical issues, immediate attention needed |

## Exit Codes

- **0**: All critical checks passed (even with warnings)
- **1**: One or more critical checks failed
- **2**: Fatal error (cannot connect, missing .env, etc.)

## Expected Warnings

Some warnings are normal:

1. **Orphaned agent_actions**: Some operations don't require routing decisions
2. **No recent error/success actions**: System may be working well
3. **Large text handling**: Database may have size limits on certain columns

## Output Files

- `/tmp/database_verification_latest.txt` - Summary report with scores
- Console output - Detailed check-by-check results

## Integration with CI/CD

The script is integrated into the master test suite:

```bash
# Run all functional tests (includes database verification)
./scripts/test_system_functionality.sh
```

## Troubleshooting

### Connection Failed

```bash
# Verify .env file exists
ls -la .env

# Check environment variables
source .env
echo "DB: ${POSTGRES_DATABASE}"
echo "Host: ${POSTGRES_HOST}"
echo "Port: ${POSTGRES_PORT}"

# Test manual connection
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
```

### Low Health Score

1. Review console output for failed checks
2. Check `/tmp/database_verification_latest.txt` for summary
3. Investigate specific failures:
   - Missing tables: Check schema migrations
   - Failed CRUD: Check permissions
   - Poor performance: Check indexes, connection pool

### Warnings About Missing Tables

If tables are reported as missing but you know they exist:
1. Verify you're connecting to the correct database
2. Check table names match exactly (case-sensitive)
3. Verify schema is `public` (default)

## Advanced Usage

### Run Specific Sections

The script runs all sections by default. To run specific checks, modify the script or create a custom version.

### Custom Thresholds

Edit the script to adjust performance thresholds:

```bash
# Line ~370-375: Query latency thresholds
if [ $LATENCY_MS -lt 500 ]; then     # Change 500 to your threshold
    pass "Query latency: ${LATENCY_MS}ms (excellent)"
```

### Add Custom Checks

Add new checks by following the pattern:

```bash
# Your custom check
check
RESULT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "YOUR SQL QUERY HERE" | tr -d ' ')
if [ "$RESULT" == "expected" ]; then
    pass "Your check: description"
else
    fail "Your check: failure message"
fi
```

## Example Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COMPREHENSIVE DATABASE SYSTEM VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Database: omninode_bridge @ 192.168.86.200:5436
User: postgres
Timestamp: 2025-11-09 19:02:43

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. CONNECTIVITY TEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ PostgreSQL connection successful

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VERIFICATION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total Checks:    70
Passed:          62
Warnings:        4

Health Score:    88% (Good)

Coverage Summary:
  ✓ Tables verified: 29
  ✓ Views verified: 9
  ✓ Action types: 4
  ✓ CRUD operations: 4 (Create, Read, Update, Delete)
  ✓ Performance metrics: 2 (latency, connections)
  ✓ Edge cases: 3 (NULL, timestamps, large text)

✓ Database system verification PASSED
All critical checks successful
```

## Related Documentation

- **Health Check Script**: `scripts/health_check.sh` - Service-level health checks
- **PostgreSQL Test**: `scripts/tests/test_postgres_functionality.sh` - Basic PostgreSQL test
- **System Tests**: `scripts/test_system_functionality.sh` - Master test suite
- **Agent History Browser**: `agents/lib/agent_history_browser.py` - Browse execution history

## Maintenance

### Regular Verification Schedule

Recommended schedule:
- **CI/CD**: Every commit/PR
- **Development**: Daily or before major changes
- **Production**: Hourly via monitoring

### Updating the Script

When adding new tables:
1. Add table name to appropriate array (CORE_TABLES, INFRA_TABLES, etc.)
2. Increment expected counts in data integrity checks
3. Update this documentation

When adding new views:
1. Add view name to CRITICAL_VIEWS array
2. Optionally add functionality test in Section 11
3. Update this documentation

## Contact

For issues or questions about database verification:
- Check OmniClaude documentation: `CLAUDE.md`
- Review observability docs: `docs/observability/AGENT_TRACEABILITY.md`
- Check infrastructure guide: `~/.claude/CLAUDE.md`
