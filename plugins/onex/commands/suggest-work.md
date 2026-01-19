---
name: suggest-work
description: Suggest Work Command - Priority Backlog Recommendations
tags: [linear, backlog, priority, planning]
---

# Suggest Work Command - Priority Backlog Recommendations

Get highest priority unblocked issues from your Linear backlog with intelligent repo-based prioritization.

## Task

Query Linear for priority backlog issues, filter out blocked items, and return actionable work suggestions sorted by priority and relevance to your current repo context.

## Steps

### 1. Run the Suggest Work Skill

Execute the skill with desired options:

```bash
# Default: 5 suggestions for current repo context
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work

# Custom count
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --count 10

# Specific project
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --project Beta

# Override repo context
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --repo omnibase_core

# Filter by label
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --label bug

# JSON output
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --json

# Get execution prompt only (pipeable)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/suggest-work --execute
```

### 2. Review the Generated Query

The skill outputs a structured prompt for Linear MCP. The output includes:

**Markdown Mode** (default):
- Project info and context
- MCP query to execute
- Filtering instructions (blocked labels)
- Sorting rules (repo match, priority, age)
- Expected output format

**JSON Mode** (`--json`):
- Machine-readable query specification
- Cache metadata
- Full MCP parameters

**Execute Mode** (`--execute`):
- Raw execution prompt only
- Pipeable to clipboard or other tools

### 3. Execute the Linear MCP Query

Use the generated MCP query to fetch issues:

```python
mcp__linear-server__list_issues(
    project="<project_id>",
    state="Backlog",
    limit=15  # 3x requested count for filtering headroom
)
```

### 4. Apply Filters and Sorting

After receiving results:

1. **Exclude blocked issues** with labels: `blocked`, `waiting`, `on-hold`, `needs-clarification`, `dependent`

2. **Sort by priority**:
   - Repo-matching issues first (if repo context detected)
   - Priority: Urgent > High > Normal > Low
   - Age: oldest first within same priority

3. **Return top N** issues as specified by `--count`

## Example Usage

```bash
# Get 5 suggestions, auto-detect repo context
/suggest-work

# Get 10 suggestions for Beta project
/suggest-work --project Beta --count 10

# Pure priority sort (no repo bias)
/suggest-work --no-repo

# Filter to bugs only
/suggest-work --label bug

# Get JSON output for automation
/suggest-work --json

# Get execution prompt for clipboard
/suggest-work --execute | pbcopy

# Force fresh query (bypass cache)
/suggest-work --no-cache
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--count N` | Number of suggestions to return | 5 |
| `--project PROJECT` | Project name (MVP, Beta, Production, etc.) | MVP |
| `--repo REPO` | Override auto-detected repo context | Auto-detected |
| `--no-repo` | Disable repo-based prioritization | false |
| `--label LABEL` | Filter to issues with specific label | none |
| `--json` | Output as JSON instead of markdown | false |
| `--execute` | Output ONLY the execution prompt (pipeable) | false |
| `--no-cache` | Bypass cache (force fresh query) | false |
| `-h, --help` | Show help | - |

## Available Projects

| Shortcut | Full Name |
|----------|-----------|
| MVP | MVP - OmniNode Platform Foundation |
| Beta | Beta - OmniNode Platform Hardening |
| Production | Production - OmniNode Platform Scale |
| NodeReducer | NodeReducer v1.0 - Contract-Driven FSM |
| EventBusAlignment | Event Bus Alignment - OmniNode Platform |
| PipelineOptimization | Synchronous Pipeline Optimization |

## Expected Output Format

### Markdown Output (Default)

```
# Suggested Work: MVP

**Generated**: 2025-12-14 10:30:00
**Project**: MVP - OmniNode Platform Foundation
**Project ID**: `abc123`
**Repo Context**: `omniclaude` (issues with this label shown first)
**Cache**: Miss (will cache for 300s)

---

## Execute Now

To get suggestions, ask Claude:

Query Linear for the top 5 unblocked backlog issues in project MVP (ID: abc123).
Use: mcp__linear-server__list_issues(project="abc123", state="Backlog", limit=15)
Then filter out issues with labels: blocked, waiting, on-hold, needs-clarification, dependent
Sort by: 1) Issues with 'omniclaude' label first, 2) Priority (Urgent > High > Normal > Low), 3) Created date (oldest first)
Return the top 5 results in a table with columns: #, ID, Title, Priority, Repo Match, Created

---
...
```

### JSON Output (`--json`)

```json
{
  "generated_at": "2025-12-14T10:30:00Z",
  "cache_hit": false,
  "cache": {
    "key": "v1:suggest-work:abc123:label=none,repo=omniclaude:5",
    "ttl_seconds": 300,
    "schema_version": 1
  },
  "execution_prompt": "Query Linear for the top 5...",
  "project": {
    "shortcut": "MVP",
    "name": "MVP - OmniNode Platform Foundation",
    "id": "abc123"
  },
  "repo_context": "omniclaude",
  "mcp_query": {
    "tool": "mcp__linear-server__list_issues",
    "parameters": {
      "project": "abc123",
      "state": "Backlog",
      "limit": 15
    }
  }
}
```

### Execute Output (`--execute`)

```
Query Linear for the top 5 unblocked backlog issues in project MVP (ID: abc123).
Use: mcp__linear-server__list_issues(project="abc123", state="Backlog", limit=15)
Then filter out issues with labels: blocked, waiting, on-hold, needs-clarification, dependent
Sort by: 1) Issues with 'omniclaude' label first, 2) Priority (Urgent > High > Normal > Low), 3) Created date (oldest first)
Return the top 5 results in a table with columns: #, ID, Title, Priority, Repo Match, Created
```

### Final Suggested Work Table

After executing the MCP query and applying filters:

| # | ID | Title | Priority | Repo Match | Created |
|---|-------|-------|----------|------------|---------|
| 1 | OMNI-42 | Fix event handler retry logic | Urgent | Yes | 2025-12-01 |
| 2 | OMNI-38 | Add correlation ID to logs | High | Yes | 2025-12-03 |
| 3 | OMNI-55 | Implement DLQ consumer | Urgent | No | 2025-12-02 |
| 4 | OMNI-61 | Update API documentation | Normal | No | 2025-11-28 |
| 5 | OMNI-73 | Add unit tests for router | Low | Yes | 2025-11-25 |

## Implementation Notes

### Repo Context Detection

The skill automatically detects your current repository from:
1. Git repository name (via `git rev-parse`)
2. Path patterns (`/omnibase_core/`, `/omniclaude/`, etc.)

Issues with a label matching the repo name are prioritized first.

### Caching

- **TTL**: 300 seconds (5 minutes)
- **Key Format**: `v{schema}:suggest-work:{project}:{filters}:{count}`
- **Bypass**: Use `--no-cache` to force fresh query generation

### Blocked Labels

These issues are automatically excluded:
- `blocked`
- `waiting`
- `on-hold`
- `needs-clarification`
- `dependent`

### Priority Sorting

Within each group (repo-match vs non-match):
1. **Urgent** (1) - Highest priority
2. **High** (2)
3. **Normal** (3)
4. **Low** (4) - Lowest priority
5. **Age** - Oldest issues first (tie-breaker)

## Success Criteria

- All available projects are queryable
- Blocked issues are correctly filtered out
- Repo context auto-detection works correctly
- Issues sorted by priority and relevance
- Cache improves repeated query performance
- JSON output is valid and parseable
- Execute mode produces clean, pipeable output
- All flags function as documented

## Performance Targets

- **Query Generation**: <100ms (cached: <10ms)
- **Cache TTL**: 300 seconds
- **Default Count**: 5 issues
- **Query Limit**: 3x count (filtering headroom)
