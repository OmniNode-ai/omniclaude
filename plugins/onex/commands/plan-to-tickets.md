---
name: plan-to-tickets
description: Batch create Linear tickets from a plan markdown file - parses phases/milestones, creates epic if needed, links dependencies
tags: [linear, tickets, planning, batch, automation]
args:
  - name: plan-file
    description: Path to plan markdown file (required)
    required: true
  - name: project
    description: Linear project name
    required: false
  - name: epic-title
    description: Title for epic (overrides auto-detection from plan)
    required: false
  - name: no-create-epic
    description: Fail if epic doesn't exist (don't auto-create)
    required: false
  - name: dry-run
    description: Show what would be created without creating
    required: false
  - name: skip-existing
    description: Skip tickets that already exist (don't ask)
    required: false
  - name: team
    description: Linear team name (default Omninode)
    required: false
  - name: repo
    description: Repository label for all tickets (e.g., omniclaude, omnibase_core)
    required: false
  - name: allow-arch-violation
    description: Bypass architecture dependency validation
    required: false
---

# Batch Create Tickets from Plan

Create Linear tickets from a plan markdown file with phase/milestone parsing, epic creation, and dependency resolution.

**Announce at start:** "Creating tickets from plan: {plan-file}"

## Execution

1. Parse arguments from `$ARGUMENTS`: `<plan-file>`, `--project <name>`, `--epic-title <title>`, `--no-create-epic`, `--dry-run`, `--skip-existing`, `--team <name>`, `--repo <label>`, `--allow-arch-violation`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/plan-to-tickets/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Batch create Linear tickets from plan file",
  prompt="<POLY_PROMPT content>\n\n## Context\nPLAN_FILE: {plan_file}\nPROJECT: {project}\nEPIC_TITLE: {epic_title}\nNO_CREATE_EPIC: {no_create_epic}\nDRY_RUN: {dry_run}\nSKIP_EXISTING: {skip_existing}\nTEAM: {team}\nREPO: {repo}\nALLOW_ARCH_VIOLATION: {allow_arch_violation}"
)
```

4. Report the batch creation summary to the user.
