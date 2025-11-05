# Configuration Migration Plan

**Migration from `os.getenv()` to Pydantic Settings**

## Overview

This document outlines the migration plan from scattered `os.getenv()` calls to the centralized Pydantic Settings framework.

### Goals

- ✅ **Type Safety**: All configuration values properly typed and validated
- ✅ **Centralization**: Single source of truth for configuration
- ✅ **Developer Experience**: IDE autocomplete, inline documentation
- ✅ **Security**: Consistent handling of sensitive values
- ✅ **Testing**: Easier to mock and test configuration

### Status

- **Phase 1**: Framework Setup ✅ **COMPLETE**
  - [x] `config/settings.py` - Comprehensive Settings class
  - [x] `config/__init__.py` - Package initialization
  - [x] `config/README.md` - Documentation
  - [x] `config/test_settings.py` - Validation tests
  - [x] All configuration variables from `.env.example` included

- **Phase 2**: Gradual Migration 🚧 **NEXT**
- **Phase 3**: Cleanup 📅 **FUTURE**

## Migration Statistics

**Total Files Using `os.getenv()` / `os.environ[]`**: 82+ files

**High-Priority OmniClaude Files** (excluding third-party libraries):
- Core configuration files: **7 files** (23, 17, 14, 14, 14 usages)
- Database integration: **5 files** (12, 8, 8, 8, 5 usages)
- Event processing: **4 files** (11, 9, 8, 6 usages)
- Testing/utilities: **10+ files** (5-14 usages each)

## Migration Priority

### Priority 1: Core Configuration Files (HIGH IMPACT)

These files define configuration patterns used across the codebase. Migrate these first to establish patterns.

| File | Usage Count | Impact | Complexity |
|------|-------------|--------|------------|
| `agents/lib/version_config.py` | 23 | 🔴 High | 🟢 Low |
| `services/routing_adapter/config.py` | 17 | 🔴 High | 🟡 Medium |
| `agents/lib/config/intelligence_config.py` | 14 | 🔴 High | 🟡 Medium |
| `agents/lib/codegen_config.py` | 14 | 🔴 High | 🟡 Medium |
| `tests/test_env_loading.py` | 14 | 🟡 Medium | 🟢 Low |

**Estimated Effort**: 4-6 hours
**Blocking**: None (can start immediately)

### Priority 2: Database & Infrastructure (MEDIUM IMPACT)

Database and Kafka clients used frequently across services.

| File | Usage Count | Impact | Complexity |
|------|-------------|--------|------------|
| `agents/parallel_execution/database_integration.py` | 12 | 🟡 Medium | 🟡 Medium |
| `agents/lib/db.py` | 8 | 🟡 Medium | 🟢 Low |
| `claude_hooks/lib/tracing/postgres_client.py` | 8 | 🟡 Medium | 🟢 Low |
| `cli/utils/db.py` | 5 | 🟢 Low | 🟢 Low |

**Estimated Effort**: 3-4 hours
**Blocking**: None (can run in parallel with Priority 1)

### Priority 3: Event Processing & Services (MEDIUM IMPACT)

Consumer services and event processors.

| File | Usage Count | Impact | Complexity |
|------|-------------|--------|------------|
| `consumers/agent_actions_consumer.py` | 11 | 🟡 Medium | 🟡 Medium |
| `agents/lib/manifest_injector.py` | 9 | 🟡 Medium | 🟡 Medium |
| `agents/lib/router_metrics_logger.py` | 9 | 🟡 Medium | 🟢 Low |
| `claude_hooks/services/hook_event_processor.py` | 8 | 🟡 Medium | 🟡 Medium |
| `agents/services/agent_router_event_service.py` | 8 | 🟡 Medium | 🟡 Medium |
| `agents/lib/intelligence_cache.py` | 8 | 🟡 Medium | 🟡 Medium |
| `agents/lib/kafka_agent_action_consumer.py` | 6 | 🟢 Low | 🟢 Low |

**Estimated Effort**: 5-7 hours
**Blocking**: Should complete Priority 1 first to establish patterns

### Priority 4: Testing & Utilities (LOW IMPACT)

Test files and utility scripts. Migrate after core functionality is complete.

| File | Usage Count | Impact | Complexity |
|------|-------------|--------|------------|
| `agents/lib/test_config_validator.py` | 11 | 🟢 Low | 🟢 Low |
| `agents/tests/test_pattern_quality_database_integration.py` | 8 | 🟢 Low | 🟢 Low |
| `agents/tests/test_framework_schema.py` | 7 | 🟢 Low | 🟢 Low |
| `tests/test_kafka_consumer.py` | 7 | 🟢 Low | 🟢 Low |
| `tests/test_routing_event_flow.py` | 6 | 🟢 Low | 🟢 Low |
| `tests/test_logging_performance.py` | 6 | 🟢 Low | 🟢 Low |
| Various other test files | 5-6 | 🟢 Low | 🟢 Low |

**Estimated Effort**: 8-10 hours
**Blocking**: Can be done incrementally after Priority 1-3

## Migration Process

### Step-by-Step Guide

For each file to migrate:

#### 1. Analysis Phase

```bash
# Review current usage
grep -n "os\.getenv\|os\.environ" <file_path>

# Identify configuration variables used
# Note any custom validation or transformation logic
```

#### 2. Migration Phase

**Before**:
```python
import os

# Manual loading with type conversion
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
enable_cache = os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"

# Risky direct access
db_password = os.environ["POSTGRES_PASSWORD"]  # KeyError if missing!
```

**After**:
```python
from config import settings

# Type-safe, validated access
kafka_servers = settings.kafka_bootstrap_servers  # str
postgres_port = settings.postgres_port            # int
enable_cache = settings.enable_intelligence_cache # bool

# Safe access with clear error handling
db_password = settings.get_effective_postgres_password()  # ValueError with helpful message
```

#### 3. Update Imports

```python
# Remove unused import (if no other os usage)
# import os  # ← Remove this line

# Add settings import
from config import settings
```

#### 4. Replace Configuration Access

Use this replacement guide:

| Old Pattern | New Pattern |
|-------------|-------------|
| `os.getenv("KAFKA_BOOTSTRAP_SERVERS", default)` | `settings.kafka_bootstrap_servers` |
| `os.getenv("POSTGRES_HOST", default)` | `settings.postgres_host` |
| `int(os.getenv("POSTGRES_PORT", "5436"))` | `settings.postgres_port` |
| `bool(os.getenv("ENABLE_CACHE", "true"))` | `settings.enable_intelligence_cache` |
| `os.environ["POSTGRES_PASSWORD"]` | `settings.get_effective_postgres_password()` |

#### 5. Testing Phase

```bash
# Run unit tests for the module
pytest <test_file>

# Verify configuration loads correctly
python -c "from config import settings; print(settings.postgres_port)"

# Run integration tests if applicable
pytest tests/integration/
```

#### 6. Documentation Phase

Update docstrings/comments to reference `settings` instead of environment variables:

```python
# OLD:
"""
Load configuration from KAFKA_BOOTSTRAP_SERVERS environment variable.
"""

# NEW:
"""
Load configuration from settings (centralized configuration).
Uses settings.kafka_bootstrap_servers from config module.
"""
```

## Migration Examples

### Example 1: Simple Configuration Class

**File**: `services/routing_adapter/config.py`

**Before** (17 usages):
```python
import os

class RoutingAdapterConfig:
    def __init__(self):
        self.kafka_bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092"
        )
        self.postgres_host = os.getenv("POSTGRES_HOST", "192.168.86.200")
        self.postgres_port = int(os.getenv("POSTGRES_PORT", "5436"))
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", "")
        # ... 13 more os.getenv calls
```

**After** (0 usages):
```python
from config import settings

class RoutingAdapterConfig:
    """
    Routing adapter service configuration.

    Note: Configuration now loaded from centralized settings.
    This class provides backward compatibility and service-specific defaults.
    """
    def __init__(self):
        # Use centralized settings
        self.kafka_bootstrap_servers = settings.kafka_bootstrap_servers
        self.postgres_host = settings.postgres_host
        self.postgres_port = settings.postgres_port
        self.postgres_password = settings.get_effective_postgres_password()
        # ... use settings for all configuration
```

**Benefits**:
- Type safety (no manual int conversion)
- Validation on startup
- Clear error messages
- Consistent with rest of codebase

### Example 2: Database Client

**File**: `agents/lib/db.py`

**Before** (8 usages):
```python
import os
import asyncpg

async def get_connection():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.environ["POSTGRES_PASSWORD"]  # KeyError risk!

    return await asyncpg.connect(
        host=host, port=port, database=database,
        user=user, password=password
    )
```

**After** (0 usages):
```python
import asyncpg
from config import settings

async def get_connection():
    """Get PostgreSQL connection using centralized settings."""
    # Use helper method for full DSN
    dsn = settings.get_postgres_dsn(async_driver=True)
    return await asyncpg.connect(dsn)

    # OR if you need granular control:
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        user=settings.postgres_user,
        password=settings.get_effective_postgres_password()
    )
```

**Benefits**:
- No manual DSN construction
- Consistent error handling
- Type safety
- Cleaner code

### Example 3: Kafka Consumer

**File**: `consumers/agent_actions_consumer.py`

**Before** (11 usages):
```python
import os
from aiokafka import AIOKafkaConsumer

bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
group_id = os.getenv("KAFKA_CONSUMER_GROUP_ID", "agent-actions-consumer")
timeout_ms = int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000"))
enable_logging = os.getenv("KAFKA_ENABLE_LOGGING", "true").lower() == "true"

consumer = AIOKafkaConsumer(
    "agent-actions",
    bootstrap_servers=bootstrap_servers,
    group_id=group_id,
    request_timeout_ms=timeout_ms,
)
```

**After** (0 usages):
```python
from aiokafka import AIOKafkaConsumer
from config import settings

consumer = AIOKafkaConsumer(
    "agent-actions",
    bootstrap_servers=settings.kafka_bootstrap_servers,
    group_id="agent-actions-consumer",  # Service-specific
    request_timeout_ms=settings.kafka_request_timeout_ms,
)

if settings.kafka_enable_logging:
    # Enable logging...
    pass
```

**Benefits**:
- Correct type for timeout_ms (int, not str)
- Consistent bootstrap servers across all consumers
- Feature flag accessible

## Testing Strategy

### Unit Testing

Test files should use pytest fixtures or environment variable mocking:

**Option 1: pytest fixture** (recommended):
```python
import pytest
from config import Settings

@pytest.fixture
def test_settings():
    """Provide test-specific settings."""
    import os
    os.environ['POSTGRES_HOST'] = 'localhost'
    os.environ['POSTGRES_PORT'] = '5432'
    os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:9092'

    from config import reload_settings
    return reload_settings()

def test_database_connection(test_settings):
    assert test_settings.postgres_host == 'localhost'
    assert test_settings.postgres_port == 5432
```

**Option 2: monkeypatch** (alternative):
```python
def test_configuration(monkeypatch):
    monkeypatch.setenv('POSTGRES_PORT', '5432')

    from config import reload_settings
    settings = reload_settings()

    assert settings.postgres_port == 5432
```

### Integration Testing

Integration tests should use `.env.test`:

```bash
# Create .env.test
cp .env .env.test

# Edit .env.test for test environment
nano .env.test

# Run tests with test environment
ENVIRONMENT=test pytest tests/integration/
```

## Rollout Plan

### Week 1: Priority 1 Files (Core Configuration)

**Goals**:
- Migrate 5 core configuration files
- Establish migration patterns
- Document any issues

**Files**:
1. `agents/lib/version_config.py` (23 usages)
2. `services/routing_adapter/config.py` (17 usages)
3. `agents/lib/config/intelligence_config.py` (14 usages)
4. `agents/lib/codegen_config.py` (14 usages)
5. `tests/test_env_loading.py` (14 usages) - update to test new framework

**Validation**:
- All services start successfully
- Configuration loads correctly
- Tests pass

### Week 2: Priority 2 Files (Database & Infrastructure)

**Goals**:
- Migrate database clients
- Update PostgreSQL connection code
- Standardize connection string generation

**Files**:
1. `agents/parallel_execution/database_integration.py` (12 usages)
2. `agents/lib/db.py` (8 usages)
3. `claude_hooks/lib/tracing/postgres_client.py` (8 usages)
4. `cli/utils/db.py` (5 usages)

**Validation**:
- Database connections work
- Connection pooling functions correctly
- No performance regression

### Week 3: Priority 3 Files (Event Processing)

**Goals**:
- Migrate consumer services
- Update Kafka client code
- Standardize event processing configuration

**Files**:
1. `consumers/agent_actions_consumer.py` (11 usages)
2. `agents/lib/manifest_injector.py` (9 usages)
3. `agents/lib/router_metrics_logger.py` (9 usages)
4. `claude_hooks/services/hook_event_processor.py` (8 usages)
5. `agents/services/agent_router_event_service.py` (8 usages)
6. `agents/lib/intelligence_cache.py` (8 usages)
7. `agents/lib/kafka_agent_action_consumer.py` (6 usages)

**Validation**:
- All consumers start and process events
- Kafka connectivity works
- No event loss during migration

### Week 4: Priority 4 Files (Testing & Utilities)

**Goals**:
- Migrate test files
- Update utility scripts
- Complete migration

**Files**: 15+ test and utility files

**Validation**:
- All tests pass
- Scripts work correctly
- Documentation updated

### Week 5: Cleanup & Documentation

**Goals**:
- Remove backward compatibility aliases
- Update documentation
- Add pre-commit hooks

**Tasks**:
1. Remove legacy aliases from Settings class
2. Update CLAUDE.md with migration completion
3. Add pre-commit hook to prevent new `os.getenv()` usage
4. Create migration completion report

## Common Pitfalls & Solutions

### Pitfall 1: Type Conversion Errors

**Problem**: Manual type conversion scattered across code
```python
port = int(os.getenv("POSTGRES_PORT", "5432"))  # Repeated everywhere
```

**Solution**: Pydantic handles type conversion automatically
```python
port = settings.postgres_port  # Already int, validated
```

### Pitfall 2: Default Values Inconsistency

**Problem**: Different default values in different files
```python
# File 1:
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# File 2:
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")
```

**Solution**: Single source of truth in Settings class
```python
# All files use same value from settings
kafka_servers = settings.kafka_bootstrap_servers  # Consistent default
```

### Pitfall 3: Missing Environment Variables

**Problem**: Silent failures or KeyError
```python
password = os.environ["POSTGRES_PASSWORD"]  # KeyError if not set!
password = os.getenv("POSTGRES_PASSWORD", "")  # Empty string default (unsafe!)
```

**Solution**: Clear validation and error messages
```python
password = settings.get_effective_postgres_password()  # Raises clear error if missing
```

### Pitfall 4: Boolean Environment Variables

**Problem**: String comparison for booleans
```python
enable_cache = os.getenv("ENABLE_CACHE", "true").lower() == "true"  # Verbose
```

**Solution**: Proper boolean type with Pydantic
```python
enable_cache = settings.enable_intelligence_cache  # bool type
```

## Success Metrics

### Quantitative Metrics

- [ ] **Configuration Files**: 82+ files migrated from `os.getenv()` to settings
- [ ] **Type Safety**: 100% of configuration values properly typed
- [ ] **Test Coverage**: All migrated files have updated tests
- [ ] **Documentation**: All references updated

### Qualitative Metrics

- [ ] **Developer Experience**: Developers prefer new pattern (IDE autocomplete, type hints)
- [ ] **Code Quality**: Reduced complexity, clearer error messages
- [ ] **Maintainability**: Single source of truth for configuration
- [ ] **Security**: Consistent handling of sensitive values

## Post-Migration Maintenance

### Pre-Commit Hook

Add hook to prevent new `os.getenv()` usage:

```bash
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: no-os-getenv
      name: Prevent os.getenv usage
      entry: 'Use settings from config module instead of os.getenv'
      language: pygrep
      files: '\.py$'
      exclude: '^(config/|tests/.*test_settings\.py)'
      args: ['os\.getenv|os\.environ\[']
```

### Documentation Updates

- [x] Create `config/README.md` with comprehensive usage guide
- [ ] Update `CLAUDE.md` with configuration section
- [ ] Update all docstrings referencing environment variables
- [ ] Create migration completion report

## Resources

- **Configuration Framework**: `config/settings.py`
- **Documentation**: `config/README.md`
- **Tests**: `config/test_settings.py`
- **Environment Template**: `.env.example`
- **Security Guide**: `SECURITY_KEY_ROTATION.md`

## Questions & Support

### Common Questions

**Q: Can I use both `os.getenv()` and settings during migration?**
A: Yes! The migration is gradual. Both patterns work simultaneously.

**Q: What about environment-specific configuration (.env.dev, .env.prod)?**
A: Supported! Set `ENVIRONMENT=dev` and create `.env.dev`. See `config/README.md`.

**Q: How do I test configuration changes?**
A: Use `reload_settings()` in tests. See Testing Strategy section above.

**Q: What if I need a new configuration variable?**
A: Add it to `Settings` class in `config/settings.py` and `.env.example`. See Contributing section in `config/README.md`.

---

**Version**: 1.0.0
**Last Updated**: 2025-11-05
**Status**: Phase 1 Complete ✅ | Phase 2 Ready to Start 🚀
