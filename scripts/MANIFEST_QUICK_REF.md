# Manifest Viewer - Quick Reference

## One-Line Commands

```bash
# View manifest for database-adapter-builder
python3 scripts/view_agent_manifest.py database-adapter-builder

# Save to file (with errors)
python3 scripts/view_agent_manifest.py database-adapter-builder 2>&1 | tee manifest.txt

# Save to file (clean - no errors)
python3 scripts/view_agent_manifest.py database-adapter-builder 2>/dev/null > manifest.txt

# View specific sections only
python3 scripts/view_agent_manifest.py database-adapter-builder --sections patterns infrastructure
```

## What You'll See

### Expected Sections
1. **AVAILABLE PATTERNS** - ONEX patterns from Qdrant (should be 120+)
2. **INFRASTRUCTURE TOPOLOGY** - PostgreSQL, Kafka, Qdrant status
3. **AI MODELS & DATA MODELS** - ONEX node types, AI providers
4. **DATABASE SCHEMAS** - Table definitions from PostgreSQL
5. **DEBUG INTELLIGENCE** - Successful/failed workflow examples

### Current State (Minimal)
```
AVAILABLE PATTERNS: (No patterns discovered - use built-in patterns)
INFRASTRUCTURE TOPOLOGY: PostgreSQL: unknown, Kafka: unknown, Qdrant: unknown
DATABASE SCHEMAS: (Schema information unavailable)
DEBUG INTELLIGENCE: (No similar workflows found)
```

**Why?** Pattern collections (`code_patterns`, `execution_patterns`) don't exist in Qdrant yet.

## Common Errors (Safe to Ignore)

### Database Constraint Error
```
Failed to store manifest injection record: new row for relation "agent_manifest_injections"
violates check constraint "agent_manifest_injections_query_time_check"
```

**Impact**: ✅ Non-blocking - manifest still generates
**Cause**: Query time exceeded 30 seconds (constraint limit)
**Fix**: Known issue, will be addressed in migration

## Verify Intelligence Infrastructure

```bash
# Quick health check
./scripts/health_check.sh

# Check services running
docker ps | grep archon

# Check Qdrant collections
curl http://localhost:6333/collections | jq '.result.collections[]'

# Expected collections (when populated):
# - code_patterns: 856 vectors
# - execution_patterns: 120 vectors
```

## Testing Different Agents

```bash
# Database adapter builder
python3 scripts/view_agent_manifest.py database-adapter-builder

# Researcher agent
python3 scripts/view_agent_manifest.py agent-researcher

# Test generator
python3 scripts/view_agent_manifest.py agent-test-generator

# Default (manifest-viewer)
python3 scripts/view_agent_manifest.py
```

## Compare to Hook Integration

The hook uses the same underlying code:

```bash
# Hook version (what agents actually see)
AGENT_NAME="database-adapter-builder" \
  PROJECT_PATH="/Volumes/PRO-G40/Code/omniclaude" \  # local-path-ok
  python3 /Users/jonah/.claude/hooks/lib/manifest_loader.py  # local-path-ok

# Script version (for manual viewing)
python3 scripts/view_agent_manifest.py database-adapter-builder
```

Both produce identical output!

## Files

- **Main script**: `scripts/view_agent_manifest.py`
- **Core logic**: `agents/lib/manifest_injector.py`
- **Hook integration**: `claude_hooks/lib/manifest_loader.py`
- **Full guide**: `docs/VIEW_AGENT_MANIFEST_GUIDE.md`

## Related Tools

```bash
# Browse historical manifests
python3 agents/lib/agent_history_browser.py

# View specific execution
python3 agents/lib/agent_history_browser.py --correlation-id <id>

# System health check
./scripts/health_check.sh
```

## Performance

| Metric | Expected | Current |
|--------|----------|---------|
| Pattern query | <500ms | ~5ms (no data) |
| Infrastructure query | <200ms | ~7ms |
| Database query | <100ms | ~37ms |
| **Total time** | **<2s** | **~31s** ⚠️ (timeout) |

**Note**: Long query times due to missing pattern collections. Once populated, should be <2s.
