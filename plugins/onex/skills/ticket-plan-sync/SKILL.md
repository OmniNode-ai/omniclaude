---
name: ticket-plan-sync
description: Sync MASTER_TICKET_PLAN.md with current Linear state — full regeneration or targeted patch update
version: 1.0.0
category: workflow
tags:
  - linear
  - documentation
  - housekeeping
  - tickets
  - tracking
author: OmniClaude Team
composable: true
inputs:
  - name: mode
    type: str
    description: "full (regenerate) or patch (update changed rows only). Default: auto-select"
    required: false
  - name: output_path
    type: str
    description: Path to write the plan file (default docs/tracking/MASTER_TICKET_PLAN.md)
    required: false
  - name: dry_run
    type: bool
    description: Show what would change without writing the file
    required: false
outputs:
  - name: rows_updated
    type: int
    description: Number of rows changed (patch mode) or total rows (full mode)
---

# Ticket Plan Sync

## Overview

Keeps `docs/tracking/MASTER_TICKET_PLAN.md` aligned with actual Linear ticket state.

**Announce at start:** "I'm using the ticket-plan-sync skill to update the tracking doc."

**Imports:** `@_lib/contracts/helpers.md`

**Target file:** `docs/tracking/MASTER_TICKET_PLAN.md`

## Quick Start

```
/ticket-plan-sync                   # auto-select mode
/ticket-plan-sync --mode full       # full regeneration
/ticket-plan-sync --mode patch      # update changed rows only
/ticket-plan-sync --dry-run         # preview changes
```

## Mode Selection

### Auto-select logic

```python
def select_mode(plan_path):
    if not plan_path.exists():
        return "full"

    mtime = plan_path.stat().st_mtime
    age_days = (time.time() - mtime) / 86400

    if age_days > 7:
        return "full"   # file is stale — full refresh
    return "patch"      # file is recent — targeted update
```

Override with `--mode full` or `--mode patch`.

---

## Full Mode

Complete regeneration from Linear state.

### 1. Fetch all epics

```
mcp__linear-server__list_issues(
  state="not done",
  limit=250
)
```

Filter to epic-level tickets (tickets with children OR tickets explicitly marked as epics).
Also include epics with `state="Done"` that have In-Progress children (epic closed but
children still open — these are data quality issues to surface, not hide).

### 2. Fetch children for each epic

```
mcp__linear-server__list_issues(
  parentId=epic_id,
  limit=50
)
```

Also fetch orphaned non-done tickets (no parentId) to list at the bottom.

### 3. Map to EpicContract

For each epic, build:

```yaml
id: "OMN-XXXX"
title: "..."
emoji: "{from title prefix or label, else 🔵}"
status: "{Backlog|In Progress}"
priority: "{High|Medium|Low}"
scope: "{first sentence of description}"
repos: ["{from label or title prefix}"]
children: ["OMN-YYYY", "OMN-ZZZZ", ...]
```

**Priority sort order for the summary table:**
1. In Progress, High priority
2. In Progress, Medium priority
3. Backlog, High priority
4. Backlog, Medium/Low priority

### 4. Build MASTER_TICKET_PLAN.md

Emit the file in canonical format (see **File Format** below).

### 5. Write atomically

Write to a temp file, verify it's valid markdown with expected sections, then rename.
Never overwrite the target with a partially-written file.

---

## Patch Mode

Targeted update — only update rows that changed in Linear since the file was last written.

### 1. Read current file

Parse MASTER_TICKET_PLAN.md to extract all `OMN-XXXX` ticket IDs mentioned.

### 2. Fetch only those tickets from Linear

```
For each ticket_id in parsed_ids:
    mcp__linear-server__get_issue(id=ticket_id)
```

Batch in groups of 20 to avoid rate limits.

### 3. Diff states

Compare `current_state_in_file` vs `live_state_from_linear`:

```python
def rows_needing_update(file_tickets, linear_tickets):
    changed = []
    for ticket_id, file_state in file_tickets.items():
        live_state = linear_tickets.get(ticket_id)
        if live_state and live_state.state != file_state:
            changed.append((ticket_id, file_state, live_state.state))
    return changed
```

### 4. Apply in-place patches

For each changed row, update the `| Status |` cell in the markdown table using
find-and-replace on the exact row pattern:

```python
import re

def patch_row(content, ticket_id, new_state):
    # Match: | Old Status | OMN-XXXX | ...
    pattern = rf'\| [^\|]+ \| {re.escape(ticket_id)} \|'
    def replace(m):
        row = m.group(0)
        # Replace first cell (status) with new_state
        return re.sub(r'\| [^\|]+ \|', f'| {new_state} |', row, count=1)
    return re.sub(pattern, replace, content)
```

If a ticket no longer exists in any table row (it may have moved epics), skip silently
and note it in the patch summary.

### 5. Check for new epics

If any epic IDs are in Linear but not in the file, append them to the appropriate section.
If any epic IDs are in the file but not in Linear (deleted), mark them as `(removed)` in
the summary but do NOT remove from file — flag for human review.

### 6. Update header

Update the `Last updated: YYYY-MM-DD` line at the top of the file.

---

## File Format

The canonical MASTER_TICKET_PLAN.md format. Deviate from this and the patch parser breaks.

```markdown
## Open Epics (priority order)

Only includes work that remains to be done (Backlog or In Progress). No Done tickets.
Last updated: YYYY-MM-DD

| Status | Epic | Title | Scope | Repos |
|--------|------|-------|-------|-------|
| In Progress | 🔧 OMN-XXXX | Epic Title | Scope description | repo1, repo2 |
| Backlog | 🔵 OMN-YYYY | Another Epic | Description | repo |

---

## Epic: {emoji} OMN-XXXX — {Title} ({Priority})

{Optional 1-2 sentence description of what this epic delivers.}

| Status | Ticket | Repo | Title | Notes |
|--------|--------|------|-------|-------|
| In Progress | OMN-XXXX | omniclaude | Ticket title | Optional note |
| Backlog | OMN-YYYY | omnibase_core | Another ticket | — |

---

## Orphaned Tickets (no parent epic)

{Only included if orphans exist. Omit section header if none.}

| Status | Ticket | Repo | Title |
|--------|--------|------|-------|
| In Progress | OMN-XXXX | omniclaude | Ticket without epic |
```

### Status values (canonical)

| Linear State | File value |
|-------------|------------|
| Backlog | `Backlog` |
| In Progress | `In Progress` |
| In Review | `In Review` |
| Done | *(omitted from file)* |
| Cancelled | *(omitted from file)* |

**"IP"** is an abbreviation for "In Progress" that appears in legacy entries. Normalize
to `In Progress` on any full regeneration. Preserve on patch mode (don't change stable rows).

### Priority string (canonical)

| Linear Priority | File value |
|----------------|------------|
| 1 (Urgent) | `(Urgent)` |
| 2 (High) | `(High)` |
| 3 (Normal) | `(Medium)` |
| 4 (Low) | `(Low)` |

---

## Dry-Run Output

When `--dry-run`, print a diff-like summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ticket Plan Sync — DRY RUN (patch mode)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Would update 5 rows:

  OMN-2068  "In Progress" → "Done"
  OMN-1452  "In Review" → "Done"
  OMN-2700  "Backlog" → "In Review"
  OMN-554   "In Progress" → "In Review"
  OMN-555   "In Review" → "Done"

Would add 1 new epic:
  + OMN-2800 "[omniclaude] DB-SPLIT" (5 children)

No file changes written.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Composable Output

When invoked as a sub-skill (e.g., from `linear-housekeeping`):
- Write updated file to target path
- Return `rows_updated` count
- Exit 0 on success, 1 on write failure

## See Also

- `@_lib/contracts/helpers.md` — EpicContract schema
- `linear-triage` skill — run before sync to clean up Done tickets first
- `linear-housekeeping` skill — parent orchestrator
- Target file: `docs/tracking/MASTER_TICKET_PLAN.md`
