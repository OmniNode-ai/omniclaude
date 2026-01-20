# Fix: Agent Registry Path Validation Warning

**Date**: 2025-11-06
**Status**: ✅ FIXED
**Impact**: Router consumer service in Docker containers

## Problem

Router consumer logs showed configuration validation warning:
```
Configuration validation failed:
  - Agent registry not found at: /home/omniclaude/.claude/agent-definitions/agent-registry.yaml
```

However, the file was correctly mounted at `/agent-definitions/agent-registry.yaml` and the service was functional. This was a cosmetic validation issue caused by environment variable mismatch.

## Root Cause

**Environment Variable Mismatch**:
- Docker Compose sets: `REGISTRY_PATH=/agent-definitions/agent-registry.yaml`
- Config validation looked for: `AGENT_REGISTRY_PATH` (not set in Docker)
- When `AGENT_REGISTRY_PATH` was not found, it defaulted to: `~/.claude/agent-definitions/agent-registry.yaml`

This caused validation to check the wrong path, even though the service worked correctly because `agent_router_event_service.py` read the `REGISTRY_PATH` environment variable separately.

## Solution

Updated configuration resolution to check both environment variables with proper fallback priority:

**Priority Order**:
1. `AGENT_REGISTRY_PATH` (explicit override for local development)
2. `REGISTRY_PATH` (Docker compatibility)
3. Default: `~/.claude/agent-definitions/agent-registry.yaml`

## Files Changed

### 1. `config/settings.py`
**Location**: Line 761-782
**Change**: Updated `resolve_agent_registry_path` validator to check `REGISTRY_PATH` environment variable

```python
@field_validator("agent_registry_path", mode="before")
@classmethod
def resolve_agent_registry_path(cls, v: Optional[str]) -> str:
    """
    Resolve agent registry path with default.

    Priority:
    1. AGENT_REGISTRY_PATH environment variable (explicit override)
    2. REGISTRY_PATH environment variable (Docker compatibility)
    3. Default: ~/.claude/agent-definitions/agent-registry.yaml
    """
    if v:
        return v

    # Check for Docker-compatible REGISTRY_PATH environment variable
    registry_path = os.getenv("REGISTRY_PATH")
    if registry_path:
        return registry_path

    # Fall back to home directory default
    home_dir = Path.home()
    return str(home_dir / ".claude" / "agent-definitions" / "agent-registry.yaml")
```

### 2. `services/routing_adapter/config.py`
**Location**: Line 76-79
**Change**: Removed redundant fallback logic, now uses `settings.agent_registry_path` directly

```python
# Agent Router Configuration
# Uses settings.agent_registry_path which handles REGISTRY_PATH env var for Docker
self.agent_registry_path = settings.agent_registry_path
self.agent_definitions_path = settings.agent_definitions_path
```

### 3. `agents/services/agent_router_event_service.py`
**Location**: Line 357-365
**Change**: Updated fallback in constructor to check `REGISTRY_PATH` environment variable

```python
# Default registry path
# Priority: 1) explicit parameter, 2) REGISTRY_PATH env var, 3) home directory default
if registry_path is None:
    registry_path = os.getenv("REGISTRY_PATH")
    if registry_path is None:
        registry_path = str(
            Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
        )
self.registry_path = registry_path
```

### 4. `agents/lib/agent_router.py`
**Location**: Line 34-56, 101-115, 476
**Changes**:
- Added `_get_default_registry_path()` helper function
- Updated `__init__` to accept `Optional[str]` and use helper
- Updated `reload_registry` to use helper
- Removed hardcoded `/Users/jonah/.claude/...` paths

```python
def _get_default_registry_path() -> str:
    """
    Get default agent registry path with environment variable support.

    Priority:
    1. AGENT_REGISTRY_PATH environment variable
    2. REGISTRY_PATH environment variable (Docker compatibility)
    3. Default: ~/.claude/agent-definitions/agent-registry.yaml
    """
    if path := os.getenv("AGENT_REGISTRY_PATH"):
        return path
    if path := os.getenv("REGISTRY_PATH"):
        return path
    home_dir = Path.home()
    return str(home_dir / ".claude" / "agent-definitions" / "agent-registry.yaml")
```

### 5. `.env.example`
**Location**: Line 440-447
**Change**: Updated documentation to clarify dual environment variable approach

```bash
# ------------------------------------------------------------------------------
# Agent Registry Configuration
# ------------------------------------------------------------------------------
# Path to agent registry file
# Default: ~/.claude/agent-definitions/agent-registry.yaml
# Note: Docker containers use REGISTRY_PATH=/agent-definitions/agent-registry.yaml
# For local development, you can override with:
# AGENT_REGISTRY_PATH=~/.claude/agent-definitions/agent-registry.yaml
```

## Testing

### Verification Command

```bash
# Test path resolution with REGISTRY_PATH (Docker environment)
python3 -c "
import os
os.environ['REGISTRY_PATH'] = '/agent-definitions/agent-registry.yaml'

from config import settings
print(f'Config settings: {settings.agent_registry_path}')
assert settings.agent_registry_path == '/agent-definitions/agent-registry.yaml'

import sys
sys.path.insert(0, 'agents/lib')
from agent_router import _get_default_registry_path
path = _get_default_registry_path()
print(f'Agent router helper: {path}')
assert path == '/agent-definitions/agent-registry.yaml'

print('✅ All tests passed!')
"
```

**Expected Output**:
```
Config settings: /agent-definitions/agent-registry.yaml
Agent router helper: /agent-definitions/agent-registry.yaml
✅ All tests passed!
```

### Validation in Docker

1. **Restart the router consumer service**:
   ```bash
   cd deployment
   docker-compose restart archon-router-consumer
   ```

2. **Check logs for validation warnings**:
   ```bash
   docker logs omniclaude_archon_router_consumer 2>&1 | grep -A 5 "Configuration validation"
   ```

3. **Expected outcome**:
   - ✅ No "Agent registry not found" warnings
   - ✅ Service starts successfully
   - ✅ Routing operations work normally

## Environment Variable Reference

| Variable | Used By | Priority | Example |
|----------|---------|----------|---------|
| `AGENT_REGISTRY_PATH` | Local dev, explicit override | 1 (highest) | `~/.claude/agent-definitions/agent-registry.yaml` |
| `REGISTRY_PATH` | Docker containers | 2 | `/agent-definitions/agent-registry.yaml` |
| Home directory default | Fallback | 3 (lowest) | `~/.claude/agent-definitions/agent-registry.yaml` |

## Impact

- ✅ **No functional changes** - Service already worked correctly
- ✅ **Cleaner logs** - Removes cosmetic validation warning
- ✅ **Better consistency** - All components use same path resolution logic
- ✅ **Docker compatibility** - Respects Docker-specific environment variable
- ✅ **Local dev compatibility** - Supports explicit override for local development

## Deployment

**No deployment action required** - Changes are backward compatible:
- Existing Docker containers will work without changes (already set `REGISTRY_PATH`)
- Local development will continue working with default home directory path
- Explicit overrides via `AGENT_REGISTRY_PATH` still supported

## Related

- Docker Compose configuration: `deployment/docker-compose.yml`
- Agent registry file: `/agent-definitions/agent-registry.yaml` (in Docker)
- Configuration framework: `config/settings.py` (Pydantic Settings)
- Documentation: `.env.example`, `config/README.md`

---

**Verification**: Testing confirmed path resolution works correctly with both environment variables.
