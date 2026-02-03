---
name: plan-ticket
description: Interactive guided ticket creation - walks through requirements gathering and creates standardized Linear tickets
tags: [linear, tickets, planning, requirements, interactive]
args: []
---

# Interactive Ticket Planning

You are guiding the user through interactive ticket creation. Load and follow the full orchestration logic from the `plan-ticket` skill.

**Announce at start:** "I'm using the plan-ticket command to help you create a well-structured ticket."

## Quick Reference

The plan-ticket skill provides:
- 9-step interactive flow using AskUserQuestion
- Collects: goal, repository, work type, requirements, parent, blocked-by, project
- Generates contract YAML preview before creation
- Delegates to /create-ticket for Linear integration

## Execution

Use the Skill tool to load the full `plan-ticket` skill, then execute the interactive flow.

```
Skill(skill="onex:plan-ticket")
```

Follow the skill's orchestration logic completely. All user interactions must use AskUserQuestion.
