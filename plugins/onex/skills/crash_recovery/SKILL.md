---
description: Show recent pipeline state to orient after an unexpected session end or crash
mode: full
version: "1.0.0"
level: advanced
debug: true
category: pipeline
tags:
  - pipeline
  - recovery
  - state
  - crash
author: omninode
args:
  - name: --count
    description: "Number of pipelines to show (default 10)"
    required: false
  - name: --in-progress
    description: "Show only pipelines currently in an active phase (not ready_for_merge or done)"
    required: false
  - name: --json
    description: "Output as JSON instead of a markdown table"
    required: false
---

# Crash Recovery

**Announce at start:** "I'm using the crash-recovery skill to show recent pipeline state."

## Overview

Reads `~/.claude/pipelines/*/state.yaml` files sorted by modification time and shows what was running before a crash. Use this after any unexpected session end to quickly orient yourself.

The skill scans all pipeline state directories, extracts ticket ID, current phase, branch name, and modification time, then presents them newest-first so the most recently active work is immediately visible. Combine with `--in-progress` to narrow down to pipelines that still need action.

## Quick Start

```bash
# Show the 10 most recently modified pipelines
/crash-recovery

# Show only pipelines still in an active (non-terminal) phase
/crash-recovery --in-progress

# Show 5 pipelines in JSON format
/crash-recovery --count 5 --json
```

## Steps

### 1. Run the list-pipelines script

Execute the bundled script, passing any flags the user supplied directly through:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/crash_recovery/list-pipelines [flags]
```

Where `[flags]` is the verbatim set of arguments the user passed to `/crash-recovery`. Examples:

```bash
# No flags -- show default 10
${CLAUDE_PLUGIN_ROOT}/skills/crash_recovery/list-pipelines

# In-progress only
${CLAUDE_PLUGIN_ROOT}/skills/crash_recovery/list-pipelines --in-progress

# Custom count, JSON output
${CLAUDE_PLUGIN_ROOT}/skills/crash_recovery/list-pipelines --count 5 --json
```

### 2. Display the output

- If `--json` was passed, display the raw JSON.
- Otherwise, display the markdown table exactly as returned by the script.

### 3. Offer resume suggestions for in-progress tickets

For each ticket shown whose phase is **not** `ready_for_merge` or `done`, offer:

- "Use the `ticket-pipeline` skill for OMN-XXXX to resume from where it stopped."
- "Use the `ticket-work` skill for OMN-XXXX if it was in the `implement` phase and you want to continue coding."

Note: `ticket-pipeline` and `ticket-work` are **skills**, not slash commands. They are
invoked by asking Claude to use them (e.g., "use the ticket-pipeline skill for OMN-2367"),
not via a `/command` prefix.

Example follow-up after displaying the table:

```
OMN-2367 was in 'implement' phase. Ask Claude to use the ticket-pipeline skill for OMN-2367
to resume, or the ticket-work skill to continue implementation directly.
```

## Output Format

Default output is a fixed-width column table (newest first). Columns are space-padded, separated by a single space, with a dashed separator line — not standard markdown table syntax:

```
Ticket               Title                                                    Phase                  Branch                          Age
-------------------- -------------------------------------------------------- ---------------------- ------------------------------- ----------
OMN-2371             fix: session-end feedback loop is no-op                  ready_for_merge        omn-2371-fix-session-end        5m ago
OMN-2367             feat: delegation orchestrator                             implement              omn-2367-delegation             12m ago
OMN-2355             fix: context injection timeout                            local_review           omn-2355-context-inject         18m ago
```

Columns:

| Column | Source |
|--------|--------|
| `Ticket` | `ticket_id` field from state file |
| `Title` | `title` field (or Linear issue title if state file omits it) |
| `Phase` | `current_phase` field from state file |
| `Branch` | `branch_name` field |
| `Age` | Human-readable elapsed time since file mtime |

## Pipeline State Contract

Pipeline state files (`~/.claude/pipelines/*/state.yaml`) should be parsed as
`ModelPipelineState` from `omnibase_core.models.pipeline`:

```python
state = ModelPipelineState.from_yaml(path.read_text())
# ModelPipelineState uses extra="allow" to tolerate legacy fields
# Both "newer" and "older" schemas parse successfully
```

**Write safety:** Producers MUST use atomic write (temp file + `os.rename()`) to prevent
consumers from reading partial files. Consumers SHOULD retry once on `yaml.YAMLError`
(transient partial-read during atomic rename window).

> **Note:** This contract reference is behavioral guidance for the LLM executing this skill.
> Runtime validation not yet implemented. The model serves as the source of truth for field
> names, types, and semantics. Real enforcement at the file I/O boundary is a follow-up task.

## See Also

- `ticket-pipeline` skill -- full pipeline orchestrator (implement → review → PR → merge)
- `ticket-work` skill -- jump directly into the implement phase for a ticket
- `checkpoint` skill -- per-phase checkpoint management for finer-grained resume
