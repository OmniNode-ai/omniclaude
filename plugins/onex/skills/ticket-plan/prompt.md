# Ticket Plan Execution

You are generating a prioritized master ticket plan from Linear.

## Initialization

When `/ticket-plan [team]` is invoked:

1. Determine the team name: use the argument if provided, otherwise default to `Omninode`.

2. **Announce:** "I'm using the ticket-plan skill to generate a prioritized backlog."

## Step 1: Fetch All Active Tickets

```
mcp__linear-server__list_issues({
  team: "<team>",
  limit: 250,
  includeArchived: false
})
```

Filter OUT tickets in these states (case-insensitive): Done, Completed, Closed, Canceled,
Cancelled, Duplicate.

## Step 2: Resolve Blocking Relationships

For each remaining ticket, check its `relations` field. If `includeRelations` data is not
already present, fetch it:

```
mcp__linear-server__get_issue({ id: "<ticket_id>", includeRelations: true })
```

A ticket is **blocked** if it has `blockedBy` relations whose referenced tickets are NOT in a
terminal state (Done / Completed / Closed / Canceled / Cancelled / Duplicate).

## Step 3: Categorize

- **In Review**: state name contains "review" or "in review"
- **Blocked**: has one or more active blockers (from Step 2)
- **Available Now**: everything else (no active blockers, not in review)

## Step 4: Sort Within Each Category

Sort by Linear `priority` field ascending (1=URGENT first, then 2, 3, 4, 0/null last).

Map priority numbers to labels:
- 1 → URGENT
- 2 → HIGH
- 3 → NORMAL
- 4 → LOW
- 0 or null → NONE

## Step 5: Infer Repository

For each ticket, infer the repo from title, description, or labels using these keywords:
`omniclaude`, `omnibase_core`, `omnibase_infra`, `omnibase_spi`, `omnidash`,
`omniintelligence`, `omnimemory`, `omninode_infra`, `omniweb`, `onex_change_control`.

If unclear, mark as `TBD`.

## Step 6: Output

Print the following markdown to the screen (do NOT write to a file):

```
# Master Ticket Plan

**Generated**: <ISO timestamp>
**Team**: <team name>
**Total active**: <count>

---

## Available Now (<count>)

| Priority | Ticket | Title | Repo | State |
|----------|--------|-------|------|-------|
| URGENT   | OMN-X  | ...   | ...  | ...   |
...

---

## Blocked (<count>)

| Priority | Ticket | Title | Blocked By | Repo | State |
|----------|--------|-------|------------|------|-------|
| HIGH     | OMN-Y  | ...   | OMN-X      | ...  | ...   |
...

---

## In Review (<count>)

| Ticket | Title | Repo | State |
|--------|-------|------|-------|
| OMN-Z  | ...   | ...  | ...   |
...

---

## Statistics

| Category      | Count |
|---------------|-------|
| Available Now | X     |
| Blocked       | X     |
| In Review     | X     |
| **Total**     | X     |
```

After printing, suggest the highest-priority Available Now ticket as a next action:
"Next recommended: `<ticket-id>` — <title> (`/ticket-work <ticket-id>`)"
