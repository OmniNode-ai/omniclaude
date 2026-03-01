---
name: resume-epic
description: Resume a mid-epic interruption by re-dispatching incomplete tickets to ticket-pipeline
version: 1.0.0
category: workflow
tags: [epic, resume, recovery, linear, ticket-pipeline]
author: OmniClaude Team
composable: true
inputs:
  - name: epic_id
    type: str
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: dry_run
    type: bool
    description: Inspect and classify tickets without dispatching; reads Linear but writes nothing
    required: false
  - name: force
    type: bool
    description: Dispatch tickets that have a non-null assignee (normally skipped)
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/resume-epic.json"
    fields:
      - status: dispatched | dry_run | nothing_to_do | error
      - epic_id: str
      - dispatched: list[str]
      - skipped: list[{id, reason}]
      - total_children: int
args:
  - name: epic_id
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: --dry-run
    description: Inspect and classify tickets without dispatching; reads Linear but writes nothing
    required: false
  - name: --force
    description: Dispatch tickets even if they have a non-null assignee
    required: false
---

# Resume Epic

## Overview

Resume a mid-epic interruption by re-inspecting all child tickets of a Linear epic and
dispatching the incomplete ones to `ticket-pipeline`. Designed to recover from rate-limit
evictions, session drops, and other interruptions that leave an epic partially complete.

**Announce at start:** "I'm using the resume-epic skill to resume epic {epic_id}."

**Implements**: OMN-3195

## Quick Start

```
/resume-epic OMN-2000
/resume-epic OMN-2000 --dry-run
/resume-epic OMN-2000 --force
```

## State Classification

Each child ticket is classified by its Linear state before any dispatch decision is made:

| Linear State | Action |
|---|---|
| Done | SKIP |
| In Review | SKIP |
| Merged | SKIP |
| Cancelled | SKIP |
| In Progress | DISPATCH (subject to human-owned guard) |
| Backlog | DISPATCH |
| Todo | DISPATCH |
| Blocked | DISPATCH |

Any state not in the above table is treated as **DISPATCH** (safe default — better to
re-check a pipeline than to silently abandon a ticket).

## Human-Owned Ticket Guard

By default, any ticket whose `assignee` field is non-null is **SKIP**. The agent cannot
reliably distinguish its own identity from human assignees in Linear, so this guard
prevents accidental re-dispatch of tickets owned by people.

Override with `--force` to dispatch all dispatchable tickets regardless of assignee.

## Dry-Run Semantics

`--dry-run` is a **read-only inspection mode**:

- May call Linear **read** APIs (`get_issue`, `list_issues`).
- Must NOT call Linear **write** APIs (no state updates, no comments).
- Must NOT invoke `ticket-pipeline`.
- Outputs the full classification table and exits with `status: dry_run`.

## Idempotency Guard

Before dispatching each ticket the skill re-fetches its Linear state. If the state has
changed to a SKIP state since the initial fetch, the ticket is silently skipped. This
prevents double-dispatch when the skill is invoked concurrently or in rapid succession.

An optional local lock file prevents re-entry within a short window:

- Lock path: `~/.claude/epics/{epic_id}/resume-epic.lock`
- TTL: 15 minutes
- If a lock file exists and is younger than 15 minutes: warn and abort unless `--force`.
- On successful completion: delete the lock file.

## Dispatch Order

Tickets are dispatched **sequentially** (never in parallel). After each ticket:

1. Report the result (dispatched, skipped, failed).
2. If the pipeline call failed, log the error and continue to the next ticket.
3. Never abort the full run due to a single ticket failure.

## Resume Flow

### Acquire lock

```
lock_path = ~/.claude/epics/{epic_id}/resume-epic.lock

If lock_path exists AND mtime < 15 minutes ago:
    If NOT --force:
        Warn: "resume-epic lock exists for {epic_id} (acquired {N} minutes ago). Use --force to override."
        Exit with status: error
    Else:
        Remove lock_path (force override)

Write lock_path with current timestamp.
```

### Fetch epic and children

```python
epic = mcp__linear-server__get_issue(epic_id, includeRelations=False)
children = mcp__linear-server__list_issues(parentId=epic["id"], limit=250)
```

Store `total_children = len(children)`.

### Classify each child

For each child ticket:

```
state = child["state"]   # e.g. "Done", "In Progress", "Backlog"
assignee = child.get("assignee")

if state in {Done, In Review, Merged, Cancelled}:
    action = SKIP
    reason = f"state={state}"
elif assignee is not None and NOT --force:
    action = SKIP
    reason = "human-owned (assignee set)"
else:
    action = DISPATCH
```

Build two lists: `to_dispatch` and `skipped`.

### Dry-run output path

Print classification table:

```
Epic: {epic_id} — {epic_title}
Total children: {N}

DISPATCH ({len(to_dispatch)}):
  {id}  {title}  [{state}]
  ...

SKIP ({len(skipped)}):
  {id}  {title}  [{state}]  — {reason}
  ...
```

Write `ModelSkillResult`:
```json
{
  "status": "dry_run",
  "epic_id": "{epic_id}",
  "dispatched": [],
  "skipped": [{...}],
  "total_children": N
}
```

Exit.

### Dispatch (live run)

For each ticket in `to_dispatch` (sequential):

```
1. Re-fetch ticket state from Linear (idempotency check):
   current = mcp__linear-server__get_issue(ticket["id"])
   if current["state"] in {Done, In Review, Merged, Cancelled}:
       Record as skipped (reason: "state changed before dispatch")
       Continue to next ticket.

2. Invoke ticket-pipeline:
   Skill(skill="onex:ticket-pipeline", args="{ticket_id}")

3. If invocation succeeds:
   Record as dispatched.
4. If invocation raises or returns error:
   Log error.
   Record as skipped (reason: "pipeline dispatch failed: {error}").
   Continue.
```

### Release lock and report

```
Delete ~/.claude/epics/{epic_id}/resume-epic.lock

If len(dispatched) == 0 AND len(to_dispatch) == 0:
    status = "nothing_to_do"
Else:
    status = "dispatched"

Write ModelSkillResult:
{
  "status": "{status}",
  "epic_id": "{epic_id}",
  "dispatched": [list of dispatched ticket IDs],
  "skipped": [{"id": ..., "reason": ...}],
  "total_children": N
}
```

Print summary:

```
Resume complete for {epic_id}.
Dispatched: {len(dispatched)} tickets
Skipped:    {len(skipped)} tickets
```

## Output Format

### Dry-run output

```
resume-epic: DRY RUN for OMN-2000 — My Feature Epic
Total children: 5

DISPATCH (3):
  OMN-2001  Add Kafka consumer         [Backlog]
  OMN-2002  Wire database schema       [Todo]
  OMN-2004  In-progress implementation [In Progress]

SKIP (2):
  OMN-2003  Deploy to staging          [Done]        — state=Done
  OMN-2005  Write integration tests    [Backlog]     — human-owned (assignee set)

No tickets dispatched (dry-run mode).
```

### Live output

```
resume-epic: Resuming OMN-2000 — My Feature Epic
Total children: 5

[1/3] Dispatching OMN-2001 (Add Kafka consumer) ...
  → ticket-pipeline dispatched.

[2/3] Dispatching OMN-2002 (Wire database schema) ...
  → ticket-pipeline dispatched.

[3/3] Dispatching OMN-2004 (In-progress implementation) ...
  → ticket-pipeline dispatched.

Skipped 2 tickets (see result for reasons).

Resume complete. Dispatched: 3 | Skipped: 2
```

## Commit Message

```
feat: add resume-epic skill for rate-limit recovery [insights]
```

## See Also

- `epic-team` skill — full epic orchestration with team topology
- `ticket-pipeline` skill — per-ticket pipeline (implement → review → PR → merge)
- `crash-recovery` skill — show recent pipeline state after session drop
- `checkpoint` skill — per-phase checkpoint management
