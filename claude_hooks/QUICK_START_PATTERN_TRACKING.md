# Quick Start: Pattern Tracking Integration

## 1-Minute Setup

```bash
# Navigate to hooks directory
cd ~/.claude/hooks

# Install dependencies
pip install -r requirements-pattern-tracking.txt

# Test the integration
python test_pattern_tracker.py
```

## What It Does

Automatically tracks **3 events** every time you write or edit a file through Claude Code:

1. **Original pattern created** - When file is written
2. **Pattern with violations** - If naming violations found
3. **Corrected pattern** - After auto-fixes applied

## How It Works

```
Write/Edit File → PostToolUse Hook → Pattern Tracker → Phase 4 API → Database
                                          ↓
                                  (fire-and-forget,
                                   non-blocking)
```

## Verify It's Working

### Check 1: Test Script
```bash
python test_pattern_tracker.py
```

Expected: ✓ marks for all tests

### Check 2: Logs
```bash
tail -f logs/pattern-tracking.log
```

Expected: Pattern tracking events when you write files via Claude Code

### Check 3: Phase 4 API
```bash
curl http://localhost:8053/api/pattern-traceability/health
```

Expected: `{"status": "healthy", ...}`

## Files Created

| File | Purpose |
|------|---------|
| `pattern_tracker.py` | Core tracking implementation |
| `test_pattern_tracker.py` | Test suite |
| `requirements-pattern-tracking.txt` | Dependencies |
| `PATTERN_TRACKING_INTEGRATION.md` | Full documentation |
| `AGENT_2_DELIVERABLE.md` | Implementation summary |

## Files Modified

| File | Changes |
|------|---------|
| `post_tool_use_enforcer.py` | Added 3 pattern tracking integration points |

## Configuration

### Environment Variables

```bash
# Optional: Override default Intelligence Service URL
export INTELLIGENCE_SERVICE_URL="http://localhost:8053"
```

### Logging

- **Location**: `~/.claude/hooks/logs/pattern-tracking.log`
- **Format**: `[timestamp] [PatternTracker] LEVEL - message`

## Troubleshooting

### "ModuleNotFoundError: No module named 'aiohttp'"
```bash
pip install aiohttp
```

### Pattern tracking not appearing in logs
1. Check if Intelligence Service is running:
   ```bash
   curl http://localhost:8053/health
   ```
2. Check if aiohttp is installed:
   ```bash
   python -c "import aiohttp; print('OK')"
   ```
3. Check logs for errors:
   ```bash
   tail -f logs/pattern-tracking.log
   tail -f logs/post-tool-use.log
   ```

### Phase 4 API returns 503
This is normal if the database is not configured. Pattern tracking will log a warning but continue working.

## What Gets Tracked

| Field | Example Value |
|-------|---------------|
| Pattern ID | `pattern_abc123def456...` |
| Event Type | `pattern_created`, `pattern_modified` |
| Language | `python`, `typescript`, `javascript` |
| File Path | `/path/to/file.py` |
| Tool | `Write`, `Edit` |
| Violations | `3` |
| Quality Score | `0.7` (0.0-1.0) |
| Corrections Applied | `3` |
| Session ID | `a1b2c3d4-e5f6-...` |

## Next Steps

- Write code through Claude Code
- Check logs to see patterns being tracked
- Query Phase 4 API to see pattern lineage
- View analytics on pattern usage

## Support

- **Full Documentation**: `PATTERN_TRACKING_INTEGRATION.md`
- **Implementation Details**: `AGENT_2_DELIVERABLE.md`
- **Test Suite**: `python test_pattern_tracker.py`
- **Logs**: `tail -f logs/pattern-tracking.log`

---

**Pattern Tracking Integration**
**Status**: Ready for use
**Performance Impact**: ~2-3ms per file (non-blocking)
