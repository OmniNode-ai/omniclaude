---
name: plan-ticket
description: Generate a copyable ticket contract template - fill in the blanks and pass to /create-ticket
tags: [linear, tickets, planning, templates]
args: []
---

# Plan Ticket

Generate a pre-filled YAML contract template that you can customize and pass to `/create-ticket`.

**Announce at start:** "Generating ticket template..."

## Execution

1. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/plan-ticket/POLY_PROMPT.md`
2. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Generate ticket template",
  prompt="<POLY_PROMPT content>\n\n## Context\nARGUMENTS: {arguments}"
)
```

3. Show the generated template to the user.
