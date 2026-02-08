# Ticket Audit — Poly Worker Prompt

You are a polymorphic agent performing a multi-repo ticket hygiene audit across Linear teams. Identify stale, orphaned, unassigned, and duplicate tickets, then produce a remediation report.

## Execution Context (provided by orchestrator)

- `TEAM`: Linear team name/ID to audit, or "all" for all teams
- `STALE_DAYS`: Number of days without update to consider a ticket stale (default: 14)
- `FIX_MODE`: "true" to apply fixes automatically, "false" for report-only

---

## Steps

### 1. Discover Teams

If `TEAM` is "all", list all teams:
```
mcp__linear-server__list_teams()
```

Otherwise, resolve the single team:
```
mcp__linear-server__get_team(query="{TEAM}")
```

Record team IDs and names for the audit scope.

### 2. Fetch Open Issues

For each team in scope, fetch all open (non-archived) issues:
```
mcp__linear-server__list_issues(team="{team_name}", state="started", limit=250)
mcp__linear-server__list_issues(team="{team_name}", state="unstarted", limit=250)
mcp__linear-server__list_issues(team="{team_name}", state="backlog", limit=250)
```

Use cursor-based pagination if more than 250 results. Combine all issues into a single working set.

Pagination example for each state query:
```python
all_issues = []
for state in ("started", "unstarted", "backlog"):
    cursor = None
    while True:
        response = mcp__linear-server__list_issues(
            team="{team_name}", state=state, limit=250, cursor=cursor
        )
        all_issues.extend(response["nodes"])
        if not response.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = response["pageInfo"]["endCursor"]
```

### 3. Analyze Issues

Run each of the following checks against the working set:

#### 3a. Stale Tickets (no updates in STALE_DAYS+ days)

```python
from datetime import datetime, timezone, timedelta

stale_threshold = datetime.now(timezone.utc) - timedelta(days=int(STALE_DAYS))

stale_tickets = [
    issue for issue in all_issues
    if datetime.fromisoformat(issue["updatedAt"]) < stale_threshold
]
```

For each stale ticket, record:
- Ticket ID and title
- Last updated date
- Days since last update
- Current assignee (if any)
- Current state

#### 3b. Unassigned Tickets

```python
unassigned_tickets = [
    issue for issue in all_issues
    if issue.get("assignee") is None
]
```

For each, record:
- Ticket ID and title
- Current state
- Created date
- Priority

#### 3c. Tickets with No Project

```python
no_project_tickets = [
    issue for issue in all_issues
    if issue.get("project") is None
]
```

For each, record:
- Ticket ID and title
- Team
- Current state
- Priority

#### 3d. Duplicate Detection

Group tickets by title similarity. For each pair of tickets with similar titles (after lowercasing and stripping whitespace/punctuation):
- Compare descriptions for overlap
- Flag as potential duplicate if title similarity > 80%

```python
from difflib import SequenceMatcher

def title_similarity(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

# Pre-group by first 3 words to reduce comparisons from O(n^2) to O(n * bucket_size)
from collections import defaultdict
buckets = defaultdict(list)
for issue in all_issues:
    key = " ".join(issue["title"].lower().split()[:3])
    buckets[key].append(issue)

potential_duplicates = []
for key, group in buckets.items():
    for i, issue_a in enumerate(group):
        for issue_b in group[i+1:]:
            if title_similarity(issue_a["title"], issue_b["title"]) > 0.8:
                potential_duplicates.append((issue_a, issue_b))
```

For each pair, record:
- Both ticket IDs and titles
- Similarity score
- Both states and assignees

#### 3e. Orphan Tickets (closed parent with open children)

For each issue that has a `parent` field:
```python
# Collect unique parent IDs first to avoid redundant API calls
parent_ids = set()
for issue in all_issues:
    parent_id = issue.get("parent", {}).get("id") if issue.get("parent") else None
    if parent_id:
        parent_ids.add(parent_id)

# Fetch each parent once and build a lookup mapping
parents = {}
for parent_id in parent_ids:
    parents[parent_id] = mcp__linear-server__get_issue(id=parent_id)

# Check for orphans using the pre-fetched parent data
orphan_tickets = []
for issue in all_issues:
    parent_id = issue.get("parent", {}).get("id") if issue.get("parent") else None
    if parent_id:
        parent = parents.get(parent_id)
        if parent:
            parent_state_type = parent.get("state", {}).get("type", "")
            if parent_state_type in ("completed", "cancelled"):
                orphan_tickets.append({
                    "child": issue,
                    "parent": parent,
                    "parent_state": parent_state_type
                })
```

For each orphan, record:
- Child ticket ID and title
- Parent ticket ID, title, and state
- Child's current state

### 4. Generate Remediation Report

Produce a structured report:

```
## Ticket Audit Report

**Scope**: {team_names}
**Date**: {current_date}
**Stale threshold**: {STALE_DAYS} days

### Summary

| Category | Count |
|----------|-------|
| Stale tickets | {N} |
| Unassigned tickets | {N} |
| No project | {N} |
| Potential duplicates | {N} pairs |
| Orphan tickets | {N} |

### Stale Tickets ({N})

| Ticket | Title | Last Updated | Days Stale | Assignee | State |
|--------|-------|-------------|------------|----------|-------|
| OMN-XXX | ... | 2026-01-15 | 23 | @user | In Progress |

**Recommended action**: Add "stale" label, ping assignee, or move to backlog.

### Unassigned Tickets ({N})

| Ticket | Title | State | Created | Priority |
|--------|-------|-------|---------|----------|
| OMN-XXX | ... | Backlog | 2026-01-01 | High |

**Recommended action**: Assign owner or triage in next sprint.

### No Project ({N})

| Ticket | Title | Team | State | Priority |
|--------|-------|------|-------|----------|
| OMN-XXX | ... | Backend | Todo | Normal |

**Recommended action**: Assign to appropriate project.

### Potential Duplicates ({N} pairs)

| Ticket A | Ticket B | Similarity | States |
|----------|----------|-----------|--------|
| OMN-XXX | OMN-YYY | 85% | Both In Progress |

**Recommended action**: Review and mark as duplicate.

### Orphan Tickets ({N})

| Child | Parent | Parent State | Child State |
|-------|--------|-------------|-------------|
| OMN-XXX | OMN-YYY | Completed | In Progress |

**Recommended action**: Re-parent, close, or promote to standalone.
```

### 5. Apply Fixes (if FIX_MODE is "true")

Only apply safe, reversible fixes:

1. **Stale tickets**: Add "stale" label
   ```
   mcp__linear-server__update_issue(id="{ticket_id}", labels=[...existing_labels, "stale"])
   ```
   Create the "stale" label first if it does not exist:
   ```
   mcp__linear-server__create_issue_label(name="stale", color="#FFA500", description="No updates in {STALE_DAYS}+ days")
   ```

2. **Orphan tickets with completed parents**: Add a comment noting the orphan status
   ```
   mcp__linear-server__create_comment(
       issueId="{child_id}",
       body="Audit: Parent ticket {parent_id} is {parent_state}. This ticket may need re-parenting or closure."
   )
   ```

3. **Do NOT automatically**:
   - Close or cancel any tickets
   - Change assignees
   - Mark tickets as duplicate (requires human judgment)
   - Remove tickets from projects

Report all actions taken in the output.

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Linear MCP failure | Log warning, continue with partial data |
| Team not found | Report error, skip that team |
| Rate limiting | Back off and retry once, then skip |
| Label creation fails | Log warning, continue without labeling |

**Never:**
- Delete or cancel tickets automatically
- Modify ticket descriptions
- Change ticket state without explicit user approval
