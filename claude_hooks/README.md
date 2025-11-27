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
#!/bin/bash
# PreToolUse Logger - Phase 1 Event Discovery
# Logs all tool usage events for analysis without modifying behavior

set -euo pipefail

# Configuration
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$HOOK_DIR/logs/pre-tool-use-events.log"
JSON_LOG_FILE="$HOOK_DIR/logs/pre-tool-use-events.jsonl"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Read tool information from stdin
TOOL_INFO=$(cat)

# Extract key fields
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // "unknown"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Log human-readable entry
echo "[$TIMESTAMP] Tool: $TOOL_NAME" >> "$LOG_FILE"

# Log full JSON event for analysis (JSONL format)
echo "$TOOL_INFO" | jq -c --arg ts "$TIMESTAMP" '. + {logged_at: $ts}' >> "$JSON_LOG_FILE"

# Pass through original tool info unchanged (no modification)
echo "$TOOL_INFO"
exit 0
```

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
# View recent events (human-readable)
tail -20 ~/.claude/hooks/logs/pre-tool-use-events.log

# View recent events (JSON)
tail -5 ~/.claude/hooks/logs/pre-tool-use-events.jsonl | jq .

# Count events by tool type
cat ~/.claude/hooks/logs/pre-tool-use-events.jsonl | jq -r '.tool_name' | sort | uniq -c | sort -rn
```

### Phase 1 Log Analysis

Analyze captured events to inform Phase 2 permission rules:

```bash
# Most common tools
jq -r '.tool_name' ~/.claude/hooks/logs/pre-tool-use-events.jsonl | sort | uniq -c | sort -rn | head -10

# File write patterns
jq -r 'select(.tool_name == "Write") | .tool_input.file_path' ~/.claude/hooks/logs/pre-tool-use-events.jsonl | sort | uniq -c

# Edit operations by file type
jq -r 'select(.tool_name == "Edit") | .tool_input.file_path' ~/.claude/hooks/logs/pre-tool-use-events.jsonl | grep -oE '\.[^.]+$' | sort | uniq -c

# Bash commands executed
jq -r 'select(.tool_name == "Bash") | .tool_input.command' ~/.claude/hooks/logs/pre-tool-use-events.jsonl | head -20
```

---

## Phase 2: Permission & Quality Enforcement

Phase 2 implements intelligent permission decisions and code quality validation.

### Components

1. **pre-tool-use-permissions.py** - Smart permission hook (allow/block/modify)
2. **pre-tool-use-quality.sh** - Code quality enforcement (Write/Edit/MultiEdit)

### Step 1: Create Permission Hook

Create `~/.claude/hooks/pre-tool-use-permissions.py`:

```python
#!/usr/bin/env python3
"""
PreToolUse Permission Hook - Phase 2
Implements smart permission decisions based on tool type and context.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Configuration
HOOK_DIR = Path(__file__).parent
LOG_FILE = HOOK_DIR / "logs" / "permissions.log"

# Ensure log directory exists
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def log(message: str) -> None:
    """Log message with timestamp."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

def check_permission(tool_name: str, tool_input: dict) -> dict:
    """
    Check if tool should be allowed, blocked, or modified.

    Returns:
        dict with keys:
        - decision: "allow" | "block" | "modify"
        - reason: str (for blocking)
        - modified_input: dict (for modification)
    """
    # Example rules - customize for your needs

    # Block dangerous bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        dangerous_patterns = [
            "rm -rf /",
            "sudo rm -rf",
            "> /dev/sd",
            "mkfs.",
            "dd if=/dev/zero",
        ]
        for pattern in dangerous_patterns:
            if pattern in command:
                return {
                    "decision": "block",
                    "reason": f"Dangerous command pattern detected: {pattern}"
                }

    # Block writes to sensitive locations
    if tool_name in ("Write", "Edit", "MultiEdit"):
        file_path = tool_input.get("file_path", "")
        sensitive_paths = [
            "/etc/",
            "/usr/",
            "/var/",
            "~/.ssh/",
            "~/.aws/",
            ".env",
        ]
        for sensitive in sensitive_paths:
            if sensitive in file_path:
                return {
                    "decision": "block",
                    "reason": f"Write to sensitive location blocked: {sensitive}"
                }

    # Allow everything else
    return {"decision": "allow"}

def main():
    # Read tool info from stdin
    tool_info = json.loads(sys.stdin.read())
    tool_name = tool_info.get("tool_name", "unknown")
    tool_input = tool_info.get("tool_input", {})

    log(f"Permission check for: {tool_name}")

    # Check permission
    result = check_permission(tool_name, tool_input)

    if result["decision"] == "block":
        log(f"BLOCKED: {tool_name} - {result['reason']}")
        # Output block message and exit with code 2
        output = {
            "decision": "block",
            "reason": result["reason"]
        }
        print(json.dumps(output))
        sys.exit(2)  # Exit code 2 blocks the tool

    elif result["decision"] == "modify":
        log(f"MODIFIED: {tool_name}")
        # Output modified tool info
        tool_info["tool_input"] = result.get("modified_input", tool_input)
        print(json.dumps(tool_info))
        sys.exit(0)

    else:
        log(f"ALLOWED: {tool_name}")
        # Pass through unchanged
        print(json.dumps(tool_info))
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # On error, log and pass through (fail open)
        with open(LOG_FILE, "a") as f:
            f.write(f"[ERROR] {e}\n")
        # Read stdin if not already consumed
        print(json.dumps({"error": str(e)}))
        sys.exit(0)
```

Make it executable:

```bash
chmod +x ~/.claude/hooks/pre-tool-use-permissions.py
```

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
| `~/.claude/hooks/logs/pre-tool-use-events.log` | Human-readable event log |
| `~/.claude/hooks/logs/pre-tool-use-events.jsonl` | JSON lines for analysis |
| `~/.claude/hooks/logs/permissions.log` | Permission decisions |
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

# Export events for analysis
cp ~/.claude/hooks/logs/pre-tool-use-events.jsonl ~/Desktop/tool-events-$(date +%Y%m%d).jsonl
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
# 1. Create logger script
cat > ~/.claude/hooks/pre-tool-use-log.sh << 'EOF'
#!/bin/bash
set -euo pipefail
LOG_FILE="$HOME/.claude/hooks/logs/pre-tool-use-events.log"
mkdir -p "$(dirname "$LOG_FILE")"
TOOL_INFO=$(cat)
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $(echo "$TOOL_INFO" | jq -r '.tool_name')" >> "$LOG_FILE"
echo "$TOOL_INFO"
EOF
chmod +x ~/.claude/hooks/pre-tool-use-log.sh

# 2. Update settings.json
# Add PreToolUse hook (see Phase 1 section above)

# 3. Restart Claude Code

# 4. Verify
tail -f ~/.claude/hooks/logs/pre-tool-use-events.log
```

### Phase 2 Setup (Full Enforcement)

```bash
# 1. Create permission hook
# (See pre-tool-use-permissions.py template above)
chmod +x ~/.claude/hooks/pre-tool-use-permissions.py

# 2. Verify quality hook exists
ls -la ~/.claude/hooks/pre-tool-use-quality.sh

# 3. Update settings.json with both hooks

# 4. Restart Claude Code

# 5. Verify
tail -f ~/.claude/hooks/logs/permissions.log
tail -f ~/.claude/hooks/logs/quality_enforcer.log
```

---

**Last Updated**: 2025-11-27
**Version**: 1.0.0
**Status**: Production Ready
