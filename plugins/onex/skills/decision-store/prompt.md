# decision-store — Operational Agent Prompt

You are executing the `decision-store` skill. Follow these instructions exactly.

---

## Overview

The decision-store skill manages architectural and design decisions for the OmniNode
platform. You will perform one of three sub-operations based on the invocation:

- `record` — persist a new decision, check for conflicts, gate on HIGH severity
- `query` — retrieve and display existing decisions with optional filters
- `check-conflicts` — dry-run structural conflict check without writing

Read the sub-operation from the skill arguments. If none is specified, ask the user.

---

## Pre-conditions

Before executing any sub-operation, verify:

1. The worktree is on the correct branch (not `main`).
2. `LLM_DEEPSEEK_R1_URL` is set (see `~/.claude/CLAUDE.md` for the endpoint URL).
3. `NodeDecisionStoreEffect` (OMN-2765) and `NodeDecisionStoreQueryCompute` (OMN-2767)
   are available in the current environment.

---

## Sub-operation: `record`

### Step 1 — Collect required fields

Gather from arguments or ask the user:

| Field | Type | Required | Notes |
|---|---|---|---|
| `--type` | enum | yes | TECH_STACK_CHOICE, DESIGN_PATTERN, API_CONTRACT, SCOPE_BOUNDARY, REQUIREMENT_CHOICE |
| `--domain` | string | yes | e.g. "infrastructure", "api", "frontend" |
| `--layer` | enum | yes | architecture, design, planning |
| `--services` | list | no | comma-separated; omit = platform-wide |
| `--summary` | string | yes | one-line summary |
| `--rationale` | string | yes | full decision rationale |
| `--dry-run` | flag | no | if set, run checks but do not write |

### Step 2 — Structural conflict check

```python
from detect_conflicts import structural_confidence, compute_severity, check_conflicts_batch, DecisionEntry

candidate = DecisionEntry(
    decision_type=args.type,
    scope_domain=args.domain,
    scope_layer=args.layer,
    scope_services=args.services or [],
)

# Fetch existing entries in same domain via NodeDecisionStoreQueryCompute
existing = query_entries(domain=args.domain)

conflicts = check_conflicts_batch(candidate, existing)
```

### Step 3 — Evaluate conflict severity

For each conflict returned by `check_conflicts_batch`:

- If `base_severity == "HIGH"`: **stop and post Slack gate** (see Conflict Resolution Gate below)
- If `base_severity == "MEDIUM"` and `needs_semantic == True`: fire async semantic check
- If `base_severity == "LOW"`: log and continue
- If `needs_semantic == True`: fire async `semantic_check_async()` — do NOT await in MVP

### Step 4 — Write decision (if not dry-run)

```python
# Call NodeDecisionStoreEffect
result = NodeDecisionStoreEffect.execute_effect({
    "decision_type": args.type,
    "scope_domain": args.domain,
    "scope_layer": args.layer,
    "scope_services": args.services or [],
    "summary": args.summary,
    "rationale": args.rationale,
})
entry_id = result.entry_id
```

### Step 5 — Emit conflict events

For each conflict detected in Step 2:

```python
from omniclaude.hooks.topics import TopicBase

# Emit decision-conflict-status-changed.v1 for each new (OPEN) conflict
emit_event(TopicBase.DECISION_CONFLICT_STATUS_CHANGED, {
    "conflict_id": conflict_id,
    "decision_a_id": candidate_id,
    "decision_b_id": conflict.entry.id,
    "old_status": None,
    "new_status": "OPEN",
    "resolution_note": None,
    "resolved_by": None,
    "resolved_at": None,
    "emitted_at": now_iso8601(),
})
```

### Step 6 — Report

Output a summary:
- Decision written (or dry-run note)
- Conflicts found: count, severity breakdown
- Any Slack gate posted

---

## Sub-operation: `query`

### Step 1 — Collect filter params

```
--domain <domain>           # optional
--layer <layer>             # optional
--type <decision_type>      # optional
--service <service_name>    # optional
--status open|resolved|dismissed  # optional; default: all
--cursor <token>            # optional; for pagination
--limit <n>                 # optional; default: 20
```

### Step 2 — Call NodeDecisionStoreQueryCompute

```python
result = NodeDecisionStoreQueryCompute.execute_compute({
    "filters": {
        "domain": args.domain,
        "layer": args.layer,
        "decision_type": args.type,
        "service": args.service,
        "status": args.status,
    },
    "cursor": args.cursor,
    "limit": args.limit or 20,
})
entries = result.entries
next_cursor = result.next_cursor
```

### Step 3 — Display results

Format as a table:

```
ID          | Type               | Domain         | Layer        | Services           | Conflicts | Status
------------|--------------------|-----------     |--------------|--------------------|-----------|---------
abc123      | TECH_STACK_CHOICE  | infrastructure | architecture | platform-wide      | 2 HIGH    | OPEN
def456      | DESIGN_PATTERN     | api            | design       | auth-service       | 0         | -
```

If `next_cursor` is set:
```
[Next page: use --cursor <token>]
```

---

## Sub-operation: `check-conflicts`

Dry-run only. Never writes. Never emits events. Never fires semantic check.

### Step 1 — Collect fields

Same as `record` Step 1, but `--rationale` is optional.

### Step 2 — Run structural check

```python
from detect_conflicts import check_conflicts_batch, DecisionEntry

candidate = DecisionEntry(
    decision_type=args.type,
    scope_domain=args.domain,
    scope_layer=args.layer,
    scope_services=args.services or [],
)
existing = query_entries(domain=args.domain)
conflicts = check_conflicts_batch(candidate, existing)
```

### Step 3 — Report results

```
Conflict check (dry-run) — no writes performed.

Found N potential conflicts:

  Entry ID: abc123
    Structural confidence: 0.90
    Base severity: HIGH
    Needs semantic check: yes (would run asynchronously if this were a record)
    Conflict reason: both platform-wide, same domain + layer

  Entry ID: def456
    Structural confidence: 0.40
    Base severity: LOW
    Needs semantic check: no (below 0.6 threshold)

Summary:
  HIGH: 1  MEDIUM: 0  LOW: 1  (structural only — no semantic check in dry-run)
```

---

## Conflict Resolution Gate (Slack)

When `record` detects a HIGH severity conflict, post to the `slack-gate` skill with
`HIGH_RISK` tier and pause the pipeline.

### Integration with slack-gate skill

HIGH conflicts trigger the existing `slack-gate` skill using the `HIGH_RISK` tier interface.
See `omniclaude/plugins/onex/skills/slack-gate/SKILL.md` for the full gate interface.

The gate message format:

```
[HIGH CONFLICT] Decision conflict detected — pipeline paused.

Decision A: <summary_a> (<entry_id_a>)
Decision B: <summary_b> (<entry_id_b>)
Confidence: <confidence>
Severity: HIGH
Layer: <layer> | Domain: <domain>

Reply to resolve:
  proceed <conflict_id> [note]  — mark RESOLVED and continue
  hold    <conflict_id>          — stay paused
  dismiss <conflict_id>          — mark DISMISSED permanently
```

### Slack Command Grammar

Operators resolve conflicts by replying to the Slack gate thread. The command grammar is:

```
Format:  <action> <conflict_id> [note]

Actions:
  proceed <id> [note]  — mark RESOLVED, record approver + note, continue pipeline
  hold    <id>         — pipeline stays paused (gate remains open, no status change)
  dismiss <id>         — mark DISMISSED permanently (never resurfaces for this pair)
```

**Behavior per action:**

**`proceed <conflict_id> [note]`**
- Sets `conflict.status = RESOLVED`
- Sets `conflict.resolved_by = <slack_user_id>`
- Sets `conflict.resolved_at = <timestamp>`
- Sets `conflict.resolution_note`:
  - If note provided: `resolution_note = <provided text>`
  - If no note: `resolution_note = "proceed (no note provided)"`
- Emits `decision-conflict-status-changed.v1` (OPEN → RESOLVED)
- Resumes the pipeline

**`hold <conflict_id>`**
- Pipeline stays paused
- No status change on the conflict record
- No event emitted
- Gate remains open waiting for another reply

**`dismiss <conflict_id>`**
- Sets `conflict.status = DISMISSED`
- This pair will NEVER trigger another Slack gate again, even if re-recorded
- Emits `decision-conflict-status-changed.v1` (OPEN → DISMISSED)
- Resumes the pipeline (dismissed = acknowledged, not a blocker)

**Unrecognized command:**
- Re-prompt operator with usage (do not change any state)

**Multiple conflicts:**
- Each conflict must be resolved separately in its own reply before the pipeline resumes
- All conflicts with status OPEN block the pipeline; RESOLVED and DISMISSED do not

### Status Change Event Emission

Emit `TopicBase.DECISION_CONFLICT_STATUS_CHANGED` on EVERY status transition:

- `OPEN → RESOLVED` (via `proceed`)
- `OPEN → DISMISSED` (via `dismiss`)

The topic constant is imported from `omniclaude/src/omniclaude/hooks/topics.py`:

```python
from omniclaude.hooks.topics import TopicBase

# TopicBase.DECISION_CONFLICT_STATUS_CHANGED resolves to:
# "onex.evt.omniclaude.decision-conflict-status-changed.v1"
```

**Event payload:**

```python
emit_event(TopicBase.DECISION_CONFLICT_STATUS_CHANGED, {
    "conflict_id": conflict_id,           # UUID of the conflict record
    "old_status": "OPEN",                 # Previous status
    "new_status": "RESOLVED",            # New status ("RESOLVED" or "DISMISSED")
    "resolved_by": slack_user_id,        # Slack user ID who sent the command
    "resolved_at": now_iso8601(),        # ISO8601 timestamp
    "resolution_note": resolution_note,  # Text note or "proceed (no note provided)"
})
```

For `dismiss`, `resolution_note` is `None` (no note is recorded for dismissals).

**Emission is mandatory:** Do not skip event emission on status transitions. The event bus
is the authoritative record of conflict lifecycle for downstream consumers (omnidash, audit).

### Resolution Processing (Full Flow)

```python
from omniclaude.hooks.topics import TopicBase

def process_slack_reply(reply_text: str, slack_user_id: str) -> ReplyResult:
    tokens = reply_text.strip().split(maxsplit=2)
    if len(tokens) < 2:
        return ReplyResult(action="reprompt", message=USAGE_TEXT)

    action = tokens[0].lower()
    conflict_id = tokens[1]
    note = tokens[2] if len(tokens) > 2 else None

    if action == "proceed":
        resolution_note = note or "proceed (no note provided)"
        update_conflict(
            conflict_id,
            status="RESOLVED",
            resolved_by=slack_user_id,
            resolved_at=now_iso8601(),
            resolution_note=resolution_note,
        )
        emit_event(TopicBase.DECISION_CONFLICT_STATUS_CHANGED, {
            "conflict_id": conflict_id,
            "old_status": "OPEN",
            "new_status": "RESOLVED",
            "resolved_by": slack_user_id,
            "resolved_at": now_iso8601(),
            "resolution_note": resolution_note,
        })
        return ReplyResult(action="proceed", conflict_id=conflict_id)

    elif action == "hold":
        # No state change, no event
        return ReplyResult(action="hold", conflict_id=conflict_id)

    elif action == "dismiss":
        update_conflict(
            conflict_id,
            status="DISMISSED",
            resolved_by=slack_user_id,
            resolved_at=now_iso8601(),
            resolution_note=None,
        )
        emit_event(TopicBase.DECISION_CONFLICT_STATUS_CHANGED, {
            "conflict_id": conflict_id,
            "old_status": "OPEN",
            "new_status": "DISMISSED",
            "resolved_by": slack_user_id,
            "resolved_at": now_iso8601(),
            "resolution_note": None,
        })
        return ReplyResult(action="dismiss", conflict_id=conflict_id)

    else:
        return ReplyResult(action="reprompt", message=USAGE_TEXT)
```

---

## Error Handling

| Error | Action |
|---|---|
| NodeDecisionStoreEffect unavailable | Log error, abort `record`, report to user |
| NodeDecisionStoreQueryCompute unavailable | Log error, abort sub-operation, report |
| semantic_check_async timeout | Log warning, treat as severity_shift=0, continue |
| semantic_check_async HTTP error | Log warning, treat as severity_shift=0, continue |
| Missing required field | Ask user for the missing field before proceeding |
| Invalid enum value | Report valid options, ask user to re-specify |
| Unrecognized Slack command | Re-prompt with usage text, do not change state |
| emit_event failure | Log error, do not block pipeline (events are best-effort) |

---

## Implementation Notes

- `detect_conflicts.py` is a pure Python module — import and call directly.
- `semantic_check.py` is async — use `asyncio.create_task()` in MVP for non-blocking dispatch.
- In MVP, semantic results arrive after the pipeline continues; they update the conflict record
  when they arrive but do not re-gate the pipeline.
- All event emission uses the topic constant `TopicBase.DECISION_CONFLICT_STATUS_CHANGED`
  from `omniclaude/src/omniclaude/hooks/topics.py` (added in OMN-2766).
- Wire topic name: `"onex.evt.omniclaude.decision-conflict-status-changed.v1"`
- See `examples/record_decision.md`, `examples/query_decisions.md`, and
  `examples/conflict_resolution.md` for concrete walkthroughs.
