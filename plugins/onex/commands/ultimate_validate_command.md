---
name: ultimate_validate_command
description: "Generate comprehensive validation command for this codebase"
tags: [validation, testing, quality, automation]
---

# Ultimate Validate Command - Comprehensive Codebase Validation

Analyze the codebase deeply and generate a thorough validation command that covers linting, types, style, unit tests, and end-to-end workflows.

**Announce at start:** "Generating comprehensive validation command for this codebase..."

## Execution

1. No arguments required.
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ultimate-validate/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Generate comprehensive codebase validation command",
  prompt="<POLY_PROMPT content>\n\n## Context\nWorking directory: $CWD"
)
```

4. Report the agent's findings to the user.
