---
name: ticket-work
description: Contract-driven ticket execution with Linear integration - orchestrates intake, research, questions, spec, implementation, review, and done phases with explicit human gates
tags: [linear, tickets, automation, workflow, contract-driven]
---

# Contract-Driven Ticket Execution

**Usage:** `/ticket-work <ticket_id>` (e.g., `/ticket-work OMN-1807`)

You are executing contract-driven ticket work. Load and follow the full orchestration logic from the `ticket-work` skill.

**Announce at start:** "I'm using the ticket-work command to work on {ticket_id}."

## Quick Reference

The ticket-work skill provides:
- 7-phase workflow: intake → research → questions → spec → implementation → review → done
- Contract stored as YAML block in Linear ticket description
- Human gates required for meaningful phase transitions
- Mutation rules enforced per-phase

## Execution

Use the Skill tool to load the full `onex:ticket-work` skill, then execute with the provided ticket_id argument.

```
Skill(skill="onex:ticket-work", args="{ticket_id}")
```

Follow the skill's orchestration logic completely.
