# Claude Smart Permission Hook - Phase 1 Handoff Document

**Project**: Claude Smart Permission Hook
**Linear Ticket**: OMN-94 (Phase 1 - Event Shape Discovery)
**Branch**: `jonah/omn-94-claude-smart-permission-hook-phase-1-event-shape-discovery`
**Status**: Phase 1 COMPLETE
**Date**: 2025-11-27

---

## Executive Summary

Phase 1 of the Claude Smart Permission Hook project is complete. This phase established the foundation for intelligent permission management in Claude Code hooks by:

1. Creating an event logger to capture PreToolUse events
2. Building a permission hook skeleton with improved regex patterns
3. Implementing a safe temporary directory policy (local `./tmp` only)
4. Documenting the hook system comprehensively

The system is now ready for Phase 2 (OMN-95) which will implement the actual permission logic.

---

## Linear Ticket References

| Phase | Ticket | Title | Status |
|-------|--------|-------|--------|
| 1 | **OMN-94** | Smart Permission Hook - Event Shape Discovery | COMPLETE |
| 2 | OMN-95 | Smart Permission Hook - Permission Logic | NOT STARTED |
| 3 | OMN-96 | Smart Permission Hook - Caching & Optimization | NOT STARTED |
| 4 | OMN-97 | Smart Permission Hook - Integration & Testing | NOT STARTED |

---

## File Inventory

### Core Hook Files

| File | Purpose | Status |
|------|---------|--------|
| `~/.claude/hooks/pre-tool-use-log.sh` | Event logger (captures all PreToolUse events) | COMPLETE |
| `~/.claude/hooks/pre-tool-use-permissions.py` | Permission hook skeleton (passes through all) | COMPLETE |
| `~/.claude/hooks/README.md` | Comprehensive setup documentation | COMPLETE |
| `~/.claude/settings.json` | Hook configuration | UPDATED |

### Supporting Files

| File | Purpose | Status |
|------|---------|--------|
| `~/.claude/logs/` | Log directory for captured events | EXISTS |
| `/Volumes/PRO-G40/Code/omniclaude/tmp/` | Local temp directory with .gitignore | EXISTS |
| `~/.claude/hooks/pre-tool-use-quality.sh` | Existing quality hook (preserved) | UNCHANGED |

---

## What Was Completed (Phase 1)

### 1. Logger Script (`~/.claude/hooks/pre-tool-use-log.sh`)

Simple bash script that captures all PreToolUse events to timestamped JSON files:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${HOME}/.claude/logs"
mkdir -p "${LOG_DIR}"

TS="$(date -Iseconds | tr ':' '_')"
LOG_FILE="${LOG_DIR}/pre_tool_use_${TS}.json"

# Copy stdin to both file and stdout so Claude still sees it
tee "${LOG_FILE}"
```

**Key Features**:
- Uses `tee` to pass through events unchanged
- Creates timestamped log files
- Does not interfere with tool execution
- Executable (`chmod +x`)

### 2. Permission Hook Skeleton (`~/.claude/hooks/pre-tool-use-permissions.py`)

Full Python skeleton (394 lines) with:

**Safe Temp Directory Policy**:
```python
# POLICY: Always use local ./tmp directory, never system /tmp
SAFE_TEMP_DIRS = frozenset([
    "./tmp",           # Local repository temp directory (PREFERRED)
    "tmp",             # Relative tmp without ./
    ".claude-tmp",     # Claude-specific local temp
    ".claude/tmp",     # Claude cache temp
    "/dev/null",       # Always safe - discards output
])

SAFE_TEMP_PATTERNS = [
    re.compile(r"^\./tmp/"),           # Local ./tmp/ directory
    re.compile(r"^tmp/"),              # Relative tmp/
    re.compile(r"/\.claude-tmp/"),     # .claude-tmp anywhere in path
    re.compile(r"/\.claude/tmp/"),     # .claude/tmp anywhere in path
]
```

**`ensure_local_tmp_exists()` Function**:
```python
def ensure_local_tmp_exists() -> Path:
    """Ensure local ./tmp directory exists with .gitignore."""
    local_tmp = Path.cwd() / "tmp"
    if not local_tmp.exists():
        local_tmp.mkdir(parents=True, exist_ok=True)
        gitignore = local_tmp / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Ignore all temp files\n*\n!.gitignore\n")
    return local_tmp
```

**Improved Destructive Command Detection**:
```python
DESTRUCTIVE_PATTERNS = [
    # rm command - avoid matching 'rm' in words like 'form', 'transform'
    re.compile(r"(?:^|[;&|]\s*)rm\s+(?:-[rfivdP]+\s+)*", re.MULTILINE),
    # rmdir, dd, mkfs, dangerous redirects, curl|sh, eval, chmod/chown, kill, git destructive
    # ... (15 patterns total)
]

SENSITIVE_PATH_PATTERNS = [
    re.compile(r"/etc/(?:passwd|shadow|sudoers|hosts)"),
    re.compile(r"/root/"),
    re.compile(r"~/.ssh/"),
    re.compile(r"~/.gnupg/"),
    re.compile(r"~/.aws/"),
    re.compile(r"/usr/(?:bin|lib|local)/"),
    re.compile(r"/var/(?:log|lib)/"),
]
```

**Current Behavior**: Skeleton passes through all requests (Phase 2 will add logic)

### 3. Settings Configuration (`~/.claude/settings.json`)

Added PreToolUse hooks while preserving existing quality hook:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-quality.sh",
            "timeout": 3000
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-log.sh",
            "timeout": 5000
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-permissions.py",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

**Hook Execution Order**:
1. Quality check (pre-tool-use-quality.sh)
2. Event logging (pre-tool-use-log.sh)
3. Permission check (pre-tool-use-permissions.py - currently pass-through)

### 4. Documentation (`~/.claude/hooks/README.md`)

770+ lines covering:
- Architecture overview
- Temporary directory policy
- Phase 1 and Phase 2 setup guides
- Hook configuration reference
- Troubleshooting guide
- Quick reference commands

### 5. Local Temp Directory

Created `/Volumes/PRO-G40/Code/omniclaude/tmp/` with:
- `.gitignore` file (ignores all except itself)
- Multiple test files from previous operations

---

## Verification Commands

### Check File Permissions

```bash
# All hooks should be executable
ls -la ~/.claude/hooks/pre-tool-use-*.sh ~/.claude/hooks/pre-tool-use-*.py

# Expected output:
# -rwx--x--x  pre-tool-use-log.sh
# -rwx--x--x  pre-tool-use-permissions.py
# -rwxr-xr-x  pre-tool-use-quality.sh
```

### Verify Logger Works

```bash
# Test logger script directly
echo '{"tool_name":"Test","tool_input":{}}' | ~/.claude/hooks/pre-tool-use-log.sh

# Should output the same JSON and create a log file
ls -la ~/.claude/logs/pre_tool_use_*.json | tail -1
```

### Verify Permission Hook Works

```bash
# Test permission hook directly
echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' | python3 ~/.claude/hooks/pre-tool-use-permissions.py

# Should output: {}
# (empty JSON = pass through)
```

### Verify Settings Configuration

```bash
# Check settings.json is valid JSON
cat ~/.claude/settings.json | jq '.hooks.PreToolUse'

# Should show array with 3 hook configurations
```

### Check Log Output

```bash
# View recent log files
ls -lt ~/.claude/logs/pre_tool_use_*.json | head -5

# View contents of most recent log
cat $(ls -t ~/.claude/logs/pre_tool_use_*.json | head -1) | jq .
```

---

## What Remains (Phases 2-4)

### Phase 2: Permission Logic (OMN-95)

**Objective**: Implement actual permission decisions in `pre-tool-use-permissions.py`

**Tasks**:
1. Implement `check_permission_cache()` function
2. Implement `make_permission_decision()` function with:
   - Destructive command detection (use existing patterns)
   - Sensitive path detection (use existing patterns)
   - Safe temp path allowlist (use existing `is_safe_temp_path()`)
3. Add permission caching to reduce repeated prompts
4. Implement decision output format:
   - `{}` = allow (pass through)
   - `{"decision": "block", "reason": "..."}` with exit code 2 = block
5. Integration with existing quality hook

**Key Functions to Implement**:
```python
def check_permission_cache(tool_name: str, params: dict) -> Optional[str]:
    """Check if we have a cached permission decision."""
    # Load cache from CACHE_PATH
    # Return "allow" or "deny" if cached, None if not

def make_permission_decision(tool_name: str, params: dict, hook_input: dict) -> dict:
    """Make a permission decision for a tool invocation."""
    # 1. Check cache
    # 2. Analyze tool_name and params
    # 3. For Bash: check is_destructive_command() and touches_sensitive_path()
    # 4. For Write/Edit: check is_safe_temp_path()
    # 5. Return {} to allow, or {"decision": "block", ...} to block
```

### Phase 3: Caching & Optimization (OMN-96)

**Objective**: Add intelligent caching to reduce permission fatigue

**Tasks**:
1. Implement permission cache file (`~/.claude/.cache/permission-cache.json`)
2. Add TTL-based cache expiration
3. Add pattern-based caching (e.g., "allow all writes to ./src/**")
4. Add session-based caching (reset on Claude restart)
5. Performance optimization (target <100ms hook execution)

### Phase 4: Integration & Testing (OMN-97)

**Objective**: Full integration testing and production deployment

**Tasks**:
1. Integration tests with Claude Code
2. Load testing (many rapid tool calls)
3. Edge case testing (malformed input, timeouts)
4. Documentation updates
5. Production deployment checklist
6. Monitoring and alerting setup

---

## Architecture Notes

### Hook Data Flow

```
User Action (e.g., write file)
         |
         v
+------------------+
| Claude Code      |
| (tool invocation)|
+------------------+
         |
         v
+------------------+     +------------------+
| PreToolUse Hook  | --> | pre-tool-use-    |
| (quality check)  |     | quality.sh       |
+------------------+     +------------------+
         |
         v
+------------------+     +------------------+
| PreToolUse Hook  | --> | pre-tool-use-    |
| (event logger)   |     | log.sh           |
+------------------+     +------------------+
         |                        |
         |              +------------------+
         |              | ~/.claude/logs/  |
         |              | pre_tool_use_*   |
         |              +------------------+
         v
+------------------+     +------------------+
| PreToolUse Hook  | --> | pre-tool-use-    |
| (permission)     |     | permissions.py   |
+------------------+     +------------------+
         |
         v (if allowed)
+------------------+
| Tool Execution   |
| (Write/Edit/Bash)|
+------------------+
```

### Safe Temp Directory Policy

**Rationale**: Using local `./tmp` instead of system `/tmp` ensures:
1. Temp files are contained within the repository
2. No pollution of system temp directories
3. Easy cleanup with `git clean`
4. Consistent behavior across environments
5. Auditable (visible in repository)

**Implementation**:
- `is_safe_temp_path()` function checks against allowlist
- `ensure_local_tmp_exists()` creates `./tmp` with `.gitignore`
- System `/tmp`, `/private/tmp`, `/var/tmp` are NOT considered safe

### Exit Codes

| Code | Meaning | Effect |
|------|---------|--------|
| `0` | Success/Allow | Tool execution proceeds |
| `2` | Block | Tool execution blocked, reason shown to user |
| Other | Error | Tool execution proceeds (fail-open) |

---

## Known Issues / Considerations

### 1. Hook Execution Order

The current order (quality -> log -> permission) means:
- Quality check runs first (can reject before logging)
- Logger captures all events that pass quality check
- Permission check is last (can block after logging)

**Consider**: Reordering in Phase 2 if permission should precede quality.

### 2. Log File Growth

The logger creates a new JSON file for every PreToolUse event. This will accumulate files over time.

**Consider**: Adding log rotation or consolidation in Phase 3.

### 3. Permission Cache Location

Cache path is defined as `~/.claude/.cache/permission-cache.json` but directory may not exist.

**Consider**: Ensuring cache directory creation in Phase 2.

### 4. Regex Pattern Complexity

Destructive command patterns use complex regex with multiline flags. Some edge cases may not be caught.

**Consider**: Testing against real-world command logs in Phase 2.

---

## Next Steps for Continuation

1. **Review this document** to understand current state
2. **Run verification commands** to confirm setup is intact
3. **Analyze captured logs** (`~/.claude/logs/pre_tool_use_*.json`) for event shape discovery
4. **Begin OMN-95** by implementing `make_permission_decision()` function
5. **Test iteratively** with real Claude Code interactions

---

## Contact / References

- **Linear Project**: OmniClaude
- **Branch**: `jonah/omn-94-claude-smart-permission-hook-phase-1-event-shape-discovery`
- **Documentation**: `~/.claude/hooks/README.md`
- **Repository**: `/Volumes/PRO-G40/Code/omniclaude`

---

**Last Updated**: 2025-11-27
**Author**: Automated handoff via OmniClaude agent
**Status**: Ready for Phase 2 continuation
