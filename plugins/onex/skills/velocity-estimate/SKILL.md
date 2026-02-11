---
name: velocity-estimate
description: Velocity Estimate Command - Project Velocity & ETA Analysis
version: 1.0.0
category: reporting
tags: [linear, velocity, estimation, reporting]
author: OmniClaude Team
args:
  - name: project
    description: Project name (MVP, Beta, Production, NodeReducer)
    required: false
  - name: --project
    description: Explicit project name or ID
    required: false
  - name: --all
    description: Show all milestones overview
    required: false
  - name: --confidence
    description: Include confidence intervals
    required: false
  - name: --history
    description: Show velocity history (last 30 days)
    required: false
  - name: --weighted
    description: Use weighted rolling average (recent data weighted higher)
    required: false
  - name: --method
    description: Velocity calculation method (simple, priority, points, labels, cycle_time)
    required: false
  - name: --deep-dive-dir
    description: Custom directory for deep dive files
    required: false
  - name: --json
    description: Output as JSON for programmatic use
    required: false
---

# Velocity Estimate Command - Project Velocity & ETA Analysis

Calculate project velocity from historical data and estimate milestone completion dates using Linear backlog.

## Task

Analyze historical velocity from deep dive documents and provide completion estimates for Linear projects.

## Steps

### 1. Determine Target Project

If the user provided a project name as argument `$1`, use that. Otherwise, check if `--all` was specified for an overview.

Available projects:
- **MVP** - MVP - OmniNode Platform Foundation
- **Beta** - Beta - OmniNode Platform Hardening
- **Production** - Production - OmniNode Platform Scale
- **NodeReducer** - NodeReducer v1.0 - Contract-Driven FSM

### 2. Execute Velocity Analysis

Use the `velocity-estimate` skill to calculate velocity and ETA:

```bash
# Basic project velocity
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "${1:-MVP}"

# All milestones overview
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --all

# With confidence intervals
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "${1:-MVP}" --confidence

# With weighted rolling average (recent data weighted higher)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "${1:-MVP}" --weighted

# Use specific calculation method
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "${1:-MVP}" --method points

# Show velocity history (last 30 days)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "${1:-MVP}" --history
```

### 3. Analyze Output

The skill provides:

**Velocity Metrics**:
- Days analyzed
- Total tickets closed
- Average velocity (tickets/day)
- Method and metric grade
- Confidence level

**Metric Grades**:
- **ETA-grade**: Suitable for predictive ETA calculations (points, cycle_time methods)
- **Signal-grade**: Useful for dashboards but NOT for ETA (simple, priority, labels methods)

**Velocity Methods**:
| Method | Grade | Description |
|--------|-------|-------------|
| `simple` | Signal | Ticket count / days |
| `priority` | Signal | Priority-weighted points |
| `points` | ETA | Story point estimates |
| `labels` | Signal | Label-weighted velocity |
| `cycle_time` | ETA | Cycle time based |

### 4. Calculate ETA from Backlog

After getting velocity, query Linear for current backlog:

```python
# Get project backlog count
mcp__linear-server__list_issues(
    project="MVP - OmniNode Platform Foundation",
    limit=250
)

# Calculate:
# - Total issues in project
# - Issues with status='Done'
# - Remaining = Total - Done
# - ETA = Remaining / velocity days
```

### 5. Provide Actionable Output

Summarize findings with:
- **Velocity**: Current team velocity with method and confidence
- **Backlog Status**: Total, completed, remaining issues
- **ETA**: Estimated completion date with confidence interval
- **Recommendations**: Suggestions for improving accuracy

## Example Usage

```bash
# Check MVP project velocity
/velocity-estimate MVP

# Check all milestones
/velocity-estimate --all

# MVP with confidence intervals
/velocity-estimate MVP --confidence

# Use weighted velocity (recent data has more weight)
/velocity-estimate MVP --weighted

# Use story points for more accurate ETA
/velocity-estimate MVP --method points

# Show velocity trend over time
/velocity-estimate MVP --history

# Get JSON output for programmatic use
/velocity-estimate MVP --json

# Compare methods
/velocity-estimate MVP --method priority --json
```

## Arguments

- `$1` (optional): Project name (MVP, Beta, Production, NodeReducer) - defaults to showing help
- `--project PROJECT`: Explicit project name or ID
- `--all`: Show all milestones overview
- `--confidence`: Include confidence intervals
- `--history`: Show velocity history (last 30 days)
- `--weighted`: Use weighted rolling average (50% last 7 days, 30% days 8-14, 20% days 15-30)
- `--method METHOD`: Velocity calculation method (simple, priority, points, labels, cycle_time)
- `--deep-dive-dir DIR`: Custom directory for deep dive files
- `--json`: Output as JSON for programmatic use

## Expected Output Format

```
# Velocity Report

**Generated**: 2025-12-14 10:30:00
**Deep Dive Source**: ${HOME}/Code/omni_save

---

## Historical Velocity (from Deep Dives)

| DECEMBER_13_2025 | 12 tickets |
| DECEMBER_12_2025 | 8 tickets |
| DECEMBER_11_2025 | 10 tickets |

### Summary

| Metric | Value |
|--------|-------|
| **Days Analyzed** | 5 |
| **Total Tickets Closed** | 50 |
| **Average Velocity** | 10.0 issues/day |
| **Method** | simple |
| **Metric Grade** | SIGNAL (dashboard signal only) |
| **Confidence** | MEDIUM |

---

## Current Backlog & ETA

### ETA Calculator

With velocity of **10.0 tickets/day**:

| Remaining | Estimated Days | Target Date |
|-----------|----------------|-------------|
| 20 | 2 | 2025-12-16 |
| 30 | 3 | 2025-12-17 |
| 40 | 4 | 2025-12-18 |
| 50 | 5 | 2025-12-19 |

---

*Report generated by linear-insights velocity-estimate skill*
```

## JSON Output Format

When using `--json`:

```json
{
  "generated_at": "2025-12-14T10:30:00Z",
  "deep_dive_source": "${HOME}/Code/omni_save",
  "project": "MVP - OmniNode Platform Foundation",
  "days_analyzed": 5,
  "total_tickets_closed": 50,
  "velocity": 10.0,
  "method": "simple",
  "velocity_metrics": {
    "value": 10.0,
    "std_dev": 1.5,
    "cv": 0.15,
    "grade": "signal",
    "unit": "issues/day",
    "confidence": "medium",
    "is_eta_grade": false
  },
  "daily_breakdown": [
    {"date": "DECEMBER_13_2025", "iso_date": "2025-12-13", "tickets": 12},
    {"date": "DECEMBER_12_2025", "iso_date": "2025-12-12", "tickets": 8}
  ]
}
```

## Implementation Notes

### Data Sources

**Historical Data**:
- Deep dive documents in `omni_save` directory
- Pattern: `*_DEEP_DIVE.md` files
- Extracts "Tickets Closed: N" from each file

**Current Backlog**:
- Linear MCP (`mcp__linear-server__list_issues`)
- Queries by project name
- Calculates remaining work

### Velocity Calculation

**Simple** (default):
- Average tickets closed per day
- Easy to understand
- Signal-grade (not for ETA)

**Weighted**:
- 50% weight: Last 7 days
- 30% weight: Days 8-14
- 20% weight: Days 15-30
- Adjusts for recent performance changes

**ETA-Grade Methods**:
- `points`: Uses story point estimates
- `cycle_time`: Uses actual cycle time data

### Confidence Levels

| Days Analyzed | Confidence |
|---------------|------------|
| 7+ days | High |
| 3-6 days | Medium |
| <3 days | Low |

### Dependencies

Requires:
- Python 3 with `json` module
- Optional: `bc` for floating-point math
- Optional: `jq` for JSON parsing
- Deep dive files in expected directory

## Success Criteria

- Velocity is calculated from available deep dive data
- Method and metric grade are clearly shown
- ETA warning is shown for signal-grade methods
- Confidence level reflects data availability
- JSON output is valid and complete
- Weighted velocity shows bucket breakdown when enabled
- History chart displays trend over time

## Performance Targets

- **Velocity calculation**: <2 seconds
- **Full report with history**: <5 seconds
- **JSON output**: <1 second

## Related Commands

- `/ci-failures` - Check CI/CD failures for current PR
- Linear MCP tools for backlog queries
