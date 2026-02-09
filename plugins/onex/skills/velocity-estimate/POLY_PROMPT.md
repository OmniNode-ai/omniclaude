# Velocity Estimate — Poly Worker Prompt

You are calculating project velocity from historical deep dive data and estimating milestone completion dates using the current Linear backlog.

## Arguments

- `PROJECT`: Project name or shortcut (MVP, Beta, Production, NodeReducer). Required unless `--all`.
- `ALL`: "true" if `--all` flag provided (show all milestones overview)
- `CONFIDENCE`: "true" if `--confidence` flag provided (include confidence intervals)
- `WEIGHTED`: "true" if `--weighted` flag provided (use weighted rolling average)
- `METHOD`: Velocity calculation method (default: `simple`). One of: `simple`, `priority`, `points`, `labels`, `cycle_time`.
- `HISTORY`: "true" if `--history` flag provided (show velocity history chart)
- `DEEP_DIVE_DIR`: Directory containing deep dive files (default: `${HOME}/Code/omni_save`)
- `JSON_OUTPUT`: "true" if `--json` flag provided

## Steps

### 1. Determine Target Project

If `--all` is specified, generate an overview of all milestones. Otherwise, resolve the project name:

| Shortcut | Full Name |
|----------|-----------|
| MVP / mvp | MVP - OmniNode Platform Foundation |
| Beta / beta | Beta - OmniNode Platform Hardening |
| Production / prod | Production - OmniNode Platform Scale |
| NodeReducer / nr | NodeReducer v1.0 - Contract-Driven FSM |

If neither `--project` nor `--all` is specified, show help/usage.

### 2. Run the Velocity Estimate Skill Script

Execute the velocity-estimate script with the provided flags:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/linear-insights/velocity-estimate \
  ${PROJECT:+--project "$PROJECT"} \
  ${ALL:+--all} \
  ${CONFIDENCE:+--confidence} \
  ${WEIGHTED:+--weighted} \
  ${METHOD:+--method "$METHOD"} \
  ${HISTORY:+--history} \
  ${DEEP_DIVE_DIR:+--deep-dive-dir "$DEEP_DIVE_DIR"} \
  ${JSON_OUTPUT:+--json} \
  2>&1
```

### 3. Parse Deep Dive Files for Historical Velocity

The script scans `${DEEP_DIVE_DIR}/*_DEEP_DIVE.md` files and extracts "Tickets Closed: N" from each.

**File naming convention**: `MONTH_DAY_YEAR_DEEP_DIVE.md` (e.g., `DECEMBER_9_2025_DEEP_DIVE.md`)

For each file:
1. Extract the date from the filename
2. Extract the ticket count from the "Tickets Closed" line
3. Accumulate total tickets and total days for velocity calculation

### 4. Analyze Velocity Output

The script provides these metrics:

**Velocity Metrics**:

| Metric | Description |
|--------|-------------|
| Days Analyzed | Number of deep dive files with data |
| Total Tickets Closed | Sum of all tickets from deep dives |
| Average Velocity | tickets/day (total / days) |
| Method | Calculation method used |
| Metric Grade | ETA-grade or Signal-grade |
| Confidence | HIGH, MEDIUM, or LOW |
| Std Deviation | Velocity variability (if library available) |
| CV | Coefficient of variation (std_dev / mean) |

**Metric Grades**:

| Method | Grade | Description | ETA Suitable |
|--------|-------|-------------|--------------|
| `simple` | Signal | Ticket count / days | No |
| `priority` | Signal | Priority-weighted points | No |
| `points` | ETA | Story point estimates | Yes |
| `labels` | Signal | Label-weighted velocity | No |
| `cycle_time` | ETA | Cycle time based | Yes |

Signal-grade methods should display a warning: "This method provides a dashboard signal only. For predictive ETA, use `points` or `cycle_time` method."

**Velocity Methods Detail**:

- **Simple** (default): Average tickets closed per day. Easy to understand.
- **Priority**: Priority-weighted points. Urgent=4x, High=3x, Normal=2x, Low=1x.
- **Points**: Uses story point estimates from issues.
- **Labels**: Label-weighted velocity based on complexity labels.
- **Cycle Time**: Based on actual time from In Progress to Done.

### 5. Calculate Weighted Velocity (if `--weighted`)

When `--weighted` is enabled, apply a recency-biased rolling average:

- **Bucket 1** (Last 7 days): 50% weight
- **Bucket 2** (Days 8-14): 30% weight
- **Bucket 3** (Days 15-30): 20% weight

```
weighted_velocity = (vel_7 * weight_7) + (vel_14 * weight_14) + (vel_30 * weight_30)
```

Where weights are normalized based on which buckets have data. If all data falls in a single bucket, weighted velocity equals simple average.

### 6. Calculate ETA from Linear Backlog

After getting velocity, query Linear for the current backlog:

```python
mcp__linear-server__list_issues(
    project="{PROJECT_NAME}",
    limit=250
)
```

Then calculate:
- **Total issues** in the project
- **Completed issues** (status = Done)
- **Remaining** = Total - Done
- **Base ETA** = Remaining / velocity (in days)
- **Target date** = today + ETA days

Generate an ETA table for various remaining counts:

| Remaining | Estimated Days | Target Date |
|-----------|----------------|-------------|
| 20 | 2 | 2025-12-16 |
| 30 | 3 | 2025-12-17 |
| 40 | 4 | 2025-12-18 |
| 50 | 5 | 2025-12-19 |
| 60 | 6 | 2025-12-20 |
| 70 | 7 | 2025-12-21 |

### 7. Determine Confidence Level

**Simple confidence** (based on days of data):

| Days Analyzed | Confidence |
|---------------|------------|
| 7+ days | High |
| 3-6 days | Medium |
| < 3 days | Low |

**Enhanced confidence** (when `--confidence` flag is set, uses VelocityCalculator library):

Uses three factors:
1. **Days Analyzed**: More data = higher confidence
2. **Coefficient of Variation (CV)**: Velocity predictability
   - CV <= 15%: Stable (HIGH eligible)
   - CV <= 30%: Variable (MEDIUM eligible)
   - CV > 30%: Unpredictable (LOW)
3. **Churn Impact**: High churn (> 20%) downgrades by one level

```python
from lib.velocity_calculator import ConfidenceLevel
confidence = ConfidenceLevel.from_metrics(
    days_analyzed=7,
    cv=0.12,
    churn_ratio=0.0
)
```

### 8. Show History (if `--history`)

Display a velocity history chart from deep dive data:

```
## Velocity History

| Date | Tickets | Velocity Chart |
|------|---------|----------------|
| DECEMBER_13_2025 | 12 | ██████ |
| DECEMBER_12_2025 | 8 | ████ |
| DECEMBER_11_2025 | 10 | █████ |
```

Each block represents approximately 2 tickets.

### 9. Provide Actionable Output

Summarize findings with:
- **Velocity**: Current team velocity with method and confidence level
- **Backlog Status**: Total, completed, remaining issues
- **ETA**: Estimated completion date with confidence interval
- **Recommendations**: Suggestions for improving accuracy (e.g., switch to ETA-grade methods)

## Expected Output Format

### Markdown Output (Default)

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
...

---

*Report generated by linear-insights velocity-estimate skill*
```

### JSON Output (`--json`)

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

### Weighted JSON (with `--weighted --json`)

Adds to the above:

```json
{
  "weighted_velocity": 10.5,
  "weighted_breakdown": {
    "bucket_7_days": {"tickets": 30, "days": 3, "weight": 0.50},
    "bucket_8_14_days": {"tickets": 15, "days": 2, "weight": 0.30},
    "bucket_15_30_days": {"tickets": 5, "days": 1, "weight": 0.20}
  }
}
```

## Dependencies

- Python 3 with `json` module
- Optional: `bc` for floating-point math (falls back to integer division)
- Optional: `jq` for JSON parsing (falls back to Python)
- Deep dive files in `${DEEP_DIVE_DIR}` matching `*_DEEP_DIVE.md` pattern
- `lib/velocity_calculator.py` for enhanced metrics (graceful fallback if unavailable)

## Error Handling

| Error | Behavior |
|-------|----------|
| No deep dive files found | Report "No deep dive data found in {dir}" |
| Neither `--project` nor `--all` | Show help/usage |
| Invalid method name | Report error listing valid methods |
| VelocityCalculator import fails | Fallback to simple calculation |
| `bc` not available | Fallback to integer division |
| `jq` not available | Fallback to Python JSON parsing |

## Performance Targets

- **Velocity calculation**: <2 seconds
- **Full report with history**: <5 seconds
- **JSON output**: <1 second
