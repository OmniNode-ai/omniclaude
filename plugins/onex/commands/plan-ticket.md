---
name: plan-ticket
description: Generate a copyable ticket contract template - fill in the blanks and pass to /create-ticket
tags: [linear, tickets, planning, templates]
args: []
---

# Ticket Planning Template

Generate a pre-filled YAML contract template that you can customize and pass to `/create-ticket`. No interactive prompts - just a copyable block.

**Announce at start:** "I'm using the plan-ticket command to generate a ticket template."

## Quick Reference

The plan-ticket skill provides:
- YAML contract template generation
- Pre-fills fields based on context you provide
- Template ready for editing and passing to /create-ticket
- No interactive prompts - outputs a single copyable block

## Execution

Use the Skill tool to load the `plan-ticket` skill, then output the template.

```
Skill(skill="onex:plan-ticket")
```

Follow the skill's template generation logic. Output a copyable YAML block with next steps.
