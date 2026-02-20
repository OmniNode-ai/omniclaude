---
name: crash-recovery
description: Show recent pipeline state for crash recovery
tags: [pipeline, recovery, crash, state]
---

# Crash Recovery

**Usage:** `/crash-recovery [--count N] [--in-progress] [--json]`

Scans `~/.claude/pipelines/*/state.yaml` files sorted by modification time to show what was running before a crash or session end, so you can quickly pick up where you left off.

## Arguments

- `--count N` — show N most recent pipelines (default: 10)
- `--in-progress` — filter to only pipelines not yet at `ready_for_merge` or `done`
- `--json` — output as JSON array (useful for scripting)

## Implementation

When invoked:

1. Execute `${CLAUDE_PLUGIN_ROOT}/skills/crash-recovery/list-pipelines`, passing through any user-provided flags (`--count`, `--in-progress`, `--json`)
2. Display the output table to the user
3. If any in-progress pipelines are shown, offer to resume the most recent one using the `ticket-pipeline` skill or `ticket-work` skill with the relevant `{TICKET_ID}` (these are skills invoked by natural language, not `/command` prefixes)

## Examples

```
/crash-recovery                    # Show 10 most recent pipelines
/crash-recovery --in-progress      # Show only pipelines not yet complete
/crash-recovery --count 5          # Show only 5 most recent
/crash-recovery --json             # JSON output
```
