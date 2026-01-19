# Configuration Migration - Quick Reference Card

**Keep this open while migrating files to Pydantic Settings**

---

## 1. Setup (Pick One)

### Hooks (~/.claude/hooks/*.py)
```python
import sys
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from config import settings
```

### Skills (.claude/skills/*/scripts/*.py)
```python
import sys
from pathlib import Path
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))
from config import settings
```

### Services/Agents (already in project)
```python
from config import settings
```

---

## 2. Common Replacements

| Before (Legacy) | After (Settings) |
|----------------|------------------|
| `os.getenv("POSTGRES_HOST", "localhost")` | `settings.postgres_host` |
| `int(os.getenv("POSTGRES_PORT", "5432"))` | `settings.postgres_port` |
| `os.getenv("POSTGRES_PASSWORD")` | `settings.postgres_password` |
| `os.getenv("KAFKA_BOOTSTRAP_SERVERS", "...")` | `settings.kafka_bootstrap_servers` |
| `os.getenv("GEMINI_API_KEY")` | `settings.gemini_api_key` |
| `os.getenv("ENABLE_CACHE", "true") == "true"` | `settings.enable_intelligence_cache` |
| `float(os.getenv("MIN_QUALITY", "0.5"))` | `settings.min_pattern_quality` |

---

## 3. Helper Methods

```python
# PostgreSQL DSN
settings.get_postgres_dsn()                    # Sync
settings.get_postgres_dsn(async_driver=True)  # Async

# With legacy aliases
settings.get_effective_postgres_password()
settings.get_effective_kafka_bootstrap_servers()

# Validation
errors = settings.validate_required_services()
if errors:
    for e in errors: print(e)
    exit(1)

# Logging (sanitized)
settings.log_configuration(logger)
```

---

## 4. Delete This Code

```python
# ❌ DELETE
import os
from dotenv import load_dotenv
load_dotenv()

# ❌ DELETE manual .env parsing
with open('.env', 'r') as f:
    for line in f:
        if line.startswith('MY_VAR='):
            ...

# ❌ DELETE manual type conversion
port = int(os.getenv("PORT", "8080"))

# ❌ DELETE manual boolean parsing
enabled = os.getenv("ENABLED", "false").lower() == "true"
```

---

## 5. Checklist

**Before:**
- [ ] Found all `os.getenv()` calls
- [ ] Determined file location
- [ ] Checked Settings class has all vars

**During:**
- [ ] Added sys.path (if needed)
- [ ] Imported settings
- [ ] Replaced os.getenv()
- [ ] Used helper methods
- [ ] Removed legacy imports

**After:**
- [ ] Test import: `python3 file.py`
- [ ] Test functionality
- [ ] No os.getenv() remaining
- [ ] Clean up comments

---

## 6. Common Pitfalls

**❌ Import before sys.path**
```python
from config import settings  # FAILS
sys.path.insert(0, "...")
```

**✅ sys.path before import**
```python
sys.path.insert(0, "...")
from config import settings  # WORKS
```

**❌ Still using os.getenv()**
```python
from config import settings
host = os.getenv("POSTGRES_HOST")  # Don't mix!
```

**✅ Only use settings**
```python
from config import settings
host = settings.postgres_host  # Consistent
```

**❌ Manual DSN construction**
```python
dsn = f"postgresql://{settings.postgres_user}:..."
```

**✅ Use helper**
```python
dsn = settings.get_postgres_dsn()
```

---

## 7. Path Depth Guide

| Location | Parents Count |
|----------|---------------|
| `.claude/skills/<skill>/scripts/file.py` | 4 |
| `.claude/skills/<skill>/file.py` | 3 |
| `agents/lib/file.py` | 0 (no sys.path) |
| `services/*/file.py` | 0 (no sys.path) |
| `~/.claude/hooks/file.py` | Use absolute path |

---

## 8. Testing Snippet

```python
if __name__ == "__main__":
    from config import settings

    # Validate
    errors = settings.validate_required_services()
    if errors:
        print("Errors:", errors)
        exit(1)

    # Test values
    print(f"PostgreSQL: {settings.postgres_host}:{settings.postgres_port}")
    print(f"Kafka: {settings.kafka_bootstrap_servers}")
    print(f"API Key: {'set' if settings.gemini_api_key else 'missing'}")
    print("✅ Config OK")
```

---

## 9. Need Variable Not in Settings?

**Add to** `config/settings.py`:
```python
my_new_var: str = Field(
    default="default_value",
    description="What this variable does"
)
```

**Add to** `.env.example`:
```bash
MY_NEW_VAR=default_value
```

**Validate** range/format:
```python
@field_validator('my_new_var')
@classmethod
def validate_my_new_var(cls, v: str) -> str:
    if not v:
        raise ValueError("my_new_var cannot be empty")
    return v
```

---

## 10. Resources

- **Full Guide**: `docs/configuration/STANDARDIZATION_GUIDE.md`
- **Template**: `docs/configuration/MIGRATION_TEMPLATE.py`
- **Settings Docs**: `config/README.md`
- **Settings Source**: `config/settings.py`
- **Env Template**: `.env.example`

---

**Pro Tip**: Start with files that have most `os.getenv()` calls first.

**Find candidates**:
```bash
grep -r "os\.getenv\|os\.environ" --include="*.py" . | \
  cut -d: -f1 | sort | uniq -c | sort -rn | head -20
```

---

**Version**: 1.0.0 | **Last Updated**: 2025-11-11 | **Correlation ID**: 90b5d27d-ea3a-46f3-bd9f-bc71016414f7
