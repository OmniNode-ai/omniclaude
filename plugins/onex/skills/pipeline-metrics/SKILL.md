---
name: pipeline-metrics
description: Report pipeline health metrics — rework ratio, cycle time, CI stability, and feature velocity
version: 1.0.0
category: reporting
tags:
  - metrics
  - pipeline
  - ci
  - velocity
  - reporting
author: OmniClaude Team
args:
  - name: --since
    description: Start of time window (YYYY-MM-DD). Default is 7 days ago.
    required: false
  - name: --ticket
    description: Hard filter to one ticket's PRs (e.g. OMN-2775)
    required: false
  - name: --repo
    description: Filter to one GitHub repo (e.g. omniclaude)
    required: false
  - name: --format
    description: "Output format: table (default) or json"
    required: false
---

# /pipeline-metrics

Report pipeline health metrics for a time window or a specific ticket.

## Quick Start

```
/pipeline-metrics
/pipeline-metrics --since 2026-02-18
/pipeline-metrics --ticket OMN-2775
/pipeline-metrics --repo omniclaude --format json
```

## Metrics Reported

| Metric | Formula | Display |
|--------|---------|---------|
| Cycle Time | `mergedAt - createdAt` (hours), P50 + P90 | Cycle Time |
| Rework Cycles | `max(0, local_review_iters - 1) + ci_fix_cycles + pr_review_cycles` | Rework Cycles/Ticket |
| CI Stability | `count(ci_fix_cycles==0) / total` | CI Clean Rate % |
| Feature Velocity | Merged PRs/week, 4-week rolling avg | Feature Velocity |
| Estimation Accuracy | `story_points / (cycle_time_h / avg_h_per_point)` | Est. Accuracy |
| Skill Duration | P50 `duration_ms` by skill_name from `agent_execution_logs` | Skill Duration (P50) |

## Data Sources

| Source | Metric | Notes |
|--------|--------|-------|
| `~/.claude/pipelines/*/state.yaml` | Rework cycles, phase timing | Local |
| `agent_execution_logs` (PostgreSQL) | Skill duration (proxy) | Degrades to "unavailable" if DB unreachable |
| GitHub `gh` CLI | Cycle time, CI failure counts | Requires `gh` auth |
| Linear MCP | Story point estimates | Requires OMN-XXXX branch prefix |

## Output Format

Single markdown report, max 80 columns. Each section degrades independently
with "data unavailable" or "insufficient data" when a source is unreachable.

```
Pipeline Health Metrics — 2026-02-18 to 2026-02-25
────────────────────────────────────────────────────

Cycle Time (omniclaude)
  P50:  4.2 h    P90: 12.1 h
  ████████████████████████████████████████  P50
  ████████████████████████████████████████████████████████████  P90

CI Clean Rate: 87%  (20/23 PRs with 0 ci_fix_cycles)

Rework Cycles / Ticket (last 7 days)
  OMN-2773  ██  2
  OMN-2775  █   1
  OMN-2782  ███ 3

Feature Velocity: 5.2 PRs/week  (4-week rolling avg)

Skill Duration P50 (top 5 by call count)
  ticket-work      ████████████████████████████  42 300 ms
  local-review     ██████████████████████████████████  57 100 ms
  ci-watch         ████████  13 400 ms

Estimation Accuracy: insufficient data (need ≥5 tickets with story points)
```

## JSON Output (`--format json`)

```json
{
  "window": {"since": "2026-02-18", "until": "2026-02-25"},
  "repo_filter": null,
  "ticket_filter": null,
  "metrics": {
    "cycle_time": {"p50_hours": 4.2, "p90_hours": 12.1, "n": 23},
    "ci_clean_rate": {"pct": 87.0, "clean": 20, "total": 23},
    "rework_per_ticket": [{"ticket": "OMN-2773", "rework": 2}],
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

## Important Notes

- Without `--ticket`, report is at repo level only. Branch-name-to-ticket
  linkage (`OMN-\d+` in head ref) is a heuristic; output notes when fallback
  to PR title is used.
- Estimation accuracy requires at least 5 tickets with story points assigned
  in Linear.
- Skill duration uses `agent_execution_logs` (proxy). When OMN-2773 follow-on
  consumer ships, update to read `skill_execution_logs` directly.
