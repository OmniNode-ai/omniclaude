# PreToolUse Hook Setup Guide

This guide explains how to activate the PreToolUse quality enforcement hook for Claude Code.

## Overview

The PreToolUse hook intercepts Write, Edit, and MultiEdit operations to validate and enforce code quality standards before execution. It provides:

- Automatic naming convention validation
- Intelligent correction suggestions (when full implementation is enabled)
- RAG-powered best practices enforcement (when full implementation is enabled)
- Multi-model AI consensus scoring (when full implementation is enabled)

## Current Status

**STUB IMPLEMENTATION**: The current `quality_enforcer.py` is a pass-through stub. It logs operations but does not perform validation or modifications. This allows you to:
- Test the hook integration without impacting normal operations
- Verify the hook pipeline is working correctly
- Review log output before enabling full enforcement

## Files Created

```
~/.claude/hooks/
├── pre-tool-use-quality.sh       # Hook script (executable)
├── quality_enforcer.py            # Python enforcer (stub, executable)
├── logs/
│   └── quality_enforcer.log       # Operation log
└── PRETOOLUSE_HOOK_SETUP.md      # This file
```

## Manual Activation

### Step 1: Verify Installation

Check that the hook script exists and is executable:

```bash
ls -la ~/.claude/hooks/pre-tool-use-quality.sh
ls -la ~/.claude/hooks/quality_enforcer.py
```

Both files should have execute permissions (`-rwxr-xr-x`).

### Step 2: Configure Claude Code Settings

Add the PreToolUse hook configuration to your Claude Code settings file:

**Location**: `~/.claude/settings.json`

Add or merge the following configuration:

```json
{
  "hooks": {
    "PreToolUse": [
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
    ]
  }
}
```

**Important Notes**:
- If you already have a `hooks` section, merge this configuration into it
- The `matcher` field uses regex to filter tool names
- `timeout` is in milliseconds (3000ms = 3 seconds)
- The hook only intercepts Write, Edit, and MultiEdit operations

### Step 3: Restart Claude Code

After updating settings.json, restart Claude Code for the changes to take effect:

```bash
# If running in terminal
# Press Ctrl+C and restart

# If running as a service
# Restart the service
```

### Step 4: Verify Hook is Active

Create a test file to verify the hook is being invoked:

```bash
# Check the log file after performing a write operation
tail -f ~/.claude/hooks/logs/quality_enforcer.log
```

You should see entries like:
```
[2025-09-29T19:30:00Z] Hook invoked for tool: Write
[2025-09-29T19:30:00Z] Quality check passed for Write
```

## Testing the Hook

Test the hook with a simple operation:

1. Use Claude Code to create or edit a file
2. Check the log file: `cat ~/.claude/hooks/logs/quality_enforcer.log`
3. Verify entries show hook invocations

Example test:
```
Ask Claude: "Create a simple Python file with a hello world function"
Check log: tail ~/.claude/hooks/logs/quality_enforcer.log
```

## Full Settings.json Example

Here's a complete example with both UserPromptSubmit and PreToolUse hooks:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/user-prompt-submit-enhanced.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "PreToolUse": [
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
    ]
  }
}
```

## Upgrading to Full Implementation

To enable full quality enforcement (validation, RAG intelligence, AI consensus):

1. Review the design document: `/Volumes/PRO-G40/Code/Archon/docs/agent-framework/ai-quality-enforcement-system.md`
2. Implement the full `quality_enforcer.py` as specified (lines 821-1077)
3. Create the required library modules in `~/.claude/hooks/lib/`:
   - `validators/naming_validator.py` - Fast validation
   - `intelligence/rag_client.py` - RAG integration
   - `correction/generator.py` - Correction generation
   - `consensus/quorum.py` - AI quorum scoring
4. Configure the system in `~/.claude/hooks/config.yaml`
5. Test with non-critical files first
6. Monitor performance and adjust thresholds

## Hook Behavior

### Pass-Through Conditions

The hook passes through operations without modification when:
- Tool is not Write/Edit/MultiEdit (immediate pass-through)
- quality_enforcer.py is not found (logged warning)
- Python script returns exit code 2 (user declined)
- Python script encounters an error (logged error)
- Full implementation is disabled (current stub behavior)

### Exit Codes

The Python script uses these exit codes:
- `0` - Success (may have modified tool call)
- `2` - User declined suggestion (pass through original)
- Other - Error condition (pass through original)

## Monitoring and Logs

### Log File Location
```
~/.claude/hooks/logs/quality_enforcer.log
```

### Log Format
```
[TIMESTAMP] Hook invoked for tool: TOOL_NAME
[TIMESTAMP] Quality check passed for TOOL_NAME
[TIMESTAMP] ERROR: Error description
```

### Viewing Logs

Real-time monitoring:
```bash
tail -f ~/.claude/hooks/logs/quality_enforcer.log
```

Recent entries:
```bash
tail -20 ~/.claude/hooks/logs/quality_enforcer.log
```

Search for errors:
```bash
grep ERROR ~/.claude/hooks/logs/quality_enforcer.log
```

## Troubleshooting

### Hook Not Running

1. Check if settings.json was updated correctly
2. Verify file permissions are executable
3. Restart Claude Code
4. Check for syntax errors in settings.json: `cat ~/.claude/settings.json | jq .`

### Python Script Errors

1. Check Python version: `python3 --version` (requires 3.7+)
2. Review error logs: `tail -50 ~/.claude/hooks/logs/quality_enforcer.log`
3. Test script directly:
   ```bash
   echo '{"tool_name":"Write","parameters":{"file_path":"test.py","content":"test"}}' | python3 ~/.claude/hooks/quality_enforcer.py
   ```

### Performance Issues

If the hook is causing slowdowns:

1. Check timeout setting in settings.json (currently 3000ms)
2. Reduce timeout if needed: `"timeout": 2000`
3. Monitor execution time in logs
4. Consider disabling for large files in full implementation

## Disabling the Hook

To temporarily disable without removing:

1. Comment out the PreToolUse section in settings.json:
   ```json
   {
     "hooks": {
       // "PreToolUse": [ ... ]
     }
   }
   ```

2. Or remove the section entirely
3. Restart Claude Code

To permanently remove:
```bash
rm ~/.claude/hooks/pre-tool-use-quality.sh
rm ~/.claude/hooks/quality_enforcer.py
```

## Additional Resources

- Design Document: `/Volumes/PRO-G40/Code/Archon/docs/agent-framework/ai-quality-enforcement-system.md`
- Claude Code Hooks Documentation: [Link to official docs]
- Hook Library: `~/.claude/hooks/lib/` (when full implementation is added)

## Support

For issues or questions:
1. Check the log file first
2. Review the design document for full implementation details
3. Test with the stub implementation before enabling full enforcement
4. Report issues with log excerpts and reproduction steps