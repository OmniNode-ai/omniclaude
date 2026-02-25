# pipeline-metrics — Execution Prompt

## Overview

You are executing the `pipeline-metrics` skill for OMN-2775.

Collect pipeline health metrics from four data sources, render a markdown
report (max 80 columns), and degrade gracefully when any source is
unavailable.

## Arguments

Parse from the invocation args string:

| Arg | Default | Description |
|-----|---------|-------------|
| `--since YYYY-MM-DD` | 7 days ago | Start of analysis window |
| `--ticket OMN-XXXX` | — | Hard filter to one ticket's PRs |
| `--repo REPO` | — | Filter to one GitHub repo name |
| `--format table\|json` | table | Output format |

Compute `--until` as today (UTC).

## Step 1: Resolve time window

```python
from datetime import UTC, datetime, timedelta

until = datetime.now(UTC).date()
since = until - timedelta(days=7)  # override if --since provided
```

## Step 2: Collect pipeline state.yaml files

Scan `~/.claude/pipelines/*/state.yaml`. For each file in the time window
(started_at >= since AND started_at <= until):

Extract:

```python
# Exact state.yaml paths — do NOT guess alternative paths
ci_fix_cycles      = phases.ci_watch.artifacts.ci_fix_cycles_used       # int, default 0
pr_review_cycles   = phases.pr_review_loop.artifacts.pr_review_cycles_used  # int, default 0
local_review_iters = phases.local_review.artifacts.iteration_count       # int, default 1
phase_timings      = {phase: (started_at, completed_at) for phase in phases}
ticket_id          = ticket_id  # e.g. "OMN-2775"
repo               = repo       # e.g. "omniclaude"
```

Apply repo filter if `--repo` was given. Apply ticket filter if `--ticket`.

Compute per-ticket:
```
rework = max(0, local_review_iters - 1) + ci_fix_cycles + pr_review_cycles
```

If no state.yaml files exist in window → mark section "insufficient data".

## Step 3: Collect GitHub PR data

Use the `gh` CLI. Determine repo slug(s) from:
1. `--repo` filter if given → `OmniNode-ai/{repo}`
2. OR union of repos found in state.yaml files

For each repo slug, run:

```bash
gh pr list \
  --repo OmniNode-ai/{repo} \
  --state merged \
  --json number,title,headRefName,createdAt,mergedAt \
  --limit 200
```

Filter to PRs where `mergedAt` is within the window.

**PR-to-ticket linkage** (in order):
1. Extract `OMN-\d+` from `headRefName` (branch name) — preferred
2. Fall back to extracting `OMN-\d+` from `title`
3. If no match → label as "unlinked" in output

Apply `--ticket` filter: keep only PRs where extracted ticket matches.

Compute:
```python
cycle_time_hours = [(mergedAt - createdAt).total_seconds() / 3600 for each PR]
p50 = percentile(cycle_time_hours, 50)
p90 = percentile(cycle_time_hours, 90)
```

CI clean rate (from state.yaml cross-reference):
```python
clean = count(tickets where ci_fix_cycles == 0)
total = len(tickets)
ci_clean_pct = clean / total * 100
```

Feature velocity (4-week rolling, merged PRs/week):
```python
# Compute from gh pr list with --since = 28 days ago for velocity baseline
prs_per_week = len(merged_prs_in_window) / window_weeks
```

If `gh` is not available or returns error → mark cycle time and velocity
sections "data unavailable".

## Step 4: Collect skill duration from PostgreSQL

Query `agent_execution_logs`:

```sql
SELECT
    skill_name,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
    COUNT(*) AS call_count
FROM agent_execution_logs
WHERE created_at >= %(since)s
  AND skill_name IS NOT NULL
GROUP BY skill_name
ORDER BY call_count DESC
LIMIT 10;
```

Use `OMNIBASE_INFRA_DB_URL` or `POSTGRES_HOST`/`POSTGRES_PORT` env vars.

If connection fails (any exception) → mark skill duration section
"data unavailable". **Do not raise — degrade silently.**

## Step 5: Collect story point estimates from Linear

For each linked ticket_id found in Step 2, call:

```python
mcp__linear-server__get_issue(id=ticket_id)
# Extract: estimate (story points)
```

If fewer than 5 tickets have estimates → mark estimation accuracy
"insufficient data (need ≥5 tickets with story points)".

Else compute:
```python
avg_h_per_point = mean(cycle_time_hours) / mean(story_points)
accuracy = story_points / (cycle_time_h / avg_h_per_point)
# Values near 1.0 = accurate; >1 = underestimated; <1 = overestimated
```

## Step 6: Render output

### Table format (default)

Render a single markdown report, max 80 columns:

```
Pipeline Health Metrics — {since} to {until}
─────────────────────────────────────────────

Cycle Time  [{n} PRs{repo_filter_note}]
  P50: {p50:.1f} h    P90: {p90:.1f} h
  {ascii_bar for p50}  P50
  {ascii_bar for p90}  P90

CI Clean Rate: {pct:.0f}%  ({clean}/{total} PRs with 0 ci_fix_cycles)

Rework Cycles / Ticket
  {ticket_id}  {bar}  {rework}
  ...

Feature Velocity: {prs_per_week:.1f} PRs/week  (4-week rolling avg)

Skill Duration P50 (top 5 by call count)
  {skill_name:<20}  {bar}  {p50_ms:>8,.0f} ms
  ...

Estimation Accuracy: {value|insufficient_data|data_unavailable}
```

ASCII bar charts:
- Relative scale: longest bar = 40 chars
- Bar character: `█`
- Min bar width: 1 char (never empty for non-zero values)

Degrade rules (per section):
- No data → `  [section]: insufficient data`
- Source unavailable → `  [section]: data unavailable`
- Never omit a section — always render heading + status

Notes for fallback linkage:
- When PR-to-ticket linkage fell back to PR title, append:
  `  * OMN-XXXX linked via PR title (branch name had no ticket prefix)`

### JSON format (`--format json`)

Emit one JSON object to stdout:

```json
{
  "window": {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"},
  "repo_filter": null,
  "ticket_filter": null,
  "metrics": {
    "cycle_time": {"p50_hours": 4.2, "p90_hours": 12.1, "n": 23},
    "ci_clean_rate": {"pct": 87.0, "clean": 20, "total": 23},
    "rework_per_ticket": [
      {"ticket": "OMN-2773", "rework": 2, "ci_fix_cycles": 1,
       "pr_review_cycles": 1, "local_review_extra_iters": 0}
    ],
    "feature_velocity": {"prs_per_week": 5.2, "window_weeks": 4},
    "skill_duration_p50_ms": {"ticket-work": 42300, "local-review": 57100},
    "estimation_accuracy": null
  },
  "data_availability": {
    "state_yaml": true,
    "postgres": false,
    "github": true,
    "linear": true
  }
}
```

## Degrade test scenarios

The skill MUST degrade cleanly for these scenarios (no exception propagation):

1. `POSTGRES_HOST=invalid` — skill-duration section shows "data unavailable"
2. No state.yaml files in window — all local-source sections show
   "insufficient data"
3. `gh` CLI not authenticated — cycle time and velocity show
   "data unavailable"
4. Linear MCP returns no estimates — estimation accuracy shows
   "insufficient data (need ≥5 tickets with story points)"

## Constraints

- Max 5 fenced code blocks in output
- No nested fences
- Each section independently degrades
- `--ticket` without `--repo` is valid; search all repos
- `--repo` without `--ticket` is valid; report at repo level
- Without either, report across all repos found in state.yaml files

## Implementation note

v1 reads `agent_execution_logs` for skill duration (proxy metric).
When the OMN-2773 follow-on consumer ships and `skill_execution_logs` exists,
update Step 4 to read that table instead. Document this in the output header
with a note: `  * Skill duration sourced from agent_execution_logs (proxy)`
