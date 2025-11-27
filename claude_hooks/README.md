# Claude Code Hooks Configuration Guide

This guide documents how to configure the Claude Smart Permission Hook system for Claude Code, including the PreToolUse hooks for event logging, permission enforcement, and quality validation.

## Overview

The Claude Code hooks system intercepts tool executions at various lifecycle stages:

- **UserPromptSubmit** - Triggered when user submits a prompt (agent routing)
- **PreToolUse** - Triggered before any tool executes (permissions, quality gates)
- **PostToolUse** - Triggered after tool execution completes (metrics, logging)

This documentation focuses on **PreToolUse** hooks for implementing:

1. **Phase 1: Event Discovery** - Log all tool usage for analysis
2. **Phase 2: Permission & Quality Enforcement** - Smart permission decisions and code quality gates

## Architecture

```
User Input --> UserPromptSubmit Hook --> Agent Routing
                      |
                      v
              Tool Invocation
                      |
         +------------+------------+
         |                         |
         v                         v
  PreToolUse Hook           PreToolUse Hook
  (Permission Check)        (Quality Check)
         |                         |
         +------------+------------+
                      |
                      v
              Tool Execution
                      |
                      v
             PostToolUse Hook
              (Metrics/Logging)
```

## Temporary Directory Policy

**IMPORTANT**: This system uses **local `./tmp` directories** instead of system `/tmp`.

### Why Local ./tmp?

1. **Repository Isolation** - Temp files stay within the project
2. **No System Pollution** - Doesn't fill up system temp directories
3. **Easy Cleanup** - `git clean` removes temp files
4. **Consistent Behavior** - Same behavior across all environments
5. **Auditable** - Temp files are visible in the repository

### Safe Temp Directories

The permission hook recognizes these as safe temp locations:

| Path | Description |
|------|-------------|
| `./tmp` | Local repository temp (PREFERRED) |
| `tmp` | Relative tmp without ./ |
| `.claude-tmp` | Claude-specific local temp |
| `.claude/tmp` | Claude cache temp |
| `/dev/null` | Discard output (always safe) |

### Creating Local ./tmp

Each repository should have a `./tmp` directory with a `.gitignore`:

```bash
mkdir -p ./tmp
echo '# Ignore all temp files
*
!.gitignore' > ./tmp/.gitignore
```

The `ensure_local_tmp_exists()` function in the permission hook (`pre-tool-use-permissions.py`) does this automatically when called by hooks and skills.

### System /tmp is NOT Allowed

The following are **NOT** considered safe:
- `/tmp` - System temp directory
- `/private/tmp` - macOS system temp
- `/var/tmp` - System persistent temp
- `/var/folders` - macOS per-user system temp

If a command writes to system temp directories, it will trigger a permission prompt.

---

## Phase 1: Event Discovery

Phase 1 is a **logging-only** implementation that captures all tool usage events for analysis. This helps you understand tool usage patterns before implementing permission logic.

### Step 1: Create the Logger Script

Create `~/.claude/hooks/pre-tool-use-log.sh`:

```bash
#!/usr/bin/env bash
# PreToolUse Logger - Phase 1 Event Discovery
# Logs all tool usage events for analysis without modifying behavior
# Each event is written to a timestamped JSON file

set -euo pipefail

# Configuration - logs go to ~/.claude/logs/
LOG_DIR="${HOME}/.claude/logs"
mkdir -p "${LOG_DIR}"

# Create timestamped log file for this event
TS="$(date -Iseconds | tr ':' '_')"
LOG_FILE="${LOG_DIR}/pre_tool_use_${TS}.json"

# Copy stdin to both file and stdout so Claude still sees it
tee "${LOG_FILE}"
```

**Note**: The actual implementation in `claude_hooks/pre-tool-use-log.sh` uses this simpler approach with timestamped individual JSON files at `~/.claude/logs/pre_tool_use_*.json`.

Make it executable:

```bash
chmod +x ~/.claude/hooks/pre-tool-use-log.sh
```

### Step 2: Configure settings.json (Phase 1)

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-log.sh",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

**Notes**:
- No `matcher` field means ALL tools are logged
- `timeout: 5000` (5 seconds) provides safety margin
- The hook passes through all tool calls unchanged

### Step 3: Verify Phase 1 Setup

1. **Restart Claude Code** to load the new configuration

2. **Perform any tool operation** (create/edit a file, run a command)

3. **Check the logs**:

```bash
# List recent log files (timestamped JSON files)
ls -lt ~/.claude/logs/pre_tool_use_*.json | head -10

# View most recent event
cat "$(ls -t ~/.claude/logs/pre_tool_use_*.json | head -1)" | jq .

# View recent events (last 5 files)
for f in $(ls -t ~/.claude/logs/pre_tool_use_*.json | head -5); do cat "$f"; done | jq -s .

# Count events by tool type
cat ~/.claude/logs/pre_tool_use_*.json | jq -r '.tool_name' | sort | uniq -c | sort -rn
```

### Phase 1 Log Analysis

Analyze captured events to inform Phase 2 permission rules:

```bash
# Most common tools
cat ~/.claude/logs/pre_tool_use_*.json | jq -r '.tool_name' | sort | uniq -c | sort -rn | head -10

# File write patterns
cat ~/.claude/logs/pre_tool_use_*.json | jq -r 'select(.tool_name == "Write") | .tool_input.file_path' | sort | uniq -c

# Edit operations by file type
cat ~/.claude/logs/pre_tool_use_*.json | jq -r 'select(.tool_name == "Edit") | .tool_input.file_path' | grep -oE '\.[^.]+$' | sort | uniq -c

# Bash commands executed
cat ~/.claude/logs/pre_tool_use_*.json | jq -r 'select(.tool_name == "Bash") | .tool_input.command' | head -20
```

---

## Phase 2: Permission & Quality Enforcement

Phase 2 implements intelligent permission decisions and code quality validation.

### Components

1. **pre-tool-use-permissions.py** - Smart permission hook (allow/block/modify)
2. **pre-tool-use-quality.sh** - Code quality enforcement (Write/Edit/MultiEdit)

### Step 1: Permission Hook Setup

The permission hook is located at `claude_hooks/pre-tool-use-permissions.py`.

**Current State**: Phase 1 scaffold that passes through all requests while providing the infrastructure for Phase 2 intelligent permission logic.

#### Key Features

The permission hook includes comprehensive security infrastructure:

**Safe Temporary Directories** (`SAFE_TEMP_DIRS`):
- `./tmp` - Local repository temp (PREFERRED)
- `tmp` - Relative tmp without ./
- `.claude-tmp` - Claude-specific local temp
- `.claude/tmp` - Claude cache temp
- `/dev/null` - Discard output (always safe)

**Destructive Command Detection** (`DESTRUCTIVE_PATTERNS` - 13 patterns):
- `rm`, `rmdir` with proper word boundary matching (avoids false positives like 'form', 'transform')
- `dd` disk operations (avoids false positives like 'add', 'odd')
- `mkfs` filesystem formatting
- Dangerous redirects to root paths (except `/dev/null`)
- Remote code execution (`curl`/`wget` piped to shell)
- `eval` dynamic code execution
- Recursive `chmod`/`chown` on system paths
- Kill signals (`kill -9`, `pkill`)
- Git destructive operations (`push --force`, `reset --hard`, `clean -fd`)

**Sensitive Path Patterns** (`SENSITIVE_PATH_PATTERNS` - 8 patterns):
- `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, `/etc/hosts`
- `/root/`, `~/.ssh/`, `~/.gnupg/`, `~/.aws/`
- `/usr/bin`, `/usr/lib`, `/usr/local`
- `/var/log`, `/var/lib`

**Helper Functions**:
- `ensure_local_tmp_exists()` - Creates local ./tmp with .gitignore
- `is_safe_temp_path(path)` - Validates paths against safe temp locations
- `is_destructive_command(cmd)` - Matches commands against destructive patterns
- `touches_sensitive_path(cmd)` - Detects sensitive path references
- `normalize_bash_command(cmd)` - Normalizes commands for consistent matching
- `load_json()` / `save_json()` - Atomic JSON file operations

**Phase 2 Placeholders** (to be implemented in OMN-95):
- `check_permission_cache()` - Permission decision caching
- `make_permission_decision()` - Intelligent allow/block/modify logic

#### Installation

Copy the hook to your Claude hooks directory:

```bash
cp claude_hooks/pre-tool-use-permissions.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/pre-tool-use-permissions.py
```

> **Note**: See `claude_hooks/pre-tool-use-permissions.py` for the complete implementation with full documentation and pattern definitions.

### Step 2: Verify Quality Hook Exists

The quality enforcement hook should already exist:

```bash
ls -la ~/.claude/hooks/pre-tool-use-quality.sh
```

If not, see `PRETOOLUSE_HOOK_SETUP.md` for installation.

### Step 3: Configure settings.json (Phase 2)

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/user-prompt-submit.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-permissions.py",
            "timeout": 5000
          }
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pre-tool-use-quality.sh",
            "timeout": 3000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/post-tool-use-quality.sh",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

**Notes**:
- Permission hook runs for ALL tools (no matcher)
- Quality hook runs only for Write/Edit/MultiEdit (uses matcher)
- Hooks in array execute in order - permission check happens first

### Step 4: Verify Phase 2 Setup

1. **Restart Claude Code** to load the new configuration

2. **Test permission blocking**:
   - Ask Claude to run a dangerous command (should be blocked)
   - Ask Claude to edit a sensitive file (should be blocked)

3. **Test quality enforcement**:
   - Ask Claude to create a Python file with violations
   - Check for quality warnings in Claude's response

4. **Check the logs**:

```bash
# Permission decisions
tail -20 ~/.claude/hooks/logs/permissions.log

# Quality enforcer logs
tail -20 ~/.claude/hooks/logs/quality_enforcer.log
```

---

## Hook Configuration Reference

### settings.json Structure

```json
{
  "hooks": {
    "<HookType>": [
      {
        "matcher": "<regex>",  // Optional: filter by tool name
        "hooks": [
          {
            "type": "command",
            "command": "<path-to-script>",
            "timeout": <milliseconds>
          }
        ]
      }
    ]
  }
}
```

### Hook Types

| Hook Type | Trigger | Use Cases |
|-----------|---------|-----------|
| `UserPromptSubmit` | User sends prompt | Agent routing, context injection |
| `PreToolUse` | Before tool executes | Permission checks, quality gates |
| `PostToolUse` | After tool completes | Metrics, logging, validation |

### Exit Codes

| Code | Meaning | Effect |
|------|---------|--------|
| `0` | Success | Tool execution proceeds (with any modifications) |
| `2` | Block | Tool execution is blocked with reason shown to user |
| Other | Error | Tool execution proceeds (fail-open behavior) |

### Matcher Regex Examples

```json
// Match all file operation tools
"matcher": "Write|Edit|MultiEdit|Read"

// Match only Bash
"matcher": "Bash"

// Match anything containing "File"
"matcher": ".*File.*"

// Match Write and Edit (not MultiEdit)
"matcher": "^(Write|Edit)$"
```

---

## Viewing Captured Event Logs

### Log File Locations

| File | Purpose |
|------|---------|
| `~/.claude/logs/pre_tool_use_*.json` | Phase 1 event logs (timestamped JSON files) |
| `~/.claude/hooks/logs/permissions.log` | Permission decisions (Phase 2) |
| `~/.claude/hooks/logs/quality_enforcer.log` | Quality check results |
| `~/.claude/hooks/hook-enhanced.log` | UserPromptSubmit hook log |

### Useful Log Commands

```bash
# Real-time monitoring
tail -f ~/.claude/hooks/logs/permissions.log

# Count blocked operations
grep "BLOCKED" ~/.claude/hooks/logs/permissions.log | wc -l

# View recent quality issues
grep -E "(ERROR|WARNING|BLOCKED)" ~/.claude/hooks/logs/quality_enforcer.log | tail -20

# Export Phase 1 events for analysis
cp ~/.claude/logs/pre_tool_use_*.json ~/Desktop/tool-events-$(date +%Y%m%d)/
```

### Kafka Event Viewing (if enabled)

If Kafka logging is enabled, view events in the topic:

```bash
# View recent hook events
kcat -C -b 192.168.86.200:29092 -t omninode.logging.application.v1 -o -10 -e | jq .

# Filter by hook name
kcat -C -b 192.168.86.200:29092 -t omninode.logging.application.v1 -o beginning -e | \
  jq 'select(.payload.logger | contains("pretooluse"))'
```

---

## Troubleshooting

### Hook Not Running

**Symptoms**: No log entries, tools execute without checks

**Solutions**:

1. **Verify settings.json syntax**:
   ```bash
   cat ~/.claude/settings.json | jq .
   ```
   If jq fails, there's a JSON syntax error.

2. **Check file permissions**:
   ```bash
   ls -la ~/.claude/hooks/pre-tool-use-*.sh ~/.claude/hooks/pre-tool-use-*.py
   ```
   Scripts must be executable (`chmod +x`).

3. **Restart Claude Code**:
   Settings only reload on restart.

4. **Check hook path**:
   The path must be exactly `~/.claude/hooks/...` or absolute path.

### Hook Blocking Everything

**Symptoms**: All tools are blocked, can't do anything

**Solutions**:

1. **Check exit codes**: Ensure your script returns `0` for allow, `2` for block only.

2. **Check for exceptions**: Look for errors in logs:
   ```bash
   grep -i error ~/.claude/hooks/logs/*.log
   ```

3. **Temporarily disable**: Comment out the hook in settings.json:
   ```json
   {
     "hooks": {
       // "PreToolUse": [ ... ]
     }
   }
   ```

### Permission Denied Errors

**Symptoms**: `Permission denied` in logs

**Solutions**:

```bash
# Fix script permissions
chmod +x ~/.claude/hooks/pre-tool-use-log.sh
chmod +x ~/.claude/hooks/pre-tool-use-permissions.py
chmod +x ~/.claude/hooks/pre-tool-use-quality.sh

# Fix log directory permissions
chmod 755 ~/.claude/hooks/logs
```

### Python Script Errors

**Symptoms**: `ModuleNotFoundError`, `ImportError`

**Solutions**:

1. **Check Python version**:
   ```bash
   python3 --version  # Requires 3.7+
   ```

2. **Check PYTHONPATH**:
   Add to script: `sys.path.insert(0, os.path.expanduser("~/.claude/hooks/lib"))`

3. **Test script directly**:
   ```bash
   echo '{"tool_name":"Write","tool_input":{"file_path":"test.py"}}' | \
     python3 ~/.claude/hooks/pre-tool-use-permissions.py
   ```

### Timeout Errors

**Symptoms**: Tools hang, then proceed after delay

**Solutions**:

1. **Increase timeout** in settings.json:
   ```json
   "timeout": 10000  // 10 seconds
   ```

2. **Profile your script**:
   ```bash
   time echo '{"tool_name":"Write","tool_input":{}}' | ~/.claude/hooks/pre-tool-use-permissions.py
   ```

3. **Make async operations non-blocking**:
   Use background processes for logging: `(...) &`

### JSON Parse Errors

**Symptoms**: `json.decoder.JSONDecodeError`

**Solutions**:

1. **Ensure script outputs valid JSON**:
   ```bash
   echo '{"tool_name":"test"}' | ~/.claude/hooks/pre-tool-use-log.sh | jq .
   ```

2. **Don't mix stdout and logs**: Write logs to files, not stdout.

3. **Handle empty input**:
   ```python
   import sys
   input_data = sys.stdin.read()
   if not input_data:
       print('{}')
       sys.exit(0)
   ```

---

## Advanced Configuration

### Correlation ID Tracking

Track operations across hooks using correlation IDs:

```bash
# In your hook script
CORRELATION_ID="${CORRELATION_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
export CORRELATION_ID

# Log with correlation ID
echo "[$(date -u)] [CID:${CORRELATION_ID:0:8}] Event logged" >> "$LOG_FILE"
```

### Database Logging

Log events to PostgreSQL for analysis:

```python
from lib.hook_event_logger import log_pretooluse

log_pretooluse(
    tool_name=tool_name,
    tool_input=tool_input,
    correlation_id=correlation_id,
    quality_check_result={"decision": "allow"}
)
```

### Kafka Event Publishing

Publish events to Kafka for real-time monitoring:

```python
from lib.log_hook_event import log_hook_invocation

log_hook_invocation(
    hook_name="PreToolUse",
    prompt=str(tool_input),
    correlation_id=correlation_id
)
```

---

## Related Documentation

- `PRETOOLUSE_HOOK_SETUP.md` - Quality enforcer setup
- `HOOK_LOGGING.md` - Kafka-based logging implementation
- `QUALITY_ENFORCER_README.md` - Code quality validation details
- `POST_TOOL_USE_METRICS_README.md` - PostToolUse metrics collection
- `TROUBLESHOOTING.md` - General troubleshooting guide

---

## Quick Reference

### Phase 1 Setup (Logger Only)

```bash
# 1. Copy the logger script from this repository
cp claude_hooks/pre-tool-use-log.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/pre-tool-use-log.sh

# 2. Update settings.json
# Add PreToolUse hook (see Phase 1 section above)

# 3. Restart Claude Code

# 4. Verify - check for timestamped JSON files
ls -lt ~/.claude/logs/pre_tool_use_*.json | head -5
```

### Phase 2 Setup (Full Enforcement)

```bash
# 1. Copy the permission hook scaffold from this repository
cp claude_hooks/pre-tool-use-permissions.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/pre-tool-use-permissions.py

# 2. Verify quality hook exists
ls -la ~/.claude/hooks/pre-tool-use-quality.sh

# 3. Update settings.json with both hooks (see Phase 2 section above)

# 4. Restart Claude Code

# 5. Verify
tail -f ~/.claude/hooks/logs/permissions.log
tail -f ~/.claude/hooks/logs/quality_enforcer.log
```

---

**Last Updated**: 2025-11-27
**Version**: 1.0.0
**Status**: Production Ready
