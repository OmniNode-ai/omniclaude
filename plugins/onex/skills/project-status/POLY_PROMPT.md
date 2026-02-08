# Project Status — Poly Worker Prompt

You are generating a project health dashboard with metrics from Linear, including velocity calculations, blocker analysis, and ETA predictions with confidence levels.

## Arguments

- `PROJECT`: Project name or shortcut (MVP, Beta, Production, NodeReducer, EventBusAlignment, PipelineOptimization). Defaults to the configured default project (MVP).
- `SHOW_ALL`: "true" if `--all` flag provided (show all projects overview)
- `SHOW_BLOCKERS`: "true" if `--blockers` flag provided (include blocked issues detail)
- `SHOW_RISKS`: "true" if `--risks` flag provided (highlight risk factors)
- `SHOW_CONFIDENCE`: "true" if `--confidence` flag provided (detailed confidence breakdown)
- `JSON_OUTPUT`: "true" if `--json` flag provided

## Steps

### 1. Determine Target Project

Resolve the project from the provided argument or default. Use `config.yaml` as the source of truth for shortcut to project ID mappings. The table below is illustrative:

| Shortcut | Full Name | Project ID |
|----------|-----------|------------|
| MVP | MVP - OmniNode Platform Foundation | `e44ddbf4-b4c7-40dc-84fa-f402ec27b38e` |
| Beta | Beta - OmniNode Platform Hardening | `5db5e69e-a78d-4b6f-b78c-e59b929b9b4f` |
| Production | Production - OmniNode Platform Scale | `0fb63ff3-66cc-48e4-9c69-d64af5e4cf84` |
| NodeReducer | NodeReducer v1.0 - Contract-Driven FSM | `c2538d8b-79ca-47cd-b5f7-f21f9b76bd9d` |
| EventBusAlignment | Event Bus Alignment - OmniNode Platform | `b927f193-1c30-4707-b962-a6d240f705df` |
| PipelineOptimization | Synchronous Pipeline Optimization | `469d68a3-e5ce-48de-b9e9-80700290869e` |

If the project shortcut is not found in config, report an error listing available projects.

### 2. Run the Project Status Skill Script

Execute the project-status script:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/project-status \
  "${PROJECT}" \
  ${SHOW_ALL:+--all} \
  ${SHOW_BLOCKERS:+--blockers} \
  ${SHOW_RISKS:+--risks} \
  ${SHOW_CONFIDENCE:+--confidence} \
  ${JSON_OUTPUT:+--json} \
  2>&1
```

The script reads from `config.yaml` for project IDs, blocked labels, and thresholds.

### 3. Execute MCP Queries

The script outputs MCP queries to execute. Run them in this order:

**Query 1: All Project Issues (Progress)**

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    limit=500
)
```

Purpose: Calculate total issues and progress percentage.

**Query 2: Completed Issues (Velocity)**

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    state="Done",
    limit=100
)
```

Purpose: Filter results to last 7 days by `completedAt` field for velocity calculation.

**Query 3: Backlog Issues (Remaining Work)**

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    state="Backlog",
    limit=200
)
```

Purpose: Count remaining work for ETA calculation.

**Query 4: In Progress Issues**

```python
mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    state="In Progress",
    limit=50
)
```

Purpose: Show currently active work.

**For `--all` mode**, query all projects at once:

```python
mcp__linear-server__list_projects(
    member="me",
    limit=50
)
```

### 4. Calculate Metrics

After fetching data, compute these metrics:

**Progress**:
- Formula: `(completed_issues / total_issues) * 100`
- Status: On Track (>= expected), At Risk (< expected - 10%), Behind (< expected - 20%)

**Velocity**:
- Formula: `issues_completed_last_7_days / 7`
- Status: Stable (within 10% of average), Declining (> 10% below), Improving (> 10% above)

**Churn Ratio**:
- Formula: `(issues_added - issues_completed) / issues_completed`
- Healthy: < 20% (or negative = backlog shrinking)
- High: >= 20% (impacts confidence and ETA)

**Base ETA**:
- Formula: `remaining_issues / velocity`

**Adjusted ETA**:
- Negative churn: Reduce ETA by up to 10% (cautious)
- 0-20% churn: Increase ETA proportionally
- &gt; 20% churn: Increase ETA + downgrade confidence

**Confidence Level**:

| Level | Days Analyzed | CV (Coefficient of Variation) | Churn Impact |
|-------|---------------|-------------------------------|--------------|
| HIGH | >= 7 days | <= 15% | None |
| MEDIUM | 5-6 days | <= 30% | OR: HIGH with churn > 20% |
| LOW | < 5 days | > 30% | OR: MEDIUM with churn > 20% |

Use the velocity_calculator library functions when available:

```python
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/linear-insights")
from lib.velocity_calculator import (
    ConfidenceLevel,
    calculate_churn_ratio,
    calculate_adjusted_eta
)

churn = calculate_churn_ratio(issues_added=15, issues_completed=20)
eta = calculate_adjusted_eta(remaining=50, velocity=5.0, churn_ratio=churn)
confidence = ConfidenceLevel.from_metrics(days_analyzed=7, cv=0.12, churn_ratio=churn)
```

### 5. Detect Blockers

Issues are considered blocked if they have any of these labels:
- `blocked`
- `waiting`
- `on-hold`
- `needs-clarification`
- `dependent`

**Blocker status**:
- OK: 0 blocked issues
- Attention Needed: 1-2 blocked issues
- Critical: > 2 blocked issues

If `--blockers` flag is set, include detailed blocker information:

```python
# Get all project issues, then filter by blocked labels
issues = mcp__linear-server__list_issues(
    project="{PROJECT_ID}",
    limit=100
)
blocked_labels = ["blocked", "waiting", "on-hold", "needs-clarification", "dependent"]
blocked_issues = [i for i in issues if any(l in i.labels for l in blocked_labels)]
```

Output blocked issues in a table: Issue ID, Title, Blocked Since, Days Blocked, Downstream Impact.

### 6. Assess Risks (if `--risks`)

Evaluate four risk factors:

1. **High Priority Backlog**: Count issues in Backlog with priority Urgent (1) or High (2).
   - 0-2: Low risk, 3-5: Medium risk, > 5: High risk

2. **Velocity Drop**: Compare last 7 days velocity to previous 7 days.
   - < 10% drop: Low, 10-30%: Medium, > 30%: High

3. **ETA vs Target**: Compare calculated ETA to project target date.
   - ETA before target: Low, within 1 week: Medium, after target: High

4. **Backlog Churn**: Calculate churn ratio over last 7 days.
   - < 0% (shrinking): Low, 0-20%: Medium, > 20%: High

### 7. Provide Actionable Output

**Quick Stats Table**:

| Metric | Value | Status |
|--------|-------|--------|
| Progress | {completed}/{total} ({percent}%) | {On Track/At Risk/Behind} |
| Velocity | {N} issues/day | {Stable/Declining/Improving} |
| Blockers | {count} | {OK/Attention Needed/Critical} |
| Churn Ratio | {ratio}% | {Healthy/High} |
| Base ETA | {N} days | {date} |
| Adjusted ETA | {N} days | (churn-adjusted) |
| Confidence | {High/Medium/Low} | {N} days data, CV={X}% |

**Health Indicators Checklist**:

- [ ] Velocity stable (within 10% of average)
- [ ] ETA before target date
- [ ] Blocked issues = 0
- [ ] High priority backlog < 5
- [ ] Churn ratio < 20%

**Action Items** (generated based on status):

1. If blockers > 0: List blocked issues with resolution owners
2. If high priority backlog > 5: Prioritize or reassign urgent items
3. If ETA > target: Identify scope cuts or resource additions
4. If velocity declining: Investigate impediments
5. If churn > 20%: Review scope stability with stakeholders

## Expected Output Format

### Markdown Output (Default)

```
# Project Status: MVP

**Generated**: 2025-12-14 10:30:00
**Project**: MVP - OmniNode Platform Foundation
**Project ID**: `e44ddbf4-b4c7-40dc-84fa-f402ec27b38e`

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
```

### JSON Output (with `--json`)

```json
{
  "generated_at": "2025-12-14T10:30:00Z",
  "project": {
    "shortcut": "MVP",
    "name": "MVP - OmniNode Platform Foundation",
    "id": "e44ddbf4-b4c7-40dc-84fa-f402ec27b38e"
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

### All Projects Overview (with `--all`)

```
# All Projects Overview

| Project | Progress | Velocity | Blockers | ETA | Status |
|---------|----------|----------|----------|-----|--------|
| MVP | 45/100 (45%) | 5.2/day | 2 | Dec 26 | On Track |
| Beta | 10/50 (20%) | 2.1/day | 0 | Jan 15 | At Risk |
| Production | 0/30 (0%) | - | 0 | - | Not Started |
```

## Error Handling

| Error | Behavior |
|-------|----------|
| Project not found in config | Report error, list available projects |
| Config file missing | Report error, suggest running configure skill |
| No MCP data returned | Show template with placeholder values |
| Velocity calculation fails | Show "N/A" for velocity-dependent metrics |

## Performance Targets

- **Skill execution**: < 500ms (generates templates)
- **MCP queries**: Depends on Linear API response time
- **Total dashboard**: < 5 seconds with cached Linear data
