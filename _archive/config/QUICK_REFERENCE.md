# Configuration Framework - Quick Reference Card

**Fast reference for migrating from `os.getenv()` to Pydantic Settings**

## Quick Start

```python
# Import settings
from config import settings

# Access configuration (type-safe, validated)
settings.postgres_host            # str: "192.168.86.200"
settings.postgres_port            # int: 5436
settings.kafka_bootstrap_servers  # str: "192.168.86.200:29092"
settings.enable_intelligence_cache # bool: True
```

## Common Migrations

### Database Configuration

| Before | After |
|--------|-------|
| `os.getenv("POSTGRES_HOST", "localhost")` | `settings.postgres_host` |
| `int(os.getenv("POSTGRES_PORT", "5432"))` | `settings.postgres_port` |
| `os.getenv("POSTGRES_DATABASE", "db")` | `settings.postgres_database` |
| `os.environ["POSTGRES_PASSWORD"]` | `settings.get_effective_postgres_password()` |

**Connection string**:
```python
# Sync
dsn = settings.get_postgres_dsn()

# Async
dsn = settings.get_postgres_dsn(async_driver=True)
```

### Kafka Configuration

| Before | After |
|--------|-------|
| `os.getenv("KAFKA_BOOTSTRAP_SERVERS")` | `settings.kafka_bootstrap_servers` |
| `int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000"))` | `settings.kafka_request_timeout_ms` |
| `os.getenv("KAFKA_ENABLE_INTELLIGENCE", "true") == "true"` | `settings.kafka_enable_intelligence` |

### External Services

| Before | After |
|--------|-------|
| `os.getenv("ARCHON_INTELLIGENCE_URL")` | `settings.archon_intelligence_url` |
| `os.getenv("ARCHON_SEARCH_URL")` | `settings.archon_search_url` |
| `os.getenv("QDRANT_URL")` | `settings.qdrant_url` |

### API Keys

| Before | After |
|--------|-------|
| `os.getenv("GEMINI_API_KEY")` | `settings.gemini_api_key` |
| `os.getenv("ZAI_API_KEY")` | `settings.zai_api_key` |
| `os.getenv("OPENAI_API_KEY")` | `settings.openai_api_key` |

### Feature Flags

| Before | After |
|--------|-------|
| `os.getenv("ENABLE_PATTERN_QUALITY_FILTER", "false") == "true"` | `settings.enable_pattern_quality_filter` |
| `float(os.getenv("MIN_PATTERN_QUALITY", "0.5"))` | `settings.min_pattern_quality` |
| `int(os.getenv("MANIFEST_CACHE_TTL_SECONDS", "300"))` | `settings.manifest_cache_ttl_seconds` |

## Migration Checklist

For each file you migrate:

- [ ] Add import: `from config import settings`
- [ ] Replace all `os.getenv()` with `settings.<field>`
- [ ] Replace all `os.environ[]` with `settings.get_effective_*()` or `settings.<field>`
- [ ] Remove `import os` if no longer needed
- [ ] Remove manual type conversion (int, bool, float)
- [ ] Update tests to use `reload_settings()` if needed
- [ ] Run tests to verify
- [ ] Update docstrings/comments

## Helper Methods

```python
from config import settings

# PostgreSQL connection string
dsn = settings.get_postgres_dsn(async_driver=False)  # or True
# postgresql://postgres:pass@host:port/db

# Get password (handles aliases)
password = settings.get_effective_postgres_password()

# Get Kafka servers (handles aliases)
servers = settings.get_effective_kafka_bootstrap_servers()

# Validate configuration
errors = settings.validate_required_services()
if errors:
    for error in errors:
        print(f"Error: {error}")

# Log configuration (sanitized)
settings.log_configuration()

# Export as dict (sanitized)
config_dict = settings.to_dict_sanitized()
```

## Testing

### Option 1: pytest fixture
```python
@pytest.fixture
def test_settings():
    import os
    os.environ['POSTGRES_PORT'] = '5432'
    from config import reload_settings
    return reload_settings()

def test_something(test_settings):
    assert test_settings.postgres_port == 5432
```

### Option 2: monkeypatch
```python
def test_something(monkeypatch):
    monkeypatch.setenv('POSTGRES_PORT', '5432')
    from config import reload_settings
    settings = reload_settings()
    assert settings.postgres_port == 5432
```

## Configuration Sections

### External Services (omniarchon)
- `archon_intelligence_url` - Intelligence API
- `archon_search_url` - Search API
- `archon_bridge_url` - Bridge API
- `archon_mcp_url` - MCP server

### Shared Infrastructure (omninode_bridge)
- **Kafka**: `kafka_bootstrap_servers`, `kafka_request_timeout_ms`, `kafka_enable_*`
- **PostgreSQL**: `postgres_host`, `postgres_port`, `postgres_database`, `postgres_user`, `postgres_password`

### AI Providers
- `gemini_api_key` - Google Gemini
- `zai_api_key` - Z.ai GLM models
- `openai_api_key` - OpenAI

### Local Services
- **Qdrant**: `qdrant_host`, `qdrant_port`, `qdrant_url`
- **Valkey**: `valkey_url`, `enable_intelligence_cache`

### Feature Flags
- `enable_pattern_quality_filter` - Pattern quality filtering
- `min_pattern_quality` - Quality threshold (0.0-1.0)
- `manifest_cache_ttl_seconds` - Cache TTL

### Performance
- `kafka_request_timeout_ms` - Kafka timeout
- `routing_timeout_ms` - Routing timeout
- `cache_ttl_*` - Various cache TTLs

## Common Patterns

### Database Client
```python
import asyncpg
from config import settings

async def get_db_connection():
    dsn = settings.get_postgres_dsn(async_driver=True)
    return await asyncpg.connect(dsn)
```

### Kafka Producer
```python
from aiokafka import AIOKafkaProducer
from config import settings

producer = AIOKafkaProducer(
    bootstrap_servers=settings.kafka_bootstrap_servers,
    request_timeout_ms=settings.kafka_request_timeout_ms,
)
```

### FastAPI Startup
```python
from fastapi import FastAPI
from config import settings

@app.on_event("startup")
async def startup():
    errors = settings.validate_required_services()
    if errors:
        raise RuntimeError(f"Configuration errors: {errors}")
    settings.log_configuration()
```

## Type Safety Benefits

```python
# OLD (no type safety)
port = os.getenv("POSTGRES_PORT", "5432")  # str!
# Need to convert manually:
port = int(port)  # Can fail!

# NEW (type-safe)
port = settings.postgres_port  # int, validated
# IDE knows it's an int, autocomplete works
```

## Environment Files

### Priority Order
1. System environment variables (highest)
2. `.env.{ENVIRONMENT}` (e.g., `.env.dev`)
3. `.env` (default)
4. Settings defaults (lowest)

### Setup
```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env

# For specific environments
cp .env .env.dev
export ENVIRONMENT=development
```

## Validation

All configuration validated on startup:
- **Ports**: Must be 1-65535
- **Quality thresholds**: Must be 0.0-1.0
- **Timeouts**: Must be 1000-60000ms
- **Pool sizes**: Must be 1-100
- **Required services**: PostgreSQL password, Kafka servers

## Security

**Sensitive fields** (automatically sanitized in logs):
- All `*_password` fields
- All `*_api_key` fields
- `valkey_url` (contains password)

**Always**:
- Use `settings.to_dict_sanitized()` for logging
- Use `settings.log_configuration()` (auto-sanitizes)
- Never commit `.env` files

## Troubleshooting

### Import Error
```bash
pip install pydantic pydantic-settings
```

### Validation Error
```python
# Check what's wrong
from config import settings
errors = settings.validate_required_services()
print(errors)
```

### Configuration Not Loading
```bash
# Verify .env exists
ls -la .env

# Check specific value
grep POSTGRES_PASSWORD .env

# Test loading
python -c "from config import settings; print(settings.postgres_port)"
```

## Complete Examples

### Example: Database Integration

**Before**:
```python
import os
import asyncpg

async def connect():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    db = os.getenv("POSTGRES_DATABASE", "mydb")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.environ["POSTGRES_PASSWORD"]  # Risk!

    conn = await asyncpg.connect(
        host=host, port=port, database=db,
        user=user, password=password
    )
    return conn
```

**After**:
```python
import asyncpg
from config import settings

async def connect():
    dsn = settings.get_postgres_dsn(async_driver=True)
    return await asyncpg.connect(dsn)
```

### Example: Configuration Class

**Before**:
```python
import os

class ServiceConfig:
    def __init__(self):
        self.kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        self.timeout = int(os.getenv("REQUEST_TIMEOUT_MS", "5000"))
        self.enable_cache = os.getenv("ENABLE_CACHE", "true") == "true"
```

**After**:
```python
from config import settings

class ServiceConfig:
    def __init__(self):
        self.kafka_servers = settings.kafka_bootstrap_servers
        self.timeout = settings.request_timeout_ms
        self.enable_cache = settings.enable_intelligence_cache
```

## Resources

- **Full Documentation**: `config/README.md`
- **Migration Plan**: `config/MIGRATION_PLAN.md`
- **Settings Class**: `config/settings.py`
- **Environment Template**: `.env.example`

---

**Quick Tips**:
- Always import: `from config import settings`
- Types are automatic: `settings.postgres_port` is `int`
- Validation is automatic: invalid config raises clear errors
- IDE autocomplete works: type `settings.` and see all options
- Helper methods available: `get_postgres_dsn()`, `validate_required_services()`, etc.
