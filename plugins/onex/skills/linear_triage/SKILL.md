---
description: Scan all non-completed Linear tickets, verify status against actual PR state, auto-mark done tickets, flag stale ones, and identify orphans needing epic assignment
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - linear
  - triage
  - housekeeping
  - tickets
  - prs
author: OmniClaude Team
composable: true
inputs:
  - name: threshold_days
    type: int
    description: Tickets updated within this many days are "recent" and get PR-verified (default 14)
    required: false
  - name: dry_run
    type: bool
    description: Assess and report without writing any changes to Linear (default false)
    required: false
outputs:
  - name: skill_result
    type: TriageReport
    description: "Written to $ONEX_STATE_DIR/state/linear-triage/{run_id}.yaml"
---

# Linear Triage

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Linear triage scan",
  prompt="Run the linear-triage skill. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

**If subagent dispatch fails** (auth error, "Not logged in", tool unavailable, Agent tool blocked,
or any subagent execution error): **STOP immediately. Do NOT fall back to direct Bash, Read, Edit,
Write, or Glob calls.** Report the exact error to the user and wait for direction. Falling back to
direct tools bypasses ONEX observability, context management, and the orchestration layer. There
is no acceptable workaround — surface the failure.

## Overview

Scan all non-completed tickets in Linear, determine their true status, apply updates,
and produce a `TriageReport` for downstream skills (`linear-epic-org`, `ticket-plan --sync`).

**Announce at start:** "I'm using the linear-triage skill to assess ticket health."

**Imports:** `@_lib/contracts/helpers.md`

## Quick Start

```
/linear-triage
/linear-triage --dry-run
/linear-triage --threshold-days 7
```

## Algorithm

### Phase 1: Fetch

Fetch all non-done tickets from Linear:

```
mcp__linear-server__list_issues(
  state="not done",  # excludes: Done, Cancelled
  limit=250
)
```

Repeat with cursor until all pages fetched. Build list of `TicketContract` records.

### Phase 2: Age Classification

For each ticket, compute `age_days = today - ticket.updatedAt`:

```python
THRESHOLD_DAYS = 14  # configurable via --threshold-days

def classify(ticket):
    age_days = (today - ticket.updated_at).days
    if age_days <= THRESHOLD_DAYS:
        return "recent"
    else:
        return "stale"
```

**Recent tickets** → Phase 3 (PR status check)
**Stale tickets** → Phase 4 (staleness flagging)

### Phase 3: PR Status Check (recent tickets only)

For each recent ticket, look up its GitHub PR:

#### Step 3a: Extract repo slug

Extract repo from the ticket's Linear branch name field (`branchName`) or title prefix:

```python
def extract_repo(ticket):
    # 1. From branchName: "jonah/omn-2068-omniclaude-db-split-03-..." → "omniclaude"
    if ticket.branch_name:
        parts = ticket.branch_name.split("/", 1)
        if len(parts) > 1:
            slug = parts[1].split("-")[2]  # omn-NNNN-SLUG-rest
            if slug in KNOWN_REPOS:
                return slug

    # 2. From title prefix: "[omniclaude] ..." → "omniclaude"
    import re
    m = re.match(r'^\[([^\]]+)\]', ticket.title)
    if m and m.group(1) in KNOWN_REPOS:
        return m.group(1)

    # 3. From labels
    for label in ticket.labels:
        if label.name in KNOWN_REPOS:
            return label.name

    return None  # unknown repo — cannot PR-check

KNOWN_REPOS = [
    "omnibase_compat", "omnibase_core", "omniclaude", "omnibase_infra",
    "omnidash", "omniintelligence", "omnimemory",
    "omninode_infra", "omnibase_spi", "onex_change_control",
]
```

#### Step 3b: Search for PR

```bash
# Search by ticket ID in PR title/body
gh pr list \
  --repo omninode-ai/{repo_slug} \
  --search "{ticket_id}" \
  --state all \
  --json number,title,state,mergedAt,url \
  --limit 5
```

If no results, also try branch name search:

```bash
gh pr list \
  --repo omninode-ai/{repo_slug} \
  --head "{branch_name}" \
  --state all \
  --json number,title,state,mergedAt,url \
  --limit 3
```

#### Step 3c: Determine action

| Linear State | PR State | Action |
|-------------|----------|--------|
| In Progress / In Review | PR merged | **mark_done** |
| In Progress / In Review | PR closed (unmerged) | search all repos for sibling merged PR mentioning ticket_id → if found: **mark_done_superseded**; else: flag stale + add note |
| In Progress / In Review | PR open | no_change |
| In Progress / In Review | PR not found | no_change (skip) |
| Backlog | PR merged | **mark_done** |
| Backlog | PR not found | no_change |

**Evidence required for `mark_done` / `mark_done_superseded`:** Merged PR URL + merge date.
For `mark_done_superseded`, also include the closed PR number. Never mark done without
confirmed evidence of a merged PR.

#### Step 3c-i: Sibling merged PR search (for closed-PR tickets)

When a PR is found closed (not merged), search all known repos for any merged PR that
mentions the same ticket ID:

```bash
for REPO in omnibase_compat omnibase_core omniclaude omnibase_infra omnidash omniintelligence \
            omnimemory omninode_infra omnibase_spi onex_change_control; do
  gh pr list \
    --repo OmniNode-ai/$REPO \
    --search "{ticket_id}" \
    --state merged \
    --json number,title,mergedAt,url \
    --limit 3
done
```

**Note on `--search` scope:** GitHub's PR search (`gh pr list --search`) queries both PR
title and body text, so PRs that mention the ticket ID only in the body (not the title) are
still found. This covers the superseded-PR pattern where the body references the original
ticket but the title references only the merging ticket.

If any result is returned:
- Action: `mark_done_superseded`
- Comment: "Auto-closed by linear-triage: work delivered via sibling PR #{number} in {repo} merged {mergedAt}\n{url}\n(Original PR #{closed_pr_number} was closed as superseded)"

If no merged sibling found:
- Action: flag stale + add note (existing behavior)

#### Step 3d: Apply mark_done (unless --dry-run)

```
mcp__linear-server__save_issue(
  id=ticket_id,
  state="Done"
)

# Add comment with evidence
mcp__linear-server__create_comment(
  issueId=ticket_id,
  body="✅ Auto-closed by linear-triage: PR #{number} merged {merge_date}\n{pr_url}"
)
```

### Phase 4: Stale Flagging

For stale tickets, compute a recommendation:

```python
def recommend(ticket, age_days):
    if ticket.state in ("In Progress", "In Review") and age_days > 60:
        return "review_and_close"
    if ticket.state == "Backlog" and age_days > 30:
        return "review_and_close"
    return "keep_open"
```

**Do NOT** automatically close stale tickets. Only flag them in the TriageReport.
Human review required.

### Phase 5: Orphan Detection

For all non-done tickets without a parent epic (`parentId == null`):

```python
def is_orphaned(ticket):
    return ticket.parent_id is None and ticket.state not in ("Done", "Cancelled")
```

Infer `proposed_epic_group` from naming pattern:

```python
import re

def infer_epic_group(ticket):
    # Pattern: "[repo] PREFIX-NN: title" → group by PREFIX
    m = re.match(r'^\[[^\]]+\]\s+([A-Z][A-Z0-9-]+?)-\d+:', ticket.title)
    if m:
        return m.group(1)  # e.g., "DB-SPLIT"

    # Pattern: "PREFIX-NN: title" (no repo prefix)
    m = re.match(r'^([A-Z][A-Z0-9-]+?)-\d+:', ticket.title)
    if m:
        return m.group(1)

    return None  # ambiguous — needs human grouping
```

### Phase 5b: Epic Completion Detection

For each non-done ticket that has child tickets (i.e., any ticket where other tickets
have `parentId == this_ticket.id`):

```python
def check_epic_complete(epic_ticket, all_tickets):
    children = [t for t in all_tickets if t.parent_id == epic_ticket.id]
    if not children:
        return False  # no children — not an epic, skip
    all_done = all(t.state in ("Done", "Cancelled") for t in children)
    return all_done
```

If `check_epic_complete` returns True:
- Action: `mark_done_epic` (applied immediately unless `--dry-run`)
- Comment:
  ```
  Auto-closed by linear-triage: all {N} child tickets are Done.
  Children: {comma-separated OMN-XXXX list}
  ```

**Note:** Fetch children via:
```
mcp__linear-server__list_issues(parentId=epic_ticket.id, includeArchived=true, limit=50)
```

### Phase 6: Write TriageReport

Write report to `$ONEX_STATE_DIR/state/linear-triage/{run_id}.yaml` (see `TriageReport` in
`@_lib/contracts/helpers.md` for schema).

Print summary to stdout:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Linear Triage Report  (run: {run_id})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scanned:         {total_scanned} tickets
Recent (<{N}d):  {recent} tickets
Stale (>{N}d):   {stale} tickets

✅ Marked done:        {marked_done}  (includes {marked_done_superseded} superseded-PR, {epics_closed} epic completions)
⚠️  Stale flags:      {stale_flagged} (human review needed)
🔗 Orphans:           {orphaned} (no parent epic)
📦 Proposed new epics: {proposed_epics}

Report: $ONEX_STATE_DIR/state/linear-triage/{run_id}.yaml
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Dry-Run Mode

When `--dry-run`:
- All Linear queries execute normally
- No `save_issue` or `create_comment` calls are made
- TriageReport is written with `dry_run: true`
- All `actions_applied` entries show dry-run prefixed actions:
  - `"marked_done"` → `"would_mark_done"`
  - `"marked_done_superseded"` → `"would_mark_done_superseded"`
  - `"marked_done_epic"` → `"would_mark_done_epic"`

## Rate Limits

Linear API has per-minute rate limits. If you have >100 tickets:
- Batch PR lookups: process 20 at a time with brief pauses
- Prioritize recent In-Progress tickets over Backlog

## Composable Output

When invoked as a sub-skill (e.g., from `linear-housekeeping`), write `TriageReport`
to `$ONEX_STATE_DIR/state/linear-triage/{run_id}.yaml` and return the path in output.

The `orphaned_tickets` list from the TriageReport is the input to `linear-epic-org`.

## See Also

- `@_lib/contracts/helpers.md` — TicketContract, TriageReport schemas
- `linear-epic-org` skill — consumes orphaned_tickets from this report
- `linear-housekeeping` skill — orchestrates triage → epic-org → ticket-plan --sync
- `ticket-plan --sync` — uses triage output for MASTER_TICKET_PLAN.md sync
- Linear MCP tools (`mcp__linear-server__*`)
