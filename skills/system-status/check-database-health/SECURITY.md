# Security: SQL Injection Prevention

**Created**: 2025-11-12
**Issue**: PR #33 review identified SQL injection risk in table name handling

## Vulnerability Fixed

**CRITICAL**: User-controlled table names were used directly in SQL queries without validation.

**Vulnerable Code** (before fix):
```python
# User input directly in SQL query
tables_list = [t.strip() for t in args.tables.split(",")]
for table in tables_list:
    activity_query = f"SELECT ... FROM {table}"  # ❌ SQL injection risk
```

**Exploit Examples**:
```bash
# Drop tables
python3 execute.py --tables "agent_actions; DROP TABLE users; --"

# Exfiltrate data
python3 execute.py --tables "agent_actions UNION SELECT * FROM pg_shadow"

# Read sensitive data
python3 execute.py --tables "agent_actions' OR '1'='1"
```

## Security Fix Implementation

### 1. Whitelist Validation

**Table Name Whitelist** (`VALID_TABLES` set):
- Contains all valid omninode_bridge schema tables with `created_at` column
- 34 tables currently defined (forward-looking for future schema)
- Case-sensitive matching (PostgreSQL standard)
- Immutable set for performance

### 2. Validation Function

```python
def validate_table_name(table: str) -> str:
    """Validate table name against whitelist to prevent SQL injection.

    Args:
        table: Table name to validate

    Returns:
        Validated table name

    Raises:
        ValueError: If table name is invalid or not in whitelist
    """
    table = table.strip()

    if not table:
        raise ValueError("Table name cannot be empty")

    if table not in VALID_TABLES:
        raise ValueError(
            f"Invalid table name: '{table}'. "
            f"Must be one of: {', '.join(sorted(VALID_TABLES))}"
        )

    return table
```

**Validation Features**:
- ✅ Whitespace trimming
- ✅ Empty string rejection
- ✅ Whitelist membership check
- ✅ Clear error messages with valid options
- ✅ Returns validated table name for safe use

### 3. Usage in Code

**Before** (vulnerable):
```python
tables_list = [t.strip() for t in args.tables.split(",")]
```

**After** (secure):
```python
try:
    tables_list = [validate_table_name(t) for t in args.tables.split(",")]
except ValueError as e:
    result["error"] = str(e)
    print(format_json(result))
    return 1
```

## Test Coverage

**Test File**: `test_table_validation.py`

**11 comprehensive tests** covering:
1. ✅ Valid table names accepted
2. ✅ Whitespace trimming works
3. ✅ Empty table names rejected
4. ✅ Invalid table names rejected
5. ✅ SQL injection attempts blocked (14 patterns tested)
6. ✅ Case sensitivity enforced
7. ✅ Whitelist completeness verified
8. ✅ Helpful error messages
9. ✅ All whitelist tables pass validation
10. ✅ No duplicate entries
11. ✅ No empty/null entries

**SQL Injection Patterns Tested**:
- Classic injection: `; DROP TABLE users; --`
- Boolean injection: `' OR '1'='1`
- Union injection: `UNION SELECT * FROM pg_shadow`
- Command injection: `; $(rm -rf /)`
- Path traversal: `../../../etc/passwd`
- Special characters: `' --`, `;`, `/**/`
- URL encoding: `%27`, `%3B%20DROP%20TABLE`

## Verification

**Test malicious input**:
```bash
# Should reject with clear error message
python3 execute.py --tables "agent_actions; DROP TABLE users; --"

# Output:
# {
#   "error": "Invalid table name: 'agent_actions; DROP TABLE users; --'.
#             Must be one of: agent_actions, agent_execution_logs, ..."
# }
```

**Test valid input**:
```bash
# Should work normally
python3 execute.py --tables "agent_routing_decisions,agent_manifest_injections"

# Output:
# {
#   "connection": "healthy",
#   "recent_activity": {
#     "agent_routing_decisions": {...},
#     "agent_manifest_injections": {...}
#   }
# }
```

## Security Best Practices Applied

1. ✅ **Input Validation**: All user input validated against whitelist
2. ✅ **Fail Closed**: Invalid input rejected with error, not silent failure
3. ✅ **Defense in Depth**: Multiple layers (validation + parameterization)
4. ✅ **Clear Error Messages**: Users know exactly what went wrong
5. ✅ **Test Coverage**: Comprehensive tests for attack vectors
6. ✅ **Documentation**: Security considerations documented
7. ✅ **Principle of Least Privilege**: Only necessary tables accessible

## Whitelist Maintenance

**Adding New Tables**:
1. Verify table exists in omninode_bridge schema
2. Verify table has `created_at` column (required for queries)
3. Add to `VALID_TABLES` set in `execute.py`
4. Run tests to verify: `python3 test_table_validation.py`
5. Update this documentation

**Current Whitelist** (34 tables):
```python
VALID_TABLES = {
    # Core agent tables
    "agent_routing_decisions",
    "agent_manifest_injections",
    "agent_execution_logs",
    "agent_actions",
    "agent_transformation_events",
    "agent_sessions",

    # Workflow tables
    "workflow_steps",
    "workflow_events",

    # Intelligence tables
    "llm_calls",
    "error_events",
    "success_events",
    "router_performance_metrics",
    "intelligence_queries",
    "pattern_discoveries",
    "debug_intelligence",
    "quality_assessments",
    "onex_compliance_checks",

    # Infrastructure tables
    "correlation_tracking",
    "event_log",
    "system_metrics",
    "performance_snapshots",
    "cache_operations",
    "database_operations",
    "kafka_events",
    "service_health_checks",

    # Application tables
    "api_requests",
    "user_sessions",
    "authentication_events",
    "authorization_checks",

    # Deployment tables
    "configuration_changes",
    "deployment_events",
    "migration_history",
    "schema_versions",
    "audit_log",
}
```

## Related Security Fixes

- **PR #33**: Timeframe SQL injection fix in `check-event-activity`
- **PR #33**: Table name SQL injection fix (this document)

## References

- OWASP SQL Injection: https://owasp.org/www-community/attacks/SQL_Injection
- PostgreSQL Security: https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
- Python SQL Best Practices: https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders
