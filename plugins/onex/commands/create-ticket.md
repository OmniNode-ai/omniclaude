---
name: create-ticket
description: Create a single Linear ticket from args, contract file, or plan milestone with conflict resolution
tags: [linear, tickets, automation]
args:
  - name: title
    description: Ticket title (mutually exclusive with --from-contract, --from-plan)
    required: false
  - name: from-contract
    description: Path to YAML contract file
    required: false
  - name: from-plan
    description: Path to plan markdown file
    required: false
  - name: milestone
    description: Milestone ID when using --from-plan (e.g., M4)
    required: false
  - name: repo
    description: Repository label (e.g., omniclaude, omnibase_core)
    required: false
  - name: parent
    description: Parent issue ID for epic relationship (e.g., OMN-1800)
    required: false
  - name: blocked-by
    description: Comma-separated issue IDs that block this ticket
    required: false
  - name: project
    description: Linear project name
    required: false
  - name: team
    description: Linear team name (default Omninode)
    required: false
  - name: allow-arch-violation
    description: Bypass architecture dependency validation
    required: false
---

# Create Linear Ticket

Create a single Linear ticket from a title, contract file, or plan milestone with conflict resolution.

**Announce at start:** "Creating Linear ticket."

## Execution

1. Parse arguments from `$ARGUMENTS`: `--title`, `--from-contract <path>`, `--from-plan <path>`, `--milestone <id>`, `--repo <label>`, `--parent <id>`, `--blocked-by <ids>`, `--project <name>`, `--team <name>`, `--allow-arch-violation`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/create-ticket/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Create Linear ticket with conflict resolution",
  prompt="<POLY_PROMPT content>\n\n## Context\nTITLE: {title}\nFROM_CONTRACT: {from_contract}\nFROM_PLAN: {from_plan}\nMILESTONE: {milestone}\nREPO: {repo}\nPARENT: {parent}\nBLOCKED_BY: {blocked_by}\nPROJECT: {project}\nTEAM: {team}\nALLOW_ARCH_VIOLATION: {allow_arch_violation}"
)
```

4. Report the created ticket ID, title, and URL to the user.
