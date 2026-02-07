---
name: deep-dive
description: "Deep Dive Command - Daily Work Analysis Report"
tags: [reporting, analysis, linear, productivity]
args:
  - name: --date
    description: "Specific date to analyze (YYYY-MM-DD)"
    required: false
  - name: --days
    description: "Number of days to analyze (for weekly summary)"
    required: false
  - name: --save
    description: "Save report to output directory"
    required: false
  - name: --json
    description: "Output as JSON for programmatic processing"
    required: false
  - name: --repos
    description: "Comma-separated list of repos to include"
    required: false
---

# Deep Dive - Daily Work Analysis Report

Generate comprehensive daily work analysis reports from Linear, GitHub, and git data with velocity and effectiveness scoring.

**Announce at start:** "Generating deep dive analysis report..."

## Execution

1. Parse arguments from `$ARGUMENTS`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/deep-dive/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Generate deep dive daily work analysis report",
  prompt="<POLY_PROMPT content>\n\n## Context\nArguments: $ARGUMENTS\nWorking directory: $CWD\nDate: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
)
```

4. Report the agent's findings to the user.
