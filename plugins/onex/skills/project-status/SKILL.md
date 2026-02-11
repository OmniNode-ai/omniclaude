---
name: project-status
description: Project Status Command - Linear Insights Dashboard
version: 1.0.0
category: reporting
tags: [linear, reporting, project, status]
author: OmniClaude Team
args:
  - name: project
    description: Project name/shortcut (MVP, Beta, Production, etc.)
    required: false
  - name: --all
    description: Show all projects overview instead of single project
    required: false
  - name: --blockers
    description: Include blocked issues detail with duration
    required: false
  - name: --risks
    description: Highlight risk factors (high priority backlog, velocity drops)
    required: false
  - name: --confidence
    description: Show detailed confidence level breakdown
    required: false
  - name: --json
    description: Output as JSON instead of markdown
    required: false
---

# Project Status Command - Linear Insights Dashboard

Quick health dashboard for Linear projects including progress, velocity, blockers, ETA, and confidence metrics.

## Task

Generate a project health dashboard with metrics from Linear, including velocity calculations, blocker analysis, and ETA predictions with confidence levels.

## Steps

### 1. Determine Target Project

If the user provided a project name as argument `$1`, use that. Otherwise, use the default project from configuration.

Available project shortcuts:
- `MVP` - MVP - OmniNode Platform Foundation
- `Beta` - Beta - OmniNode Platform Hardening
- `Production` - Production - OmniNode Platform Scale
- `NodeReducer` - NodeReducer v1.0 - Contract-Driven FSM
- `EventBusAlignment` - Event Bus Alignment - OmniNode Platform
- `PipelineOptimization` - Synchronous Pipeline Optimization

### 2. Execute Project Status Skill

Use the `project-status` skill which provides a comprehensive dashboard:

```bash
# Execute the project-status skill
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status "$1" $2 $3 $4 2>&1
```

**What project-status provides**:
- MCP queries to execute for fetching Linear data
- Progress calculation templates
- Velocity and churn metrics
- Blocker detection and tracking
- ETA with confidence levels
- Health indicator checklist

### 3. Execute MCP Queries

The skill outputs MCP queries that need to be executed:

1. **All Project Issues** - For progress calculation
2. **Completed Issues** - For velocity (filter to last 7 days)
3. **Backlog Issues** - For remaining work
4. **In Progress Issues** - For current work

### 4. Calculate Metrics

After fetching data, calculate:

**Progress**:
- Formula: `(completed_issues / total_issues) * 100`
- Status: On Track / At Risk / Behind

**Velocity**:
- Formula: `issues_completed_last_7_days / 7`
- Status: Stable (within 10% of average) / Declining / Improving

**Churn Ratio**:
- Formula: `(issues_added - issues_completed) / issues_completed`
- Healthy: < 20%
- High: >= 20%

**ETA**:
- Base: `remaining_issues / velocity`
- Adjusted: Accounts for churn ratio

**Confidence Level**:
- High: >= 7 days data, CV <= 15%
- Medium: 5-6 days data, CV <= 30%
- Low: < 5 days data OR CV > 30%
- Note: Churn > 20% downgrades confidence by one level

### 5. Provide Actionable Output

Summarize the findings with:
- **Quick Stats Table**: Progress, Velocity, Blockers, Churn, ETA, Confidence
- **Health Indicators**: Checklist of pass/fail criteria
- **Action Items**: Based on issues detected

## Example Usage

```bash
# Quick status for default project
/project-status

# Status for specific project
/project-status MVP

# All projects overview
/project-status --all

# Include blocked issues detail
/project-status MVP --blockers

# Highlight risks
/project-status MVP --risks

# Show detailed confidence breakdown
/project-status MVP --confidence

# Combined flags
/project-status MVP --blockers --risks --confidence

# JSON output for programmatic use
/project-status MVP --json
```

## Arguments

- `$1` (optional): Project name/shortcut (MVP, Beta, Production, etc.)
- `--all`: Show all projects overview instead of single project
- `--blockers`: Include blocked issues detail with duration
- `--risks`: Highlight risk factors (high priority backlog, velocity drops)
- `--confidence`: Show detailed confidence level breakdown
- `--json`: Output as JSON instead of markdown

## Expected Output Format

### Markdown Output (Default)

```
# Project Status: MVP

**Generated**: 2025-12-14 10:30:00
**Project**: MVP - OmniNode Platform Foundation
**Project ID**: `abc123-def456`

---

## Quick Stats

| Metric | Value | Status |
|--------|-------|--------|
| Progress | 45/100 (45%) | On Track |
| Velocity | 5.2 issues/day | Stable |
| Blockers | 2 | Attention Needed |
| Churn Ratio | 12% | Healthy |
| Base ETA | 10.6 days | 2025-12-24 |
| Adjusted ETA | 11.8 days | 2025-12-26 |
| Confidence | Medium | 7 days data, CV=22% |

---

## Health Indicators

- [x] Velocity stable (within 10% of average)
- [x] ETA before target date
- [ ] Blocked issues = 0
- [x] High priority backlog < 5
- [x] Churn ratio < 20%

---

## Action Items

1. **Blockers**: 2 issues blocked - review OMNI-123, OMNI-456
2. **Recommendation**: Address blockers to maintain velocity

---

*Script generated by linear-insights project-status skill*
```

### JSON Output (with --json)

```json
{
  "generated_at": "2025-12-14T10:30:00Z",
  "project": {
    "shortcut": "MVP",
    "name": "MVP - OmniNode Platform Foundation",
    "id": "abc123-def456"
  },
  "metrics": {
    "progress": {"completed": 45, "total": 100, "percent": 45},
    "velocity": {"value": 5.2, "status": "stable"},
    "blockers": {"count": 2, "status": "attention"},
    "churn": {"ratio": 0.12, "status": "healthy"},
    "eta": {"base_days": 10.6, "adjusted_days": 11.8}
  },
  "confidence": {
    "level": "MEDIUM",
    "days_analyzed": 7,
    "cv": 0.22
  },
  "health_indicators": {
    "velocity_stable": true,
    "eta_before_target": true,
    "no_blockers": false,
    "low_high_priority_backlog": true,
    "healthy_churn": true
  }
}
```

## Implementation Notes

### Health Indicators

The skill evaluates 5 health indicators:

| Indicator | Check | Pass | Fail |
|-----------|-------|------|------|
| Velocity Stable | Within 10% of average | Green | Red |
| ETA Before Target | Calculated ETA <= target date | Green | Red |
| No Blockers | Blocked issue count = 0 | Green | Red |
| Low Priority Backlog | Urgent/High priority in backlog < 5 | Green | Red |
| Healthy Churn | Churn ratio < 20% | Green | Red |

### Confidence Level Calculation

Confidence is determined by three factors:

1. **Days Analyzed**: More data = higher confidence
   - >= 7 days: Can be HIGH
   - 5-6 days: Can be MEDIUM
   - < 5 days: LOW

2. **Coefficient of Variation (CV)**: Velocity predictability
   - CV <= 15%: Stable (HIGH eligible)
   - CV <= 30%: Variable (MEDIUM eligible)
   - CV > 30%: Unpredictable (LOW)

3. **Churn Impact**: High churn downgrades confidence
   - Churn > 20%: Downgrade by one level

### Blocker Detection

Issues are considered blocked if they have any of these labels:
- `blocked`
- `waiting`
- `on-hold`
- (Additional labels configurable in config.yaml)

### ETA Adjustment

The adjusted ETA accounts for backlog churn:
- **Negative churn** (backlog shrinking): Reduce ETA by up to 10%
- **0-20% churn**: Increase ETA proportionally
- **> 20% churn**: Increase ETA + downgrade confidence

### Configuration

Project configuration is stored in:
`${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/config.yaml`

Run `configure` skill first if configuration is missing.

## Success Criteria

- All MCP queries are generated correctly for the project
- Quick stats table shows all key metrics
- Health indicators checklist is populated
- Confidence level is calculated with breakdown (when --confidence used)
- Blocked issues are listed with duration (when --blockers used)
- Risk factors are highlighted (when --risks used)
- Action items are generated based on status
- Output is concise and actionable

## Performance Targets

- **Skill execution**: < 500ms (generates templates)
- **MCP queries**: Depends on Linear API response time
- **Total dashboard**: < 5 seconds with cached Linear data
