# Suggest Work — Poly Worker Prompt

You are querying Linear for the highest priority unblocked issues from the backlog and returning actionable work suggestions sorted by priority and relevance to the current repository context.

## Arguments

- `COUNT`: Number of suggestions to return (default: 5)
- `PROJECT`: Project name/shortcut (MVP, Beta, Production, etc.). Default: MVP.
- `REPO`: Override auto-detected repo context (e.g., `omnibase_core`)
- `NO_REPO`: "true" if `--no-repo` flag provided (disable repo-based prioritization)
- `LABEL`: Filter to issues with this specific label
- `JSON_OUTPUT`: "true" if `--json` flag provided
- `EXECUTE`: "true" if `--execute` flag provided (output raw execution prompt only)
- `NO_CACHE`: "true" if `--no-cache` flag provided (bypass cache)

## Steps

### 1. Run the Suggest Work Skill Script

Execute the suggest-work script with the provided flags:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work \
  ${COUNT:+--count "$COUNT"} \
  ${PROJECT:+--project "$PROJECT"} \
  ${REPO:+--repo "$REPO"} \
  ${NO_REPO:+--no-repo} \
  ${LABEL:+--label "$LABEL"} \
  ${JSON_OUTPUT:+--json} \
  ${EXECUTE:+--execute} \
  ${NO_CACHE:+--no-cache} \
  2>&1
```

The script reads project IDs and blocked labels from `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/config.yaml`.

### 2. Detect Repository Context

Unless `--no-repo` is set, the script auto-detects the current repository from:
1. Git repository name (via `git rev-parse --show-toplevel`)
2. Path patterns in the current working directory (`/omnibase_core/`, `/omniclaude/`, etc.)

Issues with a label matching the detected repo name are prioritized first in results.

### 3. Handle Output Mode

The script has three output modes:

**Execute Mode (`--execute`)**:
Outputs only the raw execution prompt. No formatting. Suitable for piping:

```
Query Linear for the top 5 unblocked backlog issues in project MVP (ID: e44ddbf4-...).
Use: mcp__linear-server__list_issues(project="e44ddbf4-...", state="Backlog", limit=15)
Then filter out issues with labels: blocked, waiting, on-hold, needs-clarification, dependent
Sort by: 1) Issues with 'omniclaude' label first, 2) Priority (Urgent > High > Normal > Low), 3) Created date (oldest first)
Return the top 5 results in a table with columns: #, ID, Title, Priority, Repo Match, Created
```

**JSON Mode (`--json`)**:
Outputs structured JSON with query parameters, cache metadata, and MCP query specification.

**Markdown Mode (default)**:
Outputs a full formatted document with the execution prompt, MCP query, filtering instructions, and expected output table.

### 4. Execute the Linear MCP Query

Use the generated query to fetch issues from Linear:

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    state="Backlog",
    limit={COUNT * 3}  # 3x requested count for filtering headroom
)
```

If a `--label` filter was specified, add it:

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    state="Backlog",
    limit={COUNT * 3},
    label="{LABEL}"
)
```

### 5. Apply Filters

**Step 1: Exclude blocked issues**

Remove any issues that have any of these labels:
- `blocked`
- `waiting`
- `on-hold`
- `needs-clarification`
- `dependent`

**Step 2: Group by repo relevance** (unless `--no-repo`)

If a repo context is detected, separate issues into:
1. **Repo-relevant**: Issues with a label matching the repo name (e.g., `omniclaude`)
2. **Other**: All remaining issues

### 6. Sort Results

**Within each group** (repo-match vs non-match), sort by:

| Sort Order | Field | Direction |
|------------|-------|-----------|
| Primary | Priority | Urgent (1) > High (2) > Normal (3) > Low (4) |
| Secondary | Created date | Oldest first (ascending) |

If repo context is active, repo-matching issues appear before non-matching issues.

If `--no-repo` is set, sort purely by priority then age.

### 7. Return Top N Issues

After filtering and sorting, return the top `{COUNT}` results.

## Expected Output Format

### Markdown Output (Default)

```
# Suggested Work: MVP

**Generated**: 2025-12-14 10:30:00
**Project**: MVP - OmniNode Platform Foundation
**Project ID**: `e44ddbf4-b4c7-40dc-84fa-f402ec27b38e`
**Repo Context**: `omniclaude` (issues with this label shown first)
**Cache**: Miss (will cache for 300s)

---

## Execute Now

To get suggestions, ask Claude:

```
Query Linear for the top 5 unblocked backlog issues in project MVP (ID: e44ddbf4-...).
...
```

---

## Query for Linear MCP

```python
mcp__linear-server__list_issues(
    project="e44ddbf4-...",
    state="Backlog",
    limit=15
)
```

---

## Filtering Instructions
...

## Expected Output Format

| # | ID | Title | Priority | Repo Match | Created |
|---|-------|-------|----------|------------|---------|
| 1 | OMNI-42 | Fix event handler retry logic | Urgent | Yes | 2025-12-01 |
| 2 | OMNI-38 | Add correlation ID to logs | High | Yes | 2025-12-03 |
| 3 | OMNI-55 | Implement DLQ consumer | Urgent | No | 2025-12-02 |
| 4 | OMNI-61 | Update API documentation | Normal | No | 2025-11-28 |
| 5 | OMNI-73 | Add unit tests for router | Low | Yes | 2025-11-25 |
```

### JSON Output (`--json`)

```json
{
  "generated_at": "2025-12-14T10:30:00Z",
  "cache_hit": false,
  "cache": {
    "key": "v1:suggest-work:e44ddbf4-...:label=none,repo=omniclaude:5",
    "ttl_seconds": 300,
    "schema_version": 1
  },
  "execution_prompt": "Query Linear for the top 5...",
  "project": {
    "shortcut": "MVP",
    "name": "MVP - OmniNode Platform Foundation",
    "id": "e44ddbf4-..."
  },
  "repo_context": "omniclaude",
  "mcp_query": {
    "tool": "mcp__linear-server__list_issues",
    "parameters": {
      "project": "e44ddbf4-...",
      "state": "Backlog",
      "limit": 15
    }
  }
}
```

### Execute Output (`--execute`)

Raw text only, no formatting:

```
Query Linear for the top 5 unblocked backlog issues in project MVP (ID: e44ddbf4-...).
Use: mcp__linear-server__list_issues(project="e44ddbf4-...", state="Backlog", limit=15)
Then filter out issues with labels: blocked, waiting, on-hold, needs-clarification, dependent
Sort by: 1) Issues with 'omniclaude' label first, 2) Priority (Urgent > High > Normal > Low), 3) Created date (oldest first)
Return the top 5 results in a table with columns: #, ID, Title, Priority, Repo Match, Created
```

## Caching

- **TTL**: 300 seconds (5 minutes)
- **Key Format**: `v{schema}:suggest-work:{project_id}:label={label},repo={repo}:{count}`
- **Bypass**: Use `--no-cache` to force fresh query generation
- **Implementation**: Uses `lib/cache_manager.py` for TTL-based caching
- Cache is checked before generating output; cache hits return stored results directly

## Available Projects

| Shortcut | Full Name | ID |
|----------|-----------|-----|
| MVP | MVP - OmniNode Platform Foundation | `e44ddbf4-b4c7-40dc-84fa-f402ec27b38e` |
| Beta | Beta - OmniNode Platform Hardening | `5db5e69e-a78d-4b6f-b78c-e59b929b9b4f` |
| Production | Production - OmniNode Platform Scale | `0fb63ff3-66cc-48e4-9c69-d64af5e4cf84` |
| NodeReducer | NodeReducer v1.0 - Contract-Driven FSM | `c2538d8b-79ca-47cd-b5f7-f21f9b76bd9d` |
| EventBusAlignment | Event Bus Alignment - OmniNode Platform | `b927f193-1c30-4707-b962-a6d240f705df` |
| PipelineOptimization | Synchronous Pipeline Optimization | `469d68a3-e5ce-48de-b9e9-80700290869e` |

> **Note**: Project UUIDs should be consolidated in `config.yaml` as the single source of truth. The table above is illustrative; always read from `config.yaml` at runtime to avoid drift.

## Error Handling

| Error | Behavior |
|-------|----------|
| Project not found in config | Report error, list available projects |
| Config file missing | Report error, suggest running configure skill |
| No issues in backlog | Report "No backlog issues found" |
| All issues blocked | Report "All {N} backlog issues are blocked" |
| Cache read/write failure | Non-fatal, continue without cache |
| Git repo detection fails | Proceed without repo context |

## Performance Targets

- **Query Generation**: <100ms (cached: <10ms)
- **Cache TTL**: 300 seconds
- **Default Count**: 5 issues
- **Query Limit**: 3x count (filtering headroom)
