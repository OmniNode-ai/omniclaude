# Phase 4 API Client - Quick Start Guide

**File**: `/Users/jonah/.claude/hooks/lib/phase4_api_client.py`

## 🚀 Quick Start (30 seconds)

```python
from phase4_api_client import Phase4APIClient

# Track pattern creation
async with Phase4APIClient() as client:
    result = await client.track_pattern_creation(
        pattern_id="abc123def456",
        pattern_name="AsyncDatabaseWriter",
        code="async def execute_effect(...)...",
        language="python"
    )

    if result["success"]:
        print(f"✅ Tracked: {result['data']['lineage_id']}")
    else:
        print(f"⚠️ Failed: {result['error']}")
```

## 📋 All 7 Endpoints

| Endpoint | Method | Purpose | Performance |
|----------|--------|---------|-------------|
| `track_lineage()` | POST /lineage/track | Track pattern lifecycle events | <50ms |
| `query_lineage()` | GET /lineage/{id} | Get pattern ancestry/descendants | <200ms |
| `compute_analytics()` | POST /analytics/compute | Compute usage analytics | <500ms |
| `get_analytics()` | GET /analytics/{id} | Get analytics (simplified) | <500ms |
| `analyze_feedback()` | POST /feedback/analyze | Trigger feedback loop | <60s |
| `search_patterns()` | POST /search | Search for patterns | <200ms |
| `validate_integrity()` | POST /validate | Validate data integrity | <600ms |

## ⚡ Key Features

- ✅ **2-second timeout** (configurable)
- ✅ **Exponential backoff retry** (3 attempts: 1s, 2s, 4s)
- ✅ **Graceful errors** - Returns `{"success": False}`, never raises
- ✅ **Context manager** - Automatic cleanup
- ✅ **Health check** - Monitor service status

## 🔧 Configuration

```python
# Production (fast fail)
client = Phase4APIClient(timeout=2.0, max_retries=3)

# Development (more patient)
client = Phase4APIClient(timeout=10.0, max_retries=5)

# High-priority (very aggressive)
client = Phase4APIClient(timeout=0.5, max_retries=2)
```

## 📖 Common Patterns

### 1. Track Pattern Creation
```python
async with Phase4APIClient() as client:
    await client.track_pattern_creation(
        pattern_id="xyz789",
        pattern_name="UserAuthHandler",
        code="def authenticate(...)...",
        language="python",
        context={"hook": "pre-commit"}
    )
```

### 2. Query Analytics
```python
async with Phase4APIClient() as client:
    analytics = await client.get_analytics(
        pattern_id="xyz789",
        time_window="weekly"
    )

    if analytics["success"]:
        print(f"Executions: {analytics['usage_metrics']['total_executions']}")
```

### 3. Error Handling
```python
result = await client.track_lineage(...)

if not result["success"]:
    # Graceful degradation - log and continue
    logger.warning(f"Tracking degraded: {result['error']}")
    return None

# Success path
return result["data"]
```

## 📊 Response Format

**Success**:
```json
{
    "success": true,
    "data": { ... },
    "metadata": { "processing_time_ms": 45.23 }
}
```

**Error** (graceful, never raises):
```json
{
    "success": false,
    "error": "Timeout after 2.0s",
    "retries_exhausted": true
}
```

## 🔗 Integration with PatternTracker

```python
from phase4_api_client import Phase4APIClient

class PatternTracker:
    def __init__(self):
        self.api = Phase4APIClient(timeout=2.0)

    async def track(self, pattern_id: str, code: str):
        async with self.api as client:
            result = await client.track_pattern_creation(
                pattern_id=pattern_id,
                pattern_name=self._extract_name(code),
                code=code
            )
            return result["data"] if result["success"] else None
```

## 🩺 Health Check

```python
async with Phase4APIClient() as client:
    health = await client.health_check()

    if health["status"] == "healthy":
        print("✅ All Phase 4 components operational")
    else:
        print(f"⚠️ Status: {health['status']}")
        print(f"Components: {health['components']}")
```

## 📚 Full Documentation

See `/Users/jonah/.claude/hooks/lib/PHASE4_API_CLIENT_DELIVERY.md` for:
- Complete endpoint reference
- Detailed retry logic explanation
- Integration examples
- Troubleshooting guide
- Performance characteristics

---

**Ready to use! All 7 endpoints operational with production-grade resilience. 🚀**
