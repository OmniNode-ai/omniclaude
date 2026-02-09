---
name: suggest-work
description: "Suggest Work Command - Priority Backlog Recommendations"
tags: [linear, backlog, priority, planning]
args:
  - name: --count
    description: "Number of suggestions to return (default: 5)"
    required: false
  - name: --project
    description: "Project name or shortcut (MVP, Beta, Production, etc.)"
    required: false
  - name: --label
    description: "Filter to issues with a specific label"
    required: false
  - name: --json
    description: "Output as JSON for programmatic processing"
    required: false
---

# Suggest Work - Priority Backlog Recommendations

Get highest priority unblocked issues from your Linear backlog with intelligent repo-based prioritization.

**Announce at start:** "Analyzing backlog for work suggestions..."

## Execution

1. Parse arguments from `$ARGUMENTS`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/suggest-work/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Suggest highest priority unblocked backlog items",
  prompt="<POLY_PROMPT content>\n\n## Context\nArguments: $ARGUMENTS\nWorking directory: $CWD\nRepo context: $(basename "$CWD")"
)
```

4. Report the agent's findings to the user.
