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

- If `base_severity == "HIGH"`: **stop and post Slack gate** (see Resolution Gate below)
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
# Emit decision-conflict-status-changed.v1
emit_event("decision-conflict-status-changed.v1", {
    "conflict_id": conflict_id,
    "decision_a_id": candidate_id,
    "decision_b_id": conflict.entry.id,
    "old_status": None,
    "new_status": "OPEN",
    "resolution_note": None,
    "approver": None,
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

When `record` detects a HIGH severity conflict, post to Slack and pause:

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

**Resolution rules:**

```
proceed <id> [note]
  → conflict.status = RESOLVED
  → conflict.resolution_note = note or "proceed (no note provided)"
  → conflict.resolved_by = <slack_user>
  → emit decision-conflict-status-changed.v1 (old: OPEN → new: RESOLVED)
  → resume pipeline

hold <id>
  → pipeline stays paused
  → no status change, no event

dismiss <id>
  → conflict.status = DISMISSED
  → emit decision-conflict-status-changed.v1 (old: OPEN → new: DISMISSED)
  → resume pipeline (dismissed = acknowledged, not a blocker)
```

Multiple conflicts: each must be resolved in a separate reply before the pipeline resumes.

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

---

## Implementation Notes

- `detect_conflicts.py` is a pure Python module — import and call directly.
- `semantic_check.py` is async — use `asyncio.create_task()` in MVP for non-blocking dispatch.
- In MVP, semantic results arrive after the pipeline continues; they update the conflict record
  when they arrive but do not re-gate the pipeline.
- All event emission uses the topic constant from `topics.py` (OMN-2766):
  `TOPIC_DECISION_CONFLICT_STATUS_CHANGED = "decision-conflict-status-changed.v1"`
- See `examples/record_decision.md` and `examples/query_decisions.md` for concrete walkthroughs.
