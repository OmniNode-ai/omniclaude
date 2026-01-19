# Configuration Standardization Guide

**Purpose**: Standardize all configuration to use Pydantic Settings framework
**Target Audience**: Developers migrating skills and hooks to type-safe configuration
**Status**: Phase 2 - Gradual Migration (82 files with legacy patterns identified)
**Last Updated**: 2025-11-11

---

## Table of Contents

1. [Why Pydantic Settings?](#why-pydantic-settings)
2. [Migration Pattern](#migration-pattern)
3. [Context-Specific Patterns](#context-specific-patterns)
4. [Common Pitfalls](#common-pitfalls)
5. [Migration Checklist](#migration-checklist)
6. [Testing Your Migration](#testing-your-migration)
7. [Examples by Use Case](#examples-by-use-case)

---

## Why Pydantic Settings?

### The Standard Approach

**Pydantic Settings** is now the standard configuration framework for all OmniClaude code (agents, hooks, skills, services).

### Key Benefits

| Feature | Legacy (os.getenv/dotenv) | Pydantic Settings |
|---------|---------------------------|-------------------|
| **Type Safety** | ❌ Manual conversion required | ✅ Automatic with validation |
| **IDE Support** | ❌ No autocomplete | ✅ Full autocomplete + docs |
| **Error Detection** | ❌ Runtime errors | ✅ Startup validation |
| **Default Values** | ❌ Inline fallbacks | ✅ Centralized defaults |
| **Validation** | ❌ Manual checks | ✅ Automatic validators |
| **Documentation** | ❌ Comments only | ✅ Field descriptions |
| **Testing** | ❌ Complex mocking | ✅ Easy override |
| **Security** | ❌ Easy to log secrets | ✅ Automatic sanitization |

### Performance Characteristics

- **Initialization**: ~5-10ms (one-time cost at import)
- **Access**: <1μs per field (same as direct attribute access)
- **Memory**: ~2KB per Settings instance (singleton pattern = one instance)
- **Validation**: Runs once at startup (fail-fast, no runtime overhead)

### Error Handling

**Legacy Pattern** (runtime errors):
```python
# ❌ Fails at runtime when value is used
port = int(os.getenv("POSTGRES_PORT", "5432"))  # TypeError if not numeric
db = connect(host=os.getenv("DB_HOST"))  # None causes cryptic errors
```

**Pydantic Pattern** (startup validation):
```python
# ✅ Fails at startup with clear error message
settings = Settings()  # ValueError: "Port must be between 1-65535, got 99999"
```

---

## Migration Pattern

### Basic Pattern

```python
# ❌ BEFORE (Legacy):
import os
from dotenv import load_dotenv

load_dotenv()  # Manual loading
db_host = os.getenv("POSTGRES_HOST", "localhost")
db_port = int(os.getenv("POSTGRES_PORT", "5432"))
db_password = os.getenv("POSTGRES_PASSWORD")  # Could be None!

# ✅ AFTER (Standard):
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings

db_host = settings.postgres_host        # str: "192.168.86.200" (validated)
db_port = settings.postgres_port        # int: 5436 (validated)
db_password = settings.postgres_password  # Never None (validated at startup)
```

### Why sys.path.insert?

**Problem**: Skills and hooks run from various directories (`.claude/hooks/`, `.claude/skills/`, etc.)

**Solution**: Add project root to Python path before importing config:

```python
import sys
from pathlib import Path

# Add project root to path (adjust path based on your location)
project_root = Path(__file__).resolve().parents[4]  # Adjust number based on depth
sys.path.insert(0, str(project_root))

# Now config import will work from anywhere
from config import settings
```

**Location-Specific Paths**:
- **Hooks** (`~/.claude/hooks/`): Use absolute path `/Volumes/PRO-G40/Code/omniclaude`
- **Skills** (`.claude/skills/<skill>/scripts/`): Navigate up to project root
- **Project files**: Direct import works (config already in path)

---

## Context-Specific Patterns

### 1. Hooks Migration

**Location**: `~/.claude/hooks/*.py`

**Current Pattern** (example from `manifest_loader.py`):
```python
# ❌ BEFORE
import os
project_path = os.environ.get("PROJECT_PATH", "")
```

**Migrated Pattern**:
```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")  # Absolute path for hooks
from config import settings

# Use settings directly - no manual path searching needed
# settings auto-loads .env from project root
```

**Why absolute path?** Hooks run in user's home directory (`~/.claude/hooks/`), far from project root. Absolute path is simplest and most reliable.

### 2. Skills Migration

**Location**: `.claude/skills/<skill-name>/scripts/*.py`

**Current Pattern** (example from `api_key_helper.py`):
```python
# ❌ BEFORE
import os
from pathlib import Path

def load_env_file(env_path: Path):
    """Manual .env file parsing"""
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith('GEMINI_API_KEY='):
                value = line.split('=', 1)[1].strip()
                return value.strip('"').strip("'")
    return None

# Search multiple locations
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    skill_dir = Path(__file__).parent.parent
    api_key = load_env_file(skill_dir / '.env')
if not api_key:
    project_dir = skill_dir.parent.parent.parent
    api_key = load_env_file(project_dir / '.env')
```

**Migrated Pattern**:
```python
# ✅ AFTER
import sys
from pathlib import Path

# Navigate to project root (adjust parents[] count based on depth)
# For .claude/skills/<skill>/scripts/: 4 levels up
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

from config import settings

# Direct access - no manual searching
api_key = settings.gemini_api_key
if not api_key:
    raise ValueError("GEMINI_API_KEY not configured. Set in .env file.")
```

**Key Improvement**:
- ✅ No manual file parsing
- ✅ No multiple fallback locations
- ✅ Single source of truth (.env in project root)
- ✅ Validation at startup (fail-fast)

### 3. Service/Agent Migration

**Location**: `agents/**/*.py`, `services/**/*.py`

**Current Pattern**:
```python
# ❌ BEFORE
import os
kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
enable_cache = os.getenv("ENABLE_CACHE", "true").lower() == "true"
```

**Migrated Pattern**:
```python
# ✅ AFTER
from config import settings

kafka_servers = settings.kafka_bootstrap_servers  # str (validated)
postgres_port = settings.postgres_port            # int (validated)
enable_cache = settings.enable_intelligence_cache # bool (validated)
```

**No sys.path needed** - files in project already have correct path.

---

## Common Pitfalls

### 1. Path Issues

**Problem**: Import fails because config module not in path

```python
# ❌ WRONG
from config import settings  # ImportError: No module named 'config'
```

**Solution**: Add project root to path first

```python
# ✅ CORRECT
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings  # Works!
```

### 2. Import Order

**Problem**: Importing settings before adding to path

```python
# ❌ WRONG
from config import settings  # Fails
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
```

**Solution**: sys.path MUST come first

```python
# ✅ CORRECT
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings  # Works!
```

### 3. Manual load_dotenv() Calls

**Problem**: Calling load_dotenv() is redundant (and can cause issues)

```python
# ❌ WRONG
from dotenv import load_dotenv
load_dotenv()  # Redundant - settings already loads .env
from config import settings
```

**Solution**: Settings auto-loads .env at import time

```python
# ✅ CORRECT
from config import settings  # .env already loaded automatically
```

### 4. Forgetting to Remove Legacy Code

**Problem**: Leaving os.getenv() and dotenv imports

```python
# ❌ INCOMPLETE MIGRATION
import os
from dotenv import load_dotenv
from config import settings

load_dotenv()
db_host = os.getenv("POSTGRES_HOST")  # Still using legacy pattern!
```

**Solution**: Remove ALL legacy configuration code

```python
# ✅ COMPLETE MIGRATION
from config import settings

db_host = settings.postgres_host  # Only use settings
```

### 5. Not Using Helper Methods

**Problem**: Manual string concatenation for DSNs/URLs

```python
# ❌ WRONG - Manual DSN construction
dsn = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_database}"
```

**Solution**: Use provided helper methods

```python
# ✅ CORRECT - Use helper
dsn = settings.get_postgres_dsn()  # Cleaner, less error-prone
async_dsn = settings.get_postgres_dsn(async_driver=True)  # For asyncpg
```

### 6. Hardcoding Paths

**Problem**: Using hardcoded paths that won't work in different environments

```python
# ❌ WRONG - Hardcoded path (won't work for other developers)
sys.path.insert(0, "/Users/jonah/Code/omniclaude")
```

**Solution**: Compute relative path from file location

```python
# ✅ CORRECT - Relative path (works anywhere)
from pathlib import Path
project_root = Path(__file__).resolve().parents[4]  # Adjust number
sys.path.insert(0, str(project_root))
```

**Exception**: Hooks can use absolute path since location is fixed:
```python
# ✅ ACCEPTABLE for hooks only
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
```

---

## Migration Checklist

Use this checklist for each file you migrate:

### Pre-Migration

- [ ] **Identify current pattern**: Find all `os.getenv()`, `os.environ[]`, `load_dotenv()` calls
- [ ] **Determine file location**: Hook? Skill? Service? Agent?
- [ ] **Calculate path depth**: How many parents to project root?
- [ ] **Check configuration coverage**: Are all needed vars in Settings class?

### Migration Steps

- [ ] **Add sys.path.insert()**: At top of file (correct path for location)
- [ ] **Import settings**: `from config import settings`
- [ ] **Replace os.getenv()**: Change to `settings.<field_name>`
- [ ] **Replace manual parsing**: Use settings instead of .env file reading
- [ ] **Use helper methods**: For DSNs, passwords, etc.
- [ ] **Remove legacy imports**: Delete `import os`, `from dotenv import load_dotenv`
- [ ] **Remove load_dotenv()**: Delete all manual .env loading
- [ ] **Remove manual validation**: Settings validates at startup

### Post-Migration

- [ ] **Test import**: `python3 <your_file>.py` (verify no import errors)
- [ ] **Test functionality**: Run with actual workload
- [ ] **Check error handling**: Verify validation errors are clear
- [ ] **Verify .env loading**: Confirm values come from .env
- [ ] **Clean up code**: Remove commented-out legacy code

### Code Review

- [ ] **No os.getenv() remaining**: Search for any missed calls
- [ ] **No dotenv imports**: Verify load_dotenv removed
- [ ] **Correct sys.path**: Path appropriate for file location
- [ ] **Helper methods used**: No manual DSN/URL construction
- [ ] **Error handling**: Graceful failure if config invalid

---

## Testing Your Migration

### 1. Import Test

```bash
# Test that file can be imported without errors
cd /Volumes/PRO-G40/Code/omniclaude
python3 -c "import sys; sys.path.insert(0, '.'); from agents.lib.your_module import *"
```

### 2. Configuration Loading Test

```python
# Test that configuration values are loaded correctly
from config import settings

# Validate required services
errors = settings.validate_required_services()
if errors:
    print("Configuration errors:")
    for error in errors:
        print(f"  - {error}")
else:
    print("✅ Configuration valid")

# Check specific values
print(f"Kafka: {settings.kafka_bootstrap_servers}")
print(f"PostgreSQL: {settings.postgres_host}:{settings.postgres_port}")
print(f"Gemini API Key: {'configured' if settings.gemini_api_key else 'not set'}")
```

### 3. Functional Test

```bash
# Test your hook/skill/script with actual workload
cd /Volumes/PRO-G40/Code/omniclaude
python3 your_script.py --test-mode
```

### 4. Environment Test

```bash
# Test with different .env values
echo "POSTGRES_PORT=5432" >> .env.test
export ENVIRONMENT=test
python3 -c "from config import settings; print(settings.postgres_port)"
# Should print: 5432
```

---

## Examples by Use Case

### Database Connection

```python
# ❌ BEFORE
import os
import psycopg2

host = os.getenv("POSTGRES_HOST", "localhost")
port = int(os.getenv("POSTGRES_PORT", "5432"))
database = os.getenv("POSTGRES_DATABASE", "mydb")
user = os.getenv("POSTGRES_USER", "postgres")
password = os.getenv("POSTGRES_PASSWORD")

conn = psycopg2.connect(
    host=host,
    port=port,
    database=database,
    user=user,
    password=password
)
```

```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings
import psycopg2

# Use helper method (recommended)
conn = psycopg2.connect(settings.get_postgres_dsn())

# OR access fields directly
conn = psycopg2.connect(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_database,
    user=settings.postgres_user,
    password=settings.postgres_password
)
```

### API Keys

```python
# ❌ BEFORE
import os

def get_api_key():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        # Try loading from .env file
        from pathlib import Path
        env_file = Path.home() / '.env'
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('GEMINI_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        break

    if not api_key:
        raise ValueError("GEMINI_API_KEY not found")

    return api_key
```

```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings

def get_api_key():
    """Get Gemini API key from settings."""
    if not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY not configured. "
            "Set in .env file at /Volumes/PRO-G40/Code/omniclaude/.env"
        )
    return settings.gemini_api_key

# Or even simpler - just use directly:
api_key = settings.gemini_api_key
```

### Kafka Configuration

```python
# ❌ BEFORE
import os
from aiokafka import AIOKafkaProducer

bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
timeout_ms = int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000"))
enable_intelligence = os.getenv("KAFKA_ENABLE_INTELLIGENCE", "true").lower() == "true"

producer = AIOKafkaProducer(
    bootstrap_servers=bootstrap_servers,
    request_timeout_ms=timeout_ms
)
```

```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings
from aiokafka import AIOKafkaProducer

# Use helper method (handles legacy aliases)
bootstrap_servers = settings.get_effective_kafka_bootstrap_servers()

producer = AIOKafkaProducer(
    bootstrap_servers=bootstrap_servers,
    request_timeout_ms=settings.kafka_request_timeout_ms
)

# Feature flag check
if settings.kafka_enable_intelligence:
    # Enable intelligence features
    pass
```

### Service URLs

```python
# ❌ BEFORE
import os
import httpx

intelligence_url = os.getenv(
    "ARCHON_INTELLIGENCE_URL",
    "http://192.168.86.101:8053"
)

async def query_intelligence(prompt: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{intelligence_url}/api/query",
            json={"prompt": prompt}
        )
        return response.json()
```

```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings
import httpx

async def query_intelligence(prompt: str):
    """Query Archon Intelligence service."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.archon_intelligence_url}/api/query",
            json={"prompt": prompt},
            timeout=settings.kafka_request_timeout_ms / 1000.0  # Convert to seconds
        )
        return response.json()
```

### Feature Flags

```python
# ❌ BEFORE
import os

enable_cache = os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"
min_quality = float(os.getenv("MIN_PATTERN_QUALITY", "0.5"))
enable_filter = os.getenv("ENABLE_PATTERN_QUALITY_FILTER", "false").lower() == "true"

def get_patterns():
    patterns = fetch_patterns()

    if enable_filter:
        patterns = [p for p in patterns if p.quality >= min_quality]

    if enable_cache:
        cache_patterns(patterns)

    return patterns
```

```python
# ✅ AFTER
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings

def get_patterns():
    """Get patterns with optional quality filtering and caching."""
    patterns = fetch_patterns()

    # Quality filtering (validated at startup: 0.0-1.0)
    if settings.enable_pattern_quality_filter:
        patterns = [
            p for p in patterns
            if p.quality >= settings.min_pattern_quality
        ]

    # Caching
    if settings.enable_intelligence_cache:
        cache_patterns(
            patterns,
            ttl=settings.cache_ttl_patterns  # Validated int (seconds)
        )

    return patterns
```

---

## Quick Reference

### Path Setup by Location

| Location | Path Pattern |
|----------|--------------|
| **Hooks** (`~/.claude/hooks/`) | `sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")` |
| **Skills** (`.claude/skills/<name>/scripts/`) | `Path(__file__).resolve().parents[4]` |
| **Agents** (`agents/lib/`) | No sys.path needed |
| **Services** (`services/`) | No sys.path needed |
| **Tests** (`tests/`) | No sys.path needed |

### Common Settings Fields

| Legacy Variable | Settings Field | Type | Helper Method |
|----------------|----------------|------|---------------|
| `POSTGRES_HOST` | `settings.postgres_host` | `str` | - |
| `POSTGRES_PORT` | `settings.postgres_port` | `int` | - |
| `POSTGRES_PASSWORD` | `settings.postgres_password` | `str` | `get_effective_postgres_password()` |
| `KAFKA_BOOTSTRAP_SERVERS` | `settings.kafka_bootstrap_servers` | `str` | `get_effective_kafka_bootstrap_servers()` |
| `GEMINI_API_KEY` | `settings.gemini_api_key` | `Optional[str]` | - |
| `ENABLE_INTELLIGENCE_CACHE` | `settings.enable_intelligence_cache` | `bool` | - |
| `MIN_PATTERN_QUALITY` | `settings.min_pattern_quality` | `float` | - |

### Helper Methods

```python
# PostgreSQL DSN
settings.get_postgres_dsn()                    # Sync driver
settings.get_postgres_dsn(async_driver=True)  # Async driver

# Password with legacy alias support
settings.get_effective_postgres_password()

# Kafka servers with legacy alias support
settings.get_effective_kafka_bootstrap_servers()

# Validation
errors = settings.validate_required_services()

# Logging (sanitized)
settings.log_configuration(logger)

# Export (sanitized)
config_dict = settings.to_dict_sanitized()
```

---

## Need Help?

### Resources

1. **Configuration README**: `/Volumes/PRO-G40/Code/omniclaude/config/README.md`
2. **Settings Source**: `/Volumes/PRO-G40/Code/omniclaude/config/settings.py`
3. **Environment Template**: `/Volumes/PRO-G40/Code/omniclaude/.env.example`
4. **Project CLAUDE.md**: Section "Type-Safe Configuration Framework"

### Common Questions

**Q: Do I still need to source .env?**
A: No! Pydantic Settings auto-loads .env at import time.

**Q: Can I use environment-specific .env files?**
A: Yes! Set `ENVIRONMENT=test` and settings loads `.env.test` automatically.

**Q: What if a variable isn't in Settings class?**
A: Add it! See `config/README.md` section "Adding New Configuration".

**Q: How do I test without changing .env?**
A: Override environment variables: `os.environ['POSTGRES_PORT'] = '5432'` then `reload_settings()`.

**Q: What if settings import fails?**
A: Check sys.path is correct and config module exists. Try absolute path first.

**Q: Should I migrate all files at once?**
A: No! Migrate incrementally. Start with high-frequency files (most os.getenv calls).

---

## Migration Status

**Phase 2 Progress**:
- ✅ Framework complete (`config/settings.py`, `config/README.md`)
- ✅ 90+ configuration variables defined and validated
- 🔄 82 files identified with legacy patterns
- 🔄 Gradual migration in progress (high-priority files first)
- 🔄 Some hooks already migrated (e.g., `health_checks.py`)
- 🔄 Most skills still using legacy patterns

**Priority Migration Targets**:
1. High-frequency files (10+ os.getenv calls)
2. Database connection files
3. Kafka producer/consumer files
4. Service initialization files
5. Agent framework files
6. Skills and hooks

---

**Version**: 1.0.0
**Last Updated**: 2025-11-11
**Status**: Active Migration Guide
**Correlation ID**: 90b5d27d-ea3a-46f3-bd9f-bc71016414f7
