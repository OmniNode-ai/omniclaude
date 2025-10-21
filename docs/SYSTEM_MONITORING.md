# System Monitoring & Detection Tracking

This document describes the OmniClaude system monitoring and detection failure tracking capabilities.

## Overview

Three new tools provide comprehensive system observability:

1. **Markdown Dashboard** - Auto-generated system health metrics
2. **Detection Failure Tracking** - Captures missed/failed agent detections
3. **Database Analysis** - Raw data queries for deep investigation

## Quick Start

### Web Dashboard (Recommended!)

```bash
# Start web dashboard (opens in browser automatically)
./start-dashboard.sh

# Or manually
cd claude_hooks/tools && python3 dashboard_web.py
# Then open http://localhost:8000 in your browser
```

**Features:**
- 🌐 Modern web interface with real-time updates
- 📊 Live metrics updated every 5 seconds via Server-Sent Events
- 📱 Responsive design that works on any screen size
- 🎨 Beautiful gradient health cards and color-coded metrics
- ⚡ No page refreshes needed - everything updates live

### Markdown Dashboard

```bash
# Generate markdown dashboard
python3 claude_hooks/tools/system_dashboard_md.py --file

# View dashboard
cat SYSTEM_DASHBOARD.md

# Or print to console
python3 claude_hooks/tools/system_dashboard_md.py
```

### Terminal Dashboard (TUI)

```bash
# Display colorful TUI dashboard (adaptive multi-column layout)
python3 claude_hooks/tools/dashboard_tui.py
```

### View Detection Failures

```bash
# View unreviewed detection failures
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM agent_detection_failures_to_review;"

# Get failure statistics
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM get_detection_failure_stats(24);"
```

## Terminal Dashboard (TUI)

### Features

- **Adaptive Multi-Column Layout**: Automatically adjusts to terminal size
  - **< 120 columns**: Single-column layout (narrow terminals)
  - **120-179 columns**: 2-column layout (medium-wide displays)
  - **180+ columns**: 3-column layout (ultra-wide monitors)
- **Real-Time Metrics**: System health, routing statistics, cache performance
- **Color-Coded Status**: Health indicators with ANSI colors
- **Recent Activity Timeline**: Last 10-15 routing decisions with timestamps
- **System Issues Detection**: Automatic identification of critical problems
- **Agent Statistics**: Detailed performance breakdown by agent
- **No Scrolling**: Content automatically fits terminal height

### Multi-Column Layouts

**Single-Column (< 120 cols):**
```
┌─────────────────────┐
│ Header              │
├─────────────────────┤
│ System Health       │
│ Quick Metrics       │
│ Issues              │
│ Recent Activity     │
│ Agent Details       │
│ Top Agents          │
│ Alerts              │
└─────────────────────┘
```

**2-Column (120-179 cols):**
```
┌──────────────────┬──────────────────┐
│ Header (full width)                 │
├──────────────────┼──────────────────┤
│ System Health    │ Recent Activity  │
│ Quick Metrics    │ (12 items)       │
│ Issues           │ Agent Details    │
│                  │ (8 items)        │
│                  │ Top Agents       │
└──────────────────┴──────────────────┘
```

**3-Column (180+ cols):**
```
┌────────┬────────┬────────┐
│ Header (full width)       │
├────────┼────────┼────────┤
│ Health │ Issues │ Recent │
│ Metrics│ Top    │ Activity│
│ Alerts │ Agents │ (15)   │
│        │ System │ Agent  │
│        │ Info   │ Details│
│        │        │ (10)   │
└────────┴────────┴────────┘
```

### Usage

```bash
# Run TUI dashboard
python3 claude_hooks/tools/dashboard_tui.py

# On wide monitors (33"+), you'll see 2-3 column layout automatically
# Terminal size and layout mode shown in header
```

## Markdown Dashboard

### Features

- **System Health Score**: Overall health rating (0-100)
- **Quick Metrics**: Routing decisions, confidence, hook events, cache hit rate
- **Detection Quality**: Breakdown by confidence levels
- **Top Agents**: Most frequently selected agents
- **Recent Errors**: Latest system errors
- **Alerts**: Critical issues requiring attention

### Example Output

```markdown
# 🎯 OmniClaude System Dashboard

**Generated**: 2025-10-19 20:54:21 UTC
**Period**: Last 24 hours

## System Health

🔴 **❌ POOR** (Health Score: 48.3/100)

### Quick Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Routing Decisions | **3** | ✅ |
| Avg Confidence | **96.7%** | ✅ |
| Avg Routing Time | **327ms** | ⚠️ |
| Hook Events | **11** (0 processed, 11 pending) | ⚠️ |
| Cache Hit Rate | **0.0%** | ❌ |

### 🚨 Alerts

- 🔴 **CRITICAL**: Cache system not functioning (0% hit rate)
```

### Health Score Calculation

```
Overall Score =
  Routing Health (50%) +
  Hook Processing (30%) +
  Cache Performance (20%)
```

### Status Thresholds

- **Excellent** (🟢): 90-100
- **Good** (🟡): 75-89
- **Fair** (🟠): 60-74
- **Poor** (🔴): 0-59

## Detection Failure Tracking

### Database Schema

The `agent_detection_failures` table tracks:

- **No detection**: Agent router found no match
- **Low confidence**: Detection below threshold (<85%)
- **Wrong agent**: User indicated incorrect agent selected
- **Timeout**: Detection timed out
- **Error**: Detection system error

### Key Fields

```sql
- detection_status       -- Type of failure
- detected_agent         -- Agent that was detected (if any)
- detection_confidence   -- Confidence score (0-1)
- failure_reason         -- Why detection failed
- user_prompt            -- The user's prompt
- trigger_matches        -- Triggers evaluated
- capability_scores      -- Capability match scores
- reviewed              -- Manual review status
- pattern_updated        -- Whether patterns were improved
```

### Query Examples

```sql
-- View unreviewed failures
SELECT * FROM agent_detection_failures_to_review;

-- View low confidence detections
SELECT * FROM agent_low_confidence_detections;

-- Get failure patterns
SELECT * FROM agent_detection_failure_patterns;

-- Get statistics (last 24 hours)
SELECT * FROM get_detection_failure_stats(24);

-- Mark failure as reviewed
SELECT mark_detection_failure_reviewed(
  1,  -- failure ID
  'admin',  -- reviewed by
  'agent-workflow-coordinator',  -- expected agent
  'Should have detected coordinator'  -- notes
);

-- Mark pattern as improved
SELECT mark_pattern_improved(
  1,  -- failure ID
  'trigger_added',  -- update type
  '{"trigger": "workflow coordinator", "confidence_improvement": 0.15}'::jsonb
);
```

### Python Integration

```python
from claude_hooks.lib.detection_failure_tracker import get_failure_tracker

tracker = get_failure_tracker()

# Record a failure
tracker.record_failure(
    correlation_id=uuid.uuid4(),
    user_prompt="Help me coordinate this workflow",
    detection_status="low_confidence",
    detected_agent="agent-task-manager",
    detection_confidence=0.72,
    failure_reason="Confidence below threshold",
    trigger_matches=[...],
    capability_scores={...}
)

# Get recent failures
failures = tracker.get_recent_failures(limit=50, unreviewed_only=True)

# Get statistics
stats = tracker.get_failure_stats(hours=24)
print(f"Total failures: {stats['total_failures']}")
print(f"No detection: {stats['no_detection_count']}")
print(f"Low confidence: {stats['low_confidence_count']}")
```

## Database Migrations

### Apply Migration

```bash
# Apply detection failures tracking migration
./scripts/apply_migration.sh agents/migrations/001_agent_detection_failures.sql
```

The migration creates:
- `agent_detection_failures` table
- 8 indexes for efficient querying
- 3 views for common queries
- 4 helper functions

### Views

1. **agent_detection_failure_patterns**: Aggregated failure patterns
2. **agent_detection_failures_to_review**: Unreviewed failures
3. **agent_low_confidence_detections**: Detections with <85% confidence

### Functions

1. **mark_detection_failure_reviewed()**: Mark failure as reviewed
2. **mark_pattern_improved()**: Record pattern improvements
3. **find_similar_detection_failures()**: Find similar prompts
4. **get_detection_failure_stats()**: Get statistics

## Workflow: Improving Detection

### 1. Identify Issues

```bash
# Generate dashboard
python3 claude_hooks/tools/system_dashboard_md.py --file

# Check detection quality section
# Look for "Poor" confidence detections
```

### 2. Review Failures

```sql
-- Get unreviewed failures
SELECT * FROM agent_detection_failures_to_review LIMIT 10;

-- Get low confidence cases
SELECT * FROM agent_low_confidence_detections;
```

### 3. Analyze Patterns

```sql
-- View failure patterns
SELECT * FROM agent_detection_failure_patterns
ORDER BY failure_count DESC;

-- Check specific agent misfires
SELECT
  user_prompt,
  detection_confidence,
  failure_reason
FROM agent_detection_failures
WHERE detected_agent = 'agent-workflow-coordinator'
  AND detection_status = 'low_confidence'
ORDER BY detection_confidence ASC
LIMIT 20;
```

### 4. Update Agent Definitions

Based on failures, update agent configuration:

```yaml
# agents/configs/agent-workflow-coordinator.yaml
triggers:
  - "coordinate workflow"      # Add missing trigger
  - "multi-step task"          # Add missing trigger
  - "orchestrate"              # Common in failed prompts

capabilities:
  - "workflow_coordination"     # Enhance capability matching
  - "task_orchestration"
```

### 5. Mark as Reviewed

```sql
-- Mark failures as reviewed and improved
SELECT mark_detection_failure_reviewed(
  42,  -- failure ID
  'developer',
  'agent-workflow-coordinator',
  'Added missing trigger: coordinate workflow'
);

SELECT mark_pattern_improved(
  42,
  'trigger_added',
  '{"trigger": "coordinate workflow", "expected_improvement": "+15% confidence"}'::jsonb
);
```

### 6. Validate Improvement

```bash
# Test with similar prompt
# Monitor detection confidence in next dashboard generation

python3 claude_hooks/tools/system_dashboard_md.py --file
```

## Automation

### Cron Job for Dashboard

```bash
# Add to crontab
# Generate dashboard every hour
0 * * * * cd /path/to/omniclaude && python3 claude_hooks/tools/system_dashboard_md.py --file

# Or every 5 minutes
*/5 * * * * cd /path/to/omniclaude && python3 claude_hooks/tools/system_dashboard_md.py --file
```

### Alerting

```bash
# Check for critical issues and send alerts
#!/bin/bash
python3 claude_hooks/tools/system_dashboard_md.py --file

# Check for critical alerts in dashboard
if grep -q "CRITICAL" SYSTEM_DASHBOARD.md; then
    # Send notification (Slack, email, etc.)
    echo "Critical system issues detected" | mail -s "OmniClaude Alert" ops@example.com
fi
```

## Metrics Reference

### Dashboard Metrics

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Routing Decisions | >0 | - | 0 (no activity) |
| Avg Confidence | ≥85% | 70-84% | <70% |
| Avg Routing Time | <100ms | 100-500ms | >500ms |
| Hook Events Pending | 0 | <100 | ≥100 |
| Cache Hit Rate | ≥60% | 30-59% | <30% |

### Detection Quality Levels

- **Excellent** (≥95%): High confidence, optimal routing
- **Good** (85-94%): Acceptable confidence
- **Fair** (70-84%): Review recommended
- **Poor** (<70%): Requires investigation and improvement

## Troubleshooting

### Dashboard Issues

**Error: "column does not exist"**
- Check database schema matches expected column names
- Run migrations: `./scripts/apply_migration.sh agents/migrations/001_agent_detection_failures.sql`

**Error: "relation does not exist"**
- Ensure all tables exist in database
- Check database connection settings

### Detection Tracking Issues

**No failures recorded**
- Check hooks are executing
- Verify failure tracker is instantiated
- Ensure detection confidence threshold is set correctly

**Too many false positives**
- Adjust low_confidence_threshold (default: 0.85)
- Review trigger matching patterns
- Check capability scoring weights

## Architecture

### Components

```
┌─────────────────────────────────────────┐
│                                         │
│  User Prompt → Agent Detection         │
│                    ↓                    │
│         Detection Result                │
│          ↓              ↓               │
│    Success         Failure              │
│      ↓                ↓                 │
│  Routing        Record Failure          │
│  Decision       in Database             │
│      ↓                ↓                 │
│  Execute        Manual Review           │
│                    ↓                    │
│              Pattern Improvement        │
│                    ↓                    │
│              Update Definitions         │
│                                         │
└─────────────────────────────────────────┘
```

### Database Schema

```
agent_detection_failures
├── Detection Info
│   ├── correlation_id (UUID)
│   ├── user_prompt (TEXT)
│   ├── detection_status (ENUM)
│   ├── detected_agent (VARCHAR)
│   └── detection_confidence (DECIMAL)
├── Failure Analysis
│   ├── failure_reason (TEXT)
│   ├── failure_category (VARCHAR)
│   └── expected_agent (VARCHAR)
├── Detection Metadata
│   ├── trigger_matches (JSONB)
│   ├── capability_scores (JSONB)
│   └── fuzzy_match_results (JSONB)
└── Review & Improvement
    ├── reviewed (BOOLEAN)
    ├── reviewed_at (TIMESTAMP)
    ├── pattern_updated (BOOLEAN)
    └── pattern_update_details (JSONB)
```

## See Also

- [Agent Framework Documentation](../agents/AGENT_FRAMEWORK.md)
- [Hook System Documentation](../claude_hooks/README.md)
- [Database Schema](../agents/migrations/)
- [System Dashboard Generator](../claude_hooks/tools/system_dashboard_md.py)
- [Detection Failure Tracker](../claude_hooks/lib/detection_failure_tracker.py)
