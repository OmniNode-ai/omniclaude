---
description: Record a friction event for a skill process blocker
mode: full
version: "1.0.0"
level: basic
debug: false
category: observability
tags: [friction, observability, pipeline]
author: omninode
args:
  - name: skill
    description: "Skill name where friction occurred (e.g., integration_sweep)"
    required: true
  - name: surface
    description: "Error class: <category>/<specific> — allowed categories: kafka, ci, config, permissions, linear, network, auth, tooling, unknown"
    required: true
  - name: severity
    description: "low | medium | high (default: medium)"
    required: false
  - name: description
    description: "One-line description of the blocker"
    required: false
  - name: ticket_id
    description: "Linear ticket context — if omitted, records with context_ticket_id=None"
    required: false
---

# Record Friction

Records a friction event to `$ONEX_STATE_DIR/state/friction/friction.ndjson`.

Friction events are the deterministic backbone of the friction tracking system
(OMN-5442). Use this skill when a skill run is blocked by an unresolved external
issue (missing Kafka topic, CI misconfiguration, permission denied, etc.).

## Usage

```
/record-friction --skill integration_sweep --surface kafka/missing-topic --severity medium
/record-friction --skill gap --surface ci/missing-workflow --severity low --description "Workflow file not found in repo"
/record-friction --skill pr_polish --surface linear/api-timeout --severity high --ticket_id OMN-5132
```

## Surface Taxonomy

Format: `<category>/<specific>` where category is one of:
`kafka` | `ci` | `config` | `permissions` | `linear` | `network` | `auth` | `tooling` | `unknown`

Unknown categories are normalized to `unknown/<mangled>`.

## Severity Thresholds

| Severity | Weight | When to use |
|----------|--------|-------------|
| `low`    | 1      | Minor, easily worked around |
| `medium` | 3      | Significant degradation, multi-step workaround |
| `high`   | 9      | Data loss, security issue, complete unavailability |

A single `high` event already crosses the score threshold (9) and will create a
Linear ticket on next `/friction-triage` run.

## Implementation

**Step 1: Resolve ticket context (nullable)**

```python
import json
import os
from pathlib import Path

ticket_id = "{{ticket_id}}" or None
# If not provided, attempt to read from session state
if not ticket_id:
    session_file = Path.home() / ".claude" / "state" / "session.json"
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text())
            ticket_id = data.get("active_ticket_id") or None
        except Exception:
            pass
    # ticket_id may remain None — this is valid; report to user
```

**Step 2: Record the friction event**

```python
import sys
import os
from datetime import UTC, datetime

plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
shared_path = f"{plugin_root}/skills/_shared"
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from friction_recorder import FrictionEvent, FrictionSeverity, record_friction

sev_str = "{{severity}}" or "medium"
try:
    severity = FrictionSeverity(sev_str)
except ValueError:
    severity = FrictionSeverity.MEDIUM

event = FrictionEvent(
    skill="{{skill}}",
    surface="{{surface}}",
    severity=severity,
    description="{{description}}" or "",
    context_ticket_id=ticket_id,
    session_id=os.environ.get("CLAUDE_SESSION_ID", ""),
    timestamp=datetime.now(UTC),
)
record_friction(event, emit_kafka=True)

# Capture normalized values for report
normalized_surface = event.surface
```

**Step 3: Report result to user**

```
Friction recorded:
  skill:    {{skill}}
  surface:  <normalized_surface>
  severity: <severity> (weight: <weight>)
  ticket:   <ticket_id or "(none — no ticket context resolved)">

Registry: $ONEX_STATE_DIR/state/friction/friction.ndjson

<if severity == high>
Note: A single 'high' event (score=9) crosses the threshold. Run /friction-triage
to escalate this surface to a Linear ticket immediately.
</if>
```

## Relationship to friction_triage

`/record-friction` appends individual events. `/friction-triage` reads the
registry, aggregates by `skill:surface` over 30 days, and creates Linear tickets
when `count >= 3` OR `severity_score >= 9`.

## Registry Format

Each line in `$ONEX_STATE_DIR/state/friction/friction.ndjson` is a JSON object:

```json
{
  "skill": "integration_sweep",
  "surface": "kafka/missing-topic",
  "severity": "medium",
  "description": "Topic onex.evt.foo.v1 not found",
  "context_ticket_id": "OMN-5132",
  "session_id": "abc123",
  "timestamp": "2026-03-19T12:00:00+00:00"
}
```
