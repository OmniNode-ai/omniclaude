---
name: project-status
description: "Project Status Command - Linear Insights Dashboard"
tags: [linear, project, status, reporting]
args:
  - name: project
    description: "Project name or shortcut (MVP, Beta, Production, etc.)"
    required: false
  - name: --all
    description: "Show all projects overview"
    required: false
  - name: --blockers
    description: "Include blocked issues detail with duration"
    required: false
  - name: --risks
    description: "Highlight risk factors"
    required: false
  - name: --json
    description: "Output as JSON for programmatic processing"
    required: false
---

# Project Status - Linear Insights Dashboard

Quick health dashboard for Linear projects including progress, velocity, blockers, ETA, and confidence metrics.

**Announce at start:** "Fetching project status dashboard..."

## Execution

1. Parse arguments from `$ARGUMENTS`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/project-status/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Generate project status dashboard from Linear data",
  prompt="<POLY_PROMPT content>\n\n## Context\nArguments: $ARGUMENTS\nWorking directory: $CWD"
)
```

4. Report the agent's findings to the user.
