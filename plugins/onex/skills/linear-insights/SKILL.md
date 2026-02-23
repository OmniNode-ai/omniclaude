---
name: linear-insights
description: Daily deep dive reports and velocity-based project completion estimates using Linear data
---

# Linear Insights

Analytics and reporting skills for Linear project management. Provides comprehensive daily deep dives and velocity-based milestone completion estimates.

## Skills Available

1. **deep-dive** - Generate a comprehensive daily work analysis (like DECEMBER_9_2025_DEEP_DIVE.md)
2. **velocity-estimate** - Calculate velocity and estimate milestone completion dates
3. **estimation-accuracy** - Track how accurate your estimates have been over time
4. **project-status** - Quick health dashboard; supports `--emit` to relay snapshots to Kafka

## When to Use

- **End of day wrap-up**: Generate a comprehensive deep dive of the day's work
- **Sprint planning**: Understand velocity trends for capacity planning
- **Milestone tracking**: Get data-driven ETAs for MVP, Beta, Production
- **Retrospectives**: Analyze estimation accuracy to improve future estimates
- **Weekly summaries**: Aggregate daily work into weekly reports

---

## Deep Dive Report

Generates a comprehensive analysis of work completed in a specified time period.
Format matches the established deep dive pattern (see `${HOME}/Code/omni_home/omni_save/DECEMBER_9_2025_DEEP_DIVE.md`).

### Usage

```bash
# Today's deep dive (display only) — auto-discovers all active repos
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive

# Specific date (auto-discovers repos with activity on that date)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --date 2025-12-09

# Last N days (for weekly summary)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --days 7

# Save to default directory (omni_save)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --save

# Save to custom directory
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --save --output-dir ~/reports

# JSON output for processing
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --json

# Analyze specific repos only (overrides auto-discovery)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive --repos omnibase_core,omniclaude
```

### Configuration

**Output Directory** (where reports are saved with `--save`):

| Method | Example | Priority |
|--------|---------|----------|
| `--output-dir` flag | `--output-dir ~/reports` | Highest |
| `LINEAR_INSIGHTS_OUTPUT_DIR` env | `export LINEAR_INSIGHTS_OUTPUT_DIR=~/reports` | Medium |
| Default | `${HOME}/Code/omni_home/omni_save` | Lowest |

**Filename Pattern**: `{MONTH}_{DAY}_{YEAR}_DEEP_DIVE.md`
- Example: `DECEMBER_13_2025_DEEP_DIVE.md`

### Deep Dive Format

The deep dive follows a structured format with these sections:

#### 1. Executive Summary
- **Velocity Score**: 0-100 based on commit volume, PRs merged, issues completed
- **Effectiveness Score**: 0-100 based on strategic value of work completed
- **Overall Assessment**: 2-3 sentence summary of the day

#### 2. Repository Activity Overview
- Commits per repository
- PRs merged per repository
- Files changed and lines added/deleted
- Focus areas

#### 3. Major Components & Work Completed
For each PR merged:
- Status, Impact level (Critical/High/Medium/Low)
- Files changed, lines added/deleted
- Description of work
- Key components/features
- Linear tickets addressed
- Significance statement

#### 4. Detailed Commit Analysis
- Commits grouped by category (Contracts, Runtime, CI, etc.)
- Key individual commits with file counts

#### 5. Metrics & Statistics
- Total commits, PRs, files changed
- PR statistics table
- Linear ticket progress (closed/in-progress)
- Code quality metrics

#### 6. Work Breakdown by Category
- Percentage breakdown of work types
- Time/effort allocation

#### 7. Key Achievements
- Bullet points of major accomplishments
- Milestone progress

#### 8. Challenges & Issues
- Technical challenges encountered
- Process observations

#### 9. Velocity Analysis
- Positive/negative velocity factors
- Velocity score justification

#### 10. Effectiveness Analysis
- High-value work identified
- Strategic impact assessment
- Effectiveness score justification

#### 11. Lessons Learned
- Key takeaways from the day
- Insights for future work

#### 12. Next Day Preview
- Expected focus areas for tomorrow
- Upcoming priorities

#### 13. Appendix
- Complete commit log with timestamps
- PR details

### Example Output

```markdown
# December 13, 2025 - Deep Dive Analysis

**Date**: Friday, December 13, 2025
**Week**: Week of December 9-13, 2025
**Day of Week**: Friday

---

## Executive Summary

**Velocity Score**: 85/100
**Effectiveness Score**: 90/100

**Overall Assessment**: Strong day with 12 issues completed across MVP and Beta milestones.
Focus on code quality improvements and deprecation fixes. 6 PRs merged with comprehensive
test coverage improvements.

---

## Repository Activity Overview

### omnibase_core
**Total Commits**: 24
**PRs Merged**: 4 (PRs #184-188)
**Files Changed**: 156
**Lines Changed**: +8,234 / -2,891
**Focus Areas**: Deprecation fixes, purity violations, structured logging

### omnibase_spi
**Total Commits**: 8
**PRs Merged**: 2 (PRs #39-40)
**Files Changed**: 23
**Lines Changed**: +1,456 / -892
**Focus Areas**: EventBus protocol cleanup, test coverage

...
```

---

## Velocity Estimate

Calculates project velocity and estimates time to completion for milestones.

### Usage

```bash
# Estimate for MVP project
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "MVP"

# All milestones overview
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --all

# Include confidence intervals
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "MVP" --confidence

# JSON output
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate --project "Beta" --json
```

### Metrics Calculated

| Metric | Description |
|--------|-------------|
| **Velocity** | Issues completed per day/week (rolling average) |
| **Backlog Size** | Remaining issues by status |
| **Burn Rate** | Current completion rate vs planned |
| **ETA** | Estimated completion date |
| **Confidence** | Low/Medium/High based on velocity variance |

### Velocity Calculation

Velocity is calculated using a weighted rolling average:
- Last 7 days: 50% weight (recent performance)
- Last 14 days: 30% weight (short-term trend)
- Last 30 days: 20% weight (baseline)

This balances recent momentum with historical patterns.

### Example Output

```markdown
# Velocity Report: MVP - OmniNode Platform Foundation

## Current Status
- **Total Issues**: 71
- **Completed**: 28 (39%)
- **In Progress**: 5
- **Backlog**: 38

## Velocity Metrics
- **7-day velocity**: 2.3 issues/day
- **14-day velocity**: 1.8 issues/day
- **30-day velocity**: 1.5 issues/day
- **Weighted velocity**: 2.0 issues/day

## Completion Estimate
- **Remaining Issues**: 43
- **Estimated Days**: 21.5 days
- **Target Date**: 2026-01-03
- **Confidence**: Medium (variance: 0.4)

## Velocity Trend
[Chart showing 30-day velocity trend]

Week of 12/02: ████████░░ 1.6/day
Week of 12/09: ██████████ 2.3/day (current)

## Risk Factors
- 5 issues blocked/waiting
- 2 urgent issues in backlog
- Holiday period may reduce velocity
```

---

## Estimation Accuracy

Tracks historical estimation accuracy to improve future estimates.

### Usage

```bash
# Show accuracy for completed milestones
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/estimation-accuracy

# Track specific project
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/estimation-accuracy --project "MVP"
```

### Metrics

- **Estimate vs Actual**: How close were predictions?
- **Optimism Bias**: Do you consistently underestimate?
- **Accuracy Trend**: Are estimates improving over time?
- **Best/Worst Predictions**: Learn from outliers

---

## Projects Tracked

The following projects are available for tracking:

| Project | Milestone | Description |
|---------|-----------|-------------|
| MVP - OmniNode Platform Foundation | MVP | Core infrastructure, DI container, node implementations |
| Beta - OmniNode Platform Hardening | Beta | Security, observability, tooling standardization |
| Production - OmniNode Platform Scale | Production | Scaling, analytics, A/B testing, visualization |
| NodeReducer v1.0 - Contract-Driven FSM | MVP (sub) | FSM-driven NodeReducer with 71 tickets |

---

## Data Sources

All data is fetched from Linear via MCP:

- `mcp__linear-server__list_issues` - Issue data
- `mcp__linear-server__list_projects` - Project metadata
- `mcp__linear-server__get_project` - Project details

No external databases or caches are used - all calculations are done on fresh Linear data.

---

## Implementation Notes

### For Polymorphic Agent Dispatch

These skills are designed to be invoked by polymorphic agents:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Generate daily work report",
  prompt="Generate a daily work report for the last 24 hours.

    Use Linear MCP tools:
    1. mcp__linear-server__list_issues with assignee='me' and updatedAt='-P1D'
    2. Categorize by status (Done, In Progress, Backlog)
    3. Extract PR links from attachments
    4. Group by repository from labels

    Format as markdown with:
    - Summary stats
    - Completed work section with PR links
    - In Progress section
    - Insights (velocity, blockers, focus areas)"
)
```

### Velocity Calculation Algorithm

```python
def calculate_velocity(issues_completed, period_days):
    """
    Weighted rolling average velocity.

    Args:
        issues_completed: List of (date, count) tuples
        period_days: Analysis period

    Returns:
        Weighted velocity (issues/day)
    """
    weights = {
        7: 0.50,   # Last week: 50%
        14: 0.30,  # Last 2 weeks: 30%
        30: 0.20,  # Last month: 20%
    }

    total = 0
    for period, weight in weights.items():
        period_issues = sum(c for d, c in issues_completed
                          if d >= now - timedelta(days=period))
        velocity = period_issues / min(period, period_days)
        total += velocity * weight

    return total
```

---

## Project Status — Kafka Emission (--emit)

The `project-status` skill supports a `--emit` flag that serializes a workstream snapshot
and relays it to Kafka via the `onex-linear-relay` CLI. This is the primary ingress path for
Linear workstream data into the ONEX event bus.

### Usage

```bash
# Show dashboard for MVP project + emit snapshot to Kafka
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status MVP --emit

# All projects overview + emit
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status --all --emit

# JSON output + emit (useful for scripting)
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status MVP --json --emit
```

### How Emission Works

1. After generating the status output, `--emit` serializes a snapshot to `/tmp/linear-snapshot-{timestamp}.json`:
   ```json
   {
     "workstreams": ["MVP", "Beta"],
     "project": "MVP - OmniNode Platform Foundation",
     "project_shortcut": "MVP",
     "source": "project-status",
     "generated_at": "2026-02-23T22:00:00+00:00"
   }
   ```
2. Calls `onex-linear-relay emit --snapshot-file /tmp/linear-snapshot-{timestamp}.json`
3. The relay publishes to `onex.evt.linear.snapshot.v1` (non-blocking, exits 0 even if Kafka is unreachable)

### Requirements

- `onex-linear-relay` must be installed and available on `PATH`
- Install via: `pip install omnibase_infra` (or `uv add omnibase_infra` in your project)
- Related ticket: OMN-2656 (Phase 2 — effect nodes and CLIs in omnibase_infra)

### IMPORTANT: Do NOT Call REST Endpoint

The `POST /api/linear/snapshot` endpoint in omnidash is **debug-only ingress**.
It must never be called from production code or skills. Use `--emit` (which calls
`onex-linear-relay`) as the only correct production path for Linear data into the event bus.

---

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/`

**Executables**:
- `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/deep-dive` - Daily deep dive generator
- `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate` - Velocity and ETA calculator
- `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/estimation-accuracy` - Estimation tracking
- `${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status` - Quick health dashboard with Kafka emission support

---

## See Also

- Linear MCP tools: `mcp__linear-server__*`
- Linear ticket skills: `${CLAUDE_PLUGIN_ROOT}/skills/linear/`
- PR review skills: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/`
- Deep dive reference: `${HOME}/Code/omni_home/omni_save/DECEMBER_9_2025_DEEP_DIVE.md`
- `onex-linear-relay` CLI — `omnibase_infra` package (OMN-2656)
