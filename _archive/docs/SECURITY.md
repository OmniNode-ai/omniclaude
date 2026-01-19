# Security Documentation

**Last Updated**: 2025-11-17
**Status**: Active

## Overview

This document outlines the security measures, best practices, and considerations implemented in the OmniClaude codebase to prevent common vulnerabilities.

## Security Measures

### 1. SQL Injection Prevention

**Risk**: SQL injection attacks occur when untrusted user input is directly interpolated into SQL queries, allowing attackers to execute arbitrary SQL commands.

**Mitigation Strategy**:

#### Parameterized Queries
All database operations use parameterized queries (also called prepared statements) where values are passed separately from the SQL statement:

```python
# ✅ SAFE: Parameterized query
query = "SELECT * FROM users WHERE id = $1"
result = await conn.fetchrow(query, user_id)

# ❌ UNSAFE: String interpolation
query = f"SELECT * FROM users WHERE id = '{user_id}'"  # NEVER DO THIS
```

#### Table and Column Name Validation
Since table and column names cannot be parameterized in SQL, we validate them to ensure they contain only safe characters:

```python
from agents.lib.security_utils import validate_sql_identifier

# Validate before using in query
validate_sql_identifier(table_name, "table")
validate_sql_identifier(column_name, "column")

# Now safe to use in f-string (with nosec comment for Bandit)
query = f"SELECT * FROM {table_name} WHERE {column_name} = $1"  # nosec B608
```

**Validation Rules**:
- Only alphanumeric characters and underscores allowed
- Must start with letter or underscore (not a digit)
- Maximum 63 characters (PostgreSQL limit)
- No special characters, quotes, or SQL keywords

#### Files Using SQL Injection Protection

**With Input Validation**:
- `agents/lib/database_event_client.py` - All CRUD operations (insert, update, delete, upsert)
- `agents/lib/performance_optimization.py` - Batch operations
- `agents/lib/migrate.py` - Database migration tracking

**With Parameterized WHERE Clauses**:
- `agents/lib/embedding_search.py` - Error search with dynamic filters
- `agents/lib/intelligence_usage_tracker.py` - Usage statistics queries
- `agents/lib/stf_execution.py` - Transform function discovery

**With Documentation Examples Only**:
- `agents/lib/test_agent_traceability.py` - Print statements showing example queries (not executed)

**With Database Introspection** (trusted sources):
- `agents/lib/migrate.py` - Column names from `information_schema`
- `agents/parallel_execution/observability_report.py` - Table and column names from schema

**Code Generation Templates**:
- `agents/lib/patterns/crud_pattern.py` - Generated code includes validation

### 2. Pickle Deserialization Security

**Risk**: Python's `pickle` module can execute arbitrary code during deserialization. Loading pickle files from untrusted sources is extremely dangerous.

**Mitigation Strategy**:

#### Limited Scope
Pickle is only used for ML model serialization in `agents/lib/mixin_learner.py`:

```python
# Model files generated internally by this system
with open(self.model_path, "rb") as f:
    self.model = pickle.load(f)  # nosec B301 - internal model files only
```

**Security Measures**:
1. Model files are generated internally (not from external sources)
2. Model paths are controlled (not user-provided)
3. Files stored in trusted directory (`.cache/models/`)
4. File permissions should be restricted (0600) in production

**Recommendations for Production**:
- Use `joblib` with compression instead of raw pickle
- Implement file integrity checks (SHA-256 hashes)
- Use model signing/verification for distributed deployments
- Restrict file permissions: `chmod 600 .cache/models/*`

**References**:
- [Python pickle documentation - Security](https://docs.python.org/3/library/pickle.html#module-pickle)
- [OWASP: Deserialization of Untrusted Data](https://owasp.org/www-community/vulnerabilities/Deserialization_of_untrusted_data)

### 3. Network Binding Security

**Risk**: Binding services to `0.0.0.0` (all network interfaces) can expose services to external networks if not properly firewalled.

**Mitigation Strategy**:

#### Intentional All-Interface Binding
In `agents/services/agent_router_event_service.py`, the health check server binds to `0.0.0.0` for Docker/Kubernetes compatibility:

```python
# Intentional for container environments
site = web.TCPSite(
    self._health_runner, "0.0.0.0", self.health_check_port
)  # nosec B104 - Docker/K8s deployment
```

**Production Recommendations**:
- Use firewall rules to restrict access (e.g., iptables, AWS security groups)
- Place behind reverse proxy (nginx, Envoy) for access control
- Use network policies in Kubernetes
- Bind to `127.0.0.1` for localhost-only access in non-containerized deployments

### 4. API Key Management

**Risk**: Hardcoded API keys in source code can be exposed through version control, logs, or error messages.

**Mitigation Strategy**:

#### Environment Variables
All API keys and secrets are loaded from environment variables:

```python
# ✅ CORRECT
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ❌ WRONG
GEMINI_API_KEY = "AIza..."  # NEVER hardcode API keys
```

**Configuration**:
- All secrets in `.env` file (never committed to version control)
- `.env.example` provides template with placeholder values
- `.gitignore` includes `.env` to prevent accidental commits

**Best Practices**:
- Rotate keys every 30-90 days
- Use separate keys for development and production
- Enable IP restrictions in provider dashboards
- Set usage quotas to limit damage from leaks
- Monitor API usage for anomalies

See **[SECURITY_KEY_ROTATION.md](../SECURITY_KEY_ROTATION.md)** for detailed key management procedures.

### 5. Password Security

**Risk**: Hardcoded passwords or weak password policies can lead to unauthorized access.

**Mitigation Strategy**:

#### Environment-Based Credentials
Database passwords and other credentials are loaded from environment variables:

```bash
# .env file (NEVER commit to version control)
POSTGRES_PASSWORD=<strong_password_here>
```

**Usage Pattern**:
```bash
# Always source .env before database operations
source .env

# Use environment variables in connection strings
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
     -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
```

**Requirements**:
- Never hardcode passwords in documentation or code
- Use placeholders like `<set_in_env>` in examples
- Change all default passwords immediately in production
- Use strong passwords (minimum 16 characters, mixed case, numbers, symbols)

## Security Scanning

### Bandit Static Analysis

We use Bandit for automated security scanning:

```bash
# Scan entire codebase
bandit -r agents/ -f json -o security-report.json

# Scan specific file
bandit agents/lib/database_event_client.py

# Scan with severity filter
bandit -r agents/ -ll  # Only show MEDIUM and HIGH
```

**Suppressing False Positives**:

Use `# nosec B<test_id>` comments only when:
1. Security measure is already in place (e.g., input validation)
2. Code is safe by design (e.g., hardcoded table list)
3. Risk is mitigated by other controls (e.g., firewall rules)

Always include a comment explaining why it's safe:

```python
# Table name validated with validate_sql_identifier()
query = f"SELECT * FROM {table_name}"  # nosec B608
```

**Common Test IDs**:
- `B608`: SQL injection (string-based query construction)
- `B301`: Pickle deserialization
- `B104`: Binding to all network interfaces
- `B403`: Pickle import

### Environment Validation

Validate `.env` configuration:

```bash
./scripts/validate-env.sh .env
```

Checks for:
- Required variables are set
- No placeholder values remain
- Password strength requirements
- URL format validation
- Port number ranges

## Incident Response

If a security issue is discovered:

1. **Do Not Panic**: Document the issue clearly
2. **Assess Severity**: Determine if it's actively exploited
3. **Isolate**: Stop affected services if necessary
4. **Patch**: Apply fix immediately
5. **Rotate Credentials**: Change any potentially compromised keys/passwords
6. **Audit**: Check logs for signs of exploitation
7. **Update Documentation**: Document the fix and lessons learned

## Security Checklist

Before deploying to production:

- [ ] All API keys in environment variables (not hardcoded)
- [ ] Strong passwords set for all database accounts
- [ ] `.env` file excluded from version control
- [ ] Bandit scan passes with zero MEDIUM+ severity issues
- [ ] Network services properly firewalled
- [ ] File permissions restricted (0600 for sensitive files)
- [ ] Logging configured (but sanitized - no secrets in logs)
- [ ] Rate limiting enabled on public endpoints
- [ ] HTTPS/TLS enabled for all network communication
- [ ] Regular dependency updates scheduled

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE: Common Weakness Enumeration](https://cwe.mitre.org/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security.html)
- [Bandit Documentation](https://bandit.readthedocs.io/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS)

---

**Contact**: For security concerns, contact the development team or file a confidential issue.
