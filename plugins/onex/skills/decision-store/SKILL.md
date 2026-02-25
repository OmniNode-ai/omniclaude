# decision-store skill

**Skill ID**: `onex:decision-store`
**Version**: 1.1.0
**Owner**: omniclaude
**Tickets**: OMN-2768 (base), OMN-2769 (Slack gate + status events)

---

## Purpose

Record, query, and conflict-check architectural and design decisions across the OmniNode
platform. Decisions are persisted by `NodeDecisionStoreEffect` (OMN-2765) and queried
via `NodeDecisionStoreQueryCompute` (OMN-2767).

Conflicts are detected in two stages:
1. **Structural check** (sync, pure function) — always runs
2. **Semantic check** (async, LLM via DeepSeek-R1) — only if structural confidence >= 0.6

HIGH-severity conflicts trigger the Slack conflict resolution gate (OMN-2769), which blocks
the pipeline until an operator resolves each conflict via Slack reply.

---

## Sub-operations

### `record`

Write a new decision entry, run structural conflict check against all existing entries
in the same domain, and route to Slack if any conflict is HIGH severity.

```
/decision-store record
  --type TECH_STACK_CHOICE|DESIGN_PATTERN|API_CONTRACT|SCOPE_BOUNDARY|REQUIREMENT_CHOICE
  --domain <domain>
  --layer architecture|design|planning
  --services <svc1,svc2,...>   # omit = platform-wide
  --summary "<one-line summary>"
  --rationale "<full rationale>"
  [--dry-run]
```

Behavior:
1. Validate required fields.
2. Call `NodeDecisionStoreEffect` to persist the entry.
3. Run `structural_confidence()` against all existing entries in the same domain.
4. For each conflict with confidence > 0.0, call `compute_severity()`.
5. If any severity is HIGH: post Slack gate via `slack-gate` skill (HIGH_RISK tier) and
   wait for operator resolution via Slack command grammar.
6. If structural confidence >= 0.6: fire async `semantic_check_async()` — non-blocking.
7. Emit `decision-conflict-status-changed.v1` event for each new conflict (status = OPEN).
8. Emit `decision-conflict-status-changed.v1` on each subsequent status transition
   (OPEN → RESOLVED or OPEN → DISMISSED) after Slack resolution.

### `query`

Retrieve existing decisions with optional filters and cursor-based pagination.

```
/decision-store query
  [--domain <domain>]
  [--layer architecture|design|planning]
  [--type <decision_type>]
  [--service <service_name>]
  [--status open|resolved|dismissed]
  [--cursor <cursor_token>]
  [--limit 20]
```

Behavior:
1. Call `NodeDecisionStoreQueryCompute` with filter params.
2. Display paginated results with conflict indicators.
3. If `--cursor` provided, fetch next page.

### `check-conflicts`

Dry-run structural conflict check for a hypothetical new decision, without writing anything.

```
/decision-store check-conflicts
  --type <decision_type>
  --domain <domain>
  --layer architecture|design|planning
  --services <svc1,svc2,...>
  --summary "<one-line summary>"
```

Behavior:
1. Run `structural_confidence()` and `compute_severity()` against all existing entries.
2. Display conflict report: confidence scores, severities, affected entries.
3. Does NOT write to the store. Does NOT trigger semantic check. Does NOT emit events.

---

## Severity Matrix

| Decision Type | Layer | Base Severity |
|---|---|---|
| TECH_STACK_CHOICE | architecture | HIGH |
| TECH_STACK_CHOICE | design | HIGH |
| TECH_STACK_CHOICE | planning | MEDIUM |
| DESIGN_PATTERN | architecture | HIGH |
| DESIGN_PATTERN | design | MEDIUM |
| DESIGN_PATTERN | planning | LOW |
| API_CONTRACT | architecture | HIGH |
| API_CONTRACT | design | MEDIUM |
| API_CONTRACT | planning | LOW |
| SCOPE_BOUNDARY | architecture | MEDIUM |
| SCOPE_BOUNDARY | design | MEDIUM |
| SCOPE_BOUNDARY | planning | LOW |
| REQUIREMENT_CHOICE | architecture | MEDIUM |
| REQUIREMENT_CHOICE | design | LOW |
| REQUIREMENT_CHOICE | planning | LOW |

**Modifiers (applied in order after base):**

1. **Platform-wide scope** (either entry has `scope_services = []`): floor at MEDIUM
2. **Architecture layer** (either entry has `scope_layer = "architecture"`): floor at HIGH
3. **Semantic shift** (from DeepSeek-R1): ±1 step, clamped to [LOW, HIGH]

**Hard rules:**
- `structural_confidence == 0.0` (cross-domain): no conflict, semantic check MUST NOT run
- `structural_confidence == 0.3` (disjoint services): semantic check CANNOT escalate to HIGH
- Semantic check only runs if `structural_confidence >= 0.6`

---

## Structural Confidence Values

| Value | Meaning |
|---|---|
| 0.0 | Cross-domain — no possible conflict (semantic blocked) |
| 0.3 | Disjoint service sets — low probability (semantic capped at MEDIUM) |
| 0.4 | Same domain, different layer |
| 0.7 | Overlapping service sets |
| 0.8 | One platform-wide vs specific |
| 0.9 | Both platform-wide |
| 1.0 | Identical service scope |

---

## Conflict Resolution (Slack Gate)

When a HIGH severity conflict is detected after `record`, the pipeline invokes the
`slack-gate` skill with `HIGH_RISK` tier, posting a conflict notification to Slack and
blocking until an operator resolves the conflict.

### Integration with slack-gate

HIGH conflicts use the existing `slack-gate` HIGH_RISK gate interface:
- See `omniclaude/plugins/onex/skills/slack-gate/SKILL.md` for gate interface details
- The conflict notification is posted as a HIGH_RISK gate
- All other HIGH_RISK gates (e.g. auto-merge) are unaffected; only decision conflicts use
  this grammar

### Slack Command Grammar

Operators resolve conflicts by replying in the Slack gate thread:

```
Format:  <action> <conflict_id> [note]

Actions:
  proceed <id> [note]  — mark RESOLVED, record approver + note, continue pipeline
  hold    <id>         — pipeline stays paused (gate remains open)
  dismiss <id>         — mark DISMISSED permanently (no further checks for this pair)
```

**`proceed` rules:**
- `proceed <id>` with no note → `resolution_note = "proceed (no note provided)"`
- `proceed <id> <note>` → `resolution_note = <note text>`

**`hold` rules:**
- Pipeline stays paused; no state change; no event emitted

**`dismiss` rules:**
- Conflict marked DISMISSED permanently
- This decision pair will NEVER trigger a Slack gate again (even if re-recorded)
- `resolution_note` is `None` for dismissals

**Multiple conflicts:**
- Each conflict must be resolved separately in its own reply
- All OPEN conflicts must be resolved before the pipeline resumes
- RESOLVED and DISMISSED conflicts do not block the pipeline

**Unrecognized commands:**
- Re-prompt operator with usage text; no state changes

### Conflict Workflow (Full Sequence)

```
1. record sub-operation detects HIGH conflict
2. Invoke slack-gate skill (HIGH_RISK tier) → post conflict message to Slack
3. Pipeline blocks (polling for Slack replies)
4. Operator replies with: proceed | hold | dismiss
5. For proceed:
   - Update conflict: status=RESOLVED, resolved_by, resolved_at, resolution_note
   - Emit decision-conflict-status-changed.v1 (OPEN → RESOLVED)
   - If all conflicts resolved: resume pipeline
6. For hold:
   - No state change, no event
   - Continue polling
7. For dismiss:
   - Update conflict: status=DISMISSED
   - Emit decision-conflict-status-changed.v1 (OPEN → DISMISSED)
   - Mark pair as permanently suppressed
   - If all conflicts resolved/dismissed: resume pipeline
8. Pipeline resumes after all blocking conflicts are RESOLVED or DISMISSED
```

---

## Status Change Events

`decision-conflict-status-changed.v1` is emitted on EVERY conflict status transition.

**Topic constant**: `TopicBase.DECISION_CONFLICT_STATUS_CHANGED`
**Wire topic**: `onex.evt.omniclaude.decision-conflict-status-changed.v1`
**Source**: `omniclaude/src/omniclaude/hooks/topics.py` (added in OMN-2766)

**Transitions that emit:**
- `None → OPEN` (conflict first detected during `record`)
- `OPEN → RESOLVED` (via `proceed` command)
- `OPEN → DISMISSED` (via `dismiss` command)

**Payload:**
```json
{
  "conflict_id": "uuid",
  "old_status": "OPEN | null",
  "new_status": "OPEN | RESOLVED | DISMISSED",
  "resolved_by": "slack_user_id | null",
  "resolved_at": "ISO8601 | null",
  "resolution_note": "string | null"
}
```

Note: `old_status` is `null` for the initial OPEN event (no previous status).
`resolution_note` is `null` for `dismiss` actions.

---

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | This document — usage, severity matrix, conflict resolution workflow |
| `prompt.md` | Operational prompt followed by the agent |
| `detect_conflicts.py` | `structural_confidence()` and `compute_severity()` pure functions |
| `semantic_check.py` | Async LLM check via DeepSeek-R1 (only if structural >= 0.6) |
| `examples/record_decision.md` | Example: recording a tech stack choice |
| `examples/query_decisions.md` | Example: querying decisions with filters |
| `examples/conflict_resolution.md` | Example: Slack conflict resolution walkthrough |

---

## Dependencies

| Ticket | Component | Role |
|---|---|---|
| OMN-2763 | `ModelDecisionStoreEntry`, `ModelDecisionConflict` | Data models |
| OMN-2765 | `NodeDecisionStoreEffect` | Write node |
| OMN-2767 | `NodeDecisionStoreQueryCompute` | Query node |
| OMN-2766 | `TopicBase.DECISION_CONFLICT_STATUS_CHANGED` in `topics.py` | Event emission |
| OMN-2769 | Slack command grammar + status change events | This ticket |

---

## Event Schema

**`decision-conflict-status-changed.v1`** (emitted on every status transition):

```json
{
  "conflict_id": "uuid",
  "old_status": "OPEN | RESOLVED | DISMISSED | null",
  "new_status": "OPEN | RESOLVED | DISMISSED",
  "resolved_by": "string | null",
  "resolved_at": "ISO8601 | null",
  "resolution_note": "string | null"
}
```

**Note**: The event schema was simplified in OMN-2769. Fields `decision_a_id`,
`decision_b_id`, and `approver` were consolidated: `approver` is now `resolved_by`,
and decision pair IDs are carried by the conflict record (not the status event).
The status event is intentionally minimal — consumers query the conflict record for
full decision pair context.
