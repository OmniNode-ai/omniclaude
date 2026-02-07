---
name: velocity-estimate
description: "Velocity Estimate Command - Project Velocity & ETA Analysis"
tags: [linear, velocity, estimation, planning]
args:
  - name: project
    description: "Project name or shortcut (MVP, Beta, Production, etc.)"
    required: false
  - name: --all
    description: "Show all milestones overview"
    required: false
  - name: --confidence
    description: "Include confidence intervals"
    required: false
  - name: --method
    description: "Velocity calculation method (simple, priority, points, labels, cycle_time)"
    required: false
  - name: --json
    description: "Output as JSON for programmatic processing"
    required: false
---

# Velocity Estimate - Project Velocity & ETA Analysis

Calculate project velocity from historical data and estimate milestone completion dates using Linear backlog.

**Announce at start:** "Calculating project velocity and ETA estimates..."

## Execution

1. Parse arguments from `$ARGUMENTS`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/velocity-estimate/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Calculate project velocity and estimate completion dates",
  prompt="<POLY_PROMPT content>\n\n## Context\nArguments: $ARGUMENTS\nWorking directory: $CWD"
)
```

4. Report the agent's findings to the user.
