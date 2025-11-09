# PostgreSQL Password Alias Migration Guide

**Migration Status**: Phase 2 - Type-Safe Configuration Framework (ADR-001)
**Created**: 2025-11-08
**Target Version**: v2.0 (Q2 2025)
**Priority**: HIGH (Security & Maintenance)

---

## Overview

This guide provides step-by-step instructions for migrating from deprecated PostgreSQL password environment variable aliases to the single standardized variable `POSTGRES_PASSWORD`.

### Why Migrate?

**Security Improvements**:
- Single password variable reduces rotation complexity
- Eliminates risk of mismatched passwords across aliases
- Simplifies security audits and compliance checks
- Reduces attack surface (fewer variables to secure)

**Maintenance Benefits**:
- Consistent naming across all services
- Easier troubleshooting (one variable to check)
- Reduced documentation complexity
- Cleaner .env file structure

---

## Deprecated Aliases

The following environment variables are **DEPRECATED** and will be removed in **v2.0** (estimated Q2 2025):

| Deprecated Variable | Used By | Replacement |
|---------------------|---------|-------------|
| `DB_PASSWORD` | Legacy Python scripts, standalone utilities | `POSTGRES_PASSWORD` |
| `OMNINODE_BRIDGE_POSTGRES_PASSWORD` | Bridge adapter, cross-repo services | `POSTGRES_PASSWORD` |
| `DATABASE_PASSWORD` | Test utilities (minimal usage) | `POSTGRES_PASSWORD` |
| `TRACEABILITY_DB_PASSWORD` | Kafka consumer services (legacy) | `POSTGRES_PASSWORD` |

---

## Standard Variable

**Use this variable for all PostgreSQL password configuration**:

```bash
POSTGRES_PASSWORD=your_secure_password_here
```

**Location**: `.env` file (never commit to version control)

**Documentation**:
- `.env.example` (line 127)
- `config/README.md` (PostgreSQL Configuration section)
- `CLAUDE.md` (Environment Configuration section)

---

## Migration Steps

### Step 1: Identify Current Configuration

Check which alias you're currently using:

```bash
# Load your .env file
source .env

# Check for deprecated aliases
echo "DB_PASSWORD: ${DB_PASSWORD:-(not set)}"
echo "OMNINODE_BRIDGE_POSTGRES_PASSWORD: ${OMNINODE_BRIDGE_POSTGRES_PASSWORD:-(not set)}"
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-(not set)}"
```

### Step 2: Update .env File

**Before** (using deprecated alias):
```bash
# OLD - DEPRECATED
DB_PASSWORD=your_password_here
```

**After** (using standard variable):
```bash
# NEW - STANDARD
POSTGRES_PASSWORD=your_password_here
```

**For Docker Compose users**, also update:
```bash
# Application database password (local containerized PostgreSQL)
APP_POSTGRES_PASSWORD=your_local_app_password

# Shared bridge database password (external PostgreSQL)
POSTGRES_PASSWORD=your_bridge_password
```

### Step 3: Verify Environment

After updating `.env`, verify the configuration:

```bash
# Reload environment
source .env

# Verify POSTGRES_PASSWORD is set
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:+SET (hidden)}"

# Test database connection
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
```

### Step 4: Remove Deprecated Aliases

**Important**: Only remove aliases AFTER verifying POSTGRES_PASSWORD works!

Edit your `.env` file and remove lines like:
```bash
# REMOVE THESE (deprecated)
DB_PASSWORD=...
OMNINODE_BRIDGE_POSTGRES_PASSWORD=...
DATABASE_PASSWORD=...
TRACEABILITY_DB_PASSWORD=...
```

### Step 5: Restart Services

Restart all services to pick up the new configuration:

```bash
# Docker Compose services
cd deployment && docker-compose restart

# Individual containers (if applicable)
docker restart omniclaude_archon_router_consumer
docker restart omniclaude_agent_consumer

# Verify services started successfully
cd deployment && docker-compose ps
```

---

## Framework Integration

### Python Code (Pydantic Settings)

**Recommended** (type-safe):
```python
from config import settings

# Access password via Settings instance
password = settings.get_effective_postgres_password()

# Build connection string
dsn = settings.get_postgres_dsn()
```

**Legacy** (backward compatible during migration):
```python
import os

# Will emit deprecation warning if using DB_PASSWORD
password = os.getenv("POSTGRES_PASSWORD")

# Or use Pydantic Settings helper
from config import settings
password = settings.get_effective_postgres_password()  # Handles aliases with warnings
```

### Shell Scripts

**Before** (deprecated):
```bash
export DB_PASSWORD="${POSTGRES_PASSWORD}"
PGPASSWORD="$DB_PASSWORD" psql ...
```

**After** (standard):
```bash
# Load environment
source .env

# Use POSTGRES_PASSWORD directly
PGPASSWORD="${POSTGRES_PASSWORD}" psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} \
  -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}
```

### Docker Compose

**Before** (deprecated):
```yaml
environment:
  - DB_PASSWORD=${DB_PASSWORD}
  - OMNINODE_BRIDGE_POSTGRES_PASSWORD=${OMNINODE_BRIDGE_POSTGRES_PASSWORD}
```

**After** (standard):
```yaml
environment:
  - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
```

---

## Deprecation Warnings

The type-safe configuration framework (`config/settings.py`) now emits deprecation warnings when legacy aliases are detected:

```
WARNING: DEPRECATION WARNING: DB_PASSWORD is deprecated and will be removed in v2.0.
Please migrate to POSTGRES_PASSWORD in your .env file.
See PASSWORD_ALIAS_MIGRATION.md for migration guide.
```

**Action Required**: If you see these warnings, follow this migration guide to update your configuration.

---

## Affected Files (23 Total)

### Python Files (11)
- `agents/parallel_execution/db_connection_pool.py`
- `claude_hooks/lib/hook_event_logger.py`
- `claude_hooks/lib/session_intelligence.py`
- `claude_hooks/services/hook_event_processor.py`
- `config/test_production_validation.py`
- `tests/test_kafka_consumer.py`

### Shell Scripts (12)
- `agents/migrations/test_004_migration.sh`
- `agents/parallel_execution/migrations/apply_migrations.sh`
- `claude_hooks/post-tool-use-quality.sh`
- `claude_hooks/pre-tool-use-quality.sh`
- `claude_hooks/services/run_processor.sh`
- `claude_hooks/setup-symlinks.sh`
- `claude_hooks/tests/validate_database.sh`
- `claude_hooks/user-prompt-submit.sh`
- `claude_hooks/validate_monitoring_indexes.sh`
- `deployment/scripts/start-routing-adapter.sh`
- `scripts/apply_migration.sh`
- `scripts/backup_patterns.sh`
- `scripts/dump_omninode_db.sh`
- `scripts/observability/monitor_routing_health.sh`
- `scripts/reingest_patterns.sh`
- `scripts/rollback_patterns.sh`
- `scripts/validate_patterns.sh`

**Status**: Files are being migrated progressively. Check `git log` for migration commits.

---

## Testing After Migration

### 1. Environment Validation

```bash
# Validate .env configuration
./scripts/validate-env.sh .env

# Check for missing POSTGRES_PASSWORD
if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "❌ ERROR: POSTGRES_PASSWORD not set"
    exit 1
fi
```

### 2. Database Connection Test

```bash
# Load environment
source .env

# Test connection
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"

# Expected output:
# ?column?
# ----------
#        1
# (1 row)
```

### 3. Service Health Check

```bash
# Run comprehensive health check
./scripts/health_check.sh

# Check for database connectivity issues
docker logs omniclaude_archon_router_consumer 2>&1 | grep -i "password\|auth\|connection"
```

### 4. Configuration Validation (Pydantic Settings)

```python
# Test in Python
from config import settings

# This should NOT emit warnings (using POSTGRES_PASSWORD)
password = settings.get_effective_postgres_password()
print(f"Password configured: {bool(password)}")

# Validate all required services
errors = settings.validate_required_services()
if errors:
    print("Configuration errors:", errors)
else:
    print("✅ All services configured correctly")
```

---

## Troubleshooting

### Issue: "PostgreSQL password not configured"

**Cause**: POSTGRES_PASSWORD not set in .env
**Fix**:
1. Verify `.env` exists: `ls -la .env`
2. Check password is set: `grep POSTGRES_PASSWORD .env`
3. Reload environment: `source .env`
4. Verify: `echo ${POSTGRES_PASSWORD:+SET}`

### Issue: "Authentication failed"

**Cause**: Password mismatch or alias still in use
**Fix**:
1. Verify correct password: Check `.env` matches database password
2. Test connection manually: `psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}`
3. Check for alias conflicts: `grep -E "DB_PASSWORD|OMNINODE_BRIDGE" .env`

### Issue: Deprecation warnings in logs

**Cause**: Services still using legacy aliases
**Fix**:
1. Identify which service: Check log source
2. Update `.env`: Replace alias with `POSTGRES_PASSWORD`
3. Restart service: `docker-compose restart <service>`
4. Verify warning gone: `docker logs <service> 2>&1 | grep -i deprecation`

### Issue: Services can't connect after migration

**Cause**: Environment not reloaded or Docker volumes persisting old config
**Fix**:
1. Reload environment: `source .env`
2. Restart Docker services: `cd deployment && docker-compose restart`
3. Check environment in container: `docker exec <container> env | grep POSTGRES`
4. If needed, recreate containers: `cd deployment && docker-compose up -d --force-recreate`

---

## Rollback Procedure

**Use this procedure if the migration causes production issues and you need to temporarily revert.**

### When to Rollback

Consider rollback if you experience:
- ❌ **Critical service failures**: Multiple services unable to connect to database
- ❌ **Authentication failures**: Persistent "password authentication failed" errors
- ❌ **Production impact**: End-user facing services down >5 minutes
- ❌ **Data access blocked**: Critical workflows unable to access PostgreSQL

**Timeline Window**: Rollback recommended within **15 minutes** of detecting critical issues.

### Emergency Restoration Steps

#### 1. Identify Failing Services

```bash
# Quick service health check
cd deployment && docker-compose ps

# Check logs for authentication errors
docker-compose logs --tail=50 | grep -i "password\|auth\|connection"

# Identify specific failing services
for service in $(docker-compose ps --services); do
    echo "Checking $service..."
    docker-compose logs --tail=10 "$service" 2>&1 | grep -i "error\|failed" && echo "❌ $service FAILING"
done
```

#### 2. Emergency Revert to Legacy Alias

**Step 2a: Restore Legacy Variable**

Edit `.env` to temporarily restore the legacy alias that was working:

```bash
# Backup current .env (IMPORTANT!)
cp .env .env.migration-backup-$(date +%Y%m%d-%H%M%S)

# Add legacy alias back (choose the one you were using)
# Option 1: If you were using DB_PASSWORD
echo "DB_PASSWORD=${POSTGRES_PASSWORD}" >> .env

# Option 2: If you were using OMNINODE_BRIDGE_POSTGRES_PASSWORD
echo "OMNINODE_BRIDGE_POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" >> .env

# Verify both are now set
source .env
echo "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:+SET}"
echo "DB_PASSWORD: ${DB_PASSWORD:+SET}"  # If using this alias
```

**Step 2b: Reload Environment**

```bash
# Reload environment variables
source .env

# Verify all required passwords are set
env | grep -E "POSTGRES_PASSWORD|DB_PASSWORD|OMNINODE_BRIDGE"
```

#### 3. Restart Services Immediately

```bash
# Restart all services with updated environment
cd deployment && docker-compose down
cd deployment && docker-compose up -d

# Watch services start
cd deployment && docker-compose logs -f
```

**Expected Recovery Time**: 1-3 minutes

#### 4. Verify Service Recovery

```bash
# Check all services are running
cd deployment && docker-compose ps

# Test database connectivity
source .env
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1"

# Check for remaining errors
docker-compose logs --tail=100 | grep -i "error\|failed"

# Run health check
./scripts/health_check.sh
```

### Service-Specific Rollback

**For individual service failures** (when only specific services fail):

```bash
# Identify failing service
SERVICE_NAME="archon-router-consumer"  # Replace with actual service

# Check service logs
docker logs ${SERVICE_NAME} --tail=50

# Restart individual service
docker restart ${SERVICE_NAME}

# Verify recovery
docker logs ${SERVICE_NAME} --tail=20 | grep -i "connected\|ready"
```

### Rollback Timeline Expectations

| Step | Duration | Critical Actions |
|------|----------|-----------------|
| **Detection** | 0-5 min | Identify failing services, check logs |
| **Decision** | 5-7 min | Assess impact, decide to rollback |
| **Restoration** | 7-10 min | Restore legacy alias, reload environment |
| **Service Restart** | 10-13 min | Restart services, verify startup |
| **Verification** | 13-15 min | Test connections, check health |
| **Total** | **~15 min** | Full rollback with verification |

### Post-Rollback Actions

After successful rollback:

1. **Document the Issue**:
   ```bash
   # Create incident log
   cat > /tmp/migration_rollback_$(date +%Y%m%d).log <<EOF
   Timestamp: $(date)
   Issue: [Describe what failed]
   Affected Services: [List services]
   Legacy Alias Restored: [DB_PASSWORD/OMNINODE_BRIDGE_POSTGRES_PASSWORD]
   Recovery Time: [Duration]
   EOF
   ```

2. **Preserve Evidence**:
   ```bash
   # Save logs before they rotate
   docker-compose logs > /tmp/migration_failure_logs_$(date +%Y%m%d-%H%M%S).txt

   # Save container state
   docker-compose ps > /tmp/migration_container_state_$(date +%Y%m%d-%H%M%S).txt
   ```

3. **Plan Retry Strategy**:
   - Review logs to identify root cause
   - Check if issue was configuration vs. timing
   - Test migration in non-production environment first
   - Schedule retry during low-traffic window

4. **Keep Legacy Alias Temporarily**:
   ```bash
   # Keep BOTH variables in .env until ready to retry
   POSTGRES_PASSWORD=your_password_here
   DB_PASSWORD=${POSTGRES_PASSWORD}  # Temporary for stability
   ```

5. **Monitor for 24 Hours**:
   ```bash
   # Verify stability
   watch -n 300 './scripts/health_check.sh'  # Every 5 minutes

   # Check for any late-appearing issues
   docker-compose logs --since 1h | grep -i "error\|warn"
   ```

### Preventing Future Rollback Needs

**Before Next Migration Attempt**:

1. **Test in Non-Production**:
   ```bash
   # Use test environment
   docker-compose --env-file .env.test up -d --profile test
   ```

2. **Gradual Migration**:
   - Migrate one service at a time
   - Verify each service before proceeding
   - Keep legacy alias until ALL services confirmed working

3. **Staging Period**:
   - Run BOTH variables for 7 days minimum
   - Monitor for any issues
   - Remove legacy alias only after proven stability

4. **Backup Everything**:
   ```bash
   # Before retry
   cp .env .env.backup
   cp deployment/docker-compose.yml deployment/docker-compose.yml.backup
   ```

---

## Security Best Practices

### Password Strength Requirements

```bash
# Minimum requirements for POSTGRES_PASSWORD:
# - Length: ≥16 characters
# - Complexity: Mix of uppercase, lowercase, numbers, special chars
# - Avoid: Dictionary words, common patterns, sequential characters

# Good example (generated):
POSTGRES_PASSWORD=$(openssl rand -base64 24)

# Bad examples:
POSTGRES_PASSWORD=password123        # Too weak
POSTGRES_PASSWORD=postgres           # Default (NEVER use)
```

### Rotation Best Practices

1. **Rotate regularly**: Every 30-90 days
2. **Update all instances**: Ensure all services use new password
3. **Test before committing**: Verify connection works with new password
4. **Document rotation**: Log rotation date and reason
5. **Revoke old access**: Ensure old password is invalidated

See `SECURITY_KEY_ROTATION.md` for detailed rotation procedures.

---

## Migration Checklist

Use this checklist to track your migration progress:

- [ ] **Step 1**: Identified current password alias usage
- [ ] **Step 2**: Updated `.env` file with `POSTGRES_PASSWORD`
- [ ] **Step 3**: Verified database connection with new variable
- [ ] **Step 4**: Removed deprecated aliases from `.env`
- [ ] **Step 5**: Restarted all services
- [ ] **Step 6**: Tested database connectivity
- [ ] **Step 7**: Verified no deprecation warnings in logs
- [ ] **Step 8**: Updated personal documentation (if any)
- [ ] **Step 9**: Committed changes (if applicable)
- [ ] **Step 10**: Verified all tests pass

---

## Timeline

| Phase | Status | Target Date |
|-------|--------|-------------|
| **Phase 1**: Documentation and warnings | ✅ Complete | 2025-11-08 |
| **Phase 2**: Code migration (in progress) | 🔄 In Progress | 2025-11-15 |
| **Phase 3**: Testing and validation | 📋 Planned | 2025-11-22 |
| **Phase 4**: Alias removal (v2.0) | 📋 Planned | 2025-Q2 |

---

## Support

**Questions or Issues?**

1. Check this migration guide for troubleshooting steps
2. Review `config/README.md` for Pydantic Settings documentation
3. Check `SECURITY_KEY_ROTATION.md` for password management
4. Review `CLAUDE.md` for environment configuration details
5. Check deprecation warnings for specific guidance

**Related Documentation**:
- `.env.example` - Configuration template
- `config/README.md` - Type-safe configuration framework
- `SECURITY_KEY_ROTATION.md` - Password rotation procedures
- `CLAUDE.md` - Complete environment setup guide

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-11-08 | Initial migration guide created |

---

**Remember**: Never commit `.env` files or hardcoded passwords to version control!
