---
name: ticket-plan
description: Generate a prioritized master ticket plan from Linear — fetches all active tickets, resolves blocking relationships, and outputs an actionable backlog sorted by priority
version: 1.0.0
category: workflow
tags:
  - linear
  - planning
  - tickets
  - backlog
author: OmniClaude Team
args:
  - name: team
    description: Linear team name to query (default: Omninode)
    required: false
---

# Ticket Plan

Fetches all active Linear tickets, resolves blocking relationships, and generates a prioritized
master plan grouped into Available Now / Blocked / In Review.

**Announce at start:** "I'm using the ticket-plan skill to generate a prioritized backlog."

## Usage

```
/ticket-plan
/ticket-plan Engineering
```

## Output

Prints a markdown table to the screen grouped by:

1. **Available Now** — no active blockers, sorted by priority
2. **Blocked** — has unresolved blockers, sorted by priority
3. **In Review** — pending merge/review

## Priority Legend

| Value | Label |
|-------|-------|
| 1 | URGENT |
| 2 | HIGH |
| 3 | NORMAL |
| 4 | LOW |
| 0 / null | NONE |

## See Also

- `/plan-ticket` — Generate a YAML contract template for a single new ticket
- `/ticket-work` — Execute a specific ticket through contract-driven phases
- `/create-followup-tickets` — Create Linear tickets from code review issues
