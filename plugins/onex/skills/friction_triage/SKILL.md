---
description: Read friction registry, escalate surfaces crossing threshold to Linear tickets
mode: full
version: "1.0.0"
level: intermediate
debug: false
category: observability
tags: [friction, triage, linear]
author: omninode
args:
  - name: dry_run
    description: "If true, report what would be created without creating tickets (default: false)"
    required: false
  - name: window_days
    description: "Rolling window in days (default: 30)"
    required: false
---

# Friction Triage

Reads `$ONEX_STATE_DIR/state/friction/friction.ndjson`, aggregates events by
`skill:surface` over a rolling window, and creates Linear tickets for surfaces
where `count >= 3` OR `severity_score >= 9`.

## Usage

```
/friction-triage
/friction-triage --dry_run true
/friction-triage --window_days 7
```

## Thresholds

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Count-based | count >= 3 | Recurring nuisance (3x low = score 3, still noisy) |
| Score-based | severity_score >= 9 | One `high` event OR three `medium` events |

## Implementation

**Step 1: Load and aggregate the registry**

```python
import sys
import os
from pathlib import Path

plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
shared_path = f"{plugin_root}/skills/_shared"
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from friction_aggregator import aggregate_friction, THRESHOLD_COUNT, THRESHOLD_SCORE, WINDOW_DAYS

window_days = int("{{window_days}}" or WINDOW_DAYS)
dry_run = "{{dry_run}}".lower() == "true"

aggregates = aggregate_friction(window_days=window_days)
crossed = [a for a in aggregates if a.threshold_crossed]

print(f"{len(aggregates)} surfaces tracked over {window_days} days")
print(f"{len(crossed)} crossed threshold (count>={THRESHOLD_COUNT} OR score>={THRESHOLD_SCORE})")
```

**Step 2: Deduplicate against existing Linear tickets**

For each crossed aggregate, check if an open ticket already exists using
`mcp__linear-server__list_issues` with the stable dedup marker
`friction_surface_key: {surface_key}` in the description.

```python
# Search for existing open ticket with this surface key
existing = mcp__linear-server__list_issues(
    query=f"[Friction] {agg.surface_key}",
    state="Todo,In Progress,Backlog",
    team="Omninode",
)

# Also check description for the stable dedup marker
for issue in existing.issues:
    if f"friction_surface_key: {agg.surface_key}" in (issue.description or ""):
        # Skip — open ticket already exists
        skip = True
        break
```

**Step 3: Create Linear ticket for new surfaces**

Use `mcp__linear-server__save_issue` for each untracked crossing:

```python
# Determine crossing reason
if agg.count >= THRESHOLD_COUNT and agg.severity_score >= THRESHOLD_SCORE:
    reason = f"count={agg.count} AND score={agg.severity_score}"
elif agg.count >= THRESHOLD_COUNT:
    reason = f"count={agg.count} (>= {THRESHOLD_COUNT})"
else:
    reason = f"score={agg.severity_score} (>= {THRESHOLD_SCORE})"

# Sample descriptions (up to 3 most recent)
sample_descriptions = "\n".join(
    f"- {d}" for d in agg.descriptions[-3:]
) if agg.descriptions else "(no descriptions recorded)"

ticket_context = f"Related ticket: {agg.most_recent_ticket}" if agg.most_recent_ticket else ""

mcp__linear-server__save_issue(
    title=f"[Friction] {agg.surface_key} — {agg.count} occurrences / score {agg.severity_score} ({window_days}d)",
    team="Omninode",
    project="Active Sprint",
    priority=2,  # High — friction crosses threshold
    description=f"""## Friction Surface Escalation

friction_surface_key: {agg.surface_key}

**Skill**: `{agg.skill}`
**Surface**: `{agg.surface}`
**Threshold crossed**: {reason}
**Rolling window**: {window_days} days
{ticket_context}

## Sample Descriptions

{sample_descriptions}

## Next Steps

1. Investigate root cause of `{agg.surface}` friction in skill `{agg.skill}`
2. Fix the underlying blocker if possible
3. If not fixable, add explicit handling / fallback in the skill
4. Close this ticket when the surface stops crossing threshold for one full window

## Friction Tracking

This ticket was auto-created by `/friction-triage` (OMN-5442).
To query current state: `/friction-triage --dry_run true`
""",
)
```

**Step 4: Report summary**

```
Friction Triage Report ({window_days}-day window)
=================================================

Surfaces tracked: {len(aggregates)}
Threshold crossings: {len(crossed)}
New tickets created: {tickets_created}
Skipped (already tracked): {tickets_skipped}

| Surface Key | Count | Score | Threshold | Action |
|-------------|-------|-------|-----------|--------|
| gap:ci/missing-workflow | 4 | 4 | count>=3 | Created OMN-XXXX |
| integration_sweep:kafka/missing-topic | 1 | 9 | score>=9 | Created OMN-XXXX |
| pr_polish:linear/api-timeout | 2 | 6 | (below) | — |

Registry: $ONEX_STATE_DIR/state/friction/friction.ndjson
```

## Dedup Marker

Every ticket created by this skill includes the stable marker:

```
friction_surface_key: <surface_key>
```

This marker is checked before creating new tickets to prevent duplicates.
The marker is intentionally in the description (not the title) so it survives
title edits.

## Relationship to record_friction

`/record-friction` appends individual events. `/friction-triage` performs the
rollup and escalation step. Run `/friction-triage` periodically (daily or
after a batch of skill runs) to convert accumulated friction into actionable
Linear tickets.
