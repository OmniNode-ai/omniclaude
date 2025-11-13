# OmniClaude Configuration Framework

**Type-safe configuration management using Pydantic Settings**

## Overview

This package provides centralized, type-safe configuration for all OmniClaude services. It replaces scattered `os.getenv()` calls with a validated, well-documented configuration system.

### Key Features

- ✅ **Type Safety**: All configuration values have proper type hints and validation
- ✅ **Auto-Loading**: `.env` files loaded automatically from project root (no manual `source .env` needed)
- ✅ **Environment Files**: Support for `.env`, `.env.dev`, `.env.test`, `.env.prod`
- ✅ **Works Anywhere**: Configuration loads correctly from any directory
- ✅ **Validation**: Configuration validated on startup with clear error messages
- ✅ **Security**: Sensitive values sanitized in logs and exports
- ✅ **Developer Experience**: IDE autocomplete, type checking, inline documentation
- ✅ **Legacy Compatible**: Supports backward compatibility aliases during migration

## Quick Start

### Installation

The configuration framework uses Pydantic Settings and python-dotenv:

```bash
pip install pydantic pydantic-settings python-dotenv
```

### Setup

1. **Copy environment template**:
   ```bash
   cp .env.example .env
   ```

2. **Edit with your values**:
   ```bash
   nano .env  # Set POSTGRES_PASSWORD, GEMINI_API_KEY, etc.
   ```

3. **Start using immediately** - no need to `source .env`!

### Basic Usage

```python
from config import settings

# .env is loaded automatically - no manual exports needed!
# Works from any directory (tests/, scripts/, agents/, etc.)

# Access configuration with full type safety
print(settings.postgres_host)  # str: "192.168.86.200"
print(settings.postgres_port)  # int: 5436
print(settings.kafka_enable_intelligence)  # bool: True

# Get database connection string
dsn = settings.get_postgres_dsn()
# postgresql://postgres:password@192.168.86.200:5436/omninode_bridge

# Async connection (for asyncpg)
async_dsn = settings.get_postgres_dsn(async_driver=True)
# postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge
```

### How Auto-Loading Works

The configuration module automatically loads `.env` files at import time:

1. **Project root detection**: Searches upward from `config/` directory for `.env` or `.git`
2. **Automatic loading**: Uses `python-dotenv` to load environment files
3. **Environment-specific files**: Loads `.env.{ENVIRONMENT}` if `ENVIRONMENT` variable is set
4. **Works anywhere**: Loads from project root regardless of current working directory

**Example**:
```python
# Run from project root
$ python3 tests/test_routing_flow.py
✅ .env loaded from /path/to/project/.env

# Run from tests/ directory
$ cd tests && python3 test_routing_flow.py
✅ .env loaded from /path/to/project/.env

# Run from any directory
$ cd /tmp && python3 /path/to/project/tests/test_routing_flow.py
✅ .env loaded from /path/to/project/.env
```

**No manual exports needed**:
```bash
# ❌ OLD WAY (no longer required)
source .env
export KAFKA_BOOTSTRAP_SERVERS="..."
python3 tests/test_routing_flow.py

# ✅ NEW WAY (automatic)
python3 tests/test_routing_flow.py
```

## Configuration Sections

### 1. External Service Discovery

Services from `omniarchon` repository (192.168.86.101):

```python
settings.archon_intelligence_url  # http://192.168.86.101:8053
settings.archon_search_url        # http://192.168.86.101:8055
settings.archon_bridge_url        # http://192.168.86.101:8054
settings.archon_mcp_url           # http://192.168.86.101:8051
```

### 2. Shared Infrastructure

**Kafka/Redpanda** (192.168.86.200):
```python
settings.kafka_bootstrap_servers      # "192.168.86.200:29092"
settings.kafka_enable_intelligence    # True
settings.kafka_request_timeout_ms     # 5000
```

**PostgreSQL** (192.168.86.200:5436):
```python
settings.postgres_host       # "192.168.86.200"
settings.postgres_port       # 5436
settings.postgres_database   # "omninode_bridge"
settings.postgres_user       # "postgres"
settings.postgres_password   # From .env (REQUIRED)
```

### 3. AI Provider API Keys

```python
settings.gemini_api_key   # Google Gemini API key
settings.zai_api_key      # Z.ai GLM models API key
settings.openai_api_key   # OpenAI API key (optional)
```

### 4. Local Services

**Qdrant Vector Database**:
```python
settings.qdrant_host  # "localhost"
settings.qdrant_port  # 6333
settings.qdrant_url   # "http://localhost:6333"
```

**Valkey Caching**:
```python
settings.enable_intelligence_cache  # True
settings.valkey_url                 # "redis://:password@archon-valkey:6379/0"
settings.cache_ttl_patterns         # 300 (seconds)
settings.cache_ttl_infrastructure   # 3600 (seconds)
```

### 5. Feature Flags

```python
settings.enable_pattern_quality_filter  # False
settings.min_pattern_quality           # 0.5
settings.manifest_cache_ttl_seconds    # 300
```

## Environment Configuration

### Environment File Priority

Configuration is loaded in this order (highest to lowest priority):

1. **System environment variables** (highest priority)
2. **`.env.{ENVIRONMENT}`** file (e.g., `.env.dev`, `.env.prod`)
3. **`.env`** file (default/fallback)
4. **Default values** in Settings class (lowest priority)

### Setting Up Environment Files

```bash
# 1. Copy example to .env
cp .env.example .env

# 2. Edit .env with your actual values
nano .env

# 3. Source environment (optional, Pydantic loads automatically)
source .env

# 4. For specific environments, create .env.dev, .env.test, .env.prod
cp .env .env.dev
nano .env.dev
```

### Environment-Specific Configuration

```bash
# Development
export ENVIRONMENT=development
python your_script.py  # Loads .env.development

# Test
export ENVIRONMENT=test
python your_script.py  # Loads .env.test

# Production
export ENVIRONMENT=production
python your_script.py  # Loads .env.prod
```

## Migration Guide

### Migrating from os.getenv()

**Before (old pattern)**:
```python
import os

# Manual type conversion, no validation
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
enable_cache = os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"

# Risk of typos, no IDE support
db_password = os.environ["POSTGRES_PASSWORD"]  # KeyError if not set!
```

**After (new pattern)**:
```python
from config import settings

# Type-safe, validated, with IDE autocomplete
kafka_servers = settings.kafka_bootstrap_servers  # str
postgres_port = settings.postgres_port            # int
enable_cache = settings.enable_intelligence_cache # bool

# Safe access with validation
db_password = settings.get_effective_postgres_password()  # Handles aliases, raises clear error if missing
```

### Migration Strategy

**Phase 1: Framework Setup** ✅ (COMPLETE)
- [x] Create `config/settings.py` with comprehensive Settings class
- [x] Create `config/__init__.py` for package initialization
- [x] Create `config/README.md` for documentation
- [x] All configuration variables from `.env.example` included

**Phase 2: Gradual Migration** (IN PROGRESS)
1. Start with high-frequency files (most `os.getenv()` calls)
2. Update one module at a time
3. Add imports: `from config import settings`
4. Replace `os.getenv()` with `settings.<field>`
5. Remove unused `import os`
6. Test thoroughly

**Phase 3: Cleanup** (FUTURE)
1. Remove backward compatibility aliases
2. Update documentation
3. Add pre-commit hook to prevent new `os.getenv()` usage

### Migration Resources

**📚 Comprehensive Guides** (in `docs/configuration/`):
- **[STANDARDIZATION_GUIDE.md](../docs/configuration/STANDARDIZATION_GUIDE.md)** - Complete migration guide with detailed examples
- **[QUICK_REFERENCE.md](../docs/configuration/QUICK_REFERENCE.md)** - Quick reference card for active migrations
- **[MIGRATION_TEMPLATE.py](../docs/configuration/MIGRATION_TEMPLATE.py)** - Template file with before/after patterns

**What Each Guide Covers**:

1. **STANDARDIZATION_GUIDE.md** (20KB, comprehensive):
   - Why Pydantic Settings is the standard
   - Benefits and performance characteristics
   - Complete migration pattern with context-specific examples
   - Common pitfalls and how to avoid them
   - Migration checklist
   - Testing strategies
   - Examples for every use case (DB, API keys, Kafka, URLs, feature flags)

2. **QUICK_REFERENCE.md** (5KB, quick lookup):
   - Keep open while migrating
   - Setup patterns by location (hooks/skills/services)
   - Common replacements table
   - Helper methods cheat sheet
   - Checklist and pitfalls
   - Path depth guide
   - Testing snippet

3. **MIGRATION_TEMPLATE.py** (10KB, code template):
   - Working Python file with before/after patterns
   - Copy-paste examples for common scenarios
   - Complete examples (DB, Kafka, API calls)
   - Validation and logging examples
   - Inline migration checklist

**Quick Start**:
```bash
# 1. Read the quick reference
cat docs/configuration/QUICK_REFERENCE.md

# 2. Copy the template
cp docs/configuration/MIGRATION_TEMPLATE.py my_file_migration.py

# 3. Follow the comprehensive guide for details
cat docs/configuration/STANDARDIZATION_GUIDE.md
```

### Identifying Migration Candidates

Files with most `os.getenv()` usage (migration priority):

```bash
# Find files using os.getenv or os.environ
grep -r "os\.getenv\|os\.environ" --include="*.py" . | cut -d: -f1 | sort | uniq -c | sort -rn

# Example output (shows file and count):
#   12 agents/lib/manifest_injector.py
#    8 agents/lib/pattern_quality_scorer.py
#    6 services/routing_adapter/config.py
```

## Advanced Usage

### Validation

Validate configuration on startup:

```python
from config import settings

# Validate required services
errors = settings.validate_required_services()
if errors:
    print("Configuration errors found:")
    for error in errors:
        print(f"  - {error}")
    exit(1)

print("Configuration is valid!")
```

### Logging Configuration

Log configuration with sensitive values sanitized:

```python
import logging
from config import settings

logger = logging.getLogger(__name__)
settings.log_configuration(logger)
```

Output:
```
================================================================================
OmniClaude Configuration
================================================================================

External Services:
  Archon Intelligence: http://192.168.86.101:8053
  Archon Search: http://192.168.86.101:8055
  Archon Bridge: http://192.168.86.101:8054
  Archon MCP: http://192.168.86.101:8051

Shared Infrastructure:
  Kafka: 192.168.86.200:29092
  PostgreSQL: 192.168.86.200:5436/omninode_bridge
  PostgreSQL User: postgres
  PostgreSQL Password: ***

Local Services:
  Qdrant: http://localhost:6333
  Valkey: redis://:***@archon-valkey:6379/0
  Intelligence Cache: enabled

AI Provider API Keys:
  Gemini: configured
  Z.ai: configured
  OpenAI: not set

Feature Flags:
  Event-based Intelligence: True
  Pattern Quality Filter: False

Performance Configuration:
  Kafka Timeout: 5000ms
  Routing Timeout: 5000ms
  Manifest Cache TTL: 300s
  Pattern Cache TTL: 300s
================================================================================
```

### Testing with Different Configuration

```python
import os
from config import reload_settings

# Override environment variable
os.environ['POSTGRES_PORT'] = '5432'
os.environ['ENABLE_PATTERN_QUALITY_FILTER'] = 'true'

# Force reload
settings = reload_settings()

# Verify changes
assert settings.postgres_port == 5432
assert settings.enable_pattern_quality_filter is True
```

### Custom Validators

The Settings class includes several validators:

- **Port validation**: Ensures ports are in valid range (1-65535)
- **Quality threshold**: Validates pattern quality is 0.0-1.0
- **Pool size validation**: Ensures connection pools are reasonable (1-100)
- **Timeout validation**: Ensures timeouts are reasonable (1-60 seconds)
- **Path resolution**: Auto-resolves agent registry and definitions paths

## Helper Methods

### get_postgres_dsn()

Get PostgreSQL connection string:

```python
# Synchronous connection (psycopg2, SQLAlchemy sync)
dsn = settings.get_postgres_dsn()
# postgresql://postgres:password@192.168.86.200:5436/omninode_bridge

# Asynchronous connection (asyncpg, SQLAlchemy async)
async_dsn = settings.get_postgres_dsn(async_driver=True)
# postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge
```

### get_effective_postgres_password()

Get PostgreSQL password with legacy alias support:

```python
# Handles: postgres_password, db_password, omninode_bridge_postgres_password
password = settings.get_effective_postgres_password()
```

### get_effective_kafka_bootstrap_servers()

Get Kafka bootstrap servers with legacy alias support:

```python
# Handles: kafka_bootstrap_servers, kafka_intelligence_bootstrap_servers
servers = settings.get_effective_kafka_bootstrap_servers()
```

### to_dict_sanitized()

Export configuration with sensitive values masked:

```python
config_dict = settings.to_dict_sanitized()
print(config_dict['postgres_password'])  # ***
print(config_dict['gemini_api_key'])     # ***
```

## Common Patterns

### Using in FastAPI Applications

```python
from fastapi import FastAPI
from config import settings

app = FastAPI(title="My Service")

@app.on_event("startup")
async def startup():
    # Validate configuration on startup
    errors = settings.validate_required_services()
    if errors:
        for error in errors:
            print(f"Configuration Error: {error}")
        raise RuntimeError("Invalid configuration")

    # Log configuration
    settings.log_configuration()

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "kafka": settings.kafka_bootstrap_servers,
        "postgres": f"{settings.postgres_host}:{settings.postgres_port}"
    }
```

### Using in Async Applications

```python
import asyncpg
from config import settings

async def connect_to_database():
    # Get async connection string
    dsn = settings.get_postgres_dsn(async_driver=True)

    # Create connection pool
    pool = await asyncpg.create_pool(
        dsn,
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
    )
    return pool
```

### Using in Kafka Producers/Consumers

```python
from aiokafka import AIOKafkaProducer
from config import settings

async def create_kafka_producer():
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        request_timeout_ms=settings.kafka_request_timeout_ms,
    )
    await producer.start()
    return producer
```

## Troubleshooting

### Configuration Validation Failed

**Error**: `Configuration validation failed: POSTGRES_PASSWORD environment variable is required`

**Solution**:
1. Ensure `.env` file exists: `ls -la .env`
2. Verify password is set: `grep POSTGRES_PASSWORD .env`
3. Check for spaces/quotes: Password should be unquoted
4. Source environment: `source .env` (optional, Pydantic loads automatically)

### Port Validation Error

**Error**: `Port must be between 1 and 65535, got 99999`

**Solution**:
1. Check `.env` file for invalid port values
2. Valid port range: 1-65535
3. Common ports: PostgreSQL (5436), Kafka (29092), Qdrant (6333)

### Import Error

**Error**: `ModuleNotFoundError: No module named 'pydantic_settings'`

**Solution**:
```bash
pip install pydantic pydantic-settings
```

### Type Errors

**Error**: `AttributeError: 'Settings' object has no attribute 'invalid_field'`

**Solution**:
- Check spelling of configuration field
- Use IDE autocomplete to see available fields
- Reference `.env.example` for all available variables

## Best Practices

### 1. Never Commit Secrets

```bash
# Add to .gitignore (already done)
.env
.env.*
!.env.example
```

### 2. Use Type Hints

```python
from config import settings

# ✅ Good - Type-safe access
def connect_to_kafka(bootstrap_servers: str) -> None:
    ...

connect_to_kafka(settings.kafka_bootstrap_servers)

# ❌ Bad - Bypassing type safety
connect_to_kafka(os.getenv("KAFKA_BOOTSTRAP_SERVERS"))
```

### 3. Validate Early

```python
# Validate configuration at application startup
def main():
    errors = settings.validate_required_services()
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        exit(1)

    # Continue with application logic
    ...
```

### 4. Log Configuration (Development Only)

```python
import logging
from config import settings

logger = logging.getLogger(__name__)

# Log full configuration in development
if settings.environment == "development":
    settings.log_configuration(logger)
else:
    # Log minimal info in production
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Kafka: {settings.kafka_bootstrap_servers}")
```

### 5. Use Helper Methods

```python
# ✅ Good - Use helper methods
dsn = settings.get_postgres_dsn(async_driver=True)
password = settings.get_effective_postgres_password()

# ❌ Bad - Manual string concatenation
dsn = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@..."
```

## Environment Variables Reference

See `.env.example` for complete reference with descriptions.

### Required Variables

Must be set in `.env`:

```bash
POSTGRES_PASSWORD=<your_password>
```

### Optional Variables with Defaults

All other variables have sensible defaults and can be overridden:

```bash
# External Services (defaults to 192.168.86.101)
ARCHON_INTELLIGENCE_URL=http://192.168.86.101:8053

# Infrastructure (defaults to 192.168.86.200)
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436

# Local Services (defaults to localhost)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Feature Flags (defaults shown)
KAFKA_ENABLE_INTELLIGENCE=true
ENABLE_PATTERN_QUALITY_FILTER=false
```

## Security

### Sensitive Values

The following configuration values contain sensitive information and are sanitized in logs:

- `postgres_password`, `db_password`, `omninode_bridge_postgres_password`
- `gemini_api_key`, `google_api_key`
- `zai_api_key`
- `openai_api_key`
- `valkey_url` (contains password)

### Sanitization

All sensitive values are replaced with `***` in:
- `log_configuration()` output
- `to_dict_sanitized()` output
- Error messages

### Key Rotation

See `SECURITY_KEY_ROTATION.md` for:
- Obtaining API keys from provider dashboards
- Step-by-step rotation procedures
- Testing new keys
- Troubleshooting common issues

## Performance

### Singleton Pattern

The settings instance is created once and reused throughout the application:

```python
from config import settings  # Singleton instance

# Same instance used everywhere
def func1():
    print(settings.postgres_port)

def func2():
    print(settings.postgres_port)
```

### Lazy Validation

Validators run on:
1. Settings instantiation (startup)
2. Field assignment (if `validate_assignment=True`)

This ensures fast startup and early error detection.

## Contributing

### Adding New Configuration

1. Add environment variable to `.env.example` with description
2. Add field to `Settings` class in `config/settings.py`
3. Add type hint and Field() with description
4. Add validator if needed
5. Update this README with usage example
6. Update tests

Example:

```python
# In config/settings.py
class Settings(BaseSettings):
    # ...

    # New configuration field
    my_new_service_url: HttpUrl = Field(
        default="http://localhost:8080",
        description="My new service API endpoint"
    )

    @field_validator('my_new_service_url')
    @classmethod
    def validate_service_url(cls, v: HttpUrl) -> HttpUrl:
        """Validate service URL is accessible."""
        # Add validation logic if needed
        return v
```

### Testing Configuration

```python
import pytest
from config import Settings

def test_configuration_defaults():
    """Test default configuration values."""
    settings = Settings()
    assert settings.postgres_port == 5436
    assert settings.kafka_enable_intelligence is True

def test_configuration_override():
    """Test configuration override from environment."""
    import os
    os.environ['POSTGRES_PORT'] = '5432'
    settings = Settings()
    assert settings.postgres_port == 5432
```

## Related Documentation

- **`.env.example`**: Complete environment variable reference
- **`CLAUDE.md`**: OmniClaude architecture and services
- **`SECURITY_KEY_ROTATION.md`**: API key management
- **`ADR-001`**: Type-safe configuration framework decision record
- **`~/.claude/CLAUDE.md`**: Shared OmniNode infrastructure

## Support

### Questions?

1. Check `.env.example` for available configuration
2. Read this README thoroughly
3. Review example usage patterns
4. Check validation error messages

### Issues?

1. Run validation: `python -c "from config import settings; print(settings.validate_required_services())"`
2. Check `.env` file exists and is properly formatted
3. Verify required variables (especially `POSTGRES_PASSWORD`) are set
4. Use `settings.log_configuration()` to see current values

---

**Version**: 1.0.0
**Last Updated**: 2025-11-05
**Implementation**: Phase 2 - ADR-001 Type-Safe Configuration Framework
