# Configuration Migration Audit Report

**Generated**: 2025-11-06
**Framework**: Pydantic Settings (`config/settings.py`)
**Documentation**: `config/README.md`

---

## Executive Summary

### Migration Status

| Metric | Count | Percentage |
|--------|-------|------------|
| **Total Python files** | 5,077 | 100% |
| **Migrated files** (settings only) | 6 | 0.1% |
| **Mixed files** (both patterns) | 7 | 0.1% |
| **Needs migration** (os.getenv/environ) | 341 | 6.7% |
| **Clean files** (neither) | 4,723 | 93.0% |

**Migration Progress**: **1.7%** (6/354 relevant files)

### Code-Level Migration

| Pattern | Occurrences |
|---------|-------------|
| `os.getenv()` calls | 573 |
| `os.environ[]` calls | 741 |
| **Total legacy calls** | **1,314** |

---

## Priority Breakdown

### Legacy Call Distribution by Priority

| Priority | Description | Legacy Calls | Files | Impact |
|----------|-------------|--------------|-------|---------|
| **P0** | Critical Services | 15 | 2 | 🔴 HIGH |
| **P1** | Core Libraries | 119 | 26 | 🟠 HIGH |
| **P2** | Tests | 58 | 16 | 🟡 MEDIUM |
| **P3** | Scripts/Hooks | 360 | 146 | 🟢 LOW |

---

## Critical Files Analysis

### P0 - Critical Services (HIGHEST PRIORITY)

#### ❌ `agents/services/agent_router_event_service.py` - 9 os.getenv() calls
**Status**: NOT MIGRATED
**Impact**: Event-based routing service (7-8ms routing time)
**Migration Priority**: **CRITICAL**

**Lines to migrate**:
```python
# Line 812-825
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", ...)
consumer_group_id = os.getenv("KAFKA_GROUP_ID", "agent-router-service")
registry_path = os.getenv("REGISTRY_PATH")
health_check_port = int(os.getenv("HEALTH_CHECK_PORT", "8070"))
db_config = {
    "db_host": os.getenv("POSTGRES_HOST", "192.168.86.200"),
    "db_port": int(os.getenv("POSTGRES_PORT", "5436")),
    "db_name": os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
    "db_user": os.getenv("POSTGRES_USER", "postgres"),
    "db_password": os.getenv("POSTGRES_PASSWORD", ""),
}
```

**Migration**:
```python
from config import settings

bootstrap_servers = settings.kafka_bootstrap_servers
consumer_group_id = settings.kafka_group_id
registry_path = settings.registry_path
health_check_port = settings.health_check_port
db_config = {
    "db_host": settings.postgres_host,
    "db_port": settings.postgres_port,
    "db_name": settings.postgres_database,
    "db_user": settings.postgres_user,
    "db_password": settings.get_effective_postgres_password(),
}
```

---

#### ⚠️ `agents/lib/routing_event_client.py` - MIXED (has config.settings but also os.getenv)
**Status**: PARTIALLY MIGRATED
**Impact**: Client library for event-based routing
**Migration Priority**: **CRITICAL**

**Action**: Remove remaining `os.getenv()` calls (lines 127-129) and use `settings.*` consistently

---

### P1 - Core Libraries (HIGH PRIORITY)

#### ❌ `agents/lib/manifest_injector.py` - 9 os.getenv() calls
**Status**: NOT MIGRATED
**Impact**: Dynamic manifest generation with intelligence context
**Migration Priority**: **HIGH**

**Lines to migrate**:
```python
# Lines 721-723, 1883-1887, 1950, 1994
self.enable_quality_filter = os.getenv("ENABLE_PATTERN_QUALITY_FILTER", "false").lower() == "true"
self.min_quality_threshold = float(os.getenv("MIN_PATTERN_QUALITY", "0.5"))

# PostgreSQL config
host = os.getenv("POSTGRES_HOST", "192.168.86.200")
port = int(os.getenv("POSTGRES_PORT", "5436"))
database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
user = os.getenv("POSTGRES_USER", "postgres")
password = os.getenv("POSTGRES_PASSWORD", "")

# Kafka config
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", ...)

# Qdrant config
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
```

**Migration**:
```python
from config import settings

self.enable_quality_filter = settings.enable_pattern_quality_filter
self.min_quality_threshold = settings.min_pattern_quality

# PostgreSQL - use helper method
dsn = settings.get_postgres_dsn()
# OR individual properties:
host = settings.postgres_host
port = settings.postgres_port
database = settings.postgres_database
user = settings.postgres_user
password = settings.get_effective_postgres_password()

# Kafka
bootstrap_servers = settings.get_effective_kafka_bootstrap_servers()

# Qdrant
qdrant_url = settings.qdrant_url
```

---

#### ❌ `agents/lib/intelligence_event_client.py` - 3 os.getenv() calls
**Status**: NOT MIGRATED
**Migration Priority**: **HIGH**

---

#### ❌ `agents/lib/database_event_client.py` - 3 os.getenv() calls
**Status**: NOT MIGRATED
**Migration Priority**: **HIGH**

---

#### ✅ `services/routing_adapter/config.py` - MIGRATED
**Status**: SUCCESSFULLY MIGRATED
**Uses**: `from config import settings` throughout

---

#### Other P1 Files Needing Migration:

| File | os.getenv() calls | Priority |
|------|-------------------|----------|
| `agents/lib/db.py` | 8 | HIGH |
| `agents/lib/router_metrics_logger.py` | 8 | HIGH |
| `agents/lib/intelligence_cache.py` | 8 | HIGH |
| `agents/lib/config_validator.py` | 7 | HIGH |

---

## Successfully Migrated Files ✅

These files demonstrate correct migration patterns:

1. ✅ `agents/lib/version_config.py`
2. ✅ `services/routing_adapter/config.py`
3. ✅ `tests/test_auto_env_loading.py`
4. ✅ `tests/test_router_consumer.py`
5. ✅ `tests/test_routing_event_flow.py`
6. ✅ `tests/test_routing_flow.py`

**Example from `agents/lib/version_config.py`**:
```python
from config import settings

# Clean usage - no os.getenv()
version = settings.omniclaude_version
environment = settings.environment
```

---

## Mixed Files (Need Cleanup) ⚠️

These files use BOTH patterns and need cleanup:

1. ⚠️ `agents/lib/codegen_config.py`
2. ⚠️ `agents/lib/routing_event_client.py`
3. ⚠️ `agents/lib/slack_notifier.py`
4. ⚠️ `config/__init__.py`
5. ⚠️ `config/settings.py` (intentional - has legacy fallbacks)
6. ⚠️ `config/test_settings.py` (intentional - tests os.environ manipulation)
7. ⚠️ `tests/test_env_loading.py` (intentional - tests both patterns)

**Action Required**: Remove `os.getenv()` calls from files #1-3 above. Files #4-7 may intentionally use both patterns for compatibility or testing.

---

## Top 15 Files Needing Migration

Ranked by number of `os.getenv()` calls:

| Priority | File | Calls |
|----------|------|-------|
| P3 | `agents/parallel_execution/database_integration.py` | 12 |
| P3 | `consumers/agent_actions_consumer.py` | 11 |
| P2 | `agents/tests/test_pattern_quality_database_integration.py` | 9 |
| **P1** | **`agents/lib/manifest_injector.py`** | **9** |
| **P0** | **`agents/services/agent_router_event_service.py`** | **9** |
| P1 | `agents/lib/db.py` | 8 |
| P1 | `agents/lib/router_metrics_logger.py` | 8 |
| P1 | `agents/lib/intelligence_cache.py` | 8 |
| P2 | `tests/test_kafka_consumer.py` | 7 |
| P2 | `agents/tests/test_framework_schema.py` | 7 |
| P1 | `agents/lib/config_validator.py` | 7 |
| P2 | `tests/test_e2e_agent_logging.py` | 6 |
| P2 | `tests/test_logging_performance.py` | 6 |
| P2 | `agents/tests/test_mixin_learning.py` | 6 |
| P2 | `agents/tests/test_code_refiner.py` | 6 |

---

## Migration Recommendations

### Phase 1: Critical Services (P0) - IMMEDIATE

**Target**: 2 files, 15 legacy calls
**Timeline**: 1-2 days
**Impact**: Core routing functionality

1. ✅ Migrate `agents/services/agent_router_event_service.py` (9 calls)
2. ✅ Clean up `agents/lib/routing_event_client.py` (remove mixed pattern)

**Verification**:
```bash
# After migration, verify no os.getenv in P0 files
grep -r "os\.getenv" agents/services/agent_router_event_service.py
# Should return: (empty)

# Verify config.settings import exists
grep "from config import settings" agents/services/agent_router_event_service.py
# Should return: from config import settings
```

---

### Phase 2: Core Libraries (P1) - HIGH PRIORITY

**Target**: 26 files, 119 legacy calls
**Timeline**: 1-2 weeks
**Impact**: Intelligence system, database, routing

**Priority Order**:
1. `agents/lib/manifest_injector.py` (9 calls) - Intelligence context injection
2. `agents/lib/db.py` (8 calls) - Database connectivity
3. `agents/lib/router_metrics_logger.py` (8 calls) - Performance metrics
4. `agents/lib/intelligence_cache.py` (8 calls) - Pattern caching
5. `agents/lib/config_validator.py` (7 calls) - Configuration validation
6. `agents/lib/intelligence_event_client.py` (3 calls) - Intelligence queries
7. `agents/lib/database_event_client.py` (3 calls) - Database events

**Common Migration Patterns**:

```python
# Pattern 1: PostgreSQL Connection
# BEFORE:
host = os.getenv("POSTGRES_HOST", "192.168.86.200")
port = int(os.getenv("POSTGRES_PORT", "5436"))
database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
user = os.getenv("POSTGRES_USER", "postgres")
password = os.getenv("POSTGRES_PASSWORD", "")

# AFTER (Option A - Individual properties):
from config import settings
host = settings.postgres_host
port = settings.postgres_port
database = settings.postgres_database
user = settings.postgres_user
password = settings.get_effective_postgres_password()

# AFTER (Option B - DSN helper):
from config import settings
dsn = settings.get_postgres_dsn()  # Returns full connection string
async_dsn = settings.get_postgres_dsn(async_driver=True)  # For asyncpg

# Pattern 2: Kafka Bootstrap Servers
# BEFORE:
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# AFTER:
from config import settings
bootstrap_servers = settings.get_effective_kafka_bootstrap_servers()
# OR
bootstrap_servers = settings.kafka_bootstrap_servers

# Pattern 3: Feature Flags
# BEFORE:
enable_feature = os.getenv("ENABLE_FEATURE", "false").lower() == "true"

# AFTER:
from config import settings
enable_feature = settings.enable_feature  # Already boolean!

# Pattern 4: Numeric Values
# BEFORE:
port = int(os.getenv("PORT", "8000"))
quality = float(os.getenv("MIN_QUALITY", "0.5"))

# AFTER:
from config import settings
port = settings.port  # Already int!
quality = settings.min_pattern_quality  # Already float!
```

---

### Phase 3: Tests (P2) - MEDIUM PRIORITY

**Target**: 16 files, 58 legacy calls
**Timeline**: 1 week
**Impact**: Test reliability and maintainability

**Notes**:
- Some test files intentionally manipulate `os.environ` to test environment handling
- These should keep `os.environ` manipulation but verify against `settings` object
- Example: `config/test_settings.py` intentionally tests environment variable behavior

---

### Phase 4: Scripts & Hooks (P3) - LOWER PRIORITY

**Target**: 146 files, 360 legacy calls
**Timeline**: 2-3 weeks (background work)
**Impact**: Script consistency, reduced maintenance

**Note**: Many of these are one-off scripts that may not need immediate migration. Focus on:
- Frequently used scripts (in `scripts/`)
- Claude hooks (in `claude_hooks/`)
- Shared utilities (in `shared_lib/`)

---

## Migration Verification Checklist

After migrating each file:

- [ ] Import added: `from config import settings`
- [ ] All `os.getenv()` calls replaced with `settings.*`
- [ ] All `os.environ[]` calls replaced (if any)
- [ ] Type conversions removed (e.g., `int()`, `float()`, `.lower() == "true"`)
- [ ] Helper methods used where appropriate (e.g., `get_postgres_dsn()`)
- [ ] No hardcoded defaults in code (rely on settings defaults)
- [ ] File runs without errors
- [ ] Tests pass (if applicable)
- [ ] Configuration validated with `settings.validate_required_services()`

---

## Testing Migration

### Verify Individual File

```bash
# Check file has config.settings import
grep "from config import settings" <file>.py

# Check file has NO os.getenv calls
grep "os\.getenv" <file>.py
# Should return: (empty)

# Run file (if executable)
python3 <file>.py
```

### Verify Entire Codebase

```bash
# Count remaining os.getenv() calls
grep -r "os\.getenv" --include="*.py" . | wc -l

# Find files still using os.getenv()
grep -r -l "os\.getenv" --include="*.py" . | grep -E "(agents/services|agents/lib)" | sort

# Validate configuration loads correctly
python3 -c "from config import settings; print('✅ Settings loaded successfully')"

# Run validation
python3 -c "from config import settings; errors = settings.validate_required_services(); print('✅ Valid' if not errors else f'❌ Errors: {errors}')"
```

---

## Benefits of Migration

### Before (os.getenv)

```python
# ❌ Problems:
- No type safety (everything is string)
- Manual type conversion required: int(), float(), .lower() == "true"
- No validation (invalid values cause runtime errors)
- Scattered defaults throughout codebase
- No IDE autocomplete
- Hard to find all usages of a config variable
- No documentation of what variables exist
```

### After (config.settings)

```python
# ✅ Benefits:
- Full type safety (int, float, bool, str)
- Automatic type conversion and validation
- Clear error messages on startup if config is invalid
- Single source of truth for all configuration
- IDE autocomplete and type hints
- Helper methods for common operations
- Comprehensive documentation in config/README.md
- Environment-specific overrides (.env.dev, .env.prod)
- Secure password handling with sanitized exports
```

---

## Common Migration Issues

### Issue 1: Import Not Found

```python
# ❌ Error: ModuleNotFoundError: No module named 'config'
from config import settings

# ✅ Solution: Ensure PYTHONPATH includes project root or use relative import
# Option A: Run from project root
cd /Volumes/PRO-G40/Code/omniclaude
python3 agents/lib/manifest_injector.py

# Option B: Add to sys.path in script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
```

### Issue 2: Attribute Not Found

```python
# ❌ Error: AttributeError: 'Settings' object has no attribute 'my_variable'
value = settings.my_variable

# ✅ Solution: Check if variable exists in config/settings.py
# If not, add it to Settings class:
class Settings(BaseSettings):
    my_variable: str = "default_value"
```

### Issue 3: Type Mismatch

```python
# ❌ Error: ValidationError: value is not a valid integer
# This happens if .env has non-numeric value for an int field

# ✅ Solution: Fix .env file or settings.py type definition
# In .env:
POSTGRES_PORT=5436  # Should be numeric, not "5436abc"

# In settings.py:
postgres_port: int = 5436  # Type should match expected value
```

### Issue 4: Missing Environment Variable

```python
# ❌ Error: ValidationError: field required
# This happens if required variable is not in .env

# ✅ Solution A: Add to .env
echo "REQUIRED_VARIABLE=value" >> .env

# ✅ Solution B: Make optional with default in settings.py
required_variable: str = "default_value"  # Not Optional[], has default
```

---

## Next Steps

1. **Immediate (This Week)**:
   - Migrate P0 critical services (2 files)
   - Verify routing service continues to work

2. **Short-term (Next 2 Weeks)**:
   - Migrate P1 core libraries (top 7 files with most calls)
   - Run integration tests after each file

3. **Medium-term (Next Month)**:
   - Complete P1 migration (remaining 19 files)
   - Migrate P2 test files (16 files)

4. **Long-term (Ongoing)**:
   - Gradually migrate P3 scripts and hooks
   - Establish policy: all new code MUST use `config.settings`

---

## Success Metrics

Track progress weekly:

```bash
# Generate updated audit
python3 << 'EOF'
import re
from pathlib import Path

migrated = 0
needs_migration = 0
total_getenv = 0

for py_file in Path('.').rglob('*.py'):
    try:
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()
            has_settings = 'from config import settings' in content
            has_getenv = bool(re.search(r'os\.getenv', content))
            getenv_count = len(re.findall(r'os\.getenv', content))

            total_getenv += getenv_count

            if has_settings and not has_getenv:
                migrated += 1
            elif has_getenv:
                needs_migration += 1
    except:
        pass

total_relevant = migrated + needs_migration
percent = (migrated * 100 / total_relevant) if total_relevant > 0 else 0

print(f"Migration Progress: {percent:.1f}%")
print(f"Migrated: {migrated} files")
print(f"Remaining: {needs_migration} files")
print(f"Total os.getenv() calls: {total_getenv}")
EOF
```

**Target**: 95%+ migration by end of quarter

---

## Questions?

- **Framework Documentation**: `config/README.md`
- **Settings Class**: `config/settings.py`
- **Example Usage**: `services/routing_adapter/config.py`
- **Test Examples**: `tests/test_env_loading.py`, `tests/test_routing_flow.py`

---

**Report Generated**: 2025-11-06
**Next Review**: 2025-11-13 (weekly)
**Version**: 1.0
